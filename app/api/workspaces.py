"""工作区管理 REST API"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth import verify_token
from app.models.workspace import WorkspaceCreate, WorkspaceInfo
from app.services.workspace_manager import workspace_manager
from app.services.message_store import message_store


class SessionResponse(BaseModel):
    """Session 响应模型"""
    id: str
    workspace_id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str


class SessionCreate(BaseModel):
    """创建 Session 请求"""
    title: Optional[str] = None


class SessionUpdate(BaseModel):
    """更新 Session 请求"""
    title: Optional[str] = None

router = APIRouter()


@router.get("", response_model=list[WorkspaceInfo])
async def list_workspaces(token: str = Depends(verify_token)):
    """列出所有工作区"""
    return workspace_manager.list_workspaces()


@router.post("", response_model=WorkspaceInfo, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace: WorkspaceCreate,
    token: str = Depends(verify_token)
):
    """创建新工作区"""
    try:
        return workspace_manager.create_workspace(workspace.name, workspace.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trash/list", response_model=list[WorkspaceInfo])
async def list_trash(token: str = Depends(verify_token)):
    """列出回收站中的工作区"""
    return workspace_manager.list_deleted_workspaces()


@router.get("/{workspace_id}", response_model=WorkspaceInfo)
async def get_workspace(workspace_id: str, token: str = Depends(verify_token)):
    """获取工作区详情"""
    workspace = workspace_manager.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    permanent: bool = False,
    token: str = Depends(verify_token)
):
    """删除工作区（默认软删除，可恢复）"""
    if not workspace_manager.delete_workspace(workspace_id, permanent=permanent):
        raise HTTPException(status_code=404, detail="Workspace not found")


@router.post("/{workspace_id}/restore", response_model=WorkspaceInfo)
async def restore_workspace(workspace_id: str, token: str = Depends(verify_token)):
    """恢复已删除的工作区"""
    workspace = workspace_manager.restore_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.get("/{workspace_id}/files")
async def list_files(
    workspace_id: str,
    path: Optional[str] = "",
    token: str = Depends(verify_token)
):
    """列出工作区文件"""
    if not workspace_manager.workspace_exists(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")

    try:
        files = workspace_manager.list_files(workspace_id, path or "")
        return {"files": files}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workspace_id}/files/{file_path:path}")
async def read_file(
    workspace_id: str,
    file_path: str,
    token: str = Depends(verify_token)
):
    """读取文件内容"""
    if not workspace_manager.workspace_exists(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")

    try:
        content = workspace_manager.read_file(workspace_id, file_path)
        return {"path": file_path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workspace_id}/sessions/{session_id}/messages")
async def get_session_messages(
    workspace_id: str,
    session_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    token: str = Depends(verify_token)
):
    """获取 session 消息历史"""
    messages = message_store.get_messages(workspace_id, session_id, limit=limit, offset=offset)
    return {"messages": messages}


@router.delete("/{workspace_id}/sessions/{session_id}/messages", status_code=status.HTTP_204_NO_CONTENT)
async def clear_session_messages(
    workspace_id: str,
    session_id: str,
    token: str = Depends(verify_token)
):
    """清空 session 消息历史"""
    message_store.clear_messages(workspace_id, session_id)


# ============== Session 管理 API ==============

@router.get("/{workspace_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(
    workspace_id: str,
    token: str = Depends(verify_token)
):
    """列出工作区下的所有 sessions"""
    if not workspace_manager.workspace_exists(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    sessions = message_store.list_sessions(workspace_id)
    return [SessionResponse(**s.to_dict()) for s in sessions]


@router.post("/{workspace_id}/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    workspace_id: str,
    session_data: SessionCreate,
    token: str = Depends(verify_token)
):
    """创建新 session"""
    if not workspace_manager.workspace_exists(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    import uuid
    session_id = str(uuid.uuid4())
    session = message_store.create_session(workspace_id, session_id, session_data.title)
    return SessionResponse(**session.to_dict())


@router.get("/{workspace_id}/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    workspace_id: str,
    session_id: str,
    token: str = Depends(verify_token)
):
    """获取 session 详情"""
    session = message_store.get_session(workspace_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(**session.to_dict())


@router.patch("/{workspace_id}/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    workspace_id: str,
    session_id: str,
    session_data: SessionUpdate,
    token: str = Depends(verify_token)
):
    """更新 session 信息"""
    session = message_store.update_session(workspace_id, session_id, session_data.title)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(**session.to_dict())


@router.delete("/{workspace_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    workspace_id: str,
    session_id: str,
    token: str = Depends(verify_token)
):
    """删除 session"""
    if not message_store.delete_session(workspace_id, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
