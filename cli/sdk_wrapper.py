"""
SDK 包装器 - 封装 ClaudeSDKClient 并添加 WebSocket 同步
"""
import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from typing import Any, Callable, Optional

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
    HookMatcher,
    HookContext,
)

logger = logging.getLogger(__name__)


@dataclass
class MuleMessage:
    """Mule 消息格式"""
    type: str  # text, tool_use, tool_result, thinking, result, error, permission_request
    data: dict

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class MuleSDKWrapper:
    """
    封装 ClaudeSDKClient，添加:
    - WebSocket 实时同步
    - 权限请求转发
    - 远程消息接收
    """

    def __init__(
        self,
        cwd: str,
        session_id: Optional[str] = None,
        on_message: Optional[Callable[[MuleMessage], None]] = None,
        on_permission_request: Optional[Callable[[dict], asyncio.Future]] = None,
    ):
        """
        Args:
            cwd: 工作目录
            session_id: 恢复的会话 ID（可选）
            on_message: 消息回调（用于同步到远程）
            on_permission_request: 权限请求回调（返回 Future 等待用户响应）
        """
        self.cwd = cwd
        self.session_id = session_id
        self.on_message = on_message
        self.on_permission_request = on_permission_request

        self._client: Optional[ClaudeSDKClient] = None
        self._is_connected = False
        self._is_processing = False
        self._current_session_id: Optional[str] = None

        # 待处理的权限请求
        self._pending_permissions: dict[str, asyncio.Future] = {}

    def _build_options(self) -> ClaudeAgentOptions:
        """构建 SDK 配置"""
        hooks = {}

        # 只有在需要权限转发时才添加 hooks
        if self.on_permission_request:
            hooks = {
                'PreToolUse': [HookMatcher(hooks=[self._pre_tool_hook])],
                'PostToolUse': [HookMatcher(hooks=[self._post_tool_hook])],
            }

        return ClaudeAgentOptions(
            cwd=self.cwd,
            resume=self.session_id,
            include_partial_messages=True,
            permission_mode="default",  # 需要权限确认
            allowed_tools=[
                "Read", "Write", "Edit", "Bash", "Glob", "Grep",
                "WebFetch", "WebSearch", "TodoWrite", "Task",
            ],
            hooks=hooks if hooks else None,
            setting_sources=["project"],  # 加载项目 CLAUDE.md
        )

    async def _pre_tool_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: Optional[str],
        context: HookContext,
    ) -> dict[str, Any]:
        """工具执行前钩子 - 转发权限请求到远程"""
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {})

        logger.info(f"PreToolUse: {tool_name}")

        # 发送权限请求
        if self.on_permission_request:
            permission_data = {
                'tool_name': tool_name,
                'tool_input': tool_input,
                'tool_use_id': tool_use_id,
            }

            # 发送消息通知远程
            if self.on_message:
                self.on_message(MuleMessage(
                    type='permission_request',
                    data=permission_data
                ))

            # 等待用户响应
            try:
                response = await self.on_permission_request(permission_data)
                return response
            except asyncio.TimeoutError:
                logger.warning(f"Permission request timeout for {tool_name}")
                return {}  # 默认允许

        return {}

    async def _post_tool_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: Optional[str],
        context: HookContext,
    ) -> dict[str, Any]:
        """工具执行后钩子 - 记录结果"""
        tool_name = input_data.get('tool_name', '')
        logger.debug(f"PostToolUse: {tool_name}")
        return {}

    async def connect(self) -> None:
        """连接到 Claude"""
        if self._is_connected:
            return

        options = self._build_options()
        self._client = ClaudeSDKClient(options)
        await self._client.connect()
        self._is_connected = True
        logger.info("Connected to Claude")

    async def disconnect(self) -> None:
        """断开连接"""
        if self._client and self._is_connected:
            await self._client.disconnect()
            self._is_connected = False
            self._client = None
            logger.info("Disconnected from Claude")

    async def query(self, prompt: str) -> None:
        """发送查询"""
        if not self._is_connected:
            await self.connect()

        self._is_processing = True
        await self._client.query(prompt)

    async def receive_messages(self):
        """接收消息流并转发"""
        async for message in self._client.receive_response():
            # 转换为 Mule 消息格式
            mule_messages = self._convert_message(message)

            for msg in mule_messages:
                # 回调通知
                if self.on_message:
                    self.on_message(msg)

                yield msg

            # 检查是否结束
            if isinstance(message, ResultMessage):
                self._current_session_id = message.session_id
                self._is_processing = False
                break

    def _convert_message(self, message) -> list[MuleMessage]:
        """将 SDK 消息转换为 Mule 消息格式"""
        messages = []

        if isinstance(message, SystemMessage):
            messages.append(MuleMessage(
                type='system',
                data={
                    'subtype': message.subtype,
                    'data': message.data,
                }
            ))

        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    messages.append(MuleMessage(
                        type='text',
                        data={'text': block.text}
                    ))
                elif isinstance(block, ThinkingBlock):
                    messages.append(MuleMessage(
                        type='thinking',
                        data={'thinking': block.thinking}
                    ))
                elif isinstance(block, ToolUseBlock):
                    messages.append(MuleMessage(
                        type='tool_use',
                        data={
                            'id': block.id,
                            'name': block.name,
                            'input': block.input,
                        }
                    ))
                elif isinstance(block, ToolResultBlock):
                    messages.append(MuleMessage(
                        type='tool_result',
                        data={
                            'tool_use_id': block.tool_use_id,
                            'content': block.content,
                            'is_error': block.is_error,
                        }
                    ))

        elif isinstance(message, UserMessage):
            # 用户消息（通常是工具结果）
            if hasattr(message, 'content') and isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        messages.append(MuleMessage(
                            type='tool_result',
                            data={
                                'tool_use_id': block.tool_use_id,
                                'content': block.content,
                                'is_error': block.is_error,
                            }
                        ))

        elif isinstance(message, ResultMessage):
            messages.append(MuleMessage(
                type='result',
                data={
                    'session_id': message.session_id,
                    'duration_ms': message.duration_ms,
                    'num_turns': message.num_turns,
                    'is_error': message.is_error,
                    'result': message.result,
                    'total_cost_usd': message.total_cost_usd,
                }
            ))

        return messages

    async def interrupt(self) -> None:
        """中断当前任务"""
        if self._client and self._is_processing:
            await self._client.interrupt()
            self._is_processing = False
            logger.info("Task interrupted")

    @property
    def current_session_id(self) -> Optional[str]:
        """获取当前会话 ID"""
        return self._current_session_id

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._is_processing

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected
