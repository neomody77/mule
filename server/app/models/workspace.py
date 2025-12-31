"""工作区数据模型"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    """创建工作区请求"""
    name: str = Field(..., min_length=1, max_length=100, description="工作区名称")
    description: Optional[str] = Field(None, max_length=500, description="工作区描述")


class WorkspaceInfo(BaseModel):
    """工作区信息响应"""
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    path: str
    deleted: bool = False
    deleted_at: Optional[datetime] = None


class Workspace(BaseModel):
    """工作区完整模型"""
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
