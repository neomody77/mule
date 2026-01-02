"""
Sandbox Agent - Docker 隔离的 Claude Code 执行环境

使用 Docker 容器运行 Claude Code，实现：
- 工作区安全隔离
- 自动传递 Claude 认证信息（每个容器独立的 .claude 目录）
- 支持流式输出
- 容器生命周期管理
"""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import AsyncGenerator, Optional
import hashlib

from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager
from app.config import settings

logger = logging.getLogger(__name__)

# Docker 镜像名称
SANDBOX_IMAGE = "mule-workspace:latest"

# Claude 认证文件路径 (宿主机)
CLAUDE_CONFIG_DIR = Path.home() / ".claude"
CLAUDE_AUTH_FILE = Path.home() / ".claude.json"

# 容器数据目录（每个容器独立的 .claude 目录）
CONTAINER_DATA_DIR = settings.data_dir / "containers"


def get_container_name(workspace_id: str, session_id: str) -> str:
    """生成容器名称"""
    hash_input = f"{workspace_id}:{session_id}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:8]
    return f"mule-sandbox-{hash_value}"


class SandboxAgent:
    """Docker 隔离的 Claude Code Agent

    在 Docker 容器中运行 Claude Code，提供安全的代码执行环境。

    认证策略：
    - 每个容器有独立的 .claude 目录（避免 projects/ 冲突）
    - 从宿主机复制认证文件 .credentials.json 和 .claude.json
    - 容器内的 .claude 目录可读写
    """

    def __init__(self, workspace_path: str, workspace_id: str = "", agent_session_id: str = ""):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id
        self.container_name = get_container_name(workspace_id, agent_session_id)

        # 容器专属的 .claude 目录（持久化）
        self.container_claude_dir = CONTAINER_DATA_DIR / self.container_name / ".claude"

        # 容器内的会话 ID
        self.session_id: Optional[str] = None
        if workspace_id and agent_session_id:
            self.session_id = workspace_manager.get_session_id(workspace_id, agent_session_id)
            if self.session_id:
                logger.info(f"Restored session {self.session_id} for {workspace_id}:{agent_session_id}")

        # 确保工作区存在
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        # 活动日志记录器
        self.activity_logger: Optional[AgentLogger] = None
        if workspace_id and agent_session_id:
            self.activity_logger = agent_logger_manager.get_logger(workspace_id, agent_session_id)

        self._process: Optional[asyncio.subprocess.Process] = None
        self._is_processing = False

    def _setup_container_claude_dir(self) -> None:
        """准备容器专属的 .claude 目录（在宿主机上）

        挂载策略：
        - .credentials.json: 只读挂载宿主机的（token 更新会同步）
        - .claude/: 容器专属目录，可读写（projects/ 等）
        - .claude.json: 复制一份到容器专属目录（Claude 需要写入）
        """
        import shutil

        # 创建容器专属目录
        self.container_claude_dir.mkdir(parents=True, exist_ok=True)

        # 复制 .claude.json 到容器专属目录（如果不存在）
        # 这个文件 Claude 需要写入，所以不能只读挂载
        src_claude_json = CLAUDE_AUTH_FILE
        dst_claude_json = self.container_claude_dir / ".claude.json"
        if src_claude_json.exists() and not dst_claude_json.exists():
            shutil.copy2(src_claude_json, dst_claude_json)
            os.chmod(dst_claude_json, 0o666)
            logger.info(f"Copied claude.json to {dst_claude_json}")

        # 设置目录权限
        os.chmod(self.container_claude_dir, 0o777)

    def _container_exists(self) -> bool:
        """检查容器是否存在"""
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        return self.container_name in result.stdout.split('\n')

    def _container_running(self) -> bool:
        """检查容器是否正在运行"""
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        return self.container_name in result.stdout.split('\n')

    def _ensure_container(self) -> None:
        """确保容器存在并运行"""
        if self._container_running():
            logger.info(f"Container {self.container_name} is already running")
            return

        if self._container_exists():
            logger.info(f"Starting existing container: {self.container_name}")
            subprocess.run(["docker", "start", self.container_name], check=True)
            return

        # 准备容器专属的 .claude 目录
        self._setup_container_claude_dir()

        # 创建新容器
        logger.info(f"Creating new sandbox container: {self.container_name}")

        host_uid = os.getuid()
        host_gid = os.getgid()

        # 获取宿主机用户名，用于确定容器内 HOME 目录
        import pwd
        host_user = pwd.getpwuid(host_uid).pw_name
        container_home = f"/home/{host_user}"

        docker_args = [
            "docker", "run", "-d",
            "--name", self.container_name,
            # 以宿主机用户身份运行（解决挂载文件权限问题）
            "--user", f"{host_uid}:{host_gid}",
            # 挂载工作区
            "-v", f"{self.workspace_path}:/workspace",
            "-w", "/workspace",
            # .claude/ 目录挂载（可读写，包含 projects/ 等）
            "-v", f"{self.container_claude_dir}:{container_home}/.claude",
            # .credentials.json 只读挂载到 .claude/ 内（token 更新会同步）
            "-v", f"{CLAUDE_CONFIG_DIR / '.credentials.json'}:{container_home}/.claude/.credentials.json:ro",
            # .claude.json 挂载（可读写）
            "-v", f"{self.container_claude_dir / '.claude.json'}:{container_home}/.claude.json",
        ]

        # 传递 API Key 环境变量（如果有）
        if os.environ.get("ANTHROPIC_API_KEY"):
            docker_args.extend(["-e", "ANTHROPIC_API_KEY"])

        # 传递代理环境变量（如果有）
        for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
            if os.environ.get(proxy_var):
                docker_args.extend(["-e", f"{proxy_var}={os.environ[proxy_var]}"])

        docker_args.extend([
            SANDBOX_IMAGE,
            "sleep", "infinity"
        ])

        subprocess.run(docker_args, check=True)
        logger.info(f"Container {self.container_name} created and started")

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """在 Docker 容器中执行 Claude Code"""
        self._is_processing = True

        try:
            # 确保容器运行
            self._ensure_container()

            logger.info(f"Executing prompt in sandbox: {prompt[:100]}...")

            # 记录任务开始
            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            yield {
                "event": "status",
                "data": {"type": "task_start", "message": "Starting task in sandbox..."}
            }

            # 构建 claude 命令
            # 注意: --output-format stream-json 需要配合 --verbose 使用
            claude_cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]

            # 如果有之前的会话，使用 --resume 继续
            if self.session_id:
                claude_cmd.extend(["--resume", self.session_id])

            # 在容器中执行（容器已以正确 UID 运行，无需 -u）
            docker_exec = [
                "docker", "exec", "-w", "/workspace",
                self.container_name,
                "/bin/bash", "-lc",
                " ".join(f'"{arg}"' if " " in arg else arg for arg in claude_cmd)
            ]

            logger.debug(f"Docker exec command: {' '.join(docker_exec)}")

            # 启动进程
            self._process = await asyncio.create_subprocess_exec(
                *docker_exec,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # 后台任务持续消费 stderr，避免缓冲区满导致死锁
            stderr_lines: list[str] = []

            async def drain_stderr():
                async for line in self._process.stderr:
                    stderr_lines.append(line.decode('utf-8').rstrip())

            stderr_task = asyncio.create_task(drain_stderr())

            # 处理流式输出
            async for line in self._process.stdout:
                line_text = line.decode('utf-8').strip()
                if not line_text:
                    continue

                try:
                    event = json.loads(line_text)
                    event_type = event.get("type", "")

                    # 转换事件格式
                    if event_type == "assistant":
                        message = event.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if block.get("type") == "text":
                                yield {
                                    "event": "text_delta",
                                    "data": {"text": block.get("text", "")}
                                }
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "")
                                tool_input = block.get("input", {})
                                tool_id = block.get("id", "")

                                if self.activity_logger:
                                    self._log_tool_use(tool_name, tool_input)

                                yield {
                                    "event": "tool_use_start",
                                    "data": {
                                        "id": tool_id,
                                        "name": tool_name,
                                        "input": tool_input,
                                        "description": self._get_tool_description(tool_name, tool_input),
                                    }
                                }

                    elif event_type == "user":
                        message = event.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if block.get("type") == "tool_result":
                                yield {
                                    "event": "tool_result",
                                    "data": {
                                        "id": block.get("tool_use_id", ""),
                                        "content": str(block.get("content", ""))[:300],
                                        "is_error": block.get("is_error", False),
                                    }
                                }

                    elif event_type == "result":
                        session_id = event.get("session_id", "")
                        self.session_id = session_id

                        if self.workspace_id and self.agent_session_id and session_id:
                            workspace_manager.set_session_id(
                                self.workspace_id,
                                self.agent_session_id,
                                session_id
                            )

                        if self.activity_logger:
                            self.activity_logger.log_task_end(
                                success=not event.get("is_error", False),
                                error=event.get("result") if event.get("is_error") else None
                            )

                        yield {
                            "event": "message_end",
                            "data": {
                                "session_id": session_id,
                                "duration_ms": event.get("duration_ms", 0),
                                "num_turns": event.get("num_turns", 0),
                                "is_error": event.get("is_error", False),
                                "result": event.get("result", ""),
                                "total_cost_usd": event.get("total_cost_usd", 0),
                            }
                        }

                    elif event_type == "system":
                        subtype = event.get("subtype", "")
                        if subtype == "init":
                            yield {
                                "event": "status",
                                "data": {"type": "thinking", "message": "Thinking..."}
                            }

                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse JSON: {line_text}")
                    continue

            await self._process.wait()

            # 等待 stderr 读取完成
            await stderr_task
            if stderr_lines:
                logger.warning(f"Sandbox stderr: {chr(10).join(stderr_lines)}")

        except Exception as e:
            logger.error(f"Sandbox execution error: {e}", exc_info=True)

            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))

            yield {"event": "error", "data": {"message": str(e)}}

        finally:
            self._is_processing = False
            self._process = None

    def _log_tool_use(self, tool_name: str, tool_input: dict) -> None:
        """记录工具使用"""
        if not self.activity_logger:
            return

        log_handlers = {
            "Read": lambda: self.activity_logger.log_file_read(tool_input.get("file_path", "")),
            "Write": lambda: self.activity_logger.log_file_write(
                tool_input.get("file_path", ""),
                size=len(tool_input.get("content", "")),
                is_new=True
            ),
            "Edit": lambda: self.activity_logger.log_file_edit(
                tool_input.get("file_path", ""),
                changes={"old_len": len(tool_input.get("old_string", "")), "new_len": len(tool_input.get("new_string", ""))}
            ),
            "Bash": lambda: self.activity_logger.log_bash_exec(tool_input.get("command", "")),
            "Glob": lambda: self.activity_logger.log_glob(tool_input.get("pattern", "")),
            "Grep": lambda: self.activity_logger.log_grep(tool_input.get("pattern", ""), tool_input.get("path", "")),
        }

        handler = log_handlers.get(tool_name)
        if handler:
            handler()

    def _get_tool_description(self, tool_name: str, tool_input: dict) -> str:
        """生成工具描述"""
        def _truncate(s: str, max_len: int = 50) -> str:
            return s[:max_len - 3] + "..." if len(s) > max_len else s

        def _get_filename(path: str) -> str:
            return path.split("/")[-1] if path else "file"

        generators = {
            "Read": lambda: f"Reading {_get_filename(tool_input.get('file_path', ''))}...",
            "Write": lambda: f"Writing {_get_filename(tool_input.get('file_path', ''))}...",
            "Edit": lambda: f"Editing {_get_filename(tool_input.get('file_path', ''))}...",
            "Bash": lambda: f"Running: {_truncate(tool_input.get('command', ''))}",
            "Glob": lambda: f"Searching: {tool_input.get('pattern', '')}",
            "Grep": lambda: f"Grep: {tool_input.get('pattern', '')}",
        }

        generator = generators.get(tool_name)
        return generator() if generator else f"Using {tool_name}..."

    async def cancel(self) -> None:
        """取消当前执行"""
        if self._process and self._is_processing:
            logger.info("Cancelling sandbox execution...")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()

    def stop_container(self) -> None:
        """停止容器"""
        if self._container_running():
            logger.info(f"Stopping container: {self.container_name}")
            subprocess.run(["docker", "stop", self.container_name], check=False)

    def remove_container(self) -> None:
        """删除容器"""
        if self._container_exists():
            logger.info(f"Removing container: {self.container_name}")
            subprocess.run(["docker", "rm", "-f", self.container_name], check=False)

    def reset_session(self) -> None:
        """重置会话"""
        self.session_id = None

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._is_processing
