"""工作区管理 REST API"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import verify_token
from app.models.workspace import WorkspaceCreate, WorkspaceInfo
from app.services.workspace_manager import workspace_manager

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
