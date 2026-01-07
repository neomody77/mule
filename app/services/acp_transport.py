"""
Claude Code Transport - 基于官方 SDK stream-json 协议的传输层

使用 Claude Code 官方支持的协议:
- --output-format stream-json: 流式 JSON 输出
- --input-format stream-json: 流式 JSON 输入
- --permission-prompt-tool stdio: 通过 stdio 处理权限请求

参考 HAPI 项目的实现: https://github.com/tiann/hapi
"""
import asyncio
import json
import logging
import os
import shutil
import random
import string
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ClaudeTransportError(Exception):
    """传输层错误"""
    pass


class ClaudeTransport:
    """
    Claude Code stream-json 传输层

    使用官方 SDK 的 stream-json 协议与 Claude Code 进程通信：
    - 输入: {"type": "user", "message": {"role": "user", "content": "..."}}
    - 输出: 各种 SDK 消息类型 (system, assistant, user, result, control_request 等)
    - 权限: control_request/control_response 消息
    """

    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._is_connected = False
        self._read_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None

        # 消息处理器
        self._message_handlers: dict[str, Callable] = {}  # type -> handler
        self._control_request_handler: Optional[Callable] = None  # 权限请求处理器

        # 待处理的控制请求
        self._pending_control_requests: dict[str, asyncio.Future] = {}

        # 消息队列 (用于流式输出)
        self._message_queue: asyncio.Queue = asyncio.Queue()

    @staticmethod
    def find_claude_cli() -> Optional[str]:
        """查找 Claude CLI 路径"""
        claude_path = shutil.which("claude")
        if claude_path:
            return claude_path

        common_paths = [
            Path.home() / ".local" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
            Path.home() / ".npm-global" / "bin" / "claude",
        ]
        for path in common_paths:
            if path.exists():
                return str(path)

        return None

    async def connect(
        self,
        cwd: str,
        session_id: Optional[str] = None,
        permission_mode: str = "default",
        model: Optional[str] = None,
        allowed_tools: Optional[list[str]] = None,
        disallowed_tools: Optional[list[str]] = None,
        mcp_servers: Optional[dict] = None,
        custom_command: Optional[list[str]] = None,
    ):
        """
        启动 Claude Code 子进程

        Args:
            cwd: 工作目录
            session_id: 会话 ID (用于恢复会话)
            permission_mode: 权限模式 (default, plan, bypassPermissions)
            model: 模型 (sonnet, opus)
            allowed_tools: 允许的工具列表
            disallowed_tools: 禁止的工具列表
            mcp_servers: MCP 服务器配置
            custom_command: 自定义命令 (用于 Docker)
        """
        if self._is_connected:
            raise ClaudeTransportError("Already connected")

        # 构建命令
        if custom_command:
            command = custom_command
        else:
            cli_path = self.find_claude_cli()
            if not cli_path:
                raise ClaudeTransportError("Claude CLI not found")
            command = [cli_path]

        # 添加必要参数
        command.extend([
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
        ])

        # 权限模式
        if permission_mode == "bypass":
            command.append("--dangerously-skip-permissions")
        else:
            # 使用 stdio 处理权限请求
            command.extend(["--permission-prompt-tool", "stdio"])
            if permission_mode and permission_mode != "default":
                command.extend(["--permission-mode", permission_mode])

        # 恢复会话
        if session_id:
            command.extend(["--resume", session_id])

        # 模型
        if model:
            command.extend(["--model", model])

        # 工具过滤
        if allowed_tools:
            command.extend(["--allowedTools", ",".join(allowed_tools)])
        if disallowed_tools:
            command.extend(["--disallowedTools", ",".join(disallowed_tools)])

        # 环境变量
        process_env = os.environ.copy()
        process_env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-python"
        process_env["DISABLE_AUTOUPDATER"] = "1"

        # MCP 服务器配置
        if mcp_servers:
            process_env["CLAUDE_SDK_MCP_SERVERS"] = json.dumps(mcp_servers)

        logger.info(f"Starting Claude Code: {' '.join(command)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
                cwd=cwd,
                limit=128 * 1024 * 1024,  # 128MB buffer
            )

            self._is_connected = True

            # 启动读取循环
            self._read_task = asyncio.create_task(self._read_loop())
            self._stderr_task = asyncio.create_task(self._stderr_loop())

            logger.info(f"Claude Code started, PID: {self._process.pid}")

        except Exception as e:
            logger.error(f"Failed to start Claude Code: {e}")
            raise ClaudeTransportError(f"Failed to start process: {e}")

    async def disconnect(self):
        """断开连接"""
        if not self._is_connected:
            return

        self._is_connected = False

        # 取消读取任务
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

        # 终止进程
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        # 清理待处理的控制请求
        for future in self._pending_control_requests.values():
            if not future.done():
                future.set_exception(ClaudeTransportError("Connection closed"))
        self._pending_control_requests.clear()

        logger.info("Claude Code connection closed")

    async def send_user_message(self, content: str):
        """
        发送用户消息

        Args:
            content: 消息内容
        """
        if not self._is_connected:
            raise ClaudeTransportError("Not connected")

        message = {
            "type": "user",
            "message": {
                "role": "user",
                "content": content,
            }
        }

        await self._write(message)
        logger.debug(f"Sent user message: {content[:100]}...")

    async def send_control_response(
        self,
        request_id: str,
        behavior: str,
        updated_input: Optional[dict] = None,
    ):
        """
        发送控制响应 (权限决策)

        Args:
            request_id: 请求 ID
            behavior: 行为 ("allow", "deny", "cancelled")
            updated_input: 可选的修改后输入
        """
        if not self._is_connected:
            raise ClaudeTransportError("Not connected")

        response = {
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": request_id,
                "response": {
                    "behavior": behavior,
                }
            }
        }

        if updated_input:
            response["response"]["response"]["updatedInput"] = updated_input

        await self._write(response)
        logger.debug(f"Sent control response: {request_id} -> {behavior}")

    async def send_interrupt(self):
        """发送中断请求"""
        if not self._is_connected:
            raise ClaudeTransportError("Not connected")

        request_id = self._generate_request_id()
        request = {
            "type": "control_request",
            "request_id": request_id,
            "request": {
                "subtype": "interrupt"
            }
        }

        await self._write(request)
        logger.debug("Sent interrupt request")

    def on_message(self, message_type: str, handler: Callable):
        """
        注册消息处理器

        Args:
            message_type: 消息类型 (system, assistant, user, result, etc.)
            handler: 异步处理函数 async def handler(message: dict)
        """
        self._message_handlers[message_type] = handler

    def on_control_request(self, handler: Callable):
        """
        注册控制请求处理器 (权限请求)

        Args:
            handler: 异步处理函数 async def handler(request: dict) -> dict
                     返回 {"behavior": "allow"/"deny", "updatedInput": {...}}
        """
        self._control_request_handler = handler

    async def get_next_message(self, timeout: Optional[float] = None) -> Optional[dict]:
        """
        获取下一条消息

        Args:
            timeout: 超时时间 (秒)

        Returns:
            消息字典，或 None (超时/关闭)
        """
        try:
            if timeout:
                return await asyncio.wait_for(self._message_queue.get(), timeout=timeout)
            else:
                return await self._message_queue.get()
        except asyncio.TimeoutError:
            return None

    async def _write(self, message: dict):
        """写入消息到 stdin"""
        if not self._process or not self._process.stdin:
            raise ClaudeTransportError("Process not available")

        data = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

    async def _read_loop(self):
        """持续读取 stdout 消息"""
        try:
            async for line in self._process.stdout:
                if not self._is_connected:
                    break

                line_text = line.decode().strip()
                if not line_text:
                    continue

                try:
                    message = json.loads(line_text)
                    await self._handle_message(message)
                except json.JSONDecodeError:
                    logger.debug(f"Non-JSON output: {line_text[:200]}")
                    continue

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Read loop error: {e}")

    async def _stderr_loop(self):
        """读取 stderr 日志"""
        try:
            async for line in self._process.stderr:
                line_text = line.decode().strip()
                if line_text:
                    logger.debug(f"[Claude stderr] {line_text}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Stderr loop error: {e}")

    async def _handle_message(self, message: dict):
        """处理收到的消息"""
        msg_type = message.get("type", "")

        # 控制响应 (我们发出的请求的响应)
        if msg_type == "control_response":
            response = message.get("response", {})
            request_id = response.get("request_id")
            if request_id in self._pending_control_requests:
                future = self._pending_control_requests.pop(request_id)
                if response.get("subtype") == "success":
                    future.set_result(response)
                else:
                    future.set_exception(ClaudeTransportError(response.get("error", "Unknown error")))
            return

        # 控制请求 (Claude 向我们请求权限)
        if msg_type == "control_request":
            await self._handle_control_request(message)
            return

        # 控制取消请求
        if msg_type == "control_cancel_request":
            request_id = message.get("request_id")
            logger.debug(f"Control cancel request: {request_id}")
            # 通知权限处理器取消
            return

        # 普通 SDK 消息 - 放入队列
        await self._message_queue.put(message)

        # 调用注册的处理器
        if msg_type in self._message_handlers:
            try:
                await self._message_handlers[msg_type](message)
            except Exception as e:
                logger.error(f"Message handler error for {msg_type}: {e}")

    async def _handle_control_request(self, message: dict):
        """处理控制请求 (权限请求)"""
        request_id = message.get("request_id", "")
        request = message.get("request", {})
        subtype = request.get("subtype", "")

        if subtype == "can_use_tool":
            tool_name = request.get("tool_name", "")
            tool_input = request.get("input", {})

            logger.info(f"Permission request: {tool_name} (id={request_id})")

            if self._control_request_handler:
                try:
                    # 调用权限处理器
                    result = await self._control_request_handler({
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                    })

                    # 发送响应
                    await self.send_control_response(
                        request_id=request_id,
                        behavior=result.get("behavior", "allow"),
                        updated_input=result.get("updatedInput"),
                    )
                except Exception as e:
                    logger.error(f"Permission handler error: {e}")
                    # 发送错误响应
                    await self._write({
                        "type": "control_response",
                        "response": {
                            "subtype": "error",
                            "request_id": request_id,
                            "error": str(e),
                        }
                    })
            else:
                # 没有处理器，默认允许
                logger.warning(f"No permission handler, auto-allowing: {tool_name}")
                await self.send_control_response(request_id, "allow")
        else:
            logger.warning(f"Unknown control request subtype: {subtype}")

    def _generate_request_id(self) -> str:
        """生成请求 ID"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected and self._process and self._process.returncode is None

    @property
    def pid(self) -> Optional[int]:
        """进程 PID"""
        return self._process.pid if self._process else None
