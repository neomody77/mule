"""
Permission Adapter - 远程权限审批适配器

实现类似 HAPI 的细粒度权限控制：
- 单次批准
- 会话级批准
- 拒绝
- 中止任务

支持通过 WebSocket 将权限请求转发到远程客户端（手机/Web）进行审批。
"""
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Any

logger = logging.getLogger(__name__)


class PermissionDecision(Enum):
    """权限决策类型"""
    APPROVED = "approved"                     # 单次批准
    APPROVED_FOR_SESSION = "approved_for_session"  # 会话期间自动批准同类操作
    DENIED = "denied"                         # 拒绝此操作
    ABORT = "abort"                           # 中止整个任务


class PermissionBehavior(Enum):
    """ACP 权限行为"""
    ALLOW = "allow"
    REJECT = "reject"
    CANCELLED = "cancelled"


@dataclass
class PermissionRequest:
    """权限请求"""
    tool_use_id: str
    tool_name: str
    tool_input: dict
    options: list[dict] = field(default_factory=list)
    description: str = ""
    created_at: float = 0


@dataclass
class PermissionResponse:
    """权限响应"""
    behavior: PermissionBehavior
    updated_input: Optional[dict] = None


class PermissionAdapter:
    """
    远程权限审批适配器

    处理来自 Agent 的权限请求，将其转发到远程客户端，
    等待用户决策后返回给 Agent。

    特性：
    - 支持会话级批准（同类工具自动批准）
    - 支持超时自动处理
    - 支持批量取消
    """

    DEFAULT_TIMEOUT = 300.0  # 5 分钟超时

    def __init__(
        self,
        on_permission_request: Callable[[dict], Any],
        default_behavior: PermissionBehavior = PermissionBehavior.ALLOW,
    ):
        """
        Args:
            on_permission_request: 权限请求回调（发送到远程客户端）
            default_behavior: 超时时的默认行为
        """
        self._on_permission_request = on_permission_request
        self._default_behavior = default_behavior

        # 待处理的权限请求: tool_use_id -> Future
        self._pending: dict[str, asyncio.Future] = {}

        # 待处理请求的元数据: tool_use_id -> PermissionRequest
        self._pending_requests: dict[str, PermissionRequest] = {}

        # 会话级批准的工具: tool_name -> True
        self._session_approved: set[str] = set()

        # 会话级拒绝的工具: tool_name -> True
        self._session_denied: set[str] = set()

    async def handle_permission_request(self, request: dict) -> dict:
        """
        处理来自 Agent 的权限请求

        这是 ACP 协议中 Agent 调用我们的方法。

        Args:
            request: 权限请求参数
                - tool_use_id: 工具调用 ID
                - tool_name: 工具名称
                - tool_input: 工具输入参数
                - options: 可选的决策选项
                - description: 操作描述

        Returns:
            ACP 权限响应
                - behavior: "allow" | "reject" | "cancelled"
                - updatedInput: 可选的修改后输入
        """
        tool_use_id = request.get("tool_use_id", "")
        tool_name = request.get("tool_name", "")
        tool_input = request.get("tool_input", {})
        options = request.get("options", [])
        description = request.get("description", "")

        logger.info(f"Permission request: {tool_name} (id={tool_use_id})")

        # 检查会话级批准
        if tool_name in self._session_approved:
            logger.info(f"Auto-approved (session): {tool_name}")
            return {"behavior": PermissionBehavior.ALLOW.value}

        # 检查会话级拒绝
        if tool_name in self._session_denied:
            logger.info(f"Auto-denied (session): {tool_name}")
            return {"behavior": PermissionBehavior.REJECT.value}

        # 创建请求记录
        perm_request = PermissionRequest(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_input=tool_input,
            options=options,
            description=description,
            created_at=asyncio.get_event_loop().time(),
        )
        self._pending_requests[tool_use_id] = perm_request

        # 创建 Future 等待用户响应
        future = asyncio.get_event_loop().create_future()
        self._pending[tool_use_id] = future

        # 通知远程客户端
        try:
            await self._on_permission_request({
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "options": options,
                "description": description or self._generate_description(tool_name, tool_input),
            })
        except Exception as e:
            logger.error(f"Failed to send permission request: {e}")
            self._pending.pop(tool_use_id, None)
            self._pending_requests.pop(tool_use_id, None)
            return {"behavior": self._default_behavior.value}

        # 等待用户响应
        try:
            response = await asyncio.wait_for(future, timeout=self.DEFAULT_TIMEOUT)
            return self._build_response(tool_name, response)
        except asyncio.TimeoutError:
            logger.warning(f"Permission request timeout: {tool_use_id}")
            return {"behavior": self._default_behavior.value}
        except asyncio.CancelledError:
            logger.info(f"Permission request cancelled: {tool_use_id}")
            return {"behavior": PermissionBehavior.CANCELLED.value}
        finally:
            self._pending.pop(tool_use_id, None)
            self._pending_requests.pop(tool_use_id, None)

    def respond(
        self,
        tool_use_id: str,
        decision: PermissionDecision,
        updated_input: Optional[dict] = None,
    ) -> bool:
        """
        响应权限请求

        Args:
            tool_use_id: 工具调用 ID
            decision: 用户决策
            updated_input: 可选的修改后输入

        Returns:
            是否成功响应
        """
        if tool_use_id not in self._pending:
            logger.warning(f"No pending request: {tool_use_id}")
            return False

        future = self._pending[tool_use_id]
        if future.done():
            logger.warning(f"Request already resolved: {tool_use_id}")
            return False

        future.set_result({
            "decision": decision,
            "updated_input": updated_input,
        })

        logger.info(f"Permission responded: {tool_use_id} -> {decision.value}")
        return True

    def _build_response(self, tool_name: str, response: dict) -> dict:
        """构建 ACP 响应"""
        decision = response.get("decision", PermissionDecision.APPROVED)
        updated_input = response.get("updated_input")

        result = {}

        if decision == PermissionDecision.APPROVED:
            result["behavior"] = PermissionBehavior.ALLOW.value

        elif decision == PermissionDecision.APPROVED_FOR_SESSION:
            self._session_approved.add(tool_name)
            result["behavior"] = PermissionBehavior.ALLOW.value
            logger.info(f"Tool approved for session: {tool_name}")

        elif decision == PermissionDecision.DENIED:
            result["behavior"] = PermissionBehavior.REJECT.value

        elif decision == PermissionDecision.ABORT:
            result["behavior"] = PermissionBehavior.CANCELLED.value

        if updated_input:
            result["updatedInput"] = updated_input

        return result

    def _generate_description(self, tool_name: str, tool_input: dict) -> str:
        """生成操作描述"""
        descriptions = {
            "Bash": lambda: f"Run command: {tool_input.get('command', '')[:100]}",
            "Read": lambda: f"Read file: {tool_input.get('file_path', '')}",
            "Write": lambda: f"Write file: {tool_input.get('file_path', '')}",
            "Edit": lambda: f"Edit file: {tool_input.get('file_path', '')}",
            "Glob": lambda: f"Search files: {tool_input.get('pattern', '')}",
            "Grep": lambda: f"Search content: {tool_input.get('pattern', '')}",
            "WebFetch": lambda: f"Fetch URL: {tool_input.get('url', '')[:50]}",
            "WebSearch": lambda: f"Search web: {tool_input.get('query', '')}",
        }

        generator = descriptions.get(tool_name)
        if generator:
            try:
                return generator()
            except Exception:
                pass

        return f"Use tool: {tool_name}"

    def cancel_all(self, reason: str = "cancelled"):
        """
        取消所有待处理的权限请求

        Args:
            reason: 取消原因
        """
        for tool_use_id, future in list(self._pending.items()):
            if not future.done():
                future.cancel()

        self._pending.clear()
        self._pending_requests.clear()
        logger.info(f"All permission requests cancelled: {reason}")

    def reset_session_permissions(self):
        """重置会话级权限"""
        self._session_approved.clear()
        self._session_denied.clear()
        logger.info("Session permissions reset")

    def get_pending_requests(self) -> list[dict]:
        """获取所有待处理的权限请求"""
        return [
            {
                "tool_use_id": req.tool_use_id,
                "tool_name": req.tool_name,
                "tool_input": req.tool_input,
                "description": req.description or self._generate_description(req.tool_name, req.tool_input),
            }
            for req in self._pending_requests.values()
        ]

    @property
    def has_pending(self) -> bool:
        """是否有待处理的请求"""
        return len(self._pending) > 0

    @property
    def session_approved_tools(self) -> set[str]:
        """获取会话级批准的工具"""
        return self._session_approved.copy()
