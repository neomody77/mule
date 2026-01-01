"""
Google ADK Agent - 基于 Google Agent Development Kit 的 Agent

使用 Google ADK 替代 Claude Agent SDK，支持：
- Gemini 模型
- 自定义工具（文件操作、命令执行等）
- 流式响应
- 会话管理
"""
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event

from app.config import settings
from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager
from app.services.adk_tools import ALL_TOOLS
from app.prompts import get_system_prompt

logger = logging.getLogger(__name__)


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

        # 获取模型配置
        model = os.environ.get("ADK_MODEL", "gemini-2.0-flash")

        # 创建 Agent
        self.agent = Agent(
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
            app_name=f"mule_{self.workspace_id}",
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
            # 使用 Runner 执行
            result = await asyncio.to_thread(
                self.runner.run,
                prompt
            )

            # 提取最终响应文本
            if hasattr(result, 'text'):
                return result.text
            elif isinstance(result, str):
                return result
            else:
                return str(result)

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
