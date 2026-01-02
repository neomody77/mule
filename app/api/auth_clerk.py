"""
Clerk 认证模块

使用 Clerk JWT 验证请求。
当不使用 Clerk 时，此文件可安全删除。
"""
import hashlib
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer

from app.config import settings

logger = logging.getLogger(__name__)

# Clerk 配置（懒加载）
_clerk_config: Optional[ClerkConfig] = None
_clerk_auth_guard: Optional[ClerkHTTPBearer] = None


def _get_clerk_config() -> ClerkConfig:
    """获取 Clerk 配置（单例）"""
    global _clerk_config
    if _clerk_config is None:
        if not settings.clerk_jwks_url:
            raise ValueError("CLERK_JWKS_URL is not configured")
        _clerk_config = ClerkConfig(jwks_url=settings.clerk_jwks_url)
    return _clerk_config


def _get_clerk_guard() -> ClerkHTTPBearer:
    """获取 Clerk 认证守卫（单例）"""
    global _clerk_auth_guard
    if _clerk_auth_guard is None:
        _clerk_auth_guard = ClerkHTTPBearer(
            config=_get_clerk_config(),
            auto_error=False,  # 我们自己处理错误
        )
    return _clerk_auth_guard


async def verify_clerk_token(request: Request) -> str:
    """
    验证 Clerk JWT Token

    Returns:
        str: Clerk user ID（用作用户标识）
    """
    guard = _get_clerk_guard()

    try:
        credentials = await guard(request)

        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Clerk token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 从 decoded token 中获取 user ID
        decoded = getattr(credentials, 'decoded', None)
        if decoded is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Clerk token 中的 sub 字段是 user ID
        user_id = decoded.get('sub')
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User ID not found in token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug(f"Clerk auth: user_id={user_id}")
        return user_id

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Clerk auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_clerk_ws_token(token: str) -> Optional[str]:
    """
    验证 WebSocket 连接的 Clerk Token

    Returns:
        str: Clerk user ID，验证失败返回 None
    """
    try:
        guard = _get_clerk_guard()

        # 手动验证 token
        from jose import jwt
        from jose.exceptions import JWTError

        config = _get_clerk_config()

        # 获取 JWKS 并验证
        decoded = jwt.decode(
            token,
            config.jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )

        user_id = decoded.get('sub')
        if user_id:
            logger.debug(f"Clerk WS auth: user_id={user_id}")
            return user_id

        return None

    except JWTError as e:
        logger.warning(f"Clerk WS token validation failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Clerk WS auth error: {e}")
        return None


def get_workspace_id_for_clerk_user(user_id: str) -> str:
    """
    根据 Clerk user ID 获取对应的 workspace_id

    与 token 模式保持一致的映射逻辑
    """
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
    return f"ws-{user_hash}"
