"""
Claude Agent 服务 - 核心代码执行引擎

使用 Claude Agent SDK，提供:
- 流式响应处理
- 内置工具 (Read, Write, Edit, Bash, Glob, Grep)
- 会话上下文管理
- 操作日志记录
"""
import logging
import shutil
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    UserMessage,
)

from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager
from app.prompts import get_system_prompt

logger = logging.getLogger(__name__)

# 查找系统安装的 Claude CLI（使用已登录的凭据）
def find_system_claude_cli() -> str | None:
    """查找系统 Claude CLI 路径"""
    # 尝试从 PATH 中查找
    claude_path = shutil.which("claude")
    if claude_path:
        logger.info(f"Found system Claude CLI: {claude_path}")
        return claude_path
    return None

SYSTEM_CLAUDE_CLI = find_system_claude_cli()


class ClaudeCodeAgent:
    """Claude Code Agent - 使用 Claude Agent SDK 的远程代码执行代理"""

    def __init__(self, workspace_path: str, workspace_id: str = "", agent_session_id: str = ""):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id

        # 从持久化存储恢复 session_id
        self.session_id: str | None = None
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

    def _stderr_callback(self, message: str) -> None:
        """处理 stderr 输出"""
        logger.warning(f"Claude CLI stderr: {message}")

    def _get_options(self, resume_session: bool = False) -> ClaudeAgentOptions:
        """获取 Agent SDK 配置

        Args:
            resume_session: 是否续接之前的会话
        """
        options = ClaudeAgentOptions(
            # 允许的工具 - 使用 SDK 内置工具
            allowed_tools=[
                "Read",      # 读取文件
                "Write",     # 写入文件
                "Edit",      # 编辑文件
                "Bash",      # 执行命令
                "Glob",      # 文件模式匹配
                "Grep",      # 搜索文件内容
            ],
            # 工作目录
            cwd=str(self.workspace_path),
            # 权限模式 - 跳过所有权限检查（服务端运行）
            permission_mode="bypassPermissions",
            # stderr 回调 - 捕获错误信息
            stderr=self._stderr_callback,
            # 使用系统 Claude CLI（已登录）
            cli_path=SYSTEM_CLAUDE_CLI,
            # 续接之前的会话
            resume=self.session_id if resume_session and self.session_id else None,
            # 系统提示 - 使用增强版 prompt
            system_prompt=get_system_prompt(str(self.workspace_path)),
        )

        if SYSTEM_CLAUDE_CLI:
            logger.info(f"Using system Claude CLI: {SYSTEM_CLAUDE_CLI}")
        else:
            logger.warning("System Claude CLI not found, using bundled version")

        return options

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """
        执行用户提示，返回流式响应

        Yields:
            dict: 事件字典，格式为 {"event": str, "data": dict}
        """
        try:
            # 判断是否需要续接会话
            resume_session = self.session_id is not None
            options = self._get_options(resume_session=resume_session)

            if resume_session:
                logger.info(f"Resuming session: {self.session_id}")
            logger.info(f"Executing prompt: {prompt[:100]}...")

            # 记录任务开始
            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            # 发送 task_start 状态
            yield {
                "event": "status",
                "data": {"type": "task_start", "message": "Starting task..."}
            }

            async for message in query(prompt=prompt, options=options):
                logger.debug(f"Received message type: {type(message).__name__}")

                # 处理系统消息
                if isinstance(message, SystemMessage):
                    logger.info(f"System message: {message.subtype}")
                    if hasattr(message, 'session_id'):
                        self.session_id = message.session_id
                        logger.info(f"Session started: {self.session_id}")
                    # 发送 thinking 状态
                    if message.subtype == 'init':
                        yield {
                            "event": "status",
                            "data": {"type": "thinking", "message": "Thinking..."}
                        }
                    continue

                # 处理用户消息 - 包含工具执行结果
                if isinstance(message, UserMessage):
                    if hasattr(message, 'content') and isinstance(message.content, list):
                        for block in message.content:
                            # ToolResultBlock - 工具执行结果
                            if hasattr(block, 'tool_use_id'):
                                tool_id = block.tool_use_id
                                is_error = getattr(block, 'is_error', False) or False
                                content = getattr(block, 'content', '')

                                # 截断过长的内容用于显示
                                display_content = content
                                if isinstance(content, str) and len(content) > 300:
                                    display_content = content[:300] + "..."

                                logger.debug(f"Tool result for {tool_id}: error={is_error}")

                                yield {
                                    "event": "tool_result",
                                    "data": {
                                        "id": tool_id,
                                        "is_error": is_error,
                                        "content": display_content,
                                    }
                                }
                    continue

                # 处理助手消息
                if isinstance(message, AssistantMessage):
                    logger.debug(f"Assistant message with {len(message.content)} blocks")
                    for block in message.content:
                        block_type = type(block).__name__
                        logger.debug(f"Block type: {block_type}")

                        if hasattr(block, 'text'):
                            text_content = block.text
                            logger.info(f"Text content: {text_content[:200] if len(text_content) > 200 else text_content}")
                            yield {
                                "event": "text_delta",
                                "data": {"text": text_content}
                            }
                        elif hasattr(block, 'name'):  # ToolUseBlock
                            tool_name = block.name
                            tool_input = getattr(block, 'input', {})
                            tool_id = getattr(block, 'id', '')

                            # 生成用户友好的工具描述
                            tool_desc = self._get_tool_description(tool_name, tool_input)

                            # === 记录工具使用日志 ===
                            if self.activity_logger:
                                self._log_tool_use(tool_name, tool_input)

                            yield {
                                "event": "tool_use_start",
                                "data": {
                                    "id": tool_id,
                                    "name": tool_name,
                                    "input": tool_input,
                                    "description": tool_desc,
                                }
                            }
                        elif hasattr(block, 'tool_use_id'):  # ToolResultBlock
                            yield {
                                "event": "tool_result",
                                "data": {
                                    "id": block.tool_use_id,
                                    "content": getattr(block, 'content', ''),
                                    "is_error": getattr(block, 'is_error', False),
                                }
                            }

                # 处理结果消息
                if isinstance(message, ResultMessage):
                    logger.info(f"Result: session={message.session_id}, turns={message.num_turns}")

                    # 记录任务结束
                    if self.activity_logger:
                        self.activity_logger.log_task_end(
                            success=not message.is_error,
                            error=getattr(message, 'result', '') if message.is_error else None
                        )

                    yield {
                        "event": "message_end",
                        "data": {
                            "session_id": message.session_id,
                            "duration_ms": getattr(message, 'duration_ms', 0),
                            "num_turns": message.num_turns,
                            "is_error": message.is_error,
                            "result": getattr(message, 'result', ''),
                        }
                    }
                    self.session_id = message.session_id
                    # 持久化 session_id
                    if self.workspace_id and self.agent_session_id and self.session_id:
                        workspace_manager.set_session_id(
                            self.workspace_id,
                            self.agent_session_id,
                            self.session_id
                        )
                    break

        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)

            # 记录任务失败
            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))

            yield {"event": "error", "data": {"message": str(e)}}

    def _log_tool_use(self, tool_name: str, tool_input: dict) -> None:
        """记录工具使用到活动日志"""
        if not self.activity_logger:
            return

        if tool_name == "Read":
            file_path = tool_input.get("file_path", "")
            self.activity_logger.log_file_read(file_path)

        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            content = tool_input.get("content", "")
            self.activity_logger.log_file_write(
                file_path,
                size=len(content) if content else None,
                is_new=True
            )

        elif tool_name == "Edit":
            file_path = tool_input.get("file_path", "")
            old_string = tool_input.get("old_string", "")
            new_string = tool_input.get("new_string", "")
            self.activity_logger.log_file_edit(
                file_path,
                changes={
                    "old_len": len(old_string),
                    "new_len": len(new_string),
                }
            )

        elif tool_name == "Bash":
            command = tool_input.get("command", "")
            self.activity_logger.log_bash_exec(command)

        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            self.activity_logger.log_glob(pattern)

        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", "")
            self.activity_logger.log_grep(pattern, path)

    def _get_tool_description(self, tool_name: str, tool_input: dict) -> str:
        """生成用户友好的工具描述"""
        if tool_name == "Read":
            file_path = tool_input.get("file_path", "")
            # 只显示文件名
            filename = file_path.split("/")[-1] if file_path else "file"
            return f"Reading {filename}..."
        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            filename = file_path.split("/")[-1] if file_path else "file"
            return f"Writing {filename}..."
        elif tool_name == "Edit":
            file_path = tool_input.get("file_path", "")
            filename = file_path.split("/")[-1] if file_path else "file"
            return f"Editing {filename}..."
        elif tool_name == "Bash":
            command = tool_input.get("command", "")
            # 截断过长的命令
            if len(command) > 50:
                command = command[:47] + "..."
            return f"Running: {command}"
        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            return f"Searching: {pattern}"
        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            return f"Grep: {pattern}"
        else:
            return f"Using {tool_name}..."

    async def cancel(self) -> None:
        """取消当前执行 - 对于 query() 不支持中断"""
        logger.info("Cancel requested (not supported for query mode)")

    def reset_session(self) -> None:
        """重置会话"""
        self.session_id = None
