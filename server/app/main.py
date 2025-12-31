"""
Claude Code Remote - FastAPI 主入口

移动端远程编码平台服务端
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import workspaces, websocket, connect
from app.services.workspace_manager import workspace_manager

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 配置 Claude Agent SDK 详细日志
logging.getLogger("claude_agent_sdk").setLevel(logging.DEBUG)
logging.getLogger("claude_agent_sdk._internal").setLevel(logging.DEBUG)
logging.getLogger("claude_agent_sdk._internal.client").setLevel(logging.DEBUG)
logging.getLogger("claude_agent_sdk._internal.query").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info(f"Starting Claude Code Remote Server...")
    logger.info(f"Workspace base directory: {settings.workspace_base_dir.absolute()}")
    settings.ensure_workspace_base_dir()

    # 确保默认工作空间存在
    default_ws = workspace_manager.ensure_default_workspace()
    logger.info(f"Default workspace ready: {default_ws.name} ({default_ws.id})")

    logger.info("Server started successfully")

    yield

    # 关闭时
    logger.info("Shutting down server...")


app = FastAPI(
    title="Claude Code Remote",
    description="移动端远程编码平台 - 通过 Claude Agent 实现远程代码操作",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(workspaces.router, prefix="/api/workspaces", tags=["workspaces"])
app.include_router(websocket.router, tags=["websocket"])
app.include_router(connect.router, prefix="/api/connect", tags=["connect"])


@app.get("/")
async def root():
    """根路径 - 服务信息"""
    return {
        "name": "Claude Code Remote",
        "version": "0.1.0",
        "status": "running",
        "workspace_dir": str(settings.workspace_base_dir.absolute()),
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
