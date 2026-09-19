import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, List

import mcp.types as types
import uvicorn
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlmodel import Session
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from ..core.subtitle_languages import SUBTITLE_LANGUAGES
from ..db.models import SubtitleTask
from ..db.session import create_db_and_tables, engine
from ..services.media_service import MediaService, global_task_status
from ..services.search_service import SearchService
from ..services.settings_service import SettingsService
from ..services.subtitle_inspection_service import SubtitleInspectionError, SubtitleInspectionService
from ..services.subtitle_upload_service import SubtitleUploadError, SubtitleUploadService
from ..services.system_service import SystemService
from ..services.task_service import TaskService

logger = logging.getLogger(__name__)

DEFAULT_MCP_HTTP_HOST = os.getenv("MCP_HTTP_HOST", "0.0.0.0")
DEFAULT_MCP_HTTP_PORT = int(os.getenv("MCP_HTTP_PORT", "8001"))
DEFAULT_MCP_HTTP_PATH = os.getenv("MCP_HTTP_PATH", "/mcp")

# 创建 MCP 服务器实例
server = Server("zimuku-subtitle-server")
MCPResponse = List[types.TextContent | types.ImageContent | types.EmbeddedResource]


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _content(text: str) -> List[types.TextContent]:
    return [types.TextContent(type="text", text=text)]


def _success(title: str, data: Any) -> List[types.TextContent]:
    return _content(f"{title}\n{_json_text(data)}")


def _error(message: str) -> List[types.TextContent]:
    return _content(message)


def _missing_fields(*fields: str) -> List[types.TextContent]:
    return _error(f"Error: Missing {' or '.join(fields)}")


def _serialize_model(model: Any) -> Any:
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model


def _serialize_models(items: list[Any]) -> list[Any]:
    return [_serialize_model(item) for item in items]


def _format_search_results(results_data: list[dict[str, Any]]) -> List[types.TextContent]:
    lines = [f"找到 {len(results_data)} 个结果:"]
    for result in results_data:
        lines.append(f"- [{'/'.join(result['lang'])}] {result['title']}")
        lines.append(f"  URL: {result['link']}")
    return _content("\n".join(lines) + "\n")


def normalize_mcp_path(mcp_path: str) -> str:
    """标准化 MCP 挂载路径。"""
    normalized_path = mcp_path if mcp_path.startswith("/") else f"/{mcp_path}"
    return normalized_path.rstrip("/") or "/"


class MCPPathRewriteMiddleware:
    """将不带尾部斜杠的 MCP 路径内部改写为挂载路径，避免 307 重定向。"""

    def __init__(self, app, mcp_path: str):
        self.app = app
        self.mcp_path = normalize_mcp_path(mcp_path)
        self.rewritten_path = "/" if self.mcp_path == "/" else f"{self.mcp_path}/"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == self.mcp_path and self.rewritten_path != self.mcp_path:
            rewritten_scope = dict(scope)
            rewritten_scope["path"] = self.rewritten_path
            raw_path = scope.get("raw_path")
            if raw_path is not None:
                rewritten_scope["raw_path"] = self.rewritten_path.encode("utf-8")
            await self.app(rewritten_scope, receive, send)
            return

        await self.app(scope, receive, send)


class MCPHTTPApp:
    """为 MCP 挂载点提供更清晰的 HTTP 行为。"""

    def __init__(self, session_manager: StreamableHTTPSessionManager, mcp_path: str):
        self.session_manager = session_manager
        self.mcp_path = normalize_mcp_path(mcp_path)

    def _plain_http_hint(self) -> JSONResponse:
        return JSONResponse(
            {
                "message": "This is an MCP endpoint.",
                "transport": "streamable-http",
                "path": self.mcp_path,
                "usage": {
                    "post": "Send JSON-RPC requests to this endpoint with Content-Type: application/json",
                    "get": "Use Accept: text/event-stream when establishing an SSE stream",
                },
            }
        )

    @staticmethod
    def _headers(scope) -> dict[str, str]:
        return {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.session_manager.handle_request(scope, receive, send)
            return

        method = scope["method"].upper()
        accept = self._headers(scope).get("accept", "")

        if method == "GET" and "text/event-stream" not in accept:
            await self._plain_http_hint()(scope, receive, send)
            return

        await self.session_manager.handle_request(scope, receive, send)


def _search_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_subtitles",
            description="在字幕库中搜索字幕",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词（如电影或剧集名称）"},
                    "season": {"type": "integer", "description": "季数（可选，用于剧集精确匹配）"},
                    "episode": {"type": "integer", "description": "集数（可选，用于剧集精确匹配）"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="download_subtitle",
            description="根据搜索结果的详情链接下载字幕",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "字幕标题"},
                    "source_url": {"type": "string", "description": "详情页 URL"},
                },
                "required": ["title", "source_url"],
            },
        ),
    ]


