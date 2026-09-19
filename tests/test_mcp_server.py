from unittest.mock import AsyncMock, patch

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.db.models import Setting
from app.db.session import create_db_and_tables
from app.mcp.server import create_http_app, handle_call_tool, handle_list_tools
from app.services.subtitle_upload_service import SubtitleUploadResult


@pytest.fixture(autouse=True)
def setup_db():
    create_db_and_tables()


@pytest.mark.anyio
async def test_mcp_list_tools():
    """验证工具注册情况"""
    tools = await handle_list_tools()
    tool_names = [t.name for t in tools]

    assert "search_subtitles" in tool_names
    assert "download_subtitle" in tool_names
    assert "list_media_paths" in tool_names
    assert "list_media" in tool_names
    assert "scan_media_library" in tool_names
    assert "list_tasks" in tool_names
    assert "update_setting" in tool_names
    assert "get_system_stats" in tool_names
    assert "list_subtitle_languages" in tool_names
    assert "upload_subtitle_file" in tool_names

    # 验证 search_subtitles 的 schema
    search_tool = next(t for t in tools if t.name == "search_subtitles")
    assert "query" in search_tool.inputSchema["properties"]

    upload_tool = next(t for t in tools if t.name == "upload_subtitle_file")
    assert upload_tool.inputSchema["required"] == ["file_id", "filename", "content_base64"]
    assert upload_tool.inputSchema["properties"]["language"]["enum"] == [
        "zh-CN",
        "zh-TW",
        "en",
        "zh-CN-en",
    ]


@pytest.mark.anyio
async def test_mcp_lists_subtitle_languages():
    result = await handle_call_tool("list_subtitle_languages", {})

    assert '"code": "zh-CN"' in result[0].text
    assert '"filename_tag": "zh-CN-en"' in result[0].text


@pytest.mark.anyio
async def test_mcp_upload_subtitle_file():
    upload_result = SubtitleUploadResult(
        file_id=7,
        language="zh-CN",
        saved_count=1,
        saved_paths=["/media/Movie.zh-CN.srt"],
    )
    with patch("app.mcp.server.SubtitleUploadService.upload", return_value=upload_result) as upload:
        result = await handle_call_tool(
            "upload_subtitle_file",
            {
                "file_id": 7,
                "filename": "subtitle.srt",
                "content_base64": "YQ==",
                "language": "zh-CN",
            },
        )

    upload.assert_called_once()
    assert "字幕文件上传成功" in result[0].text
    assert '"saved_count": 1' in result[0].text


@pytest.mark.anyio
async def test_mcp_call_search_tool():
    """验证 MCP 调用搜索逻辑"""
    with patch(
        "app.mcp.server.SearchService.search",
        new=AsyncMock(return_value=[{"title": "Test", "link": "http://test", "lang": ["中文"], "rating": "10"}]),
    ):
        results = await handle_call_tool("search_subtitles", {"query": "Avengers"})

    assert len(results) == 1
    assert "找到 1 个结果" in results[0].text
    assert "Test" in results[0].text


def test_mcp_http_health_endpoint():
    """验证 HTTP MCP 服务可启动并暴露健康检查。"""
    app = create_http_app("/mcp")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_http_path_does_not_redirect():
    """验证 /mcp 可直接命中，不会被 307 重定向到 /mcp/。"""
    app = create_http_app("/mcp")

    with TestClient(app) as client:
        response = client.get("/mcp", follow_redirects=False)

    assert response.status_code != 307
    assert response.status_code != 308
    assert "location" not in response.headers


def test_mcp_http_path_returns_hint_for_plain_get():
    """验证普通浏览器式 GET /mcp 返回说明，而不是 404。"""
    app = create_http_app("/mcp")

    with TestClient(app) as client:
        response = client.get("/mcp", headers={"accept": "text/html"}, follow_redirects=False)

    assert response.status_code == 200
    assert response.json()["transport"] == "streamable-http"
    assert response.json()["path"] == "/mcp"


def test_main_app_mounts_mcp_path():
    """验证主后端应用已挂载 /mcp。"""
    from app.main import app

    mounts = [route for route in app.routes if isinstance(route, Mount)]
    assert any(route.path == "/mcp" for route in mounts)


def test_main_app_can_restart_lifespan():
    """验证主应用重复启停时会为每次生命周期创建新的 MCP session manager。"""
    from app.main import app

    with TestClient(app) as first_client:
        first_response = first_client.get("/health")

    with TestClient(app) as second_client:
        second_response = second_client.get("/health")

    assert first_response.status_code == 200
    assert second_response.status_code == 200


