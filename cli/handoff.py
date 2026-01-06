#!/usr/bin/env python3
"""
Mule Handoff - 快速将本地 Claude Code 会话接手到 Mule

使用场景:
- 正在用 Claude Code 工作，临时要出门
- 快速执行 `mule handoff` 将会话转移到 Mule
- 在手机上继续工作

实现原理:
1. 检测当前项目目录
2. 找到最新的 Claude Code session
3. 提取关键上下文（最近的对话、正在进行的任务等）
4. 在 Mule 上创建新 session 并发送上下文恢复 prompt
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Claude 项目目录
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def encode_project_path(path: str) -> str:
    """编码项目路径（/ -> -）"""
    return path.replace('/', '-')


def decode_project_path(encoded_path: str) -> str:
    """解码项目路径"""
    if encoded_path.startswith('-'):
        return encoded_path.replace('-', '/')
    return encoded_path


def get_current_project_dir() -> Optional[Path]:
    """获取当前项目对应的 Claude 项目目录

    会从当前目录向上查找，直到找到有对应 Claude 会话的目录
    """
    cwd = Path.cwd().resolve()

    # 首先尝试精确匹配
    encoded_path = encode_project_path(str(cwd))
    project_dir = CLAUDE_PROJECTS_DIR / encoded_path
    if project_dir.exists():
        return project_dir

    # 向上查找父目录
    for parent in cwd.parents:
        encoded_parent = encode_project_path(str(parent))
        parent_project_dir = CLAUDE_PROJECTS_DIR / encoded_parent
        if parent_project_dir.exists():
            return parent_project_dir

        # 到根目录就停止
        if parent == parent.parent:
            break

    return None


def find_latest_session(project_dir: Path) -> Optional[Path]:
    """找到最新的会话文件"""
    session_files = list(project_dir.glob("*.jsonl"))

    if not session_files:
        return None

    # 按修改时间排序，找最新的非空文件
    valid_files = []
    for f in session_files:
        if f.stat().st_size > 0:
            valid_files.append((f, f.stat().st_mtime))

    if not valid_files:
        return None

    valid_files.sort(key=lambda x: x[1], reverse=True)
    return valid_files[0][0]


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


def extract_context(messages: list[dict], max_messages: int = 20) -> dict:
    """提取会话上下文

    返回:
    - recent_conversation: 最近的对话内容
    - active_tasks: 正在进行的任务（来自 TodoWrite）
    - current_files: 最近操作的文件
    - last_prompt: 用户的最后一条提示
    """
    recent_conversation: list[dict] = []
    active_tasks: list[dict] = []
    current_files: set[str] = set()
    last_prompt: Optional[str] = None
    session_id: Optional[str] = None
    cwd: Optional[str] = None

    # 只取最后 N 条消息
    recent = messages[-max_messages * 3:] if len(messages) > max_messages * 3 else messages

    for msg in recent:
        msg_type = msg.get('type', '')

        # 获取 session ID 和工作目录
        if 'sessionId' in msg:
            session_id = msg['sessionId']
        if 'cwd' in msg:
            cwd = msg['cwd']

        # 提取用户消息
        if msg_type == 'user':
            message_data = msg.get('message', {})
            content = message_data.get('content', [])

            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text = block.get('text', '')
                    recent_conversation.append({
                        'role': 'user',
                        'content': text[:1000]  # 限制长度
                    })
                    last_prompt = text

        # 提取助手消息
        elif msg_type == 'assistant':
            message_data = msg.get('message', {})
            content = message_data.get('content', [])

            assistant_text = []
            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        assistant_text.append(block.get('text', ''))
                    elif block.get('type') == 'tool_use':
                        tool_name = block.get('name', '')
                        tool_input = block.get('input', {})

                        # 提取文件操作
                        if tool_name in ('Read', 'Edit', 'Write'):
                            file_path = tool_input.get('file_path', '')
                            if file_path:
                                current_files.add(file_path)

                        # 提取 TodoWrite
                        if tool_name == 'TodoWrite':
                            todos = tool_input.get('todos', [])
                            for todo in todos:
                                if todo.get('status') in ('pending', 'in_progress'):
                                    active_tasks.append({
                                        'content': todo.get('content', ''),
                                        'status': todo.get('status', ''),
                                    })

            if assistant_text:
                recent_conversation.append({
                    'role': 'assistant',
                    'content': '\n'.join(assistant_text)[:2000]
                })

    return {
        'recent_conversation': recent_conversation[-max_messages:],
        'active_tasks': active_tasks[-10:],
        'current_files': list(current_files)[-10:],
        'last_prompt': last_prompt,
        'session_id': session_id,
        'cwd': cwd,
    }


def generate_handoff_prompt(context: dict, project_path: str) -> str:
    """生成用于恢复上下文的 prompt"""

    parts = []

    # 项目信息
    parts.append("# 会话接手 (Handoff)")
    parts.append("\n我刚从本地 Claude Code 会话接手过来，以下是上下文：")
    parts.append(f"\n## 项目路径\n{project_path}")

    # 正在进行的任务
    if context['active_tasks']:
        parts.append("\n## 正在进行的任务")
        for task in context['active_tasks']:
            status = "⏳" if task['status'] == 'in_progress' else "📋"
            parts.append(f"- {status} {task['content']}")

    # 最近操作的文件
    if context['current_files']:
        parts.append("\n## 最近操作的文件")
        for f in context['current_files']:
            parts.append(f"- {f}")

    # 最近对话摘要
    if context['recent_conversation']:
        parts.append("\n## 最近对话摘要")
        for msg in context['recent_conversation'][-6:]:  # 最近 3 轮
            role = "用户" if msg['role'] == 'user' else "助手"
            content = msg['content'][:500]
            if len(msg['content']) > 500:
                content += "..."
            parts.append(f"\n**{role}**: {content}")

    # 最后的用户请求
    if context['last_prompt']:
        parts.append("\n## 用户最后的请求")
        parts.append(context['last_prompt'][:1000])

    parts.append("\n---")
    parts.append("\n请根据以上上下文，继续帮我完成工作。如果需要了解更多细节，可以读取相关文件。")

    return '\n'.join(parts)


async def handoff_to_mule(
    server_url: str,
    token: str,
    workspace_id: str,
    context: dict,
    project_path: str,
    auto_start: bool = True,
) -> dict:
    """将会话接手到 Mule

    返回:
    - session_id: 新创建的 session ID
    - workspace_id: workspace ID
    - prompt: 生成的恢复 prompt
    """
    # 生成恢复 prompt
    prompt = generate_handoff_prompt(context, project_path)

    async with httpx.AsyncClient(timeout=30) as client:
        # 创建新 session
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        base_url = server_url.rstrip('/')

        # 创建 session
        create_url = f"{base_url}/api/workspaces/{workspace_id}/sessions"

        session_title = f"Handoff: {Path(project_path).name}"
        response = await client.post(
            create_url,
            headers=headers,
            json={"title": session_title}
        )

        if response.status_code != 200:
            raise Exception(f"Failed to create session: {response.text}")

        session_data = response.json()
        session_id = session_data.get('id')

        result = {
            'session_id': session_id,
            'workspace_id': workspace_id,
            'prompt': prompt,
            'server_url': server_url,
            'auto_start': auto_start,
        }

        return result


def print_handoff_info(result: dict, context: dict):
    """打印接手信息"""
    print("\n" + "=" * 60)
    print("✅ Handoff 准备完成!")
    print("=" * 60)

    print(f"\n📦 Server: {result['server_url']}")
    print(f"🗂️  Workspace: {result['workspace_id']}")
    print(f"💬 Session: {result['session_id']}")

    if context['active_tasks']:
        print(f"\n📋 待完成任务: {len(context['active_tasks'])} 个")
        for task in context['active_tasks'][:3]:
            print(f"   - {task['content'][:50]}")

    if context['current_files']:
        print(f"\n📁 相关文件: {len(context['current_files'])} 个")

    print("\n" + "-" * 60)
    print("现在可以在手机上打开 Mule 继续工作了!")
    print("-" * 60 + "\n")


async def run_handoff(
    server_url: str,
    token: str,
    workspace_id: str = "default",
    project_dir: Optional[str] = None,
    auto_start: bool = True,
    verbose: bool = False,
):
    """执行 handoff"""

    # 确定项目目录
    cwd: Path
    claude_project_dir: Optional[Path]

    if project_dir:
        cwd = Path(project_dir).resolve()
        encoded_path = encode_project_path(str(cwd))
        claude_project_dir = CLAUDE_PROJECTS_DIR / encoded_path
    else:
        cwd = Path.cwd().resolve()
        claude_project_dir = get_current_project_dir()

    if not claude_project_dir or not claude_project_dir.exists():
        print("❌ 未找到当前项目的 Claude Code 会话")
        print(f"   项目路径: {cwd}")
        print(f"   期望的会话目录: {CLAUDE_PROJECTS_DIR / encode_project_path(str(cwd))}")
        return None

    # 找最新的 session
    session_file = find_latest_session(claude_project_dir)

    if not session_file:
        print("❌ 未找到有效的会话文件")
        print(f"   会话目录: {claude_project_dir}")
        return None

    if verbose:
        print(f"📄 找到会话: {session_file.name}")

    # 解析会话
    messages = parse_jsonl_file(session_file)

    if not messages:
        print("❌ 会话文件为空或无法解析")
        return None

    if verbose:
        print(f"📊 消息数量: {len(messages)}")

    # 提取上下文
    context = extract_context(messages)

    if verbose:
        print(f"📋 任务数量: {len(context['active_tasks'])}")
        print(f"📁 相关文件: {len(context['current_files'])}")

    # 发送到 Mule
    print("\n🚀 正在连接 Mule 服务器...")

    try:
        result = await handoff_to_mule(
            server_url=server_url,
            token=token,
            workspace_id=workspace_id,
            context=context,
            project_path=str(cwd),
            auto_start=auto_start,
        )

        print_handoff_info(result, context)

        # 如果 auto_start，发送 prompt 启动任务
        if auto_start:
            print("🏃 正在启动会话...")
            from .mule_cli import MuleCLI

            cli = MuleCLI(
                server_url=server_url,
                token=token,
                workspace_id=workspace_id,
                session_id=result['session_id'],
            )

            await cli.run_once(result['prompt'])

        return result

    except Exception as e:
        print(f"❌ Handoff 失败: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return None


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(
        description='Mule Handoff - 将本地 Claude Code 会话接手到 Mule',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 在项目目录下执行，自动接手最新会话
  mule-handoff

  # 指定服务器
  mule-handoff --server http://192.168.1.100:8080

  # 只准备，不自动启动
  mule-handoff --no-start

  # 指定项目目录
  mule-handoff --project /path/to/project

环境变量:
  MULE_SERVER    - Mule 服务器地址
  MULE_TOKEN     - 认证 token
  MULE_WORKSPACE - 默认 workspace ID
        """
    )

    parser.add_argument(
        '-s', '--server',
        default=os.getenv('MULE_SERVER', 'http://localhost:8080'),
        help='Mule 服务器地址'
    )
    parser.add_argument(
        '-t', '--token',
        default=os.getenv('MULE_TOKEN', ''),
        help='认证 token'
    )
    parser.add_argument(
        '-w', '--workspace',
        default=os.getenv('MULE_WORKSPACE', 'default'),
        help='Workspace ID'
    )
    parser.add_argument(
        '-p', '--project',
        help='项目目录路径（默认当前目录）'
    )
    parser.add_argument(
        '--no-start',
        action='store_true',
        help='不自动启动会话'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='详细输出'
    )

    args = parser.parse_args()

    # 检查 token
    if not args.token:
        print("❌ 需要认证 token (--token 或 MULE_TOKEN 环境变量)")
        sys.exit(1)

    # 执行 handoff
    result = asyncio.run(run_handoff(
        server_url=args.server,
        token=args.token,
        workspace_id=args.workspace,
        project_dir=args.project,
        auto_start=not args.no_start,
        verbose=args.verbose,
    ))

    if not result:
        sys.exit(1)


if __name__ == '__main__':
    main()