def _media_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_media_task_status",
            description="获取当前媒体扫描与匹配后台状态",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="list_media_paths",
            description="列出所有媒体库路径",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="add_media_path",
            description="添加媒体库路径",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "媒体库路径"},
                    "path_type": {"type": "string", "enum": ["movie", "tv"], "description": "路径类型"},
                },
                "required": ["path", "path_type"],
            },
        ),
        types.Tool(
            name="delete_media_path",
            description="删除媒体库路径",
            inputSchema={
                "type": "object",
                "properties": {"path_id": {"type": "integer", "description": "媒体库路径 ID"}},
                "required": ["path_id"],
            },
        ),
        types.Tool(
            name="update_media_path",
            description="更新媒体库路径配置",
            inputSchema={
                "type": "object",
                "properties": {
                    "path_id": {"type": "integer", "description": "媒体库路径 ID"},
                    "enabled": {"type": "boolean", "description": "是否启用"},
                    "path_type": {"type": "string", "enum": ["movie", "tv"], "description": "路径类型"},
                },
                "required": ["path_id"],
            },
        ),
        types.Tool(
            name="list_scanned_files",
            description="列出已扫描的媒体文件",
            inputSchema={
                "type": "object",
                "properties": {
                    "path_type": {"type": "string", "enum": ["movie", "tv"], "description": "文件类型过滤"},
                    "offset": {"type": "integer", "description": "偏移量", "minimum": 0},
                    "limit": {"type": "integer", "description": "数量限制", "minimum": 1, "maximum": 1000},
                },
            },
        ),
        types.Tool(
            name="list_media",
            description="按电影、剧、季或集聚合查询媒体库，支持文件名和 NFO 标题、原始标题、别名的模糊搜索",
            inputSchema={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["movie", "show", "season", "episode"],
                        "description": "返回层级；默认剧集层级 show",
                    },
                    "media_type": {"type": "string", "enum": ["movie", "tv"], "description": "媒体类型过滤"},
                    "query": {"type": "string", "description": "文件名、年份或 NFO 标题、原始标题、别名的模糊关键词"},
                    "title": {"type": "string", "description": "指定剧名后向下查询季或集"},
                    "season": {"type": "integer", "minimum": 1, "description": "指定季后查询该季的集"},
                    "offset": {"type": "integer", "minimum": 0, "description": "偏移量"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "数量限制"},
                },
            },
        ),
        types.Tool(
            name="scan_media_library",
            description="刷新媒体库列表：仅扫描电影/剧集目录并更新已扫描文件记录，不会自动搜索、下载或移动字幕",
            inputSchema={
                "type": "object",
                "properties": {"path_type": {"type": "string", "enum": ["movie", "tv"], "description": "扫描类型过滤"}},
            },
        ),
        types.Tool(
            name="auto_match_file",
            description="对单个已扫描文件执行自动匹配和字幕下载",
            inputSchema={
                "type": "object",
                "properties": {"file_id": {"type": "integer", "description": "已扫描文件 ID"}},
                "required": ["file_id"],
            },
        ),
        types.Tool(
            name="match_tv_season",
            description="对指定剧集季执行批量字幕匹配",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "剧集标题"},
                    "season": {"type": "integer", "description": "季数", "minimum": 1},
                },
                "required": ["title", "season"],
            },
        ),
        types.Tool(
            name="upload_subtitle_file",
            description="上传字幕文件或字幕压缩包，并关联到指定的已扫描媒体文件",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "integer", "description": "已扫描媒体文件 ID", "minimum": 1},
                    "filename": {
                        "type": "string",
                        "description": "原始文件名，支持 srt/ass/ssa/vtt/sub/sup/zip/7z",
                    },
                    "content_base64": {"type": "string", "description": "文件内容的原始 Base64 编码"},
                    "language": {
                        "type": "string",
                        "enum": [language.code for language in SUBTITLE_LANGUAGES],
                        "description": "可选字幕语言代码，可通过 list_subtitle_languages 查询",
                    },
                },
                "required": ["file_id", "filename", "content_base64"],
            },
        ),
        types.Tool(
            name="list_media_subtitles",
            description="查询指定媒体文件的已有字幕列表，包含文件名、路径、大小以及通过实际内容分析得出的真实语言（如双语判定、中英文比例、抽样对白）",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "integer", "description": "已扫描媒体文件 ID", "minimum": 1},
                },
                "required": ["file_id"],
            },
        ),
        types.Tool(
            name="read_subtitle_content",
            description="读取指定媒体文件的已有字幕内容与纯文本对白，可验证其实际语言与文本内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "integer", "description": "已扫描媒体文件 ID", "minimum": 1},
                    "filename": {
                        "type": "string",
                        "description": "字幕文件名（当媒体关联多个字幕时必填，单个字幕时可省略）",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "最大返回行数（默认 100）",
                        "default": 100,
                        "minimum": 1,
                        "maximum": 2000,
                    },
                    "clean_text": {
                        "type": "boolean",
                        "description": "是否清理时间轴和样式代码，返回纯对白文本（默认 true）",
                        "default": True,
                    },
                },
                "required": ["file_id"],
            },
        ),
    ]


