"""
会话标题生成服务

使用 Claude API 根据首次对话内容自动生成会话标题
"""
import logging
from typing import Optional

from claude_agent_sdk import query, ClaudeAgentOptions

from app.prompts.session_title import TITLE_GENERATION_SYSTEM, SESSION_TITLE_PROMPT

logger = logging.getLogger(__name__)


async def generate_session_title(
    user_message: str = "",
    assistant_response: str = "",
    messages: list = None,
    max_length: int = 20
) -> Optional[str]:
    """
    根据对话内容生成会话标题

    Args:
        user_message: 用户的首条消息（简单模式）
        assistant_response: 助手响应的摘要/前200字（简单模式）
        messages: 完整消息历史（用于重新生成标题）
        max_length: 标题最大长度

    Returns:
        生成的标题，失败返回 None
    """
    try:
        # 如果提供了完整消息历史，从中提取内容
        if messages:
            user_msgs = []
            assistant_msgs = []
            for msg in messages[:10]:  # 只取前10条消息
                role = msg.get('role', '')
                content = msg.get('content', '')
                if isinstance(content, list):
                    content = ' '.join(
                        block.get('text', '') for block in content
                        if isinstance(block, dict) and block.get('type') == 'text'
                    )
                if role == 'user':
                    user_msgs.append(content[:200])
                elif role == 'assistant':
                    assistant_msgs.append(content[:200])
            user_message = ' | '.join(user_msgs[:3])[:500]
            assistant_response = ' | '.join(assistant_msgs[:2])[:300]

        # 截断过长的内容
        user_msg = user_message[:500] if len(user_message) > 500 else user_message
        assistant_summary = assistant_response[:300] if len(assistant_response) > 300 else assistant_response

        prompt = SESSION_TITLE_PROMPT.format(
            user_message=user_msg,
            assistant_summary=assistant_summary
        )

        options = ClaudeAgentOptions(
            allowed_tools=[],  # 不需要工具
            system_prompt=TITLE_GENERATION_SYSTEM,
            permission_mode="bypassPermissions",
        )

        title = ""
        async for message in query(prompt=prompt, options=options):
            # 只取文本内容
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        title += block.text

        # 清理标题
        title = title.strip().strip('"\'')

        # 限制长度
        if len(title) > max_length:
            title = title[:max_length]

        if title:
            logger.info(f"Generated session title: {title}")
            return title

    except Exception as e:
        logger.error(f"Failed to generate session title: {e}")

    return None
