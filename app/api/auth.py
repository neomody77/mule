"""
认证模块 - 支持 Token 和 Clerk 两种认证方式

通过 AUTH_PROVIDER 环境变量切换:
- token（默认）: 使用静态 API Token
- clerk: 使用 Clerk JWT 认证
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings


security = HTTPBearer(auto_error=False)


# ==================== Token 认证（默认）====================

async def _verify_token_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """验证静态 API Token"""
    token = None

    # 方式1: Bearer Token
    if credentials:
        token = credentials.credentials

    # 方式2: 自定义 Header
    if not token:
        token = request.headers.get("X-API-Token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.is_valid_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


async def _verify_ws_token_auth(token: str) -> bool:
    """验证 WebSocket 的静态 Token"""
    return settings.is_valid_token(token)


# ==================== Clerk 认证 ====================

async def _verify_clerk_auth(request: Request) -> str:
    """验证 Clerk JWT Token"""
    from app.api.auth_clerk import verify_clerk_token
    return await verify_clerk_token(request)


async def _verify_ws_clerk_auth(token: str) -> bool:
    """验证 WebSocket 的 Clerk Token"""
    from app.api.auth_clerk import verify_clerk_ws_token
    result = await verify_clerk_ws_token(token)
    return result is not None


# ==================== 统一入口 ====================

async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    验证请求认证

    根据 settings.auth_provider 选择认证方式:
    - token: 返回 API token
    - clerk: 返回 Clerk user ID
    """
    if settings.use_clerk_auth:
        return await _verify_clerk_auth(request)
    else:
        return await _verify_token_auth(request, credentials)


async def verify_ws_token(token: str) -> bool:
    """
    验证 WebSocket 连接的认证

    根据 settings.auth_provider 选择认证方式
    """
    if settings.use_clerk_auth:
        return await _verify_ws_clerk_auth(token)
    else:
        return await _verify_ws_token_auth(token)


def resolve_workspace_id(workspace_id: str, token_or_user_id: str) -> str:
    """
    解析 workspace_id

    如果 workspace_id 是 "default"，则映射到用户对应的 workspace
    - Token 模式: 使用 token hash
    - Clerk 模式: 使用 user_id hash
    """
    if workspace_id == "default":
        if settings.use_clerk_auth:
            from app.api.auth_clerk import get_workspace_id_for_clerk_user
            return get_workspace_id_for_clerk_user(token_or_user_id)
        else:
            return settings.get_workspace_id_for_token(token_or_user_id)
    return workspace_id
