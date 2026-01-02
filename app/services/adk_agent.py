"""
Google ADK Agent - 基于 Google Agent Development Kit 的 Agent

使用 Google ADK 替代 Claude Agent SDK，支持：
- Gemini 模型（原生支持）
- 第三方模型（通过 LiteLLM，如 OpenRouter、OpenAI、Anthropic）
- 自定义工具（文件操作、命令执行等）
- 流式响应
- 会话管理

第三方 API 配置示例（OpenRouter）：
    ADK_MODEL=openrouter/anthropic/claude-3.5-sonnet
    ADK_API_BASE=https://openrouter.ai/api/v1
    ADK_API_KEY=sk-or-xxx
"""
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional, Union

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.config import settings
from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager
from app.services.adk_tools import ALL_TOOLS
from app.prompts import get_system_prompt

logger = logging.getLogger(__name__)


def _create_model():
    """
    创建模型实例

    根据配置决定使用：
    - Gemini 模型（直接使用模型名称字符串）
    - LiteLLM 模型（使用 LiteLlm 包装器）

    环境变量：
    - ADK_MODEL: 模型名称，如 "gemini-2.0-flash" 或 "openrouter/anthropic/claude-3.5-sonnet"
    - ADK_API_BASE: 自定义 API 端点（用于 LiteLLM）
    - ADK_API_KEY: API 密钥（用于 LiteLLM）
    """
    model_name = os.environ.get("ADK_MODEL", "gemini-2.0-flash")
    api_base = os.environ.get("ADK_API_BASE", "")
    api_key = os.environ.get("ADK_API_KEY", "")

    # 判断是否需要使用 LiteLLM
    # LiteLLM 模型名称通常包含 "/" 如 "openai/gpt-4" 或 "openrouter/..."
    use_litellm = (
        "/" in model_name and not model_name.startswith("gemini")
    ) or api_base

    if use_litellm:
        try:
            from google.adk.models.lite_llm import LiteLlm

            kwargs = {"model": model_name}
            if api_base:
                kwargs["api_base"] = api_base
            if api_key:
                kwargs["api_key"] = api_key

            logger.info(f"Using LiteLLM model: {model_name}, api_base: {api_base or 'default'}")
            return LiteLlm(**kwargs)
        except ImportError:
            logger.warning("LiteLLM not available, falling back to direct model name")
            return model_name
    else:
        logger.info(f"Using Gemini model: {model_name}")
        return model_name


class ADKAgent:
    """基于 Google ADK 的 Coding Agent"""

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

        # 初始化 ADK 组件
        self._init_adk()

    def _init_adk(self):
        """初始化 Google ADK 组件"""
        # 获取系统提示
        system_prompt = get_system_prompt(str(self.workspace_path))

        # 创建模型（支持 Gemini 或 LiteLLM）
        model = _create_model()

        # 使用 "agents" 作为 app_name（ADK 从包路径推断出 "agents"）
        self.app_name = "agents"
        self.user_id = f"user_{self.workspace_id or 'default'}"

        # 创建 Agent（使用 LlmAgent 支持更多配置）
        self.agent = LlmAgent(
            name="coding_agent",
            model=model,
            description="A coding assistant that helps with software development tasks",
            instruction=system_prompt,
            tools=ALL_TOOLS,
        )

        # 创建 Session 服务
        self.session_service = InMemorySessionService()

        # 创建 Runner
        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """
        执行用户提示，返回流式响应

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
                "data": {"type": "task_start", "message": "Starting task..."}
            }

            # 创建或获取会话
            if not self.session_id:
                self.session_id = str(uuid.uuid4())
                logger.info(f"Created new session: {self.session_id}")

            yield {
                "event": "status",
                "data": {"type": "init", "session_id": self.session_id}
            }

            # 发送 thinking 状态
            yield {
                "event": "status",
                "data": {"type": "thinking", "message": "Thinking..."}
            }

            # 切换到工作目录
            original_cwd = os.getcwd()
            os.chdir(self.workspace_path)

            try:
                # 运行 Agent
                response = await self._run_agent(prompt)

                # 发送响应
                if response:
                    yield {
                        "event": "text_delta",
                        "data": {"text": response}
                    }

                # 持久化 session_id
                if self.workspace_id and self.agent_session_id:
                    workspace_manager.set_session_id(
                        self.workspace_id,
                        self.agent_session_id,
                        self.session_id
                    )

                # 发送结束事件
                yield {
                    "event": "message_end",
                    "data": {
                        "session_id": self.session_id,
                        "is_error": False,
                        "result": response or "",
                    }
                }

            finally:
                os.chdir(original_cwd)

            # 记录任务结束
            if self.activity_logger:
                self.activity_logger.log_task_end(success=True)

        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)

            # 记录任务失败
            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))

            yield {"event": "error", "data": {"message": str(e)}}

    async def _run_agent(self, prompt: str) -> str:
        """运行 ADK Agent 并获取响应"""
        try:
            # 创建用户消息内容
            user_content = types.Content(
                role="user",
                parts=[types.Part(text=prompt)]
            )

            # 确保 session 存在（ADK InMemorySessionService 方法是 async 的）
            existing = await self.session_service.get_session(
                app_name=self.app_name,
                user_id=self.user_id,
                session_id=self.session_id
            )
            if existing is None:
                # Session 不存在，创建新的
                session = await self.session_service.create_session(
                    app_name=self.app_name,
                    user_id=self.user_id,
                    session_id=self.session_id
                )
                logger.info(f"Created ADK session: {session.id} for app={self.app_name} user={self.user_id}")
            else:
                logger.info(f"Using existing ADK session: {existing.id}")

            # 使用 Runner.run_async（异步版本）
            response_parts = []
            async for event in self.runner.run_async(
                user_id=self.user_id,
                session_id=self.session_id,
                new_message=user_content
            ):
                # 从事件中提取文本响应
                if hasattr(event, 'content') and event.content:
                    for part in event.content.parts:
                        if hasattr(part, 'text') and part.text:
                            response_parts.append(part.text)

            return "".join(response_parts) if response_parts else ""

        except Exception as e:
            logger.error(f"ADK runner error: {e}", exc_info=True)
            raise

    async def execute_streaming(self, prompt: str) -> AsyncGenerator[dict, None]:
        """
        流式执行（如果 ADK 支持）

        目前 ADK 的流式 API 主要用于语音/视频，
        这里提供一个兼容接口
        """
        async for event in self.execute(prompt):
            yield event

    async def cancel(self) -> None:
        """取消当前执行"""
        logger.info("Cancel requested")
        # TODO: ADK 取消机制

    def reset_session(self) -> None:
        """重置会话"""
        self.session_id = None
        self._init_adk()


class ADKAgentFactory:
    """ADK Agent 工厂"""

    @staticmethod
    def create(
        workspace_path: str,
        workspace_id: str = "",
        agent_session_id: str = ""
    ) -> ADKAgent:
        """创建 ADK Agent 实例"""
        return ADKAgent(
            workspace_path=workspace_path,
            workspace_id=workspace_id,
            agent_session_id=agent_session_id
        )


# 检查是否启用 ADK
def is_adk_enabled() -> bool:
    """检查是否启用 Google ADK"""
    return os.environ.get("USE_GOOGLE_ADK", "").lower() in ("1", "true", "yes")