def _task_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="create_download_task",
            description="创建字幕下载任务并立即执行",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "字幕标题"},
                    "source_url": {"type": "string", "description": "详情页 URL"},
                    "target_path": {"type": "string", "description": "目标目录"},
                    "target_type": {"type": "string", "enum": ["movie", "tv"], "description": "媒体类型"},
                    "season": {"type": "integer", "description": "季数"},
                    "episode": {"type": "integer", "description": "集数"},
                    "language": {"type": "string", "description": "语言标记"},
                },
                "required": ["title", "source_url"],
            },
        ),
        types.Tool(
            name="get_task",
            description="获取指定下载任务详情",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "integer", "description": "任务 ID"}},
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="list_tasks",
            description="分页列出下载任务",
            inputSchema={
                "type": "object",
                "properties": {
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "status": {"type": "string", "description": "任务状态过滤"},
                },
            },
        ),
        types.Tool(
            name="retry_task",
            description="重试失败的下载任务",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "integer", "description": "任务 ID"}},
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="delete_task",
            description="删除下载任务",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "任务 ID"},
                    "delete_files": {"type": "boolean", "description": "是否同时删除关联文件"},
                },
                "required": ["task_id"],
            },
        ),
        types.Tool(
            name="clear_completed_tasks",
            description="清理所有已完成任务记录",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def _system_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_subtitle_languages",
            description="列出系统支持的字幕语言代码及文件名标签",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="list_settings",
            description="列出系统设置",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="update_setting",
            description="更新系统设置项",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "设置键"},
                    "value": {"type": "string", "description": "设置值"},
                    "description": {"type": "string", "description": "设置描述"},
                },
                "required": ["key", "value"],
            },
        ),
        types.Tool(
            name="get_system_stats",
            description="获取系统统计信息",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_recent_logs",
            description="获取最近日志",
            inputSchema={
                "type": "object",
                "properties": {"lines": {"type": "integer", "description": "日志行数", "minimum": 1, "maximum": 1000}},
            },
        ),
    ]


async def _handle_search_tool(arguments: dict[str, Any]) -> List[types.TextContent]:
    query = arguments.get("query")
    season = arguments.get("season")
    episode = arguments.get("episode")
    if not query:
        return _missing_fields("query")

    try:
        with Session(engine) as session:
            results_data = await SearchService.search(session, query, season=season, episode=episode)
        if not results_data:
            return _error(f"未找到关于 '{query}' 的字幕")
        return _format_search_results(results_data)
    except Exception as e:
        return _error(f"搜索出错: {str(e)}")


