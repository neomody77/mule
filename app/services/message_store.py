"""
消息持久化存储服务

使用 JSONL 格式存储每个 session 的消息历史：
- 每行一条消息记录
- 支持追加写入（高效）
- 支持读取全部历史
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class MessageStore:
    """消息存储服务"""

    def __init__(self):
        self.base_dir = settings.data_dir / "messages"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_file(self, workspace_id: str, session_id: str) -> Path:
        """获取 session 消息文件路径"""
        workspace_dir = self.base_dir / workspace_id
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir / f"{session_id}.jsonl"

    def append_message(
        self,
        workspace_id: str,
        session_id: str,
        message_type: str,
        content: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """追加一条消息记录"""
        file_path = self._get_session_file(workspace_id, session_id)

        record = {
            "timestamp": datetime.now().isoformat(),
            "type": message_type,
            "content": content,
        }
        if data:
            record["data"] = data

        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to append message: {e}")

    def append_user_message(
        self,
        workspace_id: str,
        session_id: str,
        content: str,
    ) -> None:
        """追加用户消息"""
        self.append_message(workspace_id, session_id, "user", content)

    def append_assistant_message(
        self,
        workspace_id: str,
        session_id: str,
        content: str,
    ) -> None:
        """追加助手消息"""
        self.append_message(workspace_id, session_id, "assistant", content)

    def append_tool_use(
        self,
        workspace_id: str,
        session_id: str,
        tool_id: str,
        tool_name: str,
        description: str | None = None,
    ) -> None:
        """追加工具调用记录"""
        self.append_message(
            workspace_id,
            session_id,
            "tool_use",
            description or tool_name,
            data={"id": tool_id, "name": tool_name},
        )

    def append_tool_result(
        self,
        workspace_id: str,
        session_id: str,
        tool_id: str,
        content: str,
        is_error: bool = False,
    ) -> None:
        """追加工具结果记录"""
        self.append_message(
            workspace_id,
            session_id,
            "tool_result",
            content[:500] if content else "",  # 截断过长内容
            data={"id": tool_id, "is_error": is_error},
        )

    def get_messages(
        self,
        workspace_id: str,
        session_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """获取消息历史"""
        file_path = self._get_session_file(workspace_id, session_id)

        if not file_path.exists():
            return []

        messages = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Failed to read messages: {e}")
            return []

        # 应用 offset 和 limit
        if offset > 0:
            messages = messages[offset:]
        if limit is not None:
            messages = messages[:limit]

        return messages

    def clear_messages(self, workspace_id: str, session_id: str) -> None:
        """清空 session 消息"""
        file_path = self._get_session_file(workspace_id, session_id)
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.error(f"Failed to clear messages: {e}")

    def delete_workspace_messages(self, workspace_id: str) -> None:
        """删除整个 workspace 的消息"""
        workspace_dir = self.base_dir / workspace_id
        try:
            if workspace_dir.exists():
                import shutil
                shutil.rmtree(workspace_dir)
        except Exception as e:
            logger.error(f"Failed to delete workspace messages: {e}")


# 全局实例
message_store = MessageStore()
