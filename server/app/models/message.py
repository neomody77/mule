"""消息数据模型"""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """消息类型"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    STATUS = "status"


class ToolCall(BaseModel):
    """工具调用"""
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """工具执行结果"""
    tool_call_id: str
    name: str
    result: Any
    success: bool = True
    error: Optional[str] = None


class Message(BaseModel):
    """消息模型"""
    id: str = Field(default_factory=lambda: "")
    type: MessageType
    content: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[ToolResult] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamEvent(BaseModel):
    """流式事件"""
    event: str  # text_delta, tool_use_start, tool_use_end, message_end, error
    data: dict[str, Any]