async def _handle_download_tool(arguments: dict[str, Any]) -> List[types.TextContent]:
    title = arguments.get("title")
    source_url = arguments.get("source_url")
    if not title or not source_url:
        return _missing_fields("title", "source_url")

    with Session(engine) as session:
        task = SubtitleTask(title=title, source_url=source_url)
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id

        await TaskService.run_download_task(task_id)

        session.refresh(task)
        if task.status == "completed":
            return _content(f"字幕下载并处理成功！保存路径: {task.save_path}")

        return _content(f"下载任务已创建 (ID: {task_id})，当前状态: {task.status}. {task.error_msg or ''}")


async def _handle_media_tool(name: str, arguments: dict[str, Any]) -> List[types.TextContent] | None:
    if name == "get_media_task_status":
        return _success("当前媒体任务状态：", global_task_status.to_dict())

    if name == "list_media_paths":
        with Session(engine) as session:
            paths = MediaService.list_paths(session)
        return _success("媒体库路径列表：", _serialize_models(paths))

    if name == "add_media_path":
        path = arguments.get("path")
        path_type = arguments.get("path_type")
        if not path or not path_type:
            return _missing_fields("path", "path_type")
        try:
            with Session(engine) as session:
                path_record = MediaService.add_path(session, path, path_type)
            return _success("媒体库路径已添加：", _serialize_model(path_record))
        except Exception as e:
            return _error(f"添加媒体库路径出错: {str(e)}")

    if name == "delete_media_path":
        path_id = arguments.get("path_id")
        if path_id is None:
            return _missing_fields("path_id")
        with Session(engine) as session:
            deleted = MediaService.delete_path(session, path_id)
        if not deleted:
            return _error(f"未找到媒体库路径: {path_id}")
        return _content(f"媒体库路径 {path_id} 已删除")

    if name == "update_media_path":
        path_id = arguments.get("path_id")
        if path_id is None:
            return _missing_fields("path_id")
        enabled = arguments.get("enabled")
        path_type = arguments.get("path_type")
        with Session(engine) as session:
            updated = MediaService.update_path(session, path_id, enabled, path_type)
        if not updated:
            return _error(f"未找到媒体库路径: {path_id}")
        return _success("媒体库路径已更新：", _serialize_model(updated))

    if name == "list_scanned_files":
        path_type = arguments.get("path_type")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit")
        with Session(engine) as session:
            files = MediaService.list_files_paginated(session, path_type, offset, limit)
        return _success("已扫描文件列表：", _serialize_models(files))

    if name == "list_media":
        level = arguments.get("level", "show")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", 50)
        try:
            with Session(engine) as session:
                items, total = MediaService.list_media_paginated(
                    session,
                    level=level,
                    media_type=arguments.get("media_type"),
                    query=arguments.get("query"),
                    title=arguments.get("title"),
                    season=arguments.get("season"),
                    offset=offset,
                    limit=limit,
                )
            return _success("媒体库列表：", {"total": total, "offset": offset, "limit": limit, "items": items})
        except (KeyError, ValueError) as exc:
            return _error(f"媒体库查询出错: {exc}")

    if name == "scan_media_library":
        path_type = arguments.get("path_type")
        try:
            await MediaService.run_media_scan_and_match(path_type)
            return _success(
                "媒体库列表刷新已完成：",
                {
                    "path_type": path_type or "all",
                    "effects": [
                        "scan_enabled_media_paths",
                        "update_scanned_file_records",
                        "refresh_has_subtitle_flags",
                    ],
                    "does_not": [
                        "search_subtitles",
                        "download_subtitles",
                        "move_subtitle_files",
                    ],
                },
            )
        except Exception as e:
            return _error(f"媒体库扫描出错: {str(e)}")

    if name == "auto_match_file":
        file_id = arguments.get("file_id")
        if file_id is None:
            return _missing_fields("file_id")
        try:
            matched = await MediaService.run_auto_match_process(file_id)
            return _success("单文件自动匹配已执行：", {"file_id": file_id, "matched": matched})
        except Exception as e:
            return _error(f"单文件自动匹配出错: {str(e)}")

    if name == "match_tv_season":
        title = arguments.get("title")
        season = arguments.get("season")
        if not title or season is None:
            return _missing_fields("title", "season")
        try:
            await MediaService.run_season_match_process(title, season)
            return _success("剧集季匹配已完成：", {"title": title, "season": season})
        except Exception as e:
            return _error(f"剧集季匹配出错: {str(e)}")

    if name == "upload_subtitle_file":
        file_id = arguments.get("file_id")
        filename = arguments.get("filename")
        content_base64 = arguments.get("content_base64")
        if file_id is None or not filename or not content_base64:
            return _missing_fields("file_id", "filename", "content_base64")
        try:
            with Session(engine) as session:
                result = SubtitleUploadService.upload(
                    session,
                    file_id=file_id,
                    filename=filename,
                    content_base64=content_base64,
                    language=arguments.get("language"),
                )
            return _success("字幕文件上传成功：", result.to_dict())
        except SubtitleUploadError as exc:
            return _error(f"字幕文件上传失败: {exc}")
        except Exception as exc:
            logger.exception("字幕文件上传发生未预期错误")
            return _error(f"字幕文件上传失败: {exc}")

    if name == "list_media_subtitles":
        file_id = arguments.get("file_id")
        if file_id is None:
            return _missing_fields("file_id")
        try:
            with Session(engine) as session:
                subtitles = SubtitleInspectionService.get_existing_subtitles(session, file_id)
            return _success("已有字幕列表及语言检测：", [sub.to_dict() for sub in subtitles])
        except SubtitleInspectionError as exc:
            return _error(f"查询已有字幕失败: {exc}")
        except Exception as exc:
            logger.exception("查询已有字幕发生未预期错误")
            return _error(f"查询已有字幕失败: {exc}")

    if name == "read_subtitle_content":
        file_id = arguments.get("file_id")
        if file_id is None:
            return _missing_fields("file_id")
        filename = arguments.get("filename")
        max_lines = arguments.get("max_lines", 100)
        clean_text = arguments.get("clean_text", True)
        try:
            with Session(engine) as session:
                result = SubtitleInspectionService.read_subtitle_content(
                    session,
                    file_id=file_id,
                    filename=filename,
                    max_lines=max_lines,
                    clean_text=clean_text,
                )
            return _success("字幕内容与语言分析：", result.to_dict())
        except SubtitleInspectionError as exc:
            return _error(f"读取字幕内容失败: {exc}")
        except Exception as exc:
            logger.exception("读取字幕内容发生未预期错误")
            return _error(f"读取字幕内容失败: {exc}")

    return None


