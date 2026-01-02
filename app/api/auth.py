"""认证模块 - 简单 Token 认证"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings


security = HTTPBearer(auto_error=False)


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """验证 API Token

    支持两种方式:
    1. Authorization: Bearer <token>
    2. X-API-Token: <token>
    """
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


async def verify_ws_token(token: str) -> bool:
    """验证 WebSocket 连接的 Token"""
    return settings.is_valid_token(token)


def resolve_workspace_id(workspace_id: str, token: str) -> str:
    """解析 workspace_id

    如果 workspace_id 是 "default"，则映射到用户 token 对应的 workspace
    """
    if workspace_id == "default":
        return settings.get_workspace_id_for_token(token)
    return workspace_id
