"""
消息持久化存储服务

使用 JSONL 格式存储每个 session 的消息历史：
- 每行一条消息记录
- 支持追加写入（高效）
- 支持读取全部历史
- Session 元数据存储在 _sessions.json 文件中
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class SessionInfo:
    """Session 元数据"""
    def __init__(
        self,
        id: str,
        workspace_id: str,
        title: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ):
        self.id = id
        self.workspace_id = workspace_id
        self.title = title
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionInfo":
        return cls(
            id=data["id"],
            workspace_id=data["workspace_id"],
            title=data.get("title"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class MessageStore:
    """消息存储服务"""

    def __init__(self):
        self.base_dir = settings.data_dir / "messages"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_sessions_file(self, workspace_id: str) -> Path:
        """获取 workspace 的 sessions 元数据文件路径"""
        workspace_dir = self.base_dir / workspace_id
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir / "_sessions.json"

    def _load_sessions_meta(self, workspace_id: str) -> dict[str, dict]:
        """加载 sessions 元数据"""
        file_path = self._get_sessions_file(workspace_id)
        if not file_path.exists():
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sessions meta: {e}")
            return {}

    def _save_sessions_meta(self, workspace_id: str, sessions: dict[str, dict]) -> None:
        """保存 sessions 元数据"""
        file_path = self._get_sessions_file(workspace_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(sessions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sessions meta: {e}")

    def create_session(
        self,
        workspace_id: str,
        session_id: str,
        title: str | None = None,
    ) -> SessionInfo:
        """创建新 session"""
        sessions = self._load_sessions_meta(workspace_id)
        now = datetime.now().isoformat()
        # 如果没有提供 title，使用 session_id 的前 8 位
        if title is None:
            title = session_id[:8]
        session_info = SessionInfo(
            id=session_id,
            workspace_id=workspace_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        sessions[session_id] = session_info.to_dict()
        self._save_sessions_meta(workspace_id, sessions)
        return session_info

    def get_session(self, workspace_id: str, session_id: str) -> SessionInfo | None:
        """获取 session 信息"""
        sessions = self._load_sessions_meta(workspace_id)
        if session_id in sessions:
            return SessionInfo.from_dict(sessions[session_id])
        return None

    def update_session(
        self,
        workspace_id: str,
        session_id: str,
        title: str | None = None,
    ) -> SessionInfo | None:
        """更新 session 信息"""
        sessions = self._load_sessions_meta(workspace_id)
        if session_id not in sessions:
            return None
        sessions[session_id]["updated_at"] = datetime.now().isoformat()
        if title is not None:
            sessions[session_id]["title"] = title
        self._save_sessions_meta(workspace_id, sessions)
        return SessionInfo.from_dict(sessions[session_id])

    def delete_session(self, workspace_id: str, session_id: str) -> bool:
        """删除 session"""
        sessions = self._load_sessions_meta(workspace_id)
        if session_id not in sessions:
            return False
        del sessions[session_id]
        self._save_sessions_meta(workspace_id, sessions)
        # 同时删除消息文件
        self.clear_messages(workspace_id, session_id)
        return True

    def list_sessions(self, workspace_id: str) -> list[SessionInfo]:
        """列出 workspace 下的所有 sessions"""
        sessions = self._load_sessions_meta(workspace_id)
        # 同时检查实际存在的消息文件（兼容旧数据）
        workspace_dir = self.base_dir / workspace_id
        if workspace_dir.exists():
            for file_path in workspace_dir.glob("*.jsonl"):
                session_id = file_path.stem
                if session_id not in sessions:
                    # 从文件中获取创建时间
                    stat = file_path.stat()
                    created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()
                    updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    sessions[session_id] = {
                        "id": session_id,
                        "workspace_id": workspace_id,
                        "title": None,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    }
            # 保存更新后的元数据
            self._save_sessions_meta(workspace_id, sessions)

        result = [SessionInfo.from_dict(s) for s in sessions.values()]
        # 按更新时间倒序排列
        result.sort(key=lambda x: x.updated_at or "", reverse=True)
        return result

    def ensure_session_exists(
        self,
        workspace_id: str,
        session_id: str,
        title: str | None = None,
    ) -> SessionInfo:
        """确保 session 存在，不存在则创建"""
        session = self.get_session(workspace_id, session_id)
        if session:
            return session
        return self.create_session(workspace_id, session_id, title)

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
