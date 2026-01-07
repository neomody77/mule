"""
测试 ACP 相关模块
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPermissionAdapter:
    """测试权限适配器"""

    def test_permission_decision_enum(self):
        """测试权限决策枚举"""
        from app.services.permission_adapter import PermissionDecision

        assert PermissionDecision.APPROVED.value == "approved"
        assert PermissionDecision.APPROVED_FOR_SESSION.value == "approved_for_session"
        assert PermissionDecision.DENIED.value == "denied"
        assert PermissionDecision.ABORT.value == "abort"

    @pytest.mark.asyncio
    async def test_permission_adapter_creation(self):
        """测试创建权限适配器"""
        from app.services.permission_adapter import PermissionAdapter

        callback = AsyncMock()
        adapter = PermissionAdapter(on_permission_request=callback)

        assert adapter.has_pending == False
        assert len(adapter.get_pending_requests()) == 0

    @pytest.mark.asyncio
    async def test_session_approved_tools(self):
        """测试会话级批准"""
        from app.services.permission_adapter import PermissionAdapter, PermissionDecision

        callback = AsyncMock()
        adapter = PermissionAdapter(on_permission_request=callback)

        # 模拟会话级批准
        adapter._session_approved.add("Bash")

        assert "Bash" in adapter.session_approved_tools

        # 重置
        adapter.reset_session_permissions()
        assert len(adapter.session_approved_tools) == 0


class TestModeManager:
    """测试模式管理器"""

    def test_control_mode_enum(self):
        """测试控制模式枚举"""
        from app.services.mode_manager import ControlMode

        assert ControlMode.LOCAL.value == "local"
        assert ControlMode.REMOTE.value == "remote"

    @pytest.mark.asyncio
    async def test_mode_manager_creation(self):
        """测试创建模式管理器"""
        from app.services.mode_manager import ModeManager, ControlMode

        manager = ModeManager(
            session_key="test:session",
            initial_mode=ControlMode.REMOTE,
        )

        assert manager.current_mode == ControlMode.REMOTE
        assert manager.is_remote == True
        assert manager.is_local == False

    @pytest.mark.asyncio
    async def test_mode_switch(self):
        """测试模式切换"""
        from app.services.mode_manager import ModeManager, ControlMode, ModeChangeReason

        callback = AsyncMock()
        manager = ModeManager(
            session_key="test:session",
            initial_mode=ControlMode.REMOTE,
            on_mode_change=callback,
        )

        # 切换到本地
        await manager.switch_to_local(ModeChangeReason.USER_REQUEST)

        assert manager.current_mode == ControlMode.LOCAL
        assert manager.is_local == True
        callback.assert_called_once()

        # 切换回远程
        await manager.switch_to_remote(ModeChangeReason.USER_REQUEST)

        assert manager.current_mode == ControlMode.REMOTE
        assert callback.call_count == 2

    @pytest.mark.asyncio
    async def test_mode_toggle(self):
        """测试模式切换"""
        from app.services.mode_manager import ModeManager, ControlMode

        manager = ModeManager(
            session_key="test:session",
            initial_mode=ControlMode.REMOTE,
        )

        # 切换
        new_mode = await manager.toggle_mode()
        assert new_mode == ControlMode.LOCAL

        new_mode = await manager.toggle_mode()
        assert new_mode == ControlMode.REMOTE

    @pytest.mark.asyncio
    async def test_mode_status(self):
        """测试获取状态"""
        from app.services.mode_manager import ModeManager, ControlMode

        manager = ModeManager(
            session_key="test:session",
            initial_mode=ControlMode.REMOTE,
        )

        status = manager.get_status()

        assert status["mode"] == "remote"
        assert "switched_at" in status
        assert status["remote_connections"] == 0

    @pytest.mark.asyncio
    async def test_remote_connection_tracking(self):
        """测试远程连接跟踪"""
        from app.services.mode_manager import ModeManager, ControlMode

        manager = ModeManager(
            session_key="test:session",
            initial_mode=ControlMode.REMOTE,
        )

        manager.on_remote_connect()
        assert manager.get_status()["remote_connections"] == 1

        manager.on_remote_connect()
        assert manager.get_status()["remote_connections"] == 2

        manager.on_remote_disconnect()
        assert manager.get_status()["remote_connections"] == 1

        manager.on_remote_disconnect()
        assert manager.get_status()["remote_connections"] == 0


class TestSessionModeRegistry:
    """测试会话模式注册表"""

    @pytest.mark.asyncio
    async def test_registry_get_or_create(self):
        """测试获取或创建"""
        from app.services.mode_manager import SessionModeRegistry, ControlMode

        registry = SessionModeRegistry()

        manager1 = await registry.get_or_create("ws1:s1")
        manager2 = await registry.get_or_create("ws1:s1")

        # 应该返回同一个实例
        assert manager1 is manager2

        manager3 = await registry.get_or_create("ws2:s2")
        assert manager3 is not manager1

    @pytest.mark.asyncio
    async def test_registry_remove(self):
        """测试移除"""
        from app.services.mode_manager import SessionModeRegistry

        registry = SessionModeRegistry()

        await registry.get_or_create("ws1:s1")
        assert registry.get("ws1:s1") is not None

        await registry.remove("ws1:s1")
        assert registry.get("ws1:s1") is None


class TestAcpTransport:
    """测试 ACP 传输层"""

    def test_find_claude_cli(self):
        """测试查找 Claude CLI"""
        from app.services.acp_transport import AcpTransport

        # 这个测试依赖环境，可能找不到
        path = AcpTransport.find_claude_cli()
        # 不做断言，只测试不抛异常

    @pytest.mark.asyncio
    async def test_transport_not_connected(self):
        """测试未连接状态"""
        from app.services.acp_transport import AcpTransport, AcpTransportError

        transport = AcpTransport()

        assert transport.is_connected == False

        with pytest.raises(AcpTransportError):
            await transport.send_request("test", {})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