async def _handle_task_tool(name: str, arguments: dict[str, Any]) -> List[types.TextContent] | None:
    if name == "create_download_task":
        title = arguments.get("title")
        source_url = arguments.get("source_url")
        if not title or not source_url:
            return _missing_fields("title", "source_url")
        with Session(engine) as session:
            task = TaskService.create_task(
                session,
                title,
                source_url,
                target_path=arguments.get("target_path"),
                target_type=arguments.get("target_type"),
                season=arguments.get("season"),
                episode=arguments.get("episode"),
                language=arguments.get("language"),
            )
            task_id = task.id
        if task_id is None:
            return _error("创建任务失败: task id missing")
        await TaskService.run_download_task(task_id)
        with Session(engine) as session:
            task = TaskService.get_task(session, task_id)
        return _success("下载任务已执行：", _serialize_model(task))

    if name == "get_task":
        task_id = arguments.get("task_id")
        if task_id is None:
            return _missing_fields("task_id")
        with Session(engine) as session:
            task = TaskService.get_task(session, task_id)
        if not task:
            return _error(f"未找到任务: {task_id}")
        return _success("任务详情：", _serialize_model(task))

    if name == "list_tasks":
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", 10)
        status = arguments.get("status")
        with Session(engine) as session:
            items, total = TaskService.list_tasks(session, offset, limit, status)
        return _success(
            "任务列表：",
            {"total": total, "offset": offset, "limit": limit, "items": _serialize_models(items)},
        )

    if name == "retry_task":
        task_id = arguments.get("task_id")
        if task_id is None:
            return _missing_fields("task_id")
        with Session(engine) as session:
            task = TaskService.retry_task(session, task_id)
        if not task:
            return _error(f"任务 {task_id} 不存在，或当前状态不允许重试")
        if task.id is None:
            return _error(f"任务 {task_id} 重试失败: task id missing")
        await TaskService.run_download_task(task.id)
        with Session(engine) as session:
            task = TaskService.get_task(session, task_id)
        return _success("任务已重试：", _serialize_model(task))

    if name == "delete_task":
        task_id = arguments.get("task_id")
        if task_id is None:
            return _missing_fields("task_id")
        delete_files = bool(arguments.get("delete_files", False))
        with Session(engine) as session:
            deleted = TaskService.delete_task(session, task_id, delete_files)
        if not deleted:
            return _error(f"未找到任务: {task_id}")
        return _content(f"任务 {task_id} 已删除")

    if name == "clear_completed_tasks":
        with Session(engine) as session:
            cleared = TaskService.clear_completed(session)
        return _success("已清理完成任务：", {"cleared_count": cleared})

    return None


