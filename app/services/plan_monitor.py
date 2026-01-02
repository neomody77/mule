"""
Plan Monitor 服务 - 定时检测并执行 plan.md

功能:
- 每隔 N 分钟检测 workspaces/{workspace_id}/plan.md
- 内容变化时自动执行
- 支持用户手动触发
- 定时间隔可配置（存储在 workspaces/{workspace_id}/plan_config.json）
- 支持多 workspace 隔离（每个 token 对应独立的 workspace）
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Any

from app.config import settings

logger = logging.getLogger(__name__)

# 默认检测间隔（秒）
DEFAULT_INTERVAL_SECONDS = 600  # 10 分钟

# 特殊 session ID
PLAN_MONITOR_SESSION_ID = "plan-monitor"


class PlanConfig:
    """Plan 配置"""

    def __init__(self, workspace_path: Path):
        self.config_file = workspace_path / "plan_config.json"
        self._config: dict = {}
        self._load()

    def _load(self):
        """加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load plan config: {e}")
                self._config = {}

    def _save(self):
        """保存配置"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save plan config: {e}")

    @property
    def interval_seconds(self) -> int:
        """获取检测间隔（秒）"""
        return self._config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)

    @interval_seconds.setter
    def interval_seconds(self, value: int):
        """设置检测间隔（秒）"""
        self._config["interval_seconds"] = max(60, value)  # 最小 1 分钟
        self._config["updated_at"] = datetime.now().isoformat()
        self._save()
        logger.info(f"Plan monitor interval updated to {value} seconds")

    @property
    def last_hash(self) -> str | None:
        """获取上次执行时的内容 hash"""
        return self._config.get("last_hash")

    @last_hash.setter
    def last_hash(self, value: str):
        """设置上次执行时的内容 hash"""
        self._config["last_hash"] = value
        self._config["last_executed_at"] = datetime.now().isoformat()
        self._save()

    @property
    def enabled(self) -> bool:
        """是否启用定时检测"""
        return self._config.get("enabled", True)

    @enabled.setter
    def enabled(self, value: bool):
        """启用/禁用定时检测"""
        self._config["enabled"] = value
        self._config["updated_at"] = datetime.now().isoformat()
        self._save()

    @property
    def last_executed_at(self) -> str | None:
        """上次执行时间"""
        return self._config.get("last_executed_at")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "interval_seconds": self.interval_seconds,
            "interval_minutes": self.interval_seconds // 60,
            "enabled": self.enabled,
            "last_hash": self.last_hash,
            "last_executed_at": self.last_executed_at,
        }


class PlanMonitor:
    """Plan.md 定时监控服务（单个 workspace）"""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.workspace_path = settings.workspace_base_dir / workspace_id
        self.plan_file = self.workspace_path / "plan.md"
        self.config = PlanConfig(self.workspace_path)
        self._running = False
        self._task: asyncio.Task | None = None
        self._execute_callback: Callable[[str, str, str], Any] | None = None  # (workspace_id, session_id, content)
        self._is_executing = False

    def set_execute_callback(self, callback: Callable[[str, str, str], Any]):
        """
        设置执行回调函数

        callback(workspace_id: str, session_id: str, content: str) -> awaitable
        """
        self._execute_callback = callback

    async def start(self):
        """启动定时监控"""
        if self._running:
            logger.warning(f"Plan monitor for {self.workspace_id} already running")
            return

        self._running = True
        logger.info(f"Plan monitor for {self.workspace_id} started, interval: {self.config.interval_seconds}s")

        while self._running:
            try:
                if self.config.enabled:
                    await self.check_and_execute()
            except Exception as e:
                logger.error(f"Plan monitor error: {e}")

            # 等待下一次检测，每秒检查一次是否需要停止
            # 这样可以更快响应间隔变化
            elapsed = 0
            while elapsed < self.config.interval_seconds and self._running:
                await asyncio.sleep(1)
                elapsed += 1

    def stop(self):
        """停止定时监控"""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info(f"Plan monitor for {self.workspace_id} stopped")

    async def check_and_execute(self, force: bool = False) -> dict:
        """
        检测 plan.md 并执行

        Args:
            force: 强制执行，忽略 hash 检查

        Returns:
            执行结果
        """
        # 检查文件是否存在
        if not self.plan_file.exists():
            return {"status": "skipped", "reason": "plan.md not found"}

        # 读取内容
        try:
            content = self.plan_file.read_text(encoding="utf-8").strip()
        except Exception as e:
            return {"status": "error", "reason": f"Failed to read plan.md: {e}"}

        if not content:
            return {"status": "skipped", "reason": "plan.md is empty"}

        # 计算 hash
        content_hash = hashlib.md5(content.encode()).hexdigest()

        # 检查是否需要执行
        if not force and content_hash == self.config.last_hash:
            return {"status": "skipped", "reason": "content unchanged"}

        # 检查是否正在执行
        if self._is_executing:
            return {"status": "skipped", "reason": "already executing"}

        # 执行
        return await self._execute(content, content_hash)

    async def _execute(self, content: str, content_hash: str) -> dict:
        """执行 plan 内容"""
        if not self._execute_callback:
            logger.warning("No execute callback set")
            return {"status": "error", "reason": "no execute callback"}

        self._is_executing = True
        try:
            logger.info(f"Executing plan.md for {self.workspace_id} (hash: {content_hash[:8]}...)")

            # 调用回调执行
            await self._execute_callback(self.workspace_id, PLAN_MONITOR_SESSION_ID, content)

            # 更新 hash
            self.config.last_hash = content_hash

            return {
                "status": "executed",
                "hash": content_hash,
                "executed_at": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to execute plan: {e}")
            return {"status": "error", "reason": str(e)}

        finally:
            self._is_executing = False

    def update_interval(self, seconds: int = None, minutes: int = None):
        """
        更新检测间隔

        Args:
            seconds: 秒数
            minutes: 分钟数（优先级高于 seconds）
        """
        if minutes is not None:
            seconds = minutes * 60
        if seconds is not None:
            self.config.interval_seconds = seconds

    def get_status(self) -> dict:
        """获取监控状态"""
        return {
            "workspace_id": self.workspace_id,
            "running": self._running,
            "executing": self._is_executing,
            "config": self.config.to_dict(),
            "plan_file_exists": self.plan_file.exists(),
        }


class PlanMonitorRegistry:
    """
    Plan Monitor 注册表

    管理多个 workspace 的 plan monitor 实例
    每个 workspace（token）有独立的 monitor
    """

    def __init__(self):
        self._monitors: dict[str, PlanMonitor] = {}
        self._execute_callback: Callable[[str, str, str], Any] | None = None
        self._tasks: dict[str, asyncio.Task] = {}

    def set_execute_callback(self, callback: Callable[[str, str, str], Any]):
        """设置全局执行回调"""
        self._execute_callback = callback
        # 更新所有现有 monitor 的回调
        for monitor in self._monitors.values():
            monitor.set_execute_callback(callback)

    def get_monitor(self, workspace_id: str) -> PlanMonitor:
        """获取或创建指定 workspace 的 monitor"""
        if workspace_id not in self._monitors:
            monitor = PlanMonitor(workspace_id)
            if self._execute_callback:
                monitor.set_execute_callback(self._execute_callback)
            self._monitors[workspace_id] = monitor
        return self._monitors[workspace_id]

    async def start_monitor(self, workspace_id: str):
        """启动指定 workspace 的 monitor"""
        monitor = self.get_monitor(workspace_id)
        if workspace_id not in self._tasks or self._tasks[workspace_id].done():
            task = asyncio.create_task(monitor.start())
            self._tasks[workspace_id] = task

    async def start_all_monitors(self):
        """启动所有已注册的 monitor"""
        for workspace_id in self._monitors:
            await self.start_monitor(workspace_id)

    def stop_monitor(self, workspace_id: str):
        """停止指定 workspace 的 monitor"""
        if workspace_id in self._monitors:
            self._monitors[workspace_id].stop()
        if workspace_id in self._tasks:
            self._tasks[workspace_id].cancel()
            del self._tasks[workspace_id]

    def stop_all_monitors(self):
        """停止所有 monitor"""
        for workspace_id in list(self._monitors.keys()):
            self.stop_monitor(workspace_id)

    def list_monitors(self) -> list[dict]:
        """列出所有 monitor 状态"""
        return [monitor.get_status() for monitor in self._monitors.values()]


# 全局注册表实例
plan_monitor_registry = PlanMonitorRegistry()