@pytest.mark.anyio
async def test_mcp_call_download_tool():
    """验证 MCP 调用下载逻辑"""
    with patch("app.mcp.server.TaskService.run_download_task", new=AsyncMock(return_value=None)):
        arguments = {"title": "Avengers", "source_url": "http://zimuku.org/detail/123"}
        results = await handle_call_tool("download_subtitle", arguments)

    assert len(results) == 1
    # 因为我们在 mock 后的任务中状态是 pending (默认状态)
    assert "下载任务已创建" in results[0].text


@pytest.mark.anyio
async def test_mcp_media_path_management_tools():
    """验证媒体库路径管理工具。"""
    added = await handle_call_tool("add_media_path", {"path": "/media/tv", "path_type": "tv"})
    listed = await handle_call_tool("list_media_paths", {})
    updated = await handle_call_tool("update_media_path", {"path_id": 1, "enabled": False})
    deleted = await handle_call_tool("delete_media_path", {"path_id": 1})

    assert "媒体库路径已添加" in added[0].text
    assert "/media/tv" in listed[0].text
    assert '"enabled": false' in updated[0].text
    assert "已删除" in deleted[0].text


@pytest.mark.anyio
async def test_mcp_list_media_tool_returns_paginated_aggregates():
    with patch("app.mcp.server.MediaService.list_media_paginated", return_value=([{"title": "Lost"}], 1)):
        result = await handle_call_tool("list_media", {"level": "show", "query": "lost"})

    assert "媒体库列表" in result[0].text
    assert '"total": 1' in result[0].text
    assert "Lost" in result[0].text


@pytest.mark.anyio
async def test_mcp_task_and_settings_tools():
    """验证任务、设置与系统工具。"""
    with (
        patch(
            "app.mcp.server.TaskService.list_tasks",
            return_value=([type("Task", (), {"model_dump": lambda self: {"id": 1, "status": "failed"}})()], 1),
        ),
        patch(
            "app.mcp.server.SettingsService.get_all_settings",
            return_value=[Setting(id=1, key="proxy", value="http://127.0.0.1:7890", description="代理")],
        ),
        patch(
            "app.mcp.server.SettingsService.set_setting",
            return_value=Setting(id=1, key="proxy", value="http://127.0.0.1:7890", description="代理"),
        ),
        patch(
            "app.mcp.server.SystemService.get_stats",
            return_value={"tasks": {"total": 1}, "cache": {"total_entries": 2}},
        ),
        patch(
            "app.mcp.server.SystemService.get_logs",
            return_value=["line1", "line2"],
        ),
    ):
        tasks = await handle_call_tool("list_tasks", {"limit": 5})
        settings = await handle_call_tool("list_settings", {})
        update = await handle_call_tool("update_setting", {"key": "proxy", "value": "http://127.0.0.1:7890"})
        stats = await handle_call_tool("get_system_stats", {})
        logs = await handle_call_tool("get_recent_logs", {"lines": 2})

    assert '"total": 1' in tasks[0].text
    assert "http://127.0.0.1:7890" in settings[0].text
    assert "系统设置已更新" in update[0].text
    assert '"total_entries": 2' in stats[0].text
    assert "line1" in logs[0].text


@pytest.mark.anyio
async def test_mcp_scan_and_retry_tools():
    """验证扫描和任务重试类工具。"""
    task_stub = type("Task", (), {"id": 1, "model_dump": lambda self: {"id": 1, "status": "completed"}})()

    with (
        patch("app.mcp.server.MediaService.run_media_scan_and_match", new=AsyncMock(return_value=None)),
        patch("app.mcp.server.MediaService.run_auto_match_process", new=AsyncMock(return_value=True)),
        patch("app.mcp.server.MediaService.run_season_match_process", new=AsyncMock(return_value=None)),
        patch("app.mcp.server.TaskService.retry_task", return_value=task_stub),
        patch("app.mcp.server.TaskService.run_download_task", new=AsyncMock(return_value=None)),
        patch("app.mcp.server.TaskService.get_task", return_value=task_stub),
    ):
        scan = await handle_call_tool("scan_media_library", {"path_type": "tv"})
        auto_match = await handle_call_tool("auto_match_file", {"file_id": 12})
        season_match = await handle_call_tool("match_tv_season", {"title": "Lost", "season": 1})
        retry = await handle_call_tool("retry_task", {"task_id": 1})

    assert '"path_type": "tv"' in scan[0].text
    assert '"matched": true' in auto_match[0].text
    assert '"title": "Lost"' in season_match[0].text
    assert "任务已重试" in retry[0].text
