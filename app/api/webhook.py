"""
Webhook API - 接收外部消息

功能:
- 接收外部 HTTP 请求，发送到 Agent 执行
- 支持创建新 session 或复用已有 session
- 支持可选回调 URL
- 支持更新 plan monitor 配置
- 根据 token 隔离不同用户的 workspace
"""
import asyncio
import logging
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import verify_token
from app.config import settings
from app.services.message_store import message_store
from app.services.task_manager import task_manager, Task
from app.services.plan_monitor import plan_monitor_registry, PLAN_MONITOR_SESSION_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

# 存储回调 URL
_pending_callbacks: dict[str, str] = {}  # task_id -> callback_url


class WebhookMessageRequest(BaseModel):
    """Webhook 消息请求"""
    content: str = Field(..., description="消息内容")
    session_id: Optional[str] = Field(None, description="可选，复用已有 session")
    callback_url: Optional[str] = Field(None, description="可选，完成后回调 URL")


class WebhookMessageResponse(BaseModel):
    """Webhook 消息响应"""
    session_id: str
    task_id: str
    workspace_id: str = "default"
    messages_url: str


class PlanConfigUpdateRequest(BaseModel):
    """Plan 配置更新请求"""
    interval_minutes: Optional[int] = Field(None, ge=1, description="检测间隔（分钟）")
    interval_seconds: Optional[int] = Field(None, ge=60, description="检测间隔（秒）")
    enabled: Optional[bool] = Field(None, description="是否启用定时检测")


class PlanTriggerRequest(BaseModel):
    """Plan 手动触发请求"""
    force: bool = Field(False, description="强制执行，忽略内容变化检查")


@router.post("/message", response_model=WebhookMessageResponse)
async def webhook_message(
    request: WebhookMessageRequest,
    token: str = Depends(verify_token),
):
    """
    接收外部 webhook 消息

    - 创建或复用 session
    - 发送消息到 Agent 执行
    - 返回 session_id 供后续查询
    - 根据 token 自动隔离到对应的 workspace
    """
    # 根据 token 获取对应的 workspace_id
    workspace_id = settings.get_workspace_id_for_token(token)

    # 创建或复用 session
    session_id = request.session_id
    if not session_id:
        session_id = str(uuid4())
        message_store.create_session(workspace_id, session_id, title="Webhook Session")
    else:
        # 确保 session 存在
        message_store.ensure_session_exists(workspace_id, session_id, title="Webhook Session")

    # 保存用户消息
    message_store.append_user_message(workspace_id, session_id, request.content)

    # 创建任务
    task_key = f"{workspace_id}:{session_id}"
    task = task_manager.create_task(task_key, request.content)

    # 如果有回调 URL，注册回调
    if request.callback_url:
        _pending_callbacks[task.id] = request.callback_url
        # 注册完成回调
        task_manager.register_completion_callback(
            task_key,
            lambda t: _handle_task_completion(t, request.callback_url)
        )

    # 获取或创建 Agent 并启动任务
    from app.api.websocket import manager
    agent = manager.get_or_create_agent(workspace_id, session_id)
    task_manager.start_task(task, agent)

    logger.info(f"Webhook message received: session={session_id}, task={task.id}")

    return WebhookMessageResponse(
        session_id=session_id,
        task_id=task.id,
        workspace_id=workspace_id,
        messages_url=f"/api/workspaces/{workspace_id}/sessions/{session_id}/messages",
    )


async def _handle_task_completion(task: Task, callback_url: str):
    """处理任务完成回调"""
    try:
        # 清理回调记录
        _pending_callbacks.pop(task.id, None)

        # 发送回调
        async with httpx.AsyncClient() as client:
            response = await client.post(
                callback_url,
                json={
                    "task_id": task.id,
                    "status": task.status.value,
                    "workspace_id": task.workspace_id,
                    "error": task.error,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                },
                timeout=30.0,
            )
            logger.info(f"Callback sent to {callback_url}: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to send callback to {callback_url}: {e}")


@router.get("/plan/status")
async def get_plan_status(token: str = Depends(verify_token)):
    """获取 plan monitor 状态（根据 token 隔离）"""
    workspace_id = settings.get_workspace_id_for_token(token)
    monitor = plan_monitor_registry.get_monitor(workspace_id)
    return monitor.get_status()


@router.post("/plan/config")
async def update_plan_config(
    request: PlanConfigUpdateRequest,
    token: str = Depends(verify_token),
):
    """
    更新 plan monitor 配置

    - 可通过 webhook 更新检测间隔
    - 也可在 plan-monitor session 中通过对话更新
    - 根据 token 隔离到对应 workspace
    """
    workspace_id = settings.get_workspace_id_for_token(token)
    monitor = plan_monitor_registry.get_monitor(workspace_id)

    if request.interval_minutes is not None:
        monitor.update_interval(minutes=request.interval_minutes)
    elif request.interval_seconds is not None:
        monitor.update_interval(seconds=request.interval_seconds)

    if request.enabled is not None:
        monitor.config.enabled = request.enabled

    return {
        "status": "updated",
        "workspace_id": workspace_id,
        "config": monitor.config.to_dict(),
    }


@router.post("/plan/trigger")
async def trigger_plan_execution(
    request: PlanTriggerRequest = PlanTriggerRequest(),
    token: str = Depends(verify_token),
):
    """
    手动触发 plan.md 执行

    - force=True: 强制执行，忽略内容变化检查
    - force=False: 仅在内容变化时执行
    - 根据 token 隔离到对应 workspace
    """
    workspace_id = settings.get_workspace_id_for_token(token)
    monitor = plan_monitor_registry.get_monitor(workspace_id)
    result = await monitor.check_and_execute(force=request.force)
    result["workspace_id"] = workspace_id
    return result


@router.get("/plan/session")
async def get_plan_session_info(token: str = Depends(verify_token)):
    """获取 plan monitor session 信息（根据 token 隔离）"""
    workspace_id = settings.get_workspace_id_for_token(token)
    session = message_store.get_session(workspace_id, PLAN_MONITOR_SESSION_ID)

    return {
        "session_id": PLAN_MONITOR_SESSION_ID,
        "workspace_id": workspace_id,
        "exists": session is not None,
        "session": session.to_dict() if session else None,
        "messages_url": f"/api/workspaces/{workspace_id}/sessions/{PLAN_MONITOR_SESSION_ID}/messages",
    }
