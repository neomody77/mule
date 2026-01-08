"""
ACP Agent - 基于 ACP 协议的 Claude Code Agent

通过 ACP (Agent Client Protocol) 直接与 Claude Code 进程通信，
提供协议级别的控制能力，包括：
- 细粒度权限控制
- 完整的消息流处理
- 本地/远程模式切换支持
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from app.services.acp_transport import AcpTransport, AcpTransportError
from app.services.permission_adapter import PermissionAdapter, PermissionDecision
from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager

logger = logging.getLogger(__name__)


class AcpAgent:
    """
    基于 ACP 协议的 Claude Code Agent

    特性：
    - 直接使用 JSON-RPC 协议与 Claude Code 通信
    - 支持远程权限审批
    - 支持本地/远程模式切换
    - 流式响应处理
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

        # ACP 传输层
        self._transport: Optional[AcpTransport] = None

        # 权限适配器
        self._permission_adapter: Optional[PermissionAdapter] = None

        # 状态
        self._is_connected = False
        self._is_processing = False
        self._current_tool_calls: dict[str, dict] = {}  # tool_use_id -> tool info

    async def _ensure_connected(self):
        """确保已连接到 Claude Code"""
        if self._is_connected and self._transport and self._transport.is_connected:
            return

        # 创建传输层
        self._transport = AcpTransport()

        # 创建权限适配器
        if self.permission_mode == "remote" and self._on_permission_request:
            self._permission_adapter = PermissionAdapter(
                on_permission_request=self._on_permission_request,
            )

        # 构建启动命令
        cli_path = AcpTransport.find_claude_cli()
        if not cli_path:
            raise AcpTransportError("Claude CLI not found")

        command = [cli_path]

        # 根据权限模式添加参数
        if self.permission_mode == "bypass":
            command.append("--dangerously-skip-permissions")

        # 环境变量
        env = {
            "CLAUDE_CODE_ENTRYPOINT": "acp",  # 使用 ACP 模式
        }

        # 连接
        await self._transport.connect(
            command=command,
            env=env,
            cwd=str(self.workspace_path),
        )

        # 注册消息处理器
        self._transport.on_notification("sessionUpdate", self._handle_session_update)
        self._transport.on_notification("toolCall", self._handle_tool_call)
        self._transport.on_notification("toolCallUpdate", self._handle_tool_call_update)

        # 注册权限请求处理器（如果启用远程审批）
        if self._permission_adapter:
            self._transport.on_request(
                "permissionRequest",
                self._permission_adapter.handle_permission_request
            )

        # 发送初始化请求
        try:
            init_result = await self._transport.send_request("initialize", {
                "protocolVersion": "1.0",
                "clientInfo": {
                    "name": "mule",
                    "version": "1.0.0",
                },
                "capabilities": {
                    "permissions": self.permission_mode == "remote",
                    "streaming": True,
                },
            })
            logger.info(f"ACP initialized: {init_result}")
        except Exception as e:
            logger.warning(f"Initialize request failed (may not be supported): {e}")

        self._is_connected = True
        logger.info(f"ACP Agent connected for {self.workspace_id}:{self.agent_session_id}")

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """
        执行用户提示，返回流式响应

        Yields:
            dict: 事件字典，格式为 {"event": str, "data": dict}
        """
        self._is_processing = True
        self._current_tool_calls.clear()

        try:
            await self._ensure_connected()

            logger.info(f"Executing prompt: {prompt[:100]}...")

            # 记录任务开始
            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            # 发送 task_start 状态
            yield {
                "event": "status",
                "data": {"type": "task_start", "message": "Starting task..."}
            }

            # 构建 prompt 请求参数
            prompt_params = {
                "text": prompt,
            }

            # 如果有会话 ID，添加 resume
            if self.session_id:
                prompt_params["sessionId"] = self.session_id

            # 发送 prompt
            # 注意：这里我们不等待响应，而是通过通知接收流式输出
            prompt_future = asyncio.create_task(
                self._transport.send_request("prompt", prompt_params)
            )

            # 发送 thinking 状态
            yield {
                "event": "status",
                "data": {"type": "thinking", "message": "Thinking..."}
            }

            # 等待 prompt 完成
            try:
                result = await prompt_future

                # 更新 session_id
                if result and isinstance(result, dict):
                    if "sessionId" in result:
                        self.session_id = result["sessionId"]
                        # 持久化 session_id
                        if self.workspace_id and self.agent_session_id:
                            workspace_manager.set_session_id(
                                self.workspace_id,
                                self.agent_session_id,
                                self.session_id
                            )

                    # 记录任务结束
                    is_error = result.get("isError", False)
                    if self.activity_logger:
                        self.activity_logger.log_task_end(
                            success=not is_error,
                            error=result.get("error") if is_error else None
                        )

                    # 提取 usage 信息
                    usage_data = {}
                    raw_usage = result.get("usage")
                    if raw_usage and isinstance(raw_usage, dict):
                        total_input = 0
                        total_output = 0
                        context_window = 200000
                        for model_name, model_usage in raw_usage.items():
                            if isinstance(model_usage, dict):
                                total_input += model_usage.get("inputTokens", 0)
                                total_output += model_usage.get("outputTokens", 0)
                                total_input += model_usage.get("cacheReadInputTokens", 0)
                                if model_usage.get("contextWindow"):
                                    context_window = model_usage["contextWindow"]
                        usage_data = {
                            "input_tokens": total_input,
                            "output_tokens": total_output,
                            "context_window": context_window,
                        }

                    yield {
                        "event": "message_end",
                        "data": {
                            "session_id": self.session_id,
                            "is_error": is_error,
                            "result": result.get("result", ""),
                            "duration_ms": result.get("durationMs", 0),
                            "num_turns": result.get("numTurns", 0),
                            "total_cost_usd": result.get("totalCostUsd", 0),
                            "usage": usage_data,
                        }
                    }

            except AcpTransportError as e:
                logger.error(f"Prompt failed: {e}")
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

    async def _handle_session_update(self, params: dict):
        """处理会话更新通知"""
        update_type = params.get("type", "")

        if update_type == "text":
            # 文本输出
            text = params.get("content", "")
            if text and self._on_event:
                await self._on_event({
                    "event": "text_delta",
                    "data": {"text": text}
                })

        elif update_type == "thinking":
            # 思考过程（可选择是否显示）
            if self._on_event:
                await self._on_event({
                    "event": "thinking",
                    "data": {"content": params.get("content", "")}
                })

        elif update_type == "result":
            # 结果
            if self._on_event:
                await self._on_event({
                    "event": "result",
                    "data": params
                })

    async def _handle_tool_call(self, params: dict):
        """处理工具调用通知"""
        tool_use_id = params.get("id", "")
        tool_name = params.get("name", "")
        tool_input = params.get("input", {})

        # 记录工具调用
        self._current_tool_calls[tool_use_id] = {
            "name": tool_name,
            "input": tool_input,
        }

        # 记录日志
        if self.activity_logger:
            self._log_tool_use(tool_name, tool_input)

        # 发送事件
        if self._on_event:
            await self._on_event({
                "event": "tool_use_start",
                "data": {
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                    "description": self._get_tool_description(tool_name, tool_input),
                }
            })

    async def _handle_tool_call_update(self, params: dict):
        """处理工具调用更新通知"""
        tool_use_id = params.get("id", "")
        status = params.get("status", "")

        if status == "completed":
            result = params.get("result", "")
            is_error = params.get("isError", False)

            # 截断过长的结果
            display_result = result
            if isinstance(result, str) and len(result) > 300:
                display_result = result[:300] + "..."

            if self._on_event:
                await self._on_event({
                    "event": "tool_result",
                    "data": {
                        "id": tool_use_id,
                        "content": display_result,
                        "is_error": is_error,
                    }
                })

            # 清理
            self._current_tool_calls.pop(tool_use_id, None)

        elif status == "progress":
            # 进度更新
            if self._on_event:
                await self._on_event({
                    "event": "tool_progress",
                    "data": {
                        "id": tool_use_id,
                        "progress": params.get("progress", {}),
                    }
                })

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
        if not self._permission_adapter:
            logger.warning("Permission adapter not available")
            return

        try:
            decision_enum = PermissionDecision(decision)
        except ValueError:
            logger.error(f"Invalid decision: {decision}")
            return

        self._permission_adapter.respond(tool_use_id, decision_enum, updated_input)

    async def cancel(self):
        """取消当前执行"""
        if self._transport and self._is_processing:
            logger.info("Cancelling current task...")
            try:
                await self._transport.send_request("cancel", {})
            except Exception as e:
                logger.error(f"Cancel failed: {e}")

            # 取消所有待处理的权限请求
            if self._permission_adapter:
                self._permission_adapter.cancel_all("task cancelled")

    async def compact(self) -> dict:
        """压缩上下文"""
        if not self.session_id:
            raise ValueError("No active session to compact")

        logger.info(f"Compacting context for session {self.session_id}")

        try:
            await self._ensure_connected()

            result = await self._transport.send_request("compact", {
                "sessionId": self.session_id,
            })

            return {
                "success": True,
                "session_id": self.session_id,
                "result": result.get("result", "Context compacted"),
            }

        except Exception as e:
            logger.error(f"Compact failed: {e}")
            raise

    async def disconnect(self):
        """断开连接"""
        if self._transport:
            await self._transport.disconnect()
            self._is_connected = False
            logger.info("ACP Agent disconnected")

    def reset_session(self):
        """重置会话"""
        self.session_id = None
        if self._permission_adapter:
            self._permission_adapter.reset_session_permissions()
        asyncio.create_task(self.disconnect())

    def get_pending_permissions(self) -> list[dict]:
        """获取待处理的权限请求"""
        if self._permission_adapter:
            return self._permission_adapter.get_pending_requests()
        return []

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._is_processing
