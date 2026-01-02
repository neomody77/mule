"""
Sandbox Agent - Docker 隔离的 Claude Code 执行环境

使用 Docker 容器运行 Claude Code，实现：
- 工作区安全隔离
- 自动传递 Claude 认证信息
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


def get_container_name(workspace_id: str, session_id: str) -> str:
    """生成容器名称"""
    hash_input = f"{workspace_id}:{session_id}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:8]
    return f"mule-sandbox-{hash_value}"


class SandboxAgent:
    """Docker 隔离的 Claude Code Agent

    在 Docker 容器中运行 Claude Code，提供安全的代码执行环境。
    """

    def __init__(self, workspace_path: str, workspace_id: str = "", agent_session_id: str = ""):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id
        self.container_name = get_container_name(workspace_id, agent_session_id)

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

        # 创建新容器
        logger.info(f"Creating new sandbox container: {self.container_name}")

        docker_args = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "-v", f"{self.workspace_path}:/workspace",
            "-w", "/workspace",
            "-e", f"HOST_UID={os.getuid()}",
            "-e", f"HOST_GID={os.getgid()}",
        ]

        # 挂载 Claude 认证信息
        if CLAUDE_CONFIG_DIR.exists():
            docker_args.extend(["-v", f"{CLAUDE_CONFIG_DIR}:/home/dev/.claude:ro"])

        if CLAUDE_AUTH_FILE.exists():
            docker_args.extend(["-v", f"{CLAUDE_AUTH_FILE}:/home/dev/.claude.json:ro"])

        # 传递环境变量
        if os.environ.get("ANTHROPIC_API_KEY"):
            docker_args.extend(["-e", "ANTHROPIC_API_KEY"])

        docker_args.append(SANDBOX_IMAGE)
        docker_args.append("sleep")
        docker_args.append("infinity")

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
            # 使用 -p 参数执行单次提示，使用 --output-format stream-json 获取流式 JSON 输出
            claude_cmd = ["claude", "-p", prompt, "--output-format", "stream-json"]

            # 如果有之前的会话，使用 --resume 继续
            if self.session_id:
                claude_cmd.extend(["--resume", self.session_id])

            # 在容器中执行
            docker_exec = [
                "docker", "exec", "-u", "dev", "-w", "/workspace",
                self.container_name,
                "/bin/bash", "-lc",
                " ".join(claude_cmd)
            ]

            logger.debug(f"Docker exec command: {' '.join(docker_exec)}")

            # 启动进程
            self._process = await asyncio.create_subprocess_exec(
                *docker_exec,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

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
                        # 文本输出
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

                                # 记录工具使用
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
                        # 工具结果
                        message = event.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if block.get("type") == "tool_result":
                                yield {
                                    "event": "tool_result",
                                    "data": {
                                        "id": block.get("tool_use_id", ""),
                                        "content": block.get("content", "")[:300],
                                        "is_error": block.get("is_error", False),
                                    }
                                }

                    elif event_type == "result":
                        # 执行结果
                        session_id = event.get("session_id", "")
                        self.session_id = session_id

                        # 持久化 session_id
                        if self.workspace_id and self.agent_session_id and session_id:
                            workspace_manager.set_session_id(
                                self.workspace_id,
                                self.agent_session_id,
                                session_id
                            )

                        # 记录任务结束
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
                        # 系统消息
                        subtype = event.get("subtype", "")
                        if subtype == "init":
                            yield {
                                "event": "status",
                                "data": {"type": "thinking", "message": "Thinking..."}
                            }

                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse JSON: {line_text}")
                    continue

            # 等待进程结束
            await self._process.wait()

            # 检查 stderr
            stderr = await self._process.stderr.read()
            if stderr:
                logger.warning(f"Sandbox stderr: {stderr.decode('utf-8')}")

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
