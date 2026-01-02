"""
任务管理器 - 支持后台执行和断线重连

功能:
- 任务在后台执行，不受 WebSocket 连接影响
- 缓存任务事件，支持客户端重连后获取历史
- 任务状态持久化
- 消息持久化到 JSONL 文件
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from app.services.message_store import message_store

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskEvent:
    """任务事件"""
    event: str
    data: dict
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Task:
    """任务"""
    id: str
    workspace_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    events: list[TaskEvent] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    # 用于标题生成
    assistant_text: str = ""  # 收集的助手响应文本

    def add_event(self, event: str, data: dict):
        """添加事件"""
        self.events.append(TaskEvent(event=event, data=data))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "prompt": self.prompt,
            "status": self.status.value,
            "events_count": len(self.events),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


class TaskManager:
    """任务管理器"""

    def __init__(self):
        self.tasks: dict[str, Task] = {}  # task_id -> Task
        self.workspace_tasks: dict[str, list[str]] = {}  # workspace_id -> [task_ids]
        self.running_tasks: dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
        self._event_callbacks: dict[str, list[callable]] = {}  # workspace_id -> callbacks
        self._completion_callbacks: dict[str, list[callable]] = {}  # workspace_id -> callbacks (called when task completes)

    def create_task(self, workspace_id: str, prompt: str) -> Task:
        """创建任务"""
        task_id = str(uuid4())[:8]
        task = Task(
            id=task_id,
            workspace_id=workspace_id,
            prompt=prompt,
        )
        self.tasks[task_id] = task

        if workspace_id not in self.workspace_tasks:
            self.workspace_tasks[workspace_id] = []
        self.workspace_tasks[workspace_id].append(task_id)

        logger.info(f"Created task {task_id} for workspace {workspace_id}")
        return task

    def get_task(self, task_id: str) -> Task | None:
        """获取任务"""
        return self.tasks.get(task_id)

    def get_workspace_tasks(self, workspace_id: str) -> list[Task]:
        """获取工作区的所有任务"""
        task_ids = self.workspace_tasks.get(workspace_id, [])
        return [self.tasks[tid] for tid in task_ids if tid in self.tasks]

    def get_current_task(self, workspace_id: str) -> Task | None:
        """获取工作区当前正在运行的任务"""
        tasks = self.get_workspace_tasks(workspace_id)
        for task in reversed(tasks):
            if task.status == TaskStatus.RUNNING:
                return task
        return None

    def get_latest_task(self, workspace_id: str) -> Task | None:
        """获取工作区最新的任务"""
        tasks = self.get_workspace_tasks(workspace_id)
        return tasks[-1] if tasks else None

    async def execute_task(self, task: Task, agent) -> None:
        """执行任务（在后台运行）"""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        # 解析 workspace_id 和 session_id
        parts = task.workspace_id.split(":", 1)
        workspace_id = parts[0] if len(parts) > 0 else ""
        session_id = parts[1] if len(parts) > 1 else ""

        try:
            async for event_dict in agent.execute(task.prompt):
                # 保存事件
                task.add_event(event_dict["event"], event_dict["data"])

                # 收集助手文本（用于标题生成）
                if event_dict["event"] == "text_delta":
                    text = event_dict["data"].get("text", "")
                    # 只收集前 500 字符用于标题生成
                    if len(task.assistant_text) < 500:
                        task.assistant_text += text

                # 持久化消息到 JSONL
                self._save_event_to_store(workspace_id, session_id, event_dict)

                # 通知已注册的回调
                await self._notify_event(task.workspace_id, event_dict)

            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            logger.info(f"Task {task.id} completed")

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            logger.info(f"Task {task.id} cancelled")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()
            logger.error(f"Task {task.id} failed: {e}")

            # 通知错误
            error_event = {"event": "error", "data": {"message": str(e)}}
            task.add_event("error", {"message": str(e)})
            await self._notify_event(task.workspace_id, error_event)

        finally:
            # 清理运行中的任务
            if task.id in self.running_tasks:
                del self.running_tasks[task.id]

            # 通知任务完成回调
            await self._notify_completion(task.workspace_id, task)

    def start_task(self, task: Task, agent) -> asyncio.Task:
        """启动任务（返回 asyncio.Task）"""
        async_task = asyncio.create_task(self.execute_task(task, agent))
        self.running_tasks[task.id] = async_task
        return async_task

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.running_tasks:
            self.running_tasks[task_id].cancel()
            return True
        return False

    def register_callback(self, workspace_id: str, callback: callable):
        """注册事件回调"""
        if workspace_id not in self._event_callbacks:
            self._event_callbacks[workspace_id] = []
        self._event_callbacks[workspace_id].append(callback)

    def unregister_callback(self, workspace_id: str, callback: callable):
        """注销事件回调"""
        if workspace_id in self._event_callbacks:
            try:
                self._event_callbacks[workspace_id].remove(callback)
            except ValueError:
                pass

    def register_completion_callback(self, workspace_id: str, callback: callable):
        """注册任务完成回调"""
        if workspace_id not in self._completion_callbacks:
            self._completion_callbacks[workspace_id] = []
        self._completion_callbacks[workspace_id].append(callback)

    def unregister_completion_callback(self, workspace_id: str, callback: callable):
        """注销任务完成回调"""
        if workspace_id in self._completion_callbacks:
            try:
                self._completion_callbacks[workspace_id].remove(callback)
            except ValueError:
                pass

    async def _notify_completion(self, workspace_id: str, task: Task):
        """通知任务完成"""
        callbacks = self._completion_callbacks.get(workspace_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task)
                else:
                    callback(task)
            except Exception as e:
                logger.error(f"Completion callback error: {e}")

    async def _notify_event(self, workspace_id: str, event: dict):
        """通知所有注册的回调"""
        callbacks = self._event_callbacks.get(workspace_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def _save_event_to_store(self, workspace_id: str, session_id: str, event_dict: dict):
        """保存事件到持久化存储"""
        if not workspace_id or not session_id:
            return

        event_type = event_dict.get("event", "")
        data = event_dict.get("data", {})

        # 事件存储处理器映射
        handlers = {
            "text_delta": lambda: self._store_text_delta(workspace_id, session_id, data),
            "tool_use_start": lambda: self._store_tool_use(workspace_id, session_id, data),
            "tool_result": lambda: self._store_tool_result(workspace_id, session_id, data),
        }

        handler = handlers.get(event_type)
        if handler:
            try:
                handler()
            except Exception as e:
                logger.error(f"Failed to save event to store: {e}")

    def _store_text_delta(self, workspace_id: str, session_id: str, data: dict):
        """存储助手消息"""
        text = data.get("text", "")
        if text:
            message_store.append_assistant_message(workspace_id, session_id, text)

    def _store_tool_use(self, workspace_id: str, session_id: str, data: dict):
        """存储工具调用"""
        message_store.append_tool_use(
            workspace_id,
            session_id,
            tool_id=data.get("id", ""),
            tool_name=data.get("name", ""),
            description=data.get("description"),
        )

    def _store_tool_result(self, workspace_id: str, session_id: str, data: dict):
        """存储工具结果"""
        message_store.append_tool_result(
            workspace_id,
            session_id,
            tool_id=data.get("id", ""),
            content=data.get("content", ""),
            is_error=data.get("is_error", False),
        )

    def get_task_events(self, task_id: str, from_index: int = 0) -> list[dict]:
        """获取任务事件（支持增量获取）"""
        task = self.tasks.get(task_id)
        if not task:
            return []
        return [e.to_dict() for e in task.events[from_index:]]

    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        now = datetime.now()
        to_remove = []

        for task_id, task in self.tasks.items():
            if task.completed_at:
                age = (now - task.completed_at).total_seconds() / 3600
                if age > max_age_hours:
                    to_remove.append(task_id)

        for task_id in to_remove:
            task = self.tasks.pop(task_id)
            if task.workspace_id in self.workspace_tasks:
                try:
                    self.workspace_tasks[task.workspace_id].remove(task_id)
                except ValueError:
                    pass

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks")


# 全局任务管理器实例
task_manager = TaskManager()
