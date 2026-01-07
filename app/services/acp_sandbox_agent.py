"""
Claude Sandbox Agent - Claude Code SDK 协议 + Docker 沙箱隔离

结合 Claude Code SDK 的流式协议和 Docker 沙箱的安全隔离：
- 远程权限审批 (--permission-prompt-tool stdio)
- Docker 容器隔离
- OAuth Token 自动刷新

参考 HAPI 项目的实现: https://github.com/tiann/hapi
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from app.services.acp_transport import ClaudeTransport, ClaudeTransportError
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


class ClaudeSandboxAgent:
    """
    Claude Code SDK + Docker 沙箱 Agent

    融合两种方案的优势：
    - Claude Code SDK：官方流式协议、远程权限审批
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

        # 传输层
        self._transport: Optional[ClaudeTransport] = None

        # 权限适配器
        self._permission_adapter: Optional[PermissionAdapter] = None

        # 待处理的权限请求
        self._pending_permissions: dict[str, asyncio.Future] = {}

        # 状态
        self._is_processing = False
        self._current_tool_calls: dict[str, dict] = {}

    def _get_container_name(self) -> str:
        """生成容器名称"""
        import hashlib
        hash_input = f"{self.workspace_id}:{self.agent_session_id}"
        hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        return f"mule-sandbox-{hash_value}"

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
            "-e", "DISABLE_AUTOUPDATER=1",
            "-e", "CLAUDE_CODE_ENTRYPOINT=sdk-python",
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

    def _build_docker_command(self) -> list[str]:
        """构建 Docker exec 命令"""
        command = [
            "docker", "exec", "-i",
            "-w", "/workspace",
            self.container_name,
            "claude",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
        ]

        # 权限模式
        if self.permission_mode == "bypass":
            command.append("--dangerously-skip-permissions")
        else:
            command.extend(["--permission-prompt-tool", "stdio"])

        # 恢复会话
        if self.session_id:
            command.extend(["--resume", self.session_id])

        return command

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """执行 prompt"""
        self._is_processing = True
        self._current_tool_calls.clear()

        try:
            # 确保容器运行
            self._ensure_container()

            # 创建传输层
            self._transport = ClaudeTransport()

            # 设置权限处理器
            if self.permission_mode == "remote" and self._on_permission_request:
                self._permission_adapter = PermissionAdapter(
                    on_permission_request=self._on_permission_request,
                )
                self._transport.on_control_request(self._handle_permission_request)

            # 连接 (使用 Docker exec)
            docker_command = self._build_docker_command()
            await self._transport.connect(
                cwd=str(self.workspace_path),
                custom_command=docker_command,
            )

            logger.info(f"Executing in sandbox: {prompt[:100]}...")

            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            yield {"event": "status", "data": {"type": "task_start", "message": "Starting..."}}

            # 发送用户消息
            await self._transport.send_user_message(prompt)

            yield {"event": "status", "data": {"type": "thinking", "message": "Thinking..."}}

            # 处理流式响应
            while True:
                message = await self._transport.get_next_message(timeout=300)

                if message is None:
                    logger.warning("Message timeout or connection closed")
                    break

                msg_type = message.get("type", "")

                # 处理系统消息
                if msg_type == "system":
                    subtype = message.get("subtype", "")
                    if subtype == "init":
                        new_session_id = message.get("session_id")
                        if new_session_id:
                            self.session_id = new_session_id
                            logger.info(f"Session started: {self.session_id}")
                            if self.workspace_id and self.agent_session_id:
                                workspace_manager.set_session_id(
                                    self.workspace_id,
                                    self.agent_session_id,
                                    self.session_id
                                )
                    continue

                # 处理 assistant 消息
                if msg_type == "assistant":
                    content = message.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield {
                                    "event": "text_delta",
                                    "data": {"text": text}
                                }
                        elif block.get("type") == "tool_use":
                            tool_id = block.get("id", "")
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})
                            self._current_tool_calls[tool_id] = {
                                "name": tool_name,
                                "input": tool_input,
                            }
                            self._log_tool_use(tool_name, tool_input)
                            yield {
                                "event": "tool_use_start",
                                "data": {
                                    "id": tool_id,
                                    "name": tool_name,
                                    "input": tool_input,
                                    "description": self._get_tool_description(tool_name, tool_input),
                                }
                            }
                    continue

                # 处理 user 消息 (工具结果)
                if msg_type == "user":
                    content = message.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "tool_result":
                            tool_id = block.get("tool_use_id", "")
                            result = block.get("content", "")
                            is_error = block.get("is_error", False)
                            display_result = result
                            if isinstance(result, str) and len(result) > 300:
                                display_result = result[:300] + "..."
                            yield {
                                "event": "tool_result",
                                "data": {
                                    "id": tool_id,
                                    "content": display_result,
                                    "is_error": is_error,
                                }
                            }
                            self._current_tool_calls.pop(tool_id, None)
                    continue

                # 处理结果消息
                if msg_type == "result":
                    is_error = message.get("is_error", False)
                    result_text = message.get("result", "")

                    if self.activity_logger:
                        self.activity_logger.log_task_end(
                            success=not is_error,
                            error=result_text if is_error else None
                        )

                    yield {
                        "event": "message_end",
                        "data": {
                            "session_id": self.session_id,
                            "is_error": is_error,
                            "result": result_text,
                            "duration_ms": message.get("duration_ms", 0),
                            "num_turns": message.get("num_turns", 0),
                        }
                    }
                    break

        except ClaudeTransportError as e:
            logger.error(f"Transport error: {e}")
            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))
            yield {"event": "error", "data": {"message": str(e)}}

        except Exception as e:
            logger.error(f"Execution error: {e}", exc_info=True)
            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))
            yield {"event": "error", "data": {"message": str(e)}}

        finally:
            self._is_processing = False
            if self._transport:
                await self._transport.disconnect()
                self._transport = None

    async def _handle_permission_request(self, request: dict) -> dict:
        """处理权限请求"""
        request_id = request.get("request_id", "")
        tool_name = request.get("tool_name", "")
        tool_input = request.get("tool_input", {})

        logger.info(f"Permission request: {tool_name} (id={request_id})")

        if self._permission_adapter:
            try:
                decision = await self._permission_adapter.handle_permission_request({
                    "tool_use_id": request_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "description": self._get_tool_description(tool_name, tool_input),
                })

                if decision.get("approved"):
                    return {
                        "behavior": "allow",
                        "updatedInput": decision.get("updated_input"),
                    }
                else:
                    return {"behavior": "deny"}

            except asyncio.TimeoutError:
                logger.warning(f"Permission request timeout: {request_id}")
                return {"behavior": "deny"}

            except Exception as e:
                logger.error(f"Permission request error: {e}")
                return {"behavior": "deny"}
        else:
            return {"behavior": "allow"}

    def _log_tool_use(self, tool_name: str, tool_input: dict):
        """记录工具使用"""
        if not self.activity_logger:
            return

        handlers = {
            "Read": lambda: self.activity_logger.log_file_read(tool_input.get("file_path", "")),
            "Write": lambda: self.activity_logger.log_file_write(
                tool_input.get("file_path", ""),
                size=len(tool_input.get("content", "")),
                is_new=True
            ),
            "Edit": lambda: self.activity_logger.log_file_edit(
                tool_input.get("file_path", ""),
                changes={}
            ),
            "Bash": lambda: self.activity_logger.log_bash_exec(tool_input.get("command", "")),
            "Glob": lambda: self.activity_logger.log_glob(tool_input.get("pattern", "")),
            "Grep": lambda: self.activity_logger.log_grep(
                tool_input.get("pattern", ""),
                tool_input.get("path", "")
            ),
        }

        handler = handlers.get(tool_name)
        if handler:
            handler()

    def _get_tool_description(self, tool_name: str, tool_input: dict) -> str:
        """生成用户友好的工具描述"""
        def _truncate(s: str, max_len: int = 50) -> str:
            return s[:max_len - 3] + "..." if len(s) > max_len else s

        def _get_filename(path: str) -> str:
            return path.split("/")[-1] if path else "file"

        generators = {
            "Read": lambda: f"Reading {_get_filename(tool_input.get('file_path', ''))}...",
            "Write": lambda: f"Writing {_get_filename(tool_input.get('file_path', ''))}...",
            "Edit": lambda: f"Editing {_get_filename(tool_input.get('file_path', ''))}...",
            "Bash": lambda: f"Running: {_truncate(tool_input.get('command', ''))}",
            "Glob": lambda: f"Searching: {tool_input.get('pattern', '')}",
            "Grep": lambda: f"Grep: {tool_input.get('pattern', '')}",
            "WebSearch": lambda: f"Searching: {tool_input.get('query', '')}",
            "WebFetch": lambda: f"Fetching: {_truncate(tool_input.get('url', ''))}",
            "Task": lambda: f"Task: {tool_input.get('description', '')}",
        }

        generator = generators.get(tool_name)
        return generator() if generator else f"Using {tool_name}..."

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
                await self._transport.send_interrupt()
            except Exception as e:
                logger.error(f"Cancel failed: {e}")

            if self._permission_adapter:
                self._permission_adapter.cancel_all("task cancelled")

    async def compact(self) -> dict:
        """压缩上下文"""
        if not self.session_id:
            raise ValueError("No active session")

        # 确保容器运行
        self._ensure_container()

        transport = ClaudeTransport()
        try:
            docker_command = [
                "docker", "exec", "-i",
                "-w", "/workspace",
                self.container_name,
                "claude",
                "--output-format", "stream-json",
                "--input-format", "stream-json",
                "--dangerously-skip-permissions",
                "--resume", self.session_id,
            ]

            await transport.connect(
                cwd=str(self.workspace_path),
                custom_command=docker_command,
            )

            await transport.send_user_message("/compact")

            result_text = ""
            while True:
                message = await transport.get_next_message(timeout=60)
                if message is None:
                    break
                if message.get("type") == "result":
                    result_text = message.get("result", "Context compacted")
                    break

            return {"success": True, "session_id": self.session_id, "result": result_text}

        finally:
            await transport.disconnect()

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
    def is_processing(self) -> bool:
        return self._is_processing


# 别名，保持兼容
AcpSandboxAgent = ClaudeSandboxAgent
