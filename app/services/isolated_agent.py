"""
Isolated Claude Agent - Docker 容器隔离版本

在 Docker 容器中运行 Claude CLI，实现：
- Workspace 隔离：每个 workspace 只能访问自己的目录
- 资源限制：CPU、内存限制
- 安全边界：无法访问宿主机文件系统
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

from app.config import settings
from app.services.docker_executor import docker_executor
from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager
from app.prompts import get_system_prompt

logger = logging.getLogger(__name__)


class IsolatedClaudeAgent:
    """Docker 隔离版 Claude Agent"""

    def __init__(
        self,
        workspace_path: str,
        workspace_id: str = "",
        agent_session_id: str = ""
    ):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id

        # 从持久化存储恢复 session_id
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

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """
        在 Docker 容器中执行用户提示，返回流式响应

        Yields:
            dict: 事件字典，格式为 {"event": str, "data": dict}
        """
        try:
            # 记录任务开始
            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            # 发送 task_start 状态
            yield {
                "event": "status",
                "data": {"type": "task_start", "message": "Starting task in container..."}
            }

            # 获取系统提示
            system_prompt = get_system_prompt("/workspace")  # 容器内路径

            # 构建 Claude CLI 命令
            cmd = [
                "claude",
                "--output-format", "stream-json",
                "--verbose",
                "--dangerously-skip-permissions",  # 容器内跳过权限检查
            ]

            if self.session_id:
                cmd.extend(["--resume", self.session_id])
                logger.info(f"Resuming session: {self.session_id}")

            # 系统提示写入临时文件
            system_prompt_file = "/tmp/system_prompt.txt"
            cmd.extend(["--system-prompt", system_prompt])

            cmd.extend(["-p", prompt])

            logger.info(f"Executing in container: {prompt[:100]}...")

            # 发送 thinking 状态
            yield {
                "event": "status",
                "data": {"type": "thinking", "message": "Thinking..."}
            }

            # 在容器中执行
            async for line in self._exec_in_container(cmd):
                event = self._parse_stream_line(line)
                if event:
                    yield event

                    # 检查是否是结果消息
                    if event.get("event") == "message_end":
                        data = event.get("data", {})
                        new_session_id = data.get("session_id")
                        if new_session_id:
                            self.session_id = new_session_id
                            # 持久化 session_id
                            if self.workspace_id and self.agent_session_id:
                                workspace_manager.set_session_id(
                                    self.workspace_id,
                                    self.agent_session_id,
                                    self.session_id
                                )

            # 记录任务结束
            if self.activity_logger:
                self.activity_logger.log_task_end(success=True)

        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)

            # 记录任务失败
            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))

            yield {"event": "error", "data": {"message": str(e)}}

    async def _exec_in_container(self, cmd: list[str]) -> AsyncGenerator[str, None]:
        """在容器中执行命令，流式返回输出"""
        container = await docker_executor.get_or_create_container(
            self.workspace_id,
            str(self.workspace_path)
        )

        if not container:
            yield '{"type": "error", "error": "Failed to get container"}'
            return

        try:
            # 创建 exec 实例 (以 coder 用户执行，避免 root 权限问题)
            exec_instance = docker_executor.client.api.exec_create(
                container.id,
                cmd,
                stdout=True,
                stderr=True,
                workdir="/workspace",
                user="coder",  # 以非 root 用户执行
            )

            # 流式读取输出 (使用 demux=True 分离 stdout/stderr)
            output = docker_executor.client.api.exec_start(
                exec_instance['Id'],
                stream=True,
                demux=True
            )

            buffer = ""
            for stdout_chunk, stderr_chunk in output:
                # 只处理 stdout，忽略 stderr（Claude 的 JSON 输出在 stdout）
                if stdout_chunk:
                    chunk = stdout_chunk.decode('utf-8', errors='replace') if isinstance(stdout_chunk, bytes) else stdout_chunk
                    buffer += chunk

                # 按行处理
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        yield line

            # 处理剩余内容
            if buffer.strip():
                yield buffer.strip()

        except Exception as e:
            logger.error(f"Container exec error: {e}")
            yield json.dumps({"type": "error", "error": str(e)})

    def _parse_stream_line(self, line: str) -> Optional[dict]:
        """解析 stream-json 输出行"""
        try:
            data = json.loads(line)
            msg_type = data.get("type", "")

            # 系统消息
            if msg_type == "system":
                subtype = data.get("subtype", "")
                if subtype == "init":
                    session_id = data.get("session_id")
                    if session_id:
                        self.session_id = session_id
                        logger.info(f"Session started: {session_id}")
                    return {
                        "event": "status",
                        "data": {"type": "init", "session_id": session_id}
                    }
                return None

            # 助手消息
            if msg_type == "assistant":
                content = data.get("message", {}).get("content", [])
                events = []

                for block in content:
                    block_type = block.get("type", "")

                    if block_type == "text":
                        return {
                            "event": "text_delta",
                            "data": {"text": block.get("text", "")}
                        }

                    elif block_type == "tool_use":
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {})
                        tool_id = block.get("id", "")

                        # 记录工具使用
                        if self.activity_logger:
                            self._log_tool_use(tool_name, tool_input)

                        return {
                            "event": "tool_use_start",
                            "data": {
                                "id": tool_id,
                                "name": tool_name,
                                "input": tool_input,
                                "description": self._get_tool_description(tool_name, tool_input),
                            }
                        }

                return None

            # 用户消息 (工具结果)
            if msg_type == "user":
                content = data.get("message", {}).get("content", [])

                for block in content:
                    if block.get("type") == "tool_result":
                        return {
                            "event": "tool_result",
                            "data": {
                                "id": block.get("tool_use_id", ""),
                                "content": block.get("content", "")[:300],
                                "is_error": block.get("is_error", False),
                            }
                        }

                return None

            # 结果消息
            if msg_type == "result":
                return {
                    "event": "message_end",
                    "data": {
                        "session_id": data.get("session_id", ""),
                        "duration_ms": data.get("duration_ms", 0),
                        "num_turns": data.get("num_turns", 0),
                        "is_error": data.get("is_error", False),
                        "result": data.get("result", ""),
                    }
                }

            return None

        except json.JSONDecodeError:
            # 非 JSON 行，可能是 stderr 输出
            logger.debug(f"Non-JSON line: {line[:100]}")
            return None

    def _log_tool_use(self, tool_name: str, tool_input: dict) -> None:
        """记录工具使用到活动日志"""
        if not self.activity_logger:
            return

        if tool_name == "Read":
            self.activity_logger.log_file_read(tool_input.get("file_path", ""))
        elif tool_name == "Write":
            self.activity_logger.log_file_write(
                tool_input.get("file_path", ""),
                size=len(tool_input.get("content", "")),
                is_new=True
            )
        elif tool_name == "Edit":
            self.activity_logger.log_file_edit(
                tool_input.get("file_path", ""),
                changes={"old_len": len(tool_input.get("old_string", "")),
                         "new_len": len(tool_input.get("new_string", ""))}
            )
        elif tool_name == "Bash":
            self.activity_logger.log_bash_exec(tool_input.get("command", ""))
        elif tool_name == "Glob":
            self.activity_logger.log_glob(tool_input.get("pattern", ""))
        elif tool_name == "Grep":
            self.activity_logger.log_grep(
                tool_input.get("pattern", ""),
                tool_input.get("path", "")
            )

    def _get_tool_description(self, tool_name: str, tool_input: dict) -> str:
        """生成用户友好的工具描述"""
        if tool_name == "Read":
            filename = tool_input.get("file_path", "file").split("/")[-1]
            return f"Reading {filename}..."
        elif tool_name == "Write":
            filename = tool_input.get("file_path", "file").split("/")[-1]
            return f"Writing {filename}..."
        elif tool_name == "Edit":
            filename = tool_input.get("file_path", "file").split("/")[-1]
            return f"Editing {filename}..."
        elif tool_name == "Bash":
            command = tool_input.get("command", "")[:47]
            if len(tool_input.get("command", "")) > 50:
                command += "..."
            return f"Running: {command}"
        elif tool_name == "Glob":
            return f"Searching: {tool_input.get('pattern', '')}"
        elif tool_name == "Grep":
            return f"Grep: {tool_input.get('pattern', '')}"
        return f"Using {tool_name}..."

    async def cancel(self) -> None:
        """取消当前执行"""
        logger.info("Cancel requested")
        # TODO: 实现容器内进程取消

    def reset_session(self) -> None:
        """重置会话"""
        self.session_id = None
