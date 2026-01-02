"""
CLI 会话 API - 读取 Claude Code 会话文件

提供:
- 列出项目列表
- 列出会话列表
- 获取会话详情
- 恢复会话
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cli", tags=["cli-sessions"])

# Claude 项目目录
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


class ProjectInfo(BaseModel):
    """项目信息"""
    path: str  # 项目路径（编码后）
    name: str  # 项目名称
    full_path: str  # 完整路径
    session_count: int  # 会话数量
    last_modified: Optional[datetime] = None


class SessionInfo(BaseModel):
    """会话信息"""
    session_id: str
    project_path: str
    created_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    last_prompt: Optional[str] = None
    total_cost_usd: Optional[float] = None


class SessionDetail(BaseModel):
    """会话详情"""
    session_id: str
    project_path: str
    messages: list[dict]  # 消息列表
    total_cost_usd: Optional[float] = None
    num_turns: int = 0


def decode_project_path(encoded_path: str) -> str:
    """解码项目路径（Claude 使用 - 替换 /）"""
    # 例如: -Users-mira-projects-myapp -> /Users/mira/projects/myapp
    if encoded_path.startswith('-'):
        return encoded_path.replace('-', '/')
    return encoded_path


def encode_project_path(path: str) -> str:
    """编码项目路径"""
    return path.replace('/', '-')


def parse_jsonl_file(file_path: Path) -> list[dict]:
    """解析 JSONL 文件"""
    messages = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"Error parsing {file_path}: {e}")
    return messages


def get_session_summary(messages: list[dict]) -> dict:
    """从消息列表中提取会话摘要"""
    summary = {
        'message_count': len(messages),
        'last_prompt': None,
        'total_cost_usd': None,
        'created_at': None,
        'last_message_at': None,
    }

    for msg in messages:
        msg_type = msg.get('type', '')

        # 提取时间戳
        if 'timestamp' in msg:
            ts = msg['timestamp']
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
            else:
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    dt = None

            if dt:
                if summary['created_at'] is None:
                    summary['created_at'] = dt
                summary['last_message_at'] = dt

        # 提取用户提示
        if msg_type == 'user':
            content = msg.get('message', {}).get('content', [])
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    summary['last_prompt'] = block.get('text', '')[:200]

        # 提取成本
        if msg_type == 'result':
            if 'costUsd' in msg:
                cost = msg['costUsd']
                if summary['total_cost_usd'] is None:
                    summary['total_cost_usd'] = 0
                summary['total_cost_usd'] += cost

    return summary


@router.get("/projects", response_model=list[ProjectInfo])
async def list_projects():
    """列出所有 Claude Code 项目"""
    projects = []

    if not CLAUDE_PROJECTS_DIR.exists():
        return projects

    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        # 获取项目名称
        encoded_path = project_dir.name
        full_path = decode_project_path(encoded_path)
        name = Path(full_path).name or full_path

        # 统计会话数量
        session_files = list(project_dir.glob("*.jsonl"))
        session_count = len(session_files)

        # 获取最后修改时间
        last_modified = None
        if session_files:
            latest_file = max(session_files, key=lambda f: f.stat().st_mtime)
            last_modified = datetime.fromtimestamp(latest_file.stat().st_mtime)

        projects.append(ProjectInfo(
            path=encoded_path,
            name=name,
            full_path=full_path,
            session_count=session_count,
            last_modified=last_modified,
        ))

    # 按最后修改时间排序
    projects.sort(key=lambda p: p.last_modified or datetime.min, reverse=True)

    return projects


@router.get("/projects/{project_path}/sessions", response_model=list[SessionInfo])
async def list_sessions(project_path: str):
    """列出项目的所有会话"""
    project_dir = CLAUDE_PROJECTS_DIR / project_path

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    sessions = []

    for session_file in project_dir.glob("*.jsonl"):
        session_id = session_file.stem

        # 解析会话文件获取摘要
        messages = parse_jsonl_file(session_file)
        summary = get_session_summary(messages)

        sessions.append(SessionInfo(
            session_id=session_id,
            project_path=project_path,
            created_at=summary['created_at'],
            last_message_at=summary['last_message_at'],
            message_count=summary['message_count'],
            last_prompt=summary['last_prompt'],
            total_cost_usd=summary['total_cost_usd'],
        ))

    # 按最后消息时间排序（处理 None 值和时区问题）
    def sort_key(s):
        if s.last_message_at is None:
            return datetime.min
        # 移除时区信息以便比较
        dt = s.last_message_at
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt

    sessions.sort(key=sort_key, reverse=True)

    return sessions


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    project_path: Optional[str] = Query(None, description="项目路径（编码后）"),
    limit: int = Query(100, description="消息数量限制"),
    offset: int = Query(0, description="偏移量"),
):
    """获取会话详情"""
    session_file = None

    if project_path:
        # 指定了项目路径
        session_file = CLAUDE_PROJECTS_DIR / project_path / f"{session_id}.jsonl"
    else:
        # 搜索所有项目
        for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if project_dir.is_dir():
                candidate = project_dir / f"{session_id}.jsonl"
                if candidate.exists():
                    session_file = candidate
                    project_path = project_dir.name
                    break

    if not session_file or not session_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    # 解析会话
    all_messages = parse_jsonl_file(session_file)
    summary = get_session_summary(all_messages)

    # 分页
    messages = all_messages[offset:offset + limit]

    return SessionDetail(
        session_id=session_id,
        project_path=project_path,
        messages=messages,
        total_cost_usd=summary['total_cost_usd'],
        num_turns=len([m for m in all_messages if m.get('type') == 'user']),
    )


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    project_path: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    types: Optional[str] = Query(None, description="消息类型过滤，逗号分隔"),
):
    """获取会话消息（支持过滤和分页）"""
    session_file = None

    if project_path:
        session_file = CLAUDE_PROJECTS_DIR / project_path / f"{session_id}.jsonl"
    else:
        for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if project_dir.is_dir():
                candidate = project_dir / f"{session_id}.jsonl"
                if candidate.exists():
                    session_file = candidate
                    break

    if not session_file or not session_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    all_messages = parse_jsonl_file(session_file)

    # 类型过滤
    if types:
        type_list = [t.strip() for t in types.split(',')]
        all_messages = [m for m in all_messages if m.get('type') in type_list]

    total = len(all_messages)
    messages = all_messages[offset:offset + limit]

    return {
        'total': total,
        'offset': offset,
        'limit': limit,
        'messages': messages,
    }


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    project_path: Optional[str] = Query(None),
):
    """
    准备恢复会话

    返回恢复会话所需的信息，实际恢复由 CLI 或 ClaudeAgent 完成
    """
    session_file = None
    full_project_path = None

    if project_path:
        session_file = CLAUDE_PROJECTS_DIR / project_path / f"{session_id}.jsonl"
        full_project_path = decode_project_path(project_path)
    else:
        for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if project_dir.is_dir():
                candidate = project_dir / f"{session_id}.jsonl"
                if candidate.exists():
                    session_file = candidate
                    project_path = project_dir.name
                    full_project_path = decode_project_path(project_path)
                    break

    if not session_file or not session_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    # 返回恢复信息
    return {
        'session_id': session_id,
        'project_path': project_path,
        'full_project_path': full_project_path,
        'resume_command': f'mule --resume {session_id} --directory "{full_project_path}"',
    }