def _handle_system_tool(name: str, arguments: dict[str, Any]) -> List[types.TextContent] | None:
    if name == "list_subtitle_languages":
        return _success("系统支持的字幕语言：", SystemService.get_subtitle_languages())

    if name == "list_settings":
        return _success("系统设置列表：", _serialize_models(SettingsService.get_all_settings()))

    if name == "update_setting":
        key = arguments.get("key")
        value = arguments.get("value")
        if not key or value is None:
            return _missing_fields("key", "value")
        try:
            setting = SettingsService.set_setting(key, value, arguments.get("description"))
            return _success("系统设置已更新：", _serialize_model(setting))
        except Exception as e:
            return _error(f"更新设置出错: {str(e)}")

    if name == "get_system_stats":
        with Session(engine) as session:
            stats = SystemService.get_stats(session)
        return _success("系统统计信息：", stats)

    if name == "get_recent_logs":
        lines = arguments.get("lines", 100)
        return _success("最近日志：", {"lines": lines, "items": SystemService.get_logs(lines)})

    return None


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    """列出可用的工具"""
    return _search_tools() + _media_tools() + _task_tools() + _system_tools()


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> MCPResponse:
    """处理工具调用"""
    arguments = arguments or {}

    if name == "search_subtitles":
        return await _handle_search_tool(arguments)

    if name == "download_subtitle":
        return await _handle_download_tool(arguments)

    media_response = await _handle_media_tool(name, arguments)
    if media_response is not None:
        return media_response

    task_response = await _handle_task_tool(name, arguments)
    if task_response is not None:
        return task_response

    system_response = _handle_system_tool(name, arguments)
    if system_response is not None:
        return system_response

    raise ValueError(f"Unknown tool: {name}")


async def run():
    """以 stdio 模式运行 MCP 服务器"""
    create_db_and_tables()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def create_http_app(mcp_path: str = DEFAULT_MCP_HTTP_PATH) -> Starlette:
    """创建基于 Streamable HTTP transport 的 MCP ASGI 应用。"""
    normalized_path = normalize_mcp_path(mcp_path)
    session_manager = StreamableHTTPSessionManager(server)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        logger.info("正在初始化 MCP HTTP 服务...")
        create_db_and_tables()
        async with session_manager.run():
            yield

    async def health(_request):
        return JSONResponse({"status": "ok"})

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Mount(normalized_path, app=MCPHTTPApp(session_manager, normalized_path)),
        ],
    )
    app.add_middleware(MCPPathRewriteMiddleware, mcp_path=normalized_path)
    return app


def run_http(
    host: str = DEFAULT_MCP_HTTP_HOST,
    port: int = DEFAULT_MCP_HTTP_PORT,
    mcp_path: str = DEFAULT_MCP_HTTP_PATH,
):
    """以 Streamable HTTP 模式运行 MCP 服务器。"""
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    uvicorn.run(create_http_app(mcp_path), host=host, port=port, log_level=log_level)


def create_session_manager() -> StreamableHTTPSessionManager:
    """创建可挂载到现有 ASGI 应用中的 MCP HTTP session manager。"""
    return StreamableHTTPSessionManager(server)
