"""
Mode Manager - 本地/远程模式切换管理器

实现类似 HAPI 的 Local-Remote Loop 功能：
- 本地模式：用户在本地终端直接操作
- 远程模式：用户通过手机/Web 远程控制
- 无缝切换：在两种模式间平滑切换，保持会话状态
"""
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Any

logger = logging.getLogger(__name__)


class ControlMode(Enum):
    """控制模式"""
    LOCAL = "local"    # 本地控制（终端）
    REMOTE = "remote"  # 远程控制（手机/Web）


class ModeChangeReason(Enum):
    """模式切换原因"""
    USER_REQUEST = "user_request"       # 用户主动请求
    TIMEOUT = "timeout"                 # 超时自动切换
    DISCONNECT = "disconnect"           # 连接断开
    HANDOFF = "handoff"                 # 主动交接
    EXIT = "exit"                       # 退出会话


@dataclass
class ModeState:
    """模式状态"""
    mode: ControlMode
    switched_at: float
    reason: ModeChangeReason
    previous_mode: Optional[ControlMode] = None


class ModeManager:
    """
    本地/远程模式管理器

    功能：
    - 管理当前控制模式
    - 处理模式切换请求
    - 通知相关组件模式变化
    - 支持自动超时切换
    """

    # 远程模式超时时间（秒），超时后自动切回本地
    REMOTE_TIMEOUT = 600  # 10 分钟

    def __init__(
        self,
        session_key: str,
        initial_mode: ControlMode = ControlMode.REMOTE,
        on_mode_change: Optional[Callable[[ModeState], Any]] = None,
    ):
        """
        Args:
            session_key: 会话标识 (workspace_id:session_id)
            initial_mode: 初始模式
            on_mode_change: 模式变化回调
        """
        self.session_key = session_key
        self._on_mode_change = on_mode_change

        # 当前状态
        self._state = ModeState(
            mode=initial_mode,
            switched_at=asyncio.get_event_loop().time(),
            reason=ModeChangeReason.USER_REQUEST,
        )

        # 远程活跃连接数
        self._remote_connections = 0

        # 本地活跃状态
        self._local_active = False

        # 超时任务
        self._timeout_task: Optional[asyncio.Task] = None

        # 锁
        self._lock = asyncio.Lock()

        logger.info(f"ModeManager created for {session_key}, initial mode: {initial_mode.value}")

    @property
    def current_mode(self) -> ControlMode:
        """当前控制模式"""
        return self._state.mode

    @property
    def state(self) -> ModeState:
        """当前状态"""
        return self._state

    @property
    def is_local(self) -> bool:
        """是否本地模式"""
        return self._state.mode == ControlMode.LOCAL

    @property
    def is_remote(self) -> bool:
        """是否远程模式"""
        return self._state.mode == ControlMode.REMOTE

    async def switch_to_local(self, reason: ModeChangeReason = ModeChangeReason.USER_REQUEST) -> bool:
        """
        切换到本地模式

        Args:
            reason: 切换原因

        Returns:
            是否切换成功
        """
        async with self._lock:
            if self._state.mode == ControlMode.LOCAL:
                logger.debug("Already in local mode")
                return True

            return await self._do_switch(ControlMode.LOCAL, reason)

    async def switch_to_remote(self, reason: ModeChangeReason = ModeChangeReason.USER_REQUEST) -> bool:
        """
        切换到远程模式

        Args:
            reason: 切换原因

        Returns:
            是否切换成功
        """
        async with self._lock:
            if self._state.mode == ControlMode.REMOTE:
                logger.debug("Already in remote mode")
                return True

            return await self._do_switch(ControlMode.REMOTE, reason)

    async def toggle_mode(self, reason: ModeChangeReason = ModeChangeReason.USER_REQUEST) -> ControlMode:
        """
        切换模式（本地 <-> 远程）

        Returns:
            切换后的模式
        """
        async with self._lock:
            new_mode = ControlMode.REMOTE if self._state.mode == ControlMode.LOCAL else ControlMode.LOCAL
            await self._do_switch(new_mode, reason)
            return self._state.mode

    async def _do_switch(self, new_mode: ControlMode, reason: ModeChangeReason) -> bool:
        """执行模式切换"""
        old_mode = self._state.mode

        # 更新状态
        self._state = ModeState(
            mode=new_mode,
            switched_at=asyncio.get_event_loop().time(),
            reason=reason,
            previous_mode=old_mode,
        )

        logger.info(f"Mode switched: {old_mode.value} -> {new_mode.value} (reason: {reason.value})")

        # 取消现有超时任务
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None

        # 如果切换到远程模式且没有活跃连接，启动超时计时
        if new_mode == ControlMode.REMOTE and self._remote_connections == 0:
            self._start_timeout()

        # 通知回调
        if self._on_mode_change:
            try:
                result = self._on_mode_change(self._state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Mode change callback error: {e}")

        return True

    def _start_timeout(self):
        """启动超时计时"""
        if self._timeout_task:
            self._timeout_task.cancel()

        async def timeout_handler():
            try:
                await asyncio.sleep(self.REMOTE_TIMEOUT)
                # 超时，切回本地模式
                logger.info(f"Remote mode timeout, switching to local")
                await self.switch_to_local(ModeChangeReason.TIMEOUT)
            except asyncio.CancelledError:
                pass

        self._timeout_task = asyncio.create_task(timeout_handler())

    def on_remote_connect(self):
        """远程客户端连接"""
        self._remote_connections += 1
        logger.debug(f"Remote connected, count: {self._remote_connections}")

        # 取消超时
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None

    def on_remote_disconnect(self):
        """远程客户端断开"""
        self._remote_connections = max(0, self._remote_connections - 1)
        logger.debug(f"Remote disconnected, count: {self._remote_connections}")

        # 如果没有远程连接且处于远程模式，启动超时
        if self._remote_connections == 0 and self.is_remote:
            self._start_timeout()

    def on_local_activity(self):
        """本地活动"""
        self._local_active = True

        # 如果处于远程模式但本地有活动，可以考虑提示用户
        if self.is_remote:
            logger.debug("Local activity detected while in remote mode")

    async def request_handoff(self, to_mode: ControlMode) -> bool:
        """
        请求交接控制权

        这是一个协商过程，会通知当前控制方

        Args:
            to_mode: 目标模式

        Returns:
            是否成功
        """
        if self._state.mode == to_mode:
            return True

        # 在实际场景中，这里可以实现交接确认流程
        # 比如通知当前控制方，等待确认等

        if to_mode == ControlMode.LOCAL:
            return await self.switch_to_local(ModeChangeReason.HANDOFF)
        else:
            return await self.switch_to_remote(ModeChangeReason.HANDOFF)

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "mode": self._state.mode.value,
            "switched_at": self._state.switched_at,
            "reason": self._state.reason.value,
            "previous_mode": self._state.previous_mode.value if self._state.previous_mode else None,
            "remote_connections": self._remote_connections,
            "local_active": self._local_active,
        }

    async def cleanup(self):
        """清理资源"""
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass


