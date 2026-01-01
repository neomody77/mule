"""
Prompts 模块

存放所有 Claude Agent 使用的系统提示和模板
"""

from .system_prompt import get_system_prompt
from .session_title import SESSION_TITLE_PROMPT

__all__ = [
    "get_system_prompt",
    "SESSION_TITLE_PROMPT",
]
