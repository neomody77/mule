"""
Claude Code Remote - FastAPI 主入口

移动端远程编码平台服务端
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.api import workspaces, websocket, connect, cli_sessions
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
app.include_router(cli_sessions.router, tags=["cli-sessions"])


@app.get("/api")
async def api_info():
    """API 信息"""
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


# 静态文件服务 (Flutter Web)
# 优先使用 static/ (生产), 否则使用 client/build/web/ (开发)
static_dir = Path("static")
if not static_dir.exists():
    static_dir = Path("client/build/web")

if static_dir.exists():
    # 挂载静态资源子目录
    for subdir in ["assets", "icons", "canvaskit", "fonts", "packages", "shaders"]:
        subdir_path = static_dir / subdir
        if subdir_path.exists():
            app.mount(f"/{subdir}", StaticFiles(directory=subdir_path), name=subdir)

    @app.get("/")
    async def serve_index():
        """服务 Flutter Web 首页"""
        return FileResponse(static_dir / "index.html")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA fallback - 处理所有未匹配的路由"""
        # 跳过 API 和 WebSocket 路由
        if full_path.startswith(("api/", "ws", "health")):
            return {"error": "Not found"}

        file_path = static_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # SPA 路由回退到 index.html
        return FileResponse(static_dir / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
