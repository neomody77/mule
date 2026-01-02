"""
WebSocket 客户端 - 连接到 Mule 服务器实现实时同步
"""
import asyncio
import json
import logging
from typing import Callable, Optional
from urllib.parse import urljoin

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class MuleWebSocketClient:
    """
    连接到 Mule 服务器的 WebSocket 客户端

    功能:
    - 发送消息到服务器（同步到移动端）
    - 接收远程消息（来自移动端的输入）
    - 处理权限请求响应
    """

    def __init__(
        self,
        server_url: str,
        token: str,
        session_id: Optional[str] = None,
    ):
        """
        Args:
            server_url: Mule 服务器地址 (如 ws://192.168.1.100:8989)
            token: 认证 token
            session_id: 会话 ID
        """
        self.server_url = server_url.rstrip('/')
        self.token = token
        self.session_id = session_id

        self._ws: Optional[WebSocketClientProtocol] = None
        self._is_connected = False
        self._receive_task: Optional[asyncio.Task] = None

        # 回调函数
        self.on_remote_message: Optional[Callable[[dict], None]] = None
        self.on_permission_response: Optional[Callable[[str, dict], None]] = None
        self.on_interrupt: Optional[Callable[[], None]] = None

        # 待处理的权限请求
        self._pending_permissions: dict[str, asyncio.Future] = {}

    @property
    def ws_url(self) -> str:
        """构建 WebSocket URL"""
        # 将 http:// 转换为 ws://
        url = self.server_url
        if url.startswith('http://'):
            url = 'ws://' + url[7:]
        elif url.startswith('https://'):
            url = 'wss://' + url[8:]
        elif not url.startswith('ws://') and not url.startswith('wss://'):
            url = 'ws://' + url

        return f"{url}/ws/cli?token={self.token}"

    async def connect(self) -> bool:
        """连接到服务器"""
        try:
            logger.info(f"Connecting to {self.ws_url}")
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=25,
                ping_timeout=10,
            )
            self._is_connected = True
            logger.info("Connected to Mule server")

            # 启动接收任务
            self._receive_task = asyncio.create_task(self._receive_loop())

            # 发送初始化消息
            await self.send({
                'type': 'cli_init',
                'session_id': self.session_id,
            })

            return True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        self._is_connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        logger.info("Disconnected from Mule server")

    async def send(self, message: dict) -> None:
        """发送消息到服务器"""
        if not self._is_connected or not self._ws:
            logger.warning("Not connected, cannot send message")
            return

        try:
            await self._ws.send(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def send_message(self, msg_type: str, data: dict) -> None:
        """发送格式化消息"""
        await self.send({
            'type': 'cli_message',
            'session_id': self.session_id,
            'message_type': msg_type,
            'data': data,
        })

    async def request_permission(self, permission_data: dict) -> dict:
        """
        发送权限请求并等待响应

        Args:
            permission_data: 权限请求数据 (tool_name, tool_input, tool_use_id)

        Returns:
            权限响应 (behavior: allow/deny, updatedInput, etc.)
        """
        tool_use_id = permission_data.get('tool_use_id', '')

        # 创建 Future 等待响应
        future = asyncio.get_event_loop().create_future()
        self._pending_permissions[tool_use_id] = future

        # 发送权限请求
        await self.send({
            'type': 'permission_request',
            'session_id': self.session_id,
            'data': permission_data,
        })

        try:
            # 等待响应（超时 5 分钟）
            response = await asyncio.wait_for(future, timeout=300)
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Permission request timeout for {tool_use_id}")
            return {'behavior': 'allow'}  # 超时默认允许
        finally:
            self._pending_permissions.pop(tool_use_id, None)

    async def _receive_loop(self) -> None:
        """接收消息循环"""
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message}")
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
        finally:
            self._is_connected = False

    async def _handle_message(self, data: dict) -> None:
        """处理接收到的消息"""
        msg_type = data.get('type', '')

        if msg_type == 'remote_prompt':
            # 来自移动端的消息
            if self.on_remote_message:
                self.on_remote_message(data)

        elif msg_type == 'permission_response':
            # 权限响应
            tool_use_id = data.get('tool_use_id', '')
            if tool_use_id in self._pending_permissions:
                future = self._pending_permissions[tool_use_id]
                if not future.done():
                    future.set_result(data.get('response', {}))

        elif msg_type == 'interrupt':
            # 中断请求
            if self.on_interrupt:
                self.on_interrupt()

        elif msg_type == 'pong':
            # 心跳响应
            pass

        else:
            logger.debug(f"Unknown message type: {msg_type}")

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected
