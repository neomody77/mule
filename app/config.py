"""
配置管理模块
支持通过环境变量或 .env 文件配置
"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载 .env 文件到 os.environ（让 Docker 容器可以继承）
load_dotenv()


class Settings(BaseSettings):
    """应用配置"""

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # 数据目录 - 存储日志、元数据等
    data_dir: Path = Path("./data")

    # 工作目录配置 - 所有工作区都在此目录下创建
    workspace_base_dir: Path = Path("./workspaces")

    # 认证配置
    api_token: str = "change-me-in-production"  # 简单 Token 认证

    # Claude Agent SDK 使用系统登录的凭证，无需配置 API key

    # WebSocket 配置
    ws_heartbeat_interval: int = 30  # 秒

    # Docker 隔离配置
    use_docker_isolation: bool = False  # 是否使用 Docker 隔离 workspace
    docker_image: str = "mule-workspace:latest"  # workspace 容器镜像

    # Agent 后端配置
    use_google_adk: bool = False  # 使用 Google ADK 替代 Claude Agent SDK
    adk_model: str = "gemini-2.0-flash"  # Google ADK 使用的模型

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    def get_workspace_path(self, workspace_id: str) -> Path:
        """获取指定工作区的完整路径"""
        return self.workspace_base_dir / workspace_id

    def ensure_workspace_base_dir(self) -> None:
        """确保工作目录存在"""
        self.workspace_base_dir.mkdir(parents=True, exist_ok=True)

    def ensure_data_dir(self) -> None:
        """确保数据目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs" / "agent").mkdir(parents=True, exist_ok=True)


# 全局配置实例
settings = Settings()

# 确保必要目录存在
settings.ensure_data_dir()
