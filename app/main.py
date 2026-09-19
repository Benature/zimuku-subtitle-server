import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core.observability import configure_logging
from .db.session import create_db_and_tables
from .mcp.server import MCPHTTPApp, MCPPathRewriteMiddleware, create_session_manager, normalize_mcp_path

# 使用环境变量控制日志级别（支持 LOG_LEVEL 或 UVICORN_LOG_LEVEL）
log_level = os.environ.get("LOG_LEVEL", os.environ.get("UVICORN_LOG_LEVEL", "INFO")).upper()
configure_logging(log_level)
logger = logging.getLogger(__name__)
MCP_HTTP_PATH = normalize_mcp_path(os.environ.get("MCP_HTTP_PATH", "/mcp"))


def _get_mcp_session_manager(app: FastAPI) -> Any:
    return app.state.mcp_session_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """初始化数据库并为当前生命周期创建 MCP session manager。"""
    logger.info("正在初始化数据库表...")
    try:
        create_db_and_tables()
        logger.info("数据库表初始化成功。")
    except Exception as e:
        logger.error(f"数据库表初始化失败: {e}")

    session_manager = create_session_manager()
    app.state.mcp_session_manager = session_manager

    from .services.scheduler_service import scheduler_service

    scheduler_service.start()
    async with session_manager.run():
        yield

    scheduler_service.shutdown()
    del app.state.mcp_session_manager
    logger.info("正在关闭应用...")


from .api import media, schedule, search, settings, system, tasks

app = FastAPI(
    title="Zimuku Subtitle Server", description="独立的字幕管理与刮削服务", version="0.1.0", lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MCPPathRewriteMiddleware, mcp_path=MCP_HTTP_PATH)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局未捕获异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务器错误"},
    )


app.include_router(search.router)
app.include_router(settings.router)
app.include_router(schedule.router)
app.include_router(tasks.router)
app.include_router(media.router)
app.include_router(system.router)


async def handle_mcp_request(scope, receive, send):
    manager = _get_mcp_session_manager(scope["app"])
    await MCPHTTPApp(manager, MCP_HTTP_PATH)(scope, receive, send)


app.mount(MCP_HTTP_PATH, handle_mcp_request)


@app.get("/health", tags=["System"])
async def health_check():
    """健康检查"""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Welcome to Zimuku Subtitle Server API. Visit /docs for documentation."}
