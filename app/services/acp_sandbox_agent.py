"""
ACP Sandbox Agent - ACP 协议 + Docker 沙箱隔离

结合 ACP 协议的细粒度控制能力和 Docker 沙箱的安全隔离，
实现最完整的远程编程助手方案：
- 远程权限审批
- 本地/远程模式切换
- Docker 容器隔离
- OAuth Token 自动刷新
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from app.services.acp_transport import AcpTransport, AcpTransportError
from app.services.permission_adapter import PermissionAdapter, PermissionDecision
from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager
from app.config import settings

logger = logging.getLogger(__name__)

# Docker 镜像名称
SANDBOX_IMAGE = "mule-workspace:latest"

# Claude 认证文件路径 (宿主机)
CLAUDE_CONFIG_DIR = Path.home() / ".claude"
CLAUDE_CREDENTIALS_FILE = CLAUDE_CONFIG_DIR / ".credentials.json"

# 容器数据目录
CONTAINER_DATA_DIR = settings.data_dir / "containers"


class AcpSandboxAgent:
    """
    ACP + Docker 沙箱 Agent

    融合两种方案的优势：
    - ACP 协议：细粒度权限控制、本地/远程模式切换
    - Docker 沙箱：安全隔离、凭据管理、环境一致性
    """

    def __init__(
        self,
        workspace_path: str,
        workspace_id: str = "",
        agent_session_id: str = "",
        on_event: Optional[Callable[[dict], Any]] = None,
        on_permission_request: Optional[Callable[[dict], Any]] = None,
        permission_mode: str = "remote",
    ):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id
        self.permission_mode = permission_mode

        self._on_event = on_event
        self._on_permission_request = on_permission_request

        # 容器名称
        self.container_name = self._get_container_name()

        # 容器专属目录
        self.container_data_dir = CONTAINER_DATA_DIR / self.container_name
        self.container_claude_dir = self.container_data_dir / ".claude"

        # 会话 ID
        self.session_id: Optional[str] = None
        if workspace_id and agent_session_id:
            self.session_id = workspace_manager.get_session_id(workspace_id, agent_session_id)

        # 确保目录存在
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        # 活动日志
        self.activity_logger: Optional[AgentLogger] = None
        if workspace_id and agent_session_id:
            self.activity_logger = agent_logger_manager.get_logger(workspace_id, agent_session_id)

        # ACP 传输层（在容器内运行）
        self._transport: Optional[AcpTransport] = None

        # 权限适配器
        self._permission_adapter: Optional[PermissionAdapter] = None

        # 状态
        self._is_connected = False
        self._is_processing = False

    def _get_container_name(self) -> str:
        """生成容器名称"""
        import hashlib
        hash_input = f"{self.workspace_id}:{self.agent_session_id}"
        hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        return f"mule-acp-{hash_value}"

    def _setup_container_dirs(self):
        """准备容器目录"""
        self.container_claude_dir.mkdir(parents=True, exist_ok=True)

        # 复制凭据
        if CLAUDE_CREDENTIALS_FILE.exists():
            dst = self.container_claude_dir / ".credentials.json"
            shutil.copy2(CLAUDE_CREDENTIALS_FILE, dst)
            os.chmod(dst, 0o600)

        # 复制 .claude.json
        src_claude_json = Path.home() / ".claude.json"
        dst_claude_json = self.container_claude_dir / ".claude.json"
        if src_claude_json.exists() and not dst_claude_json.exists():
            shutil.copy2(src_claude_json, dst_claude_json)
            os.chmod(dst_claude_json, 0o666)

        os.chmod(self.container_claude_dir, 0o777)

    def _container_running(self) -> bool:
        """检查容器是否运行"""
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        return self.container_name in result.stdout.split('\n')

    def _ensure_container(self):
        """确保容器运行"""
        if self._container_running():
            return

        # 检查容器是否存在
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        if self.container_name in result.stdout.split('\n'):
            subprocess.run(["docker", "start", self.container_name], check=True)
            return

        # 创建新容器
        self._setup_container_dirs()

        host_uid = os.getuid()
        host_gid = os.getgid()

        import pwd
        host_user = pwd.getpwuid(host_uid).pw_name
        container_home = f"/home/{host_user}"

        docker_args = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "--user", f"{host_uid}:{host_gid}",
            "-v", f"{self.workspace_path}:/workspace",
            "-w", "/workspace",
            "-v", f"{self.container_claude_dir}:{container_home}/.claude",
            "-v", f"{self.container_claude_dir / '.claude.json'}:{container_home}/.claude.json",
            "-e", "DISABLE_TELEMETRY=1",
        ]

        # 传递环境变量
        if os.environ.get("ANTHROPIC_API_KEY"):
            docker_args.extend(["-e", f"ANTHROPIC_API_KEY={os.environ['ANTHROPIC_API_KEY']}"])

        for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
            if os.environ.get(proxy_var):
                docker_args.extend(["-e", f"{proxy_var}={os.environ[proxy_var]}"])

        docker_args.extend([SANDBOX_IMAGE, "sleep", "infinity"])

        subprocess.run(docker_args, check=True)
        logger.info(f"Container {self.container_name} created")

    async def _ensure_connected(self):
        """确保已连接"""
        if self._is_connected and self._transport and self._transport.is_connected:
            return

        # 确保容器运行
        self._ensure_container()

        # 创建传输层
        self._transport = AcpTransport()

        # 创建权限适配器
        if self.permission_mode == "remote" and self._on_permission_request:
            self._permission_adapter = PermissionAdapter(
                on_permission_request=self._on_permission_request,
            )

        # 在容器内启动 Claude Code
        command = [
            "docker", "exec", "-i",
            "-w", "/workspace",
            self.container_name,
            "claude",  # 假设容器内已安装 claude
        ]

        if self.permission_mode == "bypass":
            command.append("--dangerously-skip-permissions")

        await self._transport.connect(command=command)

        # 注册处理器
        self._transport.on_notification("sessionUpdate", self._handle_session_update)
        self._transport.on_notification("toolCall", self._handle_tool_call)
        self._transport.on_notification("toolCallUpdate", self._handle_tool_call_update)

        if self._permission_adapter:
            self._transport.on_request(
                "permissionRequest",
                self._permission_adapter.handle_permission_request
            )

        # 初始化
        try:
            await self._transport.send_request("initialize", {
                "protocolVersion": "1.0",
                "capabilities": {"permissions": self.permission_mode == "remote"},
            })
        except Exception as e:
            logger.warning(f"Initialize failed: {e}")

        self._is_connected = True
        logger.info(f"ACP Sandbox Agent connected: {self.container_name}")

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """执行 prompt"""
        self._is_processing = True

        try:
            await self._ensure_connected()

            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            yield {"event": "status", "data": {"type": "task_start", "message": "Starting..."}}

            prompt_params = {"text": prompt}
            if self.session_id:
                prompt_params["sessionId"] = self.session_id

            prompt_future = asyncio.create_task(
                self._transport.send_request("prompt", prompt_params)
            )

            yield {"event": "status", "data": {"type": "thinking", "message": "Thinking..."}}

            try:
                result = await prompt_future

                if result and isinstance(result, dict):
                    if "sessionId" in result:
                        self.session_id = result["sessionId"]
                        if self.workspace_id and self.agent_session_id:
                            workspace_manager.set_session_id(
                                self.workspace_id,
                                self.agent_session_id,
                                self.session_id
                            )

                    if self.activity_logger:
                        self.activity_logger.log_task_end(
                            success=not result.get("isError", False),
                            error=result.get("error") if result.get("isError") else None
                        )

                    yield {
                        "event": "message_end",
                        "data": {
                            "session_id": self.session_id,
                            "is_error": result.get("isError", False),
                            "result": result.get("result", ""),
                        }
                    }

            except AcpTransportError as e:
                logger.error(f"Prompt failed: {e}")
                yield {"event": "error", "data": {"message": str(e)}}

        except Exception as e:
            logger.error(f"Execution error: {e}", exc_info=True)
            yield {"event": "error", "data": {"message": str(e)}}

        finally:
            self._is_processing = False

    async def _handle_session_update(self, params: dict):
        """处理会话更新"""
        update_type = params.get("type", "")

        if update_type == "text" and self._on_event:
            await self._on_event({
                "event": "text_delta",
                "data": {"text": params.get("content", "")}
            })

    async def _handle_tool_call(self, params: dict):
        """处理工具调用"""
        if self.activity_logger:
            tool_name = params.get("name", "")
            tool_input = params.get("input", {})
            self._log_tool_use(tool_name, tool_input)

        if self._on_event:
            await self._on_event({
                "event": "tool_use_start",
                "data": {
                    "id": params.get("id"),
                    "name": params.get("name"),
                    "input": params.get("input"),
                }
            })

    async def _handle_tool_call_update(self, params: dict):
        """处理工具调用更新"""
        if params.get("status") == "completed" and self._on_event:
            await self._on_event({
                "event": "tool_result",
                "data": {
                    "id": params.get("id"),
                    "content": str(params.get("result", ""))[:300],
                    "is_error": params.get("isError", False),
                }
            })

    def _log_tool_use(self, tool_name: str, tool_input: dict):
        """记录工具使用"""
        if not self.activity_logger:
            return

        handlers = {
            "Read": lambda: self.activity_logger.log_file_read(tool_input.get("file_path", "")),
            "Write": lambda: self.activity_logger.log_file_write(tool_input.get("file_path", "")),
            "Edit": lambda: self.activity_logger.log_file_edit(tool_input.get("file_path", "")),
            "Bash": lambda: self.activity_logger.log_bash_exec(tool_input.get("command", "")),
        }

        handler = handlers.get(tool_name)
        if handler:
            handler()

    async def respond_permission(self, tool_use_id: str, decision: str, updated_input: dict = None):
        """响应权限请求"""
        if self._permission_adapter:
            try:
                decision_enum = PermissionDecision(decision)
                self._permission_adapter.respond(tool_use_id, decision_enum, updated_input)
            except ValueError:
                logger.error(f"Invalid decision: {decision}")

    async def cancel(self):
        """取消执行"""
        if self._transport and self._is_processing:
            try:
                await self._transport.send_request("cancel", {})
            except Exception as e:
                logger.error(f"Cancel failed: {e}")

            if self._permission_adapter:
                self._permission_adapter.cancel_all()

    async def compact(self) -> dict:
        """压缩上下文"""
        if not self.session_id:
            raise ValueError("No active session")

        await self._ensure_connected()
        result = await self._transport.send_request("compact", {"sessionId": self.session_id})
        return {"success": True, "result": result}

    async def disconnect(self):
        """断开连接"""
        if self._transport:
            await self._transport.disconnect()
            self._is_connected = False

    def stop_container(self):
        """停止容器"""
        if self._container_running():
            subprocess.run(["docker", "stop", self.container_name], check=False)

    def remove_container(self):
        """删除容器"""
        subprocess.run(["docker", "rm", "-f", self.container_name], check=False)

    def reset_session(self):
        """重置会话"""
        self.session_id = None
        if self._permission_adapter:
            self._permission_adapter.reset_session_permissions()

    def get_pending_permissions(self) -> list[dict]:
        """获取待处理权限"""
        if self._permission_adapter:
            return self._permission_adapter.get_pending_requests()
        return []

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_processing(self) -> bool:
        return self._is_processing
