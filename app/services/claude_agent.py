"""
Claude Agent 服务 - 核心代码执行引擎

使用 Claude Agent SDK 的 ClaudeSDKClient，提供:
- 持续会话支持（多轮对话保持上下文）
- 流式响应处理
- 中断支持
- 内置工具 (Read, Write, Edit, Bash, Glob, Grep)
- 操作日志记录
"""
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
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
    """Claude Code Agent - 使用 ClaudeSDKClient 的远程代码执行代理

    特性：
    - 持续会话：多轮对话共享上下文
    - 中断支持：可以中断正在执行的任务
    - 流式响应：实时返回处理结果
    """

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

        # ClaudeSDKClient 实例 - 保持会话连续性
        self._client: Optional[ClaudeSDKClient] = None
        self._is_connected = False
        self._is_processing = False

    def _stderr_callback(self, message: str) -> None:
        """处理 stderr 输出"""
        logger.warning(f"Claude CLI stderr: {message}")

    def _get_options(self) -> ClaudeAgentOptions:
        """获取 Agent SDK 配置"""
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
            resume=self.session_id if self.session_id else None,
            # 系统提示 - 使用增强版 prompt
            system_prompt=get_system_prompt(str(self.workspace_path)),
        )

        if SYSTEM_CLAUDE_CLI:
            logger.info(f"Using system Claude CLI: {SYSTEM_CLAUDE_CLI}")
        else:
            logger.warning("System Claude CLI not found, using bundled version")

        return options

    async def _ensure_connected(self) -> None:
        """确保客户端已连接"""
        if self._client is None or not self._is_connected:
            options = self._get_options()
            self._client = ClaudeSDKClient(options=options)
            await self._client.connect()
            self._is_connected = True
            logger.info(f"ClaudeSDKClient connected for workspace {self.workspace_id}")

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """
        执行用户提示，返回流式响应

        使用 ClaudeSDKClient 保持会话连续性，支持多轮对话。

        Yields:
            dict: 事件字典，格式为 {"event": str, "data": dict}
        """
        self._is_processing = True

        try:
            # 确保客户端已连接
            await self._ensure_connected()

            logger.info(f"Executing prompt: {prompt[:100]}...")

            # 记录任务开始
            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            # 发送 task_start 状态
            yield {
                "event": "status",
                "data": {"type": "task_start", "message": "Starting task..."}
            }

            # 发送查询
            await self._client.query(prompt)

            # 处理响应流
            async for message in self._client.receive_response():
                logger.debug(f"Received message type: {type(message).__name__}")

                # 处理系统消息
                if isinstance(message, SystemMessage):
                    logger.info(f"System message: {message.subtype}")
                    if hasattr(message, 'data') and 'session_id' in message.data:
                        self.session_id = message.data['session_id']
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
                            if isinstance(block, ToolResultBlock):
                                tool_id = block.tool_use_id
                                is_error = block.is_error or False
                                content = block.content or ''

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

                        if isinstance(block, TextBlock):
                            text_content = block.text
                            logger.info(f"Text content: {text_content[:200] if len(text_content) > 200 else text_content}")
                            yield {
                                "event": "text_delta",
                                "data": {"text": text_content}
                            }
                        elif isinstance(block, ToolUseBlock):
                            tool_name = block.name
                            tool_input = block.input
                            tool_id = block.id

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
                        elif isinstance(block, ToolResultBlock):
                            yield {
                                "event": "tool_result",
                                "data": {
                                    "id": block.tool_use_id,
                                    "content": block.content or '',
                                    "is_error": block.is_error or False,
                                }
                            }

                # 处理结果消息
                if isinstance(message, ResultMessage):
                    logger.info(f"Result: session={message.session_id}, turns={message.num_turns}")

                    # 记录任务结束
                    if self.activity_logger:
                        self.activity_logger.log_task_end(
                            success=not message.is_error,
                            error=message.result if message.is_error else None
                        )

                    # 提取 usage 信息
                    usage_data = {}
                    if message.usage:
                        # usage 是 dict[model_name, ModelUsage]
                        total_input = 0
                        total_output = 0
                        context_window = 200000  # 默认值
                        for model_name, model_usage in message.usage.items():
                            if isinstance(model_usage, dict):
                                total_input += model_usage.get("inputTokens", 0)
                                total_output += model_usage.get("outputTokens", 0)
                                total_input += model_usage.get("cacheReadInputTokens", 0)
                                if model_usage.get("contextWindow"):
                                    context_window = model_usage["contextWindow"]
                        usage_data = {
                            "input_tokens": total_input,
                            "output_tokens": total_output,
                            "context_window": context_window,
                        }

                    yield {
                        "event": "message_end",
                        "data": {
                            "session_id": message.session_id,
                            "duration_ms": message.duration_ms,
                            "num_turns": message.num_turns,
                            "is_error": message.is_error,
                            "result": message.result or '',
                            "total_cost_usd": message.total_cost_usd,
                            "usage": usage_data,
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

        finally:
            self._is_processing = False

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
        def _truncate(s: str, max_len: int = 50) -> str:
            return s[:max_len - 3] + "..." if len(s) > max_len else s

        def _get_filename(path: str) -> str:
            return path.split("/")[-1] if path else "file"

        # 工具描述生成器映射
        generators = {
            "Read": lambda: f"Reading {_get_filename(tool_input.get('file_path', ''))}...",
            "Write": lambda: f"Writing {_get_filename(tool_input.get('file_path', ''))}...",
            "Edit": lambda: f"Editing {_get_filename(tool_input.get('file_path', ''))}...",
            "Bash": lambda: f"Running: {_truncate(tool_input.get('command', ''))}",
            "Glob": lambda: f"Searching: {tool_input.get('pattern', '')}",
            "Grep": lambda: f"Grep: {tool_input.get('pattern', '')}",
            "WebSearch": lambda: f"Searching: {tool_input.get('query', '')}",
            "WebFetch": lambda: f"Fetching: {_truncate(tool_input.get('url', ''))}",
            "Task": lambda: f"Task: {tool_input.get('description', '')}",
        }

        generator = generators.get(tool_name)
        return generator() if generator else f"Using {tool_name}..."

    async def cancel(self) -> None:
        """取消当前执行 - 使用 ClaudeSDKClient 的 interrupt 功能"""
        if self._client and self._is_processing:
            logger.info("Interrupting current task...")
            try:
                await self._client.interrupt()
                logger.info("Task interrupted successfully")
            except Exception as e:
                logger.error(f"Failed to interrupt task: {e}")

    async def compact(self) -> dict:
        """压缩上下文 - 手动触发上下文压缩"""
        if not self.session_id:
            raise ValueError("No active session to compact")

        logger.info(f"Compacting context for session {self.session_id}")

        try:
            # 确保客户端已连接
            await self._ensure_connected()

            # 发送 /compact 命令让 Claude 压缩上下文
            await self._client.query("/compact")

            # 处理响应
            async for message in self._client.receive_response():
                if isinstance(message, ResultMessage):
                    logger.info(f"Compact completed: {message.result}")
                    return {
                        "success": True,
                        "session_id": message.session_id,
                        "result": message.result or "Context compacted successfully",
                    }

            return {"success": True, "message": "Context compacted"}

        except Exception as e:
            logger.error(f"Compact failed: {e}")
            raise

    async def disconnect(self) -> None:
        """断开连接"""
        if self._client and self._is_connected:
            try:
                await self._client.disconnect()
                logger.info("ClaudeSDKClient disconnected")
            except Exception as e:
                logger.error(f"Failed to disconnect: {e}")
            finally:
                self._is_connected = False
                self._client = None

    def reset_session(self) -> None:
        """重置会话 - 下次执行将创建新会话"""
        self.session_id = None
        # 断开当前连接，下次 execute 时会重新连接
        if self._client:
            asyncio.create_task(self.disconnect())

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._is_processing
