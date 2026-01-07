"""
ACP Transport - JSON-RPC 2.0 over stdio 传输层

实现与 Claude Code 的 ACP (Agent Client Protocol) 通信，
参考 HAPI 的实现，提供协议级别的控制能力。
"""
import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class AcpTransportError(Exception):
    """ACP 传输层错误"""
    pass


class AcpTransport:
    """
    JSON-RPC 2.0 over stdio 传输层

    用于与 Claude Code 进程进行双向通信，支持：
    - 请求-响应模式
    - 单向通知
    - 远程请求处理（如权限请求）
    """

    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._notification_handlers: dict[str, Callable] = {}
        self._request_handlers: dict[str, Callable] = {}
        self._is_connected = False
        self._read_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._protocol_error = False

    @staticmethod
    def find_claude_cli() -> Optional[str]:
        """查找 Claude CLI 路径"""
        # 尝试从 PATH 中查找
        claude_path = shutil.which("claude")
        if claude_path:
            return claude_path

        # 常见安装路径
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
        command: Optional[list[str]] = None,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
    ):
        """
        启动 Claude Code 子进程并建立连接

        Args:
            command: 启动命令，默认为 ["claude", "--acp"]
            env: 环境变量
            cwd: 工作目录
        """
        if self._is_connected:
            raise AcpTransportError("Already connected")

        # 默认命令
        if command is None:
            cli_path = self.find_claude_cli()
            if not cli_path:
                raise AcpTransportError("Claude CLI not found")
            # 使用 print 模式，带 JSON 输出，跳过权限（由我们自己处理）
            command = [cli_path]

        # 合并环境变量
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        logger.info(f"Starting ACP process: {' '.join(command)}")

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

            # 启动消息读取循环
            self._read_task = asyncio.create_task(self._read_loop())
            self._stderr_task = asyncio.create_task(self._stderr_loop())

            logger.info(f"ACP process started, PID: {self._process.pid}")

        except Exception as e:
            logger.error(f"Failed to start ACP process: {e}")
            raise AcpTransportError(f"Failed to start process: {e}")

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

        # 拒绝所有待处理请求
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(AcpTransportError("Connection closed"))
        self._pending_requests.clear()

        logger.info("ACP connection closed")

    async def send_request(self, method: str, params: Optional[dict] = None) -> Any:
        """
        发送 JSON-RPC 请求并等待响应

        Args:
            method: 方法名
            params: 参数

        Returns:
            响应结果
        """
        if not self._is_connected:
            raise AcpTransportError("Not connected")

        if self._protocol_error:
            raise AcpTransportError("Protocol error occurred")

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        # 创建 Future 等待响应
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            await self._write(request)
            logger.debug(f"Sent request: {method} (id={request_id})")
            return await future
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            raise

    async def send_notification(self, method: str, params: Optional[dict] = None):
        """
        发送单向通知（不等待响应）

        Args:
            method: 方法名
            params: 参数
        """
        if not self._is_connected:
            raise AcpTransportError("Not connected")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            notification["params"] = params

        await self._write(notification)
        logger.debug(f"Sent notification: {method}")

    def on_notification(self, method: str, handler: Callable):
        """
        注册通知处理器

        Args:
            method: 方法名
            handler: 异步处理函数 async def handler(params: dict)
        """
        self._notification_handlers[method] = handler
        logger.debug(f"Registered notification handler: {method}")

    def on_request(self, method: str, handler: Callable):
        """
        注册请求处理器（用于处理远程请求，如权限请求）

        Args:
            method: 方法名
            handler: 异步处理函数 async def handler(params: dict) -> dict
        """
        self._request_handlers[method] = handler
        logger.debug(f"Registered request handler: {method}")

    def remove_handler(self, method: str):
        """移除处理器"""
        self._notification_handlers.pop(method, None)
        self._request_handlers.pop(method, None)

    async def _write(self, message: dict):
        """写入消息到 stdin"""
        if not self._process or not self._process.stdin:
            raise AcpTransportError("Process not available")

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
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON: {line_text[:100]}")
                    continue

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Read loop error: {e}")
            self._protocol_error = True

    async def _stderr_loop(self):
        """读取 stderr 日志"""
        try:
            async for line in self._process.stderr:
                line_text = line.decode().strip()
                if line_text:
                    logger.warning(f"[Claude stderr] {line_text}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Stderr loop error: {e}")

    async def _handle_message(self, message: dict):
        """处理收到的消息"""
        # JSON-RPC 响应
        if "id" in message and ("result" in message or "error" in message):
            request_id = message["id"]
            if request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if "error" in message:
                    error = message["error"]
                    future.set_exception(AcpTransportError(
                        f"{error.get('message', 'Unknown error')} (code={error.get('code')})"
                    ))
                else:
                    future.set_result(message.get("result"))
            return

        # JSON-RPC 请求（远程调用我们）
        if "id" in message and "method" in message:
            method = message["method"]
            params = message.get("params", {})
            request_id = message["id"]

            if method in self._request_handlers:
                try:
                    result = await self._request_handlers[method](params)
                    await self._write({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result
                    })
                except Exception as e:
                    logger.error(f"Request handler error for {method}: {e}")
                    await self._write({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": str(e)
                        }
                    })
            else:
                logger.warning(f"No handler for request: {method}")
                await self._write({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                })
            return

        # JSON-RPC 通知
        if "method" in message and "id" not in message:
            method = message["method"]
            params = message.get("params", {})

            if method in self._notification_handlers:
                try:
                    await self._notification_handlers[method](params)
                except Exception as e:
                    logger.error(f"Notification handler error for {method}: {e}")
            else:
                logger.debug(f"No handler for notification: {method}")
            return

        logger.warning(f"Unknown message format: {message}")

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected and self._process and self._process.returncode is None

    @property
    def pid(self) -> Optional[int]:
        """进程 PID"""
        return self._process.pid if self._process else None
