"""
Claude Code Agent - 基于官方 SDK stream-json 协议的 Agent

通过 Claude Code 官方 SDK 协议与 Claude Code 进程通信，支持：
- 流式消息输出
- 远程权限审批 (--permission-prompt-tool stdio)
- 会话恢复 (--resume)

参考 HAPI 项目的实现: https://github.com/tiann/hapi
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from app.services.acp_transport import ClaudeTransport, ClaudeTransportError
from app.services.permission_adapter import PermissionAdapter, PermissionDecision
from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager

logger = logging.getLogger(__name__)


class ClaudeAgent:
    """
    基于 Claude Code SDK 协议的 Agent

    特性：
    - 使用官方 stream-json 协议
    - 支持远程权限审批
    - 流式响应处理
    - 会话恢复
    """

    def __init__(
        self,
        workspace_path: str,
        workspace_id: str = "",
        agent_session_id: str = "",
        on_event: Optional[Callable[[dict], Any]] = None,
        on_permission_request: Optional[Callable[[dict], Any]] = None,
        permission_mode: str = "remote",  # "remote" | "bypass" | "local"
    ):
        """
        Args:
            workspace_path: 工作区路径
            workspace_id: 工作区 ID
            agent_session_id: Agent 会话 ID
            on_event: 事件回调（用于流式输出）
            on_permission_request: 权限请求回调（用于远程审批）
            permission_mode: 权限模式
                - "remote": 远程审批（发送到客户端）
                - "bypass": 跳过所有权限检查
                - "local": 本地终端交互（不适用于远程场景）
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id
        self.permission_mode = permission_mode

        self._on_event = on_event
        self._on_permission_request = on_permission_request

        # 会话 ID（用于恢复会话）
        self.session_id: Optional[str] = None
        if workspace_id and agent_session_id:
            self.session_id = workspace_manager.get_session_id(workspace_id, agent_session_id)
            if self.session_id:
                logger.info(f"Restored session {self.session_id}")

        # 确保工作区存在
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        # 活动日志记录器
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
        self._current_tool_calls: dict[str, dict] = {}  # tool_use_id -> tool info

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """
        执行用户提示，返回流式响应

        Yields:
            dict: 事件字典，格式为 {"event": str, "data": dict}
        """
        self._is_processing = True
        self._current_tool_calls.clear()

        try:
            # 创建传输层
            self._transport = ClaudeTransport()

            # 设置权限处理器
            if self.permission_mode == "remote" and self._on_permission_request:
                self._permission_adapter = PermissionAdapter(
                    on_permission_request=self._on_permission_request,
                )
                self._transport.on_control_request(self._handle_permission_request)

            # 连接
            await self._transport.connect(
                cwd=str(self.workspace_path),
                session_id=self.session_id,
                permission_mode="bypass" if self.permission_mode == "bypass" else "default",
            )

            logger.info(f"Executing prompt: {prompt[:100]}...")

            # 记录任务开始
            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            # 发送 task_start 状态
            yield {
                "event": "status",
                "data": {"type": "task_start", "message": "Starting task..."}
            }

            # 发送用户消息
            await self._transport.send_user_message(prompt)

            # 发送 thinking 状态
            yield {
                "event": "status",
                "data": {"type": "thinking", "message": "Thinking..."}
            }

            # 处理流式响应
            while True:
                message = await self._transport.get_next_message(timeout=300)  # 5 分钟超时

                if message is None:
                    # 超时或连接关闭
                    logger.warning("Message timeout or connection closed")
                    break

                msg_type = message.get("type", "")

                # 处理系统消息
                if msg_type == "system":
                    subtype = message.get("subtype", "")
                    if subtype == "init":
                        # 会话初始化，获取 session_id
                        new_session_id = message.get("session_id")
                        if new_session_id:
                            self.session_id = new_session_id
                            logger.info(f"Session started: {self.session_id}")
                            # 持久化 session_id
                            if self.workspace_id and self.agent_session_id:
                                workspace_manager.set_session_id(
                                    self.workspace_id,
                                    self.agent_session_id,
                                    self.session_id
                                )
                    continue

                # 处理 assistant 消息
                if msg_type == "assistant":
                    await self._handle_assistant_message(message)
                    # 提取文本内容
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
                            # 工具调用开始
                            tool_id = block.get("id", "")
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})
                            self._current_tool_calls[tool_id] = {
                                "name": tool_name,
                                "input": tool_input,
                            }
                            # 记录工具使用
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
                            # 截断过长的结果
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
                            # 清理
                            self._current_tool_calls.pop(tool_id, None)
                    continue

                # 处理结果消息
                if msg_type == "result":
                    is_error = message.get("is_error", False)
                    result_text = message.get("result", "")
                    duration_ms = message.get("duration_ms", 0)
                    num_turns = message.get("num_turns", 0)

                    # 记录任务结束
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
                            "duration_ms": duration_ms,
                            "num_turns": num_turns,
                        }
                    }
                    break  # 任务完成

        except ClaudeTransportError as e:
            logger.error(f"Transport error: {e}")
            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))
            yield {
                "event": "error",
                "data": {"message": str(e)}
            }

        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)
            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))
            yield {
                "event": "error",
                "data": {"message": str(e)}
            }

        finally:
            self._is_processing = False
            # 断开连接
            if self._transport:
                await self._transport.disconnect()
                self._transport = None

    async def _handle_assistant_message(self, message: dict):
        """处理 assistant 消息"""
        # 可以在这里添加额外的处理逻辑
        pass

    async def _handle_permission_request(self, request: dict) -> dict:
        """
        处理权限请求

        Args:
            request: {"request_id": str, "tool_name": str, "tool_input": dict}

        Returns:
            {"behavior": "allow"/"deny", "updatedInput": dict (optional)}
        """
        request_id = request.get("request_id", "")
        tool_name = request.get("tool_name", "")
        tool_input = request.get("tool_input", {})

        logger.info(f"Permission request: {tool_name} (id={request_id})")

        if self._permission_adapter:
            # 创建 Future 等待响应
            future = asyncio.get_event_loop().create_future()
            self._pending_permissions[request_id] = future

            # 发送权限请求到客户端
            try:
                decision = await self._permission_adapter.handle_permission_request({
                    "tool_use_id": request_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "description": self._get_tool_description(tool_name, tool_input),
                })

                # 转换为 SDK 格式
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

            finally:
                self._pending_permissions.pop(request_id, None)
        else:
            # 没有权限适配器，默认允许
            return {"behavior": "allow"}

    async def respond_permission(
        self,
        tool_use_id: str,
        decision: str,
        updated_input: Optional[dict] = None,
    ):
        """
        响应权限请求

        Args:
            tool_use_id: 工具调用 ID
            decision: 决策 ("approved", "approved_for_session", "denied", "abort")
            updated_input: 可选的修改后输入
        """
        if self._permission_adapter:
            try:
                decision_enum = PermissionDecision(decision)
            except ValueError:
                logger.error(f"Invalid decision: {decision}")
                return
            self._permission_adapter.respond(tool_use_id, decision_enum, updated_input)

    def _log_tool_use(self, tool_name: str, tool_input: dict):
        """记录工具使用到活动日志"""
        if not self.activity_logger:
            return

        log_handlers = {
            "Read": lambda: self.activity_logger.log_file_read(tool_input.get("file_path", "")),
            "Write": lambda: self.activity_logger.log_file_write(
                tool_input.get("file_path", ""),
                size=len(tool_input.get("content", "")),
                is_new=True
            ),
            "Edit": lambda: self.activity_logger.log_file_edit(
                tool_input.get("file_path", ""),
                changes={
                    "old_len": len(tool_input.get("old_string", "")),
                    "new_len": len(tool_input.get("new_string", ""))
                }
            ),
            "Bash": lambda: self.activity_logger.log_bash_exec(tool_input.get("command", "")),
            "Glob": lambda: self.activity_logger.log_glob(tool_input.get("pattern", "")),
            "Grep": lambda: self.activity_logger.log_grep(
                tool_input.get("pattern", ""),
                tool_input.get("path", "")
            ),
        }

        handler = log_handlers.get(tool_name)
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

    async def cancel(self):
        """取消当前执行"""
        if self._transport and self._is_processing:
            logger.info("Cancelling current task...")
            try:
                await self._transport.send_interrupt()
            except Exception as e:
                logger.error(f"Cancel failed: {e}")

            # 取消所有待处理的权限请求
            if self._permission_adapter:
                self._permission_adapter.cancel_all("task cancelled")

    async def compact(self) -> dict:
        """压缩上下文 (通过发送 /compact 命令)"""
        if not self.session_id:
            raise ValueError("No active session to compact")

        logger.info(f"Compacting context for session {self.session_id}")

        # 创建新的传输层发送 /compact
        transport = ClaudeTransport()
        try:
            await transport.connect(
                cwd=str(self.workspace_path),
                session_id=self.session_id,
                permission_mode="bypass",
            )

            await transport.send_user_message("/compact")

            # 等待结果
            result_text = ""
            while True:
                message = await transport.get_next_message(timeout=60)
                if message is None:
                    break
                if message.get("type") == "result":
                    result_text = message.get("result", "Context compacted")
                    break

            return {
                "success": True,
                "session_id": self.session_id,
                "result": result_text,
            }

        finally:
            await transport.disconnect()

    def reset_session(self):
        """重置会话"""
        self.session_id = None
        if self._permission_adapter:
            self._permission_adapter.reset_session_permissions()

    def get_pending_permissions(self) -> list[dict]:
        """获取待处理的权限请求"""
        if self._permission_adapter:
            return self._permission_adapter.get_pending_requests()
        return []

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._is_processing


# 别名，保持兼容
AcpAgent = ClaudeAgent
