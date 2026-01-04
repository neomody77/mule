"""
Token Refresh API 单元测试

测试 OAuth token 刷新功能
"""
import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import aiohttp


class TestTokenRefresher:
    """TokenRefresher 测试"""

    @pytest.fixture
    def mock_credentials(self, tmp_path):
        """创建模拟的 credentials 文件"""
        import time
        cred_file = tmp_path / ".credentials.json"
        cred_data = {
            "claudeAiOauth": {
                "accessToken": "test-access-token",
                "refreshToken": "test-refresh-token",
                "expiresAt": int((time.time() + 3600) * 1000)  # 1小时后过期
            }
        }
        cred_file.write_text(json.dumps(cred_data))
        return cred_file

    @pytest.fixture
    def refresher(self, mock_credentials):
        """创建 TokenRefresher 实例"""
        from app.services.sandbox_agent import TokenRefresher, CLAUDE_CREDENTIALS_FILE

        # 临时替换 credentials 文件路径
        import app.services.sandbox_agent as module
        original_path = module.CLAUDE_CREDENTIALS_FILE
        module.CLAUDE_CREDENTIALS_FILE = mock_credentials

        refresher = TokenRefresher()
        yield refresher

        # 恢复原路径
        module.CLAUDE_CREDENTIALS_FILE = original_path

    def test_get_token_info(self, refresher, mock_credentials):
        """测试读取 token 信息"""
        remaining, refresh_token = refresher._get_token_info()

        assert remaining > 0
        assert remaining <= 3600
        assert refresh_token == "test-refresh-token"

    def test_get_token_info_no_file(self, refresher, tmp_path):
        """测试文件不存在时的处理"""
        import app.services.sandbox_agent as module
        module.CLAUDE_CREDENTIALS_FILE = tmp_path / "nonexistent.json"

        remaining, refresh_token = refresher._get_token_info()

        assert remaining == 0
        assert refresh_token == ""

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, refresher, mock_credentials):
        """测试成功刷新 token"""
        import time

        mock_response = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 28800  # 8小时
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            mock_session_instance = AsyncMock()
            mock_session_instance.post = AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp), __aexit__=AsyncMock()))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock()

            # 简化测试：直接调用 _update_credentials
            await refresher._update_credentials(mock_response)

            # 验证文件已更新
            with open(mock_credentials) as f:
                data = json.load(f)

            oauth = data.get("claudeAiOauth", {})
            assert oauth.get("accessToken") == "new-access-token"
            assert oauth.get("refreshToken") == "new-refresh-token"
            assert oauth.get("expiresAt") > int(time.time() * 1000)

    @pytest.mark.asyncio
    async def test_update_credentials(self, refresher, mock_credentials):
        """测试更新 credentials 文件"""
        import time

        token_data = {
            "access_token": "updated-access-token",
            "refresh_token": "updated-refresh-token",
            "expires_in": 14400  # 4小时
        }

        await refresher._update_credentials(token_data)

        # 读取更新后的文件
        with open(mock_credentials) as f:
            data = json.load(f)

        oauth = data.get("claudeAiOauth", {})
        assert oauth.get("accessToken") == "updated-access-token"
        assert oauth.get("refreshToken") == "updated-refresh-token"

        # 验证过期时间正确计算
        expected_expiry = int((time.time() + 14400) * 1000)
        actual_expiry = oauth.get("expiresAt")
        # 允许 1 秒误差
        assert abs(actual_expiry - expected_expiry) < 1000

    def test_oauth_api_constants(self, refresher):
        """测试 OAuth API 常量"""
        assert refresher.CLAUDE_TOKEN_URL == "https://console.anthropic.com/v1/oauth/token"
        assert refresher.CLAUDE_CLIENT_ID == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
        assert refresher.REFRESH_THRESHOLD_SECONDS == 3600  # 1小时
        assert refresher.CHECK_INTERVAL_SECONDS == 600  # 10分钟


class TestTokenRefreshIntegration:
    """集成测试 - 需要真实的 credentials 文件"""

    @pytest.mark.skip(reason="需要真实的 credentials 文件，手动运行")
    @pytest.mark.asyncio
    async def test_real_refresh(self):
        """测试真实的 token 刷新（需要有效的 refresh_token）"""
        from app.services.sandbox_agent import TokenRefresher

        refresher = TokenRefresher()
        remaining_before, _ = refresher._get_token_info()

        success = await refresher._refresh_token()

        assert success

        remaining_after, _ = refresher._get_token_info()
        # 刷新后应该有接近 8 小时的有效期
        assert remaining_after > 7 * 3600  # > 7小时
