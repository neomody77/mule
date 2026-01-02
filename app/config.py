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

    # 认证配置 - 支持多个 token，逗号分隔
    api_tokens: str = "change-me-in-production"  # 多个 token 用逗号分隔

    # 加密密钥 - 用于加密连接信息
    connect_secret: str = "mule-secret-key-change-me"

    # ==================== Clerk 认证配置 ====================
    # 认证提供者: token（默认）或 clerk
    auth_provider: str = "token"

    # Clerk JWKS URL（仅当 auth_provider=clerk 时需要）
    # 格式: https://your-clerk-frontend-api.clerk.accounts.dev/.well-known/jwks.json
    clerk_jwks_url: Optional[str] = None

    @property
    def use_clerk_auth(self) -> bool:
        """是否使用 Clerk 认证"""
        return self.auth_provider == "clerk" and self.clerk_jwks_url is not None

    @property
    def token_list(self) -> list[str]:
        """获取 token 列表"""
        return [t.strip() for t in self.api_tokens.split(",") if t.strip()]

    def is_valid_token(self, token: str) -> bool:
        """验证 token 是否有效"""
        return token in self.token_list

    def get_workspace_id_for_token(self, token: str) -> str:
        """
        根据 token 获取对应的 workspace_id

        每个 token 对应一个独立的 workspace，使用 token 的 hash 前缀作为 workspace_id
        这样可以保证：
        1. 相同 token 始终映射到同一个 workspace
        2. 不同 token 映射到不同 workspace
        3. workspace_id 不会泄露 token 信息
        """
        import hashlib
        # 使用 token 的 sha256 hash 前 8 位作为 workspace_id
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:8]
        return f"ws-{token_hash}"

    # Claude Agent SDK 使用系统登录的凭证，无需配置 API key

    # WebSocket 配置
    ws_heartbeat_interval: int = 30  # 秒

    # Docker 隔离配置
    use_sandbox: bool = False  # 是否使用 Docker 沙箱隔离 workspace
    sandbox_image: str = "mule-workspace:latest"  # 沙箱容器镜像

    # Agent 后端配置: claude, sandbox, adk
    agent_backend: str = "claude"  # claude=直接使用SDK, sandbox=Docker隔离, adk=Google ADK
    adk_model: str = "gemini-2.0-flash"  # Google ADK 使用的模型

    # GitHub CLI 配置传递（仅 sandbox 模式）
    share_gh_config: bool = False  # 是否将宿主机 gh 配置传递给容器

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