class SessionModeRegistry:
    """
    会话模式注册表

    管理所有会话的模式状态
    """

    def __init__(self):
        self._managers: dict[str, ModeManager] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        session_key: str,
        initial_mode: ControlMode = ControlMode.REMOTE,
        on_mode_change: Optional[Callable[[ModeState], Any]] = None,
    ) -> ModeManager:
        """
        获取或创建模式管理器

        Args:
            session_key: 会话标识
            initial_mode: 初始模式（仅新建时有效）
            on_mode_change: 模式变化回调

        Returns:
            ModeManager 实例
        """
        async with self._lock:
            if session_key not in self._managers:
                self._managers[session_key] = ModeManager(
                    session_key=session_key,
                    initial_mode=initial_mode,
                    on_mode_change=on_mode_change,
                )
            return self._managers[session_key]

    def get(self, session_key: str) -> Optional[ModeManager]:
        """获取模式管理器（不创建）"""
        return self._managers.get(session_key)

    async def remove(self, session_key: str):
        """移除模式管理器"""
        async with self._lock:
            if session_key in self._managers:
                manager = self._managers.pop(session_key)
                await manager.cleanup()

    def get_all_status(self) -> dict[str, dict]:
        """获取所有会话的状态"""
        return {
            key: manager.get_status()
            for key, manager in self._managers.items()
        }


# 全局注册表
mode_registry = SessionModeRegistry()
