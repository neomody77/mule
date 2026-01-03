"""WebSocket 实时通信模块 - 支持服务器级共享连接 + CLI 中继"""
import asyncio
import json
import logging
from typing import Optional, Set, Callable, Dict, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.api.auth import verify_ws_token, resolve_workspace_id
from app.config import settings
from app.services.workspace_manager import workspace_manager
from app.services.title_generator import generate_session_title

# 根据配置导入 Agent 实现
def _get_agent_class():
    """根据配置返回 Agent 类"""
    backend = settings.agent_backend.lower()
    if backend == "sandbox":
        from app.services.sandbox_agent import SandboxAgent
        return SandboxAgent
    elif backend == "adk":
        from app.services.adk_agent import ADKAgent
        return ADKAgent
    else:  # 默认使用 claude
        from app.services.claude_agent import ClaudeCodeAgent
        return ClaudeCodeAgent
from app.services.message_store import message_store
from uuid import uuid4
from app.services.task_manager import task_manager, TaskStatus, Task

logger = logging.getLogger(__name__)
router = APIRouter()


class UnifiedConnectionManager:
    """
    统一 WebSocket 连接管理器

    支持:
    - 服务器级共享连接 (/ws)
    - 多 session 订阅/取消订阅
    - 向后兼容旧的 session 级连接 (/ws/{workspace_id}/{session_id})
    - 消息队列：任务执行中收到的消息会排队等待
    """

    def __init__(self):
        # 统一连接: connection_id -> WebSocket
        self.connections: dict[str, WebSocket] = {}
        # 连接订阅的 sessions: connection_id -> Set[(workspace_id, session_id)]
        self.subscriptions: dict[str, Set[tuple[str, str]]] = {}
        # session -> 订阅它的 connection_ids
        self.session_subscribers: dict[tuple[str, str], Set[str]] = {}
        # workspace_id -> session_id -> Agent
        self.agents: dict[str, dict[str, ClaudeCodeAgent]] = {}
        # 连接 ID 计数器
        self._conn_id_counter = 0
        # 消息队列: task_key -> list of (prompt_id, content)
        self.pending_prompts: dict[str, list[tuple[str, str]]] = {}

    def _next_conn_id(self) -> str:
        self._conn_id_counter += 1
        return f"conn_{self._conn_id_counter}"

    async def connect(self, websocket: WebSocket) -> str:
        """建立连接，返回连接 ID"""
        await websocket.accept()
        conn_id = self._next_conn_id()
        self.connections[conn_id] = websocket
        self.subscriptions[conn_id] = set()
        logger.info(f"WebSocket connected: {conn_id}")
        return conn_id

    def disconnect(self, conn_id: str):
        """断开连接"""
        if conn_id not in self.connections:
            return

        # 取消所有订阅
        for session_key in list(self.subscriptions.get(conn_id, [])):
            self._unsubscribe(conn_id, session_key[0], session_key[1])

        # 移除连接
        del self.connections[conn_id]
        if conn_id in self.subscriptions:
            del self.subscriptions[conn_id]

        logger.info(f"WebSocket disconnected: {conn_id}")

    def subscribe(self, conn_id: str, workspace_id: str, session_id: str) -> bool:
        """订阅 session 事件"""
        if conn_id not in self.connections:
            return False

        session_key = (workspace_id, session_id)

        # 添加到连接的订阅列表
        self.subscriptions[conn_id].add(session_key)

        # 添加到 session 的订阅者列表
        if session_key not in self.session_subscribers:
            self.session_subscribers[session_key] = set()
        self.session_subscribers[session_key].add(conn_id)

        logger.info(f"Connection {conn_id} subscribed to {workspace_id}:{session_id}")
        return True

    def unsubscribe(self, conn_id: str, workspace_id: str, session_id: str) -> bool:
        """取消订阅 session 事件"""
        return self._unsubscribe(conn_id, workspace_id, session_id)

    def _unsubscribe(self, conn_id: str, workspace_id: str, session_id: str) -> bool:
        session_key = (workspace_id, session_id)

        # 从连接订阅列表移除
        if conn_id in self.subscriptions:
            self.subscriptions[conn_id].discard(session_key)

        # 从 session 订阅者列表移除
        if session_key in self.session_subscribers:
            self.session_subscribers[session_key].discard(conn_id)
            if not self.session_subscribers[session_key]:
                del self.session_subscribers[session_key]

        logger.info(f"Connection {conn_id} unsubscribed from {workspace_id}:{session_id}")
        return True

    def is_subscribed(self, conn_id: str, workspace_id: str, session_id: str) -> bool:
        """检查是否已订阅"""
        session_key = (workspace_id, session_id)
        return session_key in self.subscriptions.get(conn_id, set())

    async def send_to_connection(self, conn_id: str, data: dict):
        """发送数据到指定连接"""
        if conn_id in self.connections:
            try:
                # 详细记录发送的消息
                event_type = data.get('event', 'unknown')
                session_id = data.get('session_id', '')
                logger.info(f"[WS SEND] {conn_id} <- event={event_type} session={session_id[:8] if session_id else 'N/A'}")
                logger.debug(f"[WS SEND] {conn_id} <- {json.dumps(data, ensure_ascii=False, default=str)[:500]}")
                await self.connections[conn_id].send_json(data)
            except Exception as e:
                logger.error(f"Failed to send to {conn_id}: {e}")
                self.disconnect(conn_id)

    async def send_to_session(self, workspace_id: str, session_id: str, data: dict, display_workspace_id: str = None):
        """发送数据到订阅了指定 session 的所有连接

        Args:
            workspace_id: 实际的 workspace ID (用于查找订阅者)
            session_id: session ID
            data: 要发送的数据
            display_workspace_id: 显示给客户端的 workspace ID (如 "default")，默认为 workspace_id
        """
        session_key = (workspace_id, session_id)

        # 在响应中添加 session 标识（使用 display_workspace_id 返回给客户端）
        data_with_session = {
            "workspace_id": display_workspace_id or workspace_id,
            "session_id": session_id,
            **data
        }

        subscribers = self.session_subscribers.get(session_key, set()).copy()
        for conn_id in subscribers:
            await self.send_to_connection(conn_id, data_with_session)

    def get_or_create_agent(self, workspace_id: str, session_id: str):
        """获取或创建 Agent（每个 session 独立）

        根据配置 agent_backend 选择使用:
        - sandbox: Docker 沙箱隔离
        - adk: Google ADK Agent
        - claude: 普通 Claude Agent (默认)
        """
        if workspace_id not in self.agents:
            self.agents[workspace_id] = {}
        if session_id not in self.agents[workspace_id]:
            workspace_path = settings.get_workspace_path(workspace_id)
            AgentClass = _get_agent_class()

            self.agents[workspace_id][session_id] = AgentClass(
                workspace_path=str(workspace_path),
                workspace_id=workspace_id,
                agent_session_id=session_id,
            )
            logger.info(f"Created {settings.agent_backend} agent for {workspace_id}:{session_id}")

        return self.agents[workspace_id][session_id]

    async def process_pending_prompts(self, task_key: str):
        """处理队列中的所有待执行提示（合并为一次请求）"""
        if task_key not in self.pending_prompts or not self.pending_prompts[task_key]:
            return

        # 取出所有待执行的 prompts
        pending_list = self.pending_prompts[task_key]
        self.pending_prompts[task_key] = []

        # 解析 workspace_id 和 session_id
        parts = task_key.split(":", 1)
        if len(parts) != 2:
            logger.error(f"Invalid task_key format: {task_key}")
            return

        workspace_id, session_id = parts

        # 合并所有待执行的 prompts
        prompt_ids = [p[0] for p in pending_list]
        combined_content = "\n\n---\n\n".join([p[1] for p in pending_list])

        logger.info(f"Processing {len(pending_list)} queued prompts for {task_key}: {prompt_ids}")

        # 通知客户端开始处理队列中的所有消息
        await self.send_to_session(workspace_id, session_id, {
            "event": "prompt_dequeued",
            "data": {
                "ids": prompt_ids,
                "count": len(pending_list),
            }
        })

        # 创建并启动新任务（合并后的内容）
        task = task_manager.create_task(task_key, combined_content)
        await self.send_to_session(workspace_id, session_id, {
            "event": "task_info",
            "data": {
                "task_id": task.id,
                "status": task.status.value,
                "prompt": combined_content,
            }
        })

        agent = self.get_or_create_agent(workspace_id, session_id)
        task_manager.start_task(task, agent)


manager = UnifiedConnectionManager()


# ============== 新的统一入口 ==============

@router.websocket("/ws")
async def unified_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    统一 WebSocket 连接（服务器级共享）

    消息格式:
    - 订阅: {"type": "subscribe", "workspace_id": "...", "session_id": "..."}
    - 取消订阅: {"type": "unsubscribe", "workspace_id": "...", "session_id": "..."}
    - 发送: {"type": "prompt", "workspace_id": "...", "session_id": "...", "content": "..."}
    - 心跳: {"type": "ping"}
    - 同步: {"type": "sync", "workspace_id": "...", "session_id": "..."}
    - 取消: {"type": "cancel", "workspace_id": "...", "session_id": "..."}

    响应格式 (所有响应都包含 workspace_id 和 session_id):
    - {"workspace_id": "...", "session_id": "...", "event": "text_delta", "data": {...}}
    - {"event": "pong", "data": {}}  # ping 响应不需要 session
    - {"event": "subscribed", "data": {"workspace_id": "...", "session_id": "..."}}
    - {"event": "unsubscribed", "data": {"workspace_id": "...", "session_id": "..."}}
    """
    # 验证 Token
    if not token or not await verify_ws_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    conn_id = await manager.connect(websocket)

    # 注册的回调函数 (session_key -> callback)
    registered_callbacks: dict[str, Callable] = {}
    # 注册的完成回调 (session_key -> callback)
    registered_completion_callbacks: dict[str, Callable] = {}

    try:
        # 启动心跳任务
        heartbeat_task = asyncio.create_task(heartbeat_loop_unified(conn_id))

        while True:
            try:
                data = await websocket.receive_json()
                await handle_unified_message(conn_id, data, registered_callbacks, registered_completion_callbacks, token)
            except json.JSONDecodeError:
                await manager.send_to_connection(conn_id, {
                    "event": "error",
                    "data": {"message": "Invalid JSON format"}
                })

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {conn_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {conn_id}: {e}")
    finally:
        heartbeat_task.cancel()
        # 取消注册所有回调
        for callback_key, callback in registered_callbacks.items():
            task_manager.unregister_callback(callback_key, callback)
        for callback_key, callback in registered_completion_callbacks.items():
            task_manager.unregister_completion_callback(callback_key, callback)
        manager.disconnect(conn_id)


async def heartbeat_loop_unified(conn_id: str):
    """统一连接心跳"""
    while True:
        await asyncio.sleep(settings.ws_heartbeat_interval)
        try:
            await manager.send_to_connection(conn_id, {"event": "ping", "data": {}})
        except Exception:
            break


class MessageHandlerContext:
    """消息处理上下文"""
    def __init__(self, conn_id: str, data: dict, registered_callbacks: dict, registered_completion_callbacks: dict, token: str = ""):
        self.conn_id = conn_id
        self.data = data
        self.registered_callbacks = registered_callbacks
        self.registered_completion_callbacks = registered_completion_callbacks or {}
        self.msg_type = data.get("type")
        self.token = token
        # 解析 workspace_id：如果是 "default" 则映射到用户的 token workspace
        # 保留原始 workspace_id 用于返回给客户端
        self.raw_workspace_id = data.get("workspace_id", "")
        self.workspace_id = resolve_workspace_id(self.raw_workspace_id, token) if self.raw_workspace_id else ""
        self.session_id = data.get("session_id")

    @property
    def task_key(self) -> str:
        return f"{self.workspace_id}:{self.session_id}"


async def _handle_ping(ctx: MessageHandlerContext) -> bool:
    """处理 ping 消息"""
    await manager.send_to_connection(ctx.conn_id, {"event": "pong", "data": {}})
    return True


async def _handle_subscribe(ctx: MessageHandlerContext) -> bool:
    """处理 subscribe 消息"""
    if not ctx.workspace_id or not ctx.session_id:
        await manager.send_to_connection(ctx.conn_id, {
            "event": "error",
            "data": {"message": "workspace_id and session_id required"}
        })
        return True

    if not workspace_manager.workspace_exists(ctx.workspace_id):
        await manager.send_to_connection(ctx.conn_id, {
            "event": "error",
            "data": {"message": f"Workspace not found: {ctx.workspace_id}"}
        })
        return True

    manager.subscribe(ctx.conn_id, ctx.workspace_id, ctx.session_id)

    # 注册任务回调
    callback_key = ctx.task_key
    if callback_key not in ctx.registered_callbacks:
        async def event_callback(event: dict, ws_id=ctx.workspace_id, ss_id=ctx.session_id, raw_ws_id=ctx.raw_workspace_id):
            await manager.send_to_session(ws_id, ss_id, event, display_workspace_id=raw_ws_id)
        ctx.registered_callbacks[callback_key] = event_callback
        task_manager.register_callback(callback_key, event_callback)

    # 注册完成回调
    if callback_key not in ctx.registered_completion_callbacks:
        async def completion_callback(task: Task, key=callback_key, ws_id=ctx.workspace_id, ss_id=ctx.session_id, raw_ws_id=ctx.raw_workspace_id):
            await manager.process_pending_prompts(key)
            existing_title = workspace_manager.get_session_title(ws_id, ss_id)
            if not existing_title and task.status == TaskStatus.COMPLETED:
                try:
                    title = await generate_session_title(
                        user_message=task.prompt,
                        assistant_response=task.assistant_text,
                    )
                    if title:
                        workspace_manager.set_session_title(ws_id, ss_id, title)
                        await manager.send_to_session(ws_id, ss_id, {
                            "event": "session_title_updated",
                            "data": {"title": title}
                        }, display_workspace_id=raw_ws_id)
                        logger.info(f"Generated title for {ws_id}:{ss_id}: {title}")
                except Exception as e:
                    logger.error(f"Failed to generate title: {e}")

        ctx.registered_completion_callbacks[callback_key] = completion_callback
        task_manager.register_completion_callback(callback_key, completion_callback)

    await manager.send_to_connection(ctx.conn_id, {
        "event": "subscribed",
        "data": {"workspace_id": ctx.raw_workspace_id, "session_id": ctx.session_id}
    })

    # 发送 session 的 todos（如果有的话）
    todos = message_store.get_session_todos(ctx.workspace_id, ctx.session_id)
    if todos:
        await manager.send_to_connection(ctx.conn_id, {
            "event": "todos_sync",
            "data": {"todos": todos}
        })

    # 发送当前任务状态
    current_task = task_manager.get_current_task(callback_key)
    if current_task:
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "task_info",
            "data": current_task.to_dict()
        }, display_workspace_id=ctx.raw_workspace_id)
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "status",
            "data": {"type": "task_start", "message": "Task running..."}
        }, display_workspace_id=ctx.raw_workspace_id)

    return True


async def _handle_unsubscribe(ctx: MessageHandlerContext) -> bool:
    """处理 unsubscribe 消息"""
    if ctx.workspace_id and ctx.session_id:
        manager.unsubscribe(ctx.conn_id, ctx.workspace_id, ctx.session_id)
    await manager.send_to_connection(ctx.conn_id, {
        "event": "unsubscribed",
        "data": {"workspace_id": ctx.raw_workspace_id, "session_id": ctx.session_id}
    }, display_workspace_id=ctx.raw_workspace_id)
    return True


async def _handle_prompt(ctx: MessageHandlerContext) -> bool:
    """处理 prompt 消息"""
    content = ctx.data.get("content", "")
    if not content:
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "error",
            "data": {"message": "Empty prompt"}
        }, display_workspace_id=ctx.raw_workspace_id)
        return True

    message_store.append_user_message(ctx.workspace_id, ctx.session_id, content)

    # 广播用户消息给所有订阅该 session 的客户端
    await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
        "event": "user_message",
        "data": {"content": content}
    }, display_workspace_id=ctx.raw_workspace_id)

    current_task = task_manager.get_current_task(ctx.task_key)
    if current_task and current_task.status == TaskStatus.RUNNING:
        return await _queue_prompt(ctx, content)

    task = task_manager.create_task(ctx.task_key, content)
    await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
        "event": "task_info",
        "data": {"task_id": task.id, "status": task.status.value, "prompt": content}
    }, display_workspace_id=ctx.raw_workspace_id)

    agent = manager.get_or_create_agent(ctx.workspace_id, ctx.session_id)
    task_manager.start_task(task, agent)
    return True


async def _queue_prompt(ctx: MessageHandlerContext, content: str) -> bool:
    """将 prompt 加入队列"""
    if ctx.task_key not in manager.pending_prompts:
        manager.pending_prompts[ctx.task_key] = []

    prompt_id = str(uuid4())[:8]
    manager.pending_prompts[ctx.task_key].append((prompt_id, content))

    await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
        "event": "prompt_queued",
        "data": {
            "id": prompt_id,
            "content": content,
            "position": len(manager.pending_prompts[ctx.task_key]),
        }
    }, display_workspace_id=ctx.raw_workspace_id)
    logger.info(f"Prompt {prompt_id} queued for {ctx.task_key}")
    return True


async def _handle_sync(ctx: MessageHandlerContext) -> bool:
    """处理 sync 消息"""
    current_task = task_manager.get_current_task(ctx.task_key)
    if current_task:
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "task_info",
            "data": current_task.to_dict()
        }, display_workspace_id=ctx.raw_workspace_id)
        for task_event in current_task.events:
            await manager.send_to_session(ctx.workspace_id, ctx.session_id, task_event.to_dict(), display_workspace_id=ctx.raw_workspace_id)
    else:
        latest_task = task_manager.get_latest_task(ctx.task_key)
        if latest_task:
            await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
                "event": "task_info",
                "data": latest_task.to_dict()
            }, display_workspace_id=ctx.raw_workspace_id)
    return True


async def _handle_cancel(ctx: MessageHandlerContext) -> bool:
    """处理 cancel 消息"""
    current_task = task_manager.get_current_task(ctx.task_key)
    if current_task:
        task_manager.cancel_task(current_task.id)
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "status",
            "data": {"type": "cancelled", "message": "Task cancelled"}
        }, display_workspace_id=ctx.raw_workspace_id)
    else:
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "status",
            "data": {"message": "No active task"}
        }, display_workspace_id=ctx.raw_workspace_id)
    return True


async def _handle_compact(ctx: MessageHandlerContext) -> bool:
    """处理 compact 消息 - 压缩上下文"""
    agent = manager.get_or_create_agent(ctx.workspace_id, ctx.session_id)

    # 检查 agent 是否支持 compact
    if not hasattr(agent, 'compact'):
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "error",
            "data": {"message": "Agent does not support compact"}
        }, display_workspace_id=ctx.raw_workspace_id)
        return True

    # 通知开始压缩
    await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
        "event": "status",
        "data": {"type": "compacting", "message": "Compacting context..."}
    }, display_workspace_id=ctx.raw_workspace_id)

    try:
        result = await agent.compact()
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "status",
            "data": {"type": "compact_done", "message": "Context compacted", "result": result}
        }, display_workspace_id=ctx.raw_workspace_id)
    except Exception as e:
        logger.error(f"Compact failed: {e}")
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "error",
            "data": {"message": f"Compact failed: {str(e)}"}
        }, display_workspace_id=ctx.raw_workspace_id)

    return True


async def _handle_history(ctx: MessageHandlerContext) -> bool:
    """处理 history 消息"""
    from_index = ctx.data.get("from_index", 0)
    task_id = ctx.data.get("task_id")

    if task_id:
        events = task_manager.get_task_events(task_id, from_index)
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "history",
            "data": {"task_id": task_id, "events": events}
        }, display_workspace_id=ctx.raw_workspace_id)
    else:
        tasks = task_manager.get_workspace_tasks(ctx.task_key)
        await manager.send_to_session(ctx.workspace_id, ctx.session_id, {
            "event": "tasks",
            "data": {"tasks": [t.to_dict() for t in tasks[-10:]]}
        }, display_workspace_id=ctx.raw_workspace_id)
    return True


# 消息处理器映射
_MESSAGE_HANDLERS: Dict[str, Any] = {
    "ping": _handle_ping,
    "subscribe": _handle_subscribe,
    "unsubscribe": _handle_unsubscribe,
    "prompt": _handle_prompt,
    "sync": _handle_sync,
    "cancel": _handle_cancel,
    "compact": _handle_compact,
    "history": _handle_history,
}


async def handle_unified_message(conn_id: str, data: dict, registered_callbacks: dict, registered_completion_callbacks: dict = None, token: str = ""):
    """处理统一连接的消息"""
    ctx = MessageHandlerContext(conn_id, data, registered_callbacks, registered_completion_callbacks or {}, token)

    # 日志记录
    session_short = ctx.session_id[:8] if ctx.session_id else 'N/A'
    logger.info(f"[WS RECV] {conn_id} -> type={ctx.msg_type} workspace={ctx.workspace_id} session={session_short}")
    logger.debug(f"[WS RECV] {conn_id} -> {json.dumps(data, ensure_ascii=False, default=str)[:500]}")

    # 使用 handler map 分发
    handler = _MESSAGE_HANDLERS.get(ctx.msg_type)
    if handler:
        await handler(ctx)
        return

    # 需要自动订阅的消息类型
    if ctx.workspace_id and ctx.session_id:
        if not manager.is_subscribed(ctx.conn_id, ctx.workspace_id, ctx.session_id):
            if workspace_manager.workspace_exists(ctx.workspace_id):
                # 自动订阅
                await _handle_subscribe(ctx)
            else:
                await manager.send_to_connection(ctx.conn_id, {
                    "event": "error",
                    "data": {"message": f"Workspace not found: {ctx.workspace_id}"}
                })
                return

    # 未知消息类型
    await manager.send_to_connection(ctx.conn_id, {
        "event": "error",
        "data": {"message": f"Unknown message type: {ctx.msg_type}"}
    })


# ============== CLI 中继连接 ==============

class CLIConnectionManager:
    """
    CLI 连接管理器 - 管理 mule-cli 的 WebSocket 连接

    功能:
    - CLI 客户端连接管理
    - 消息中继（CLI <-> 移动端）
    - 权限请求转发
    """

    def __init__(self):
        # CLI 连接: session_id -> WebSocket
        self.cli_connections: Dict[str, WebSocket] = {}
        # 移动端订阅者: session_id -> Set[conn_id]
        self.mobile_subscribers: Dict[str, Set[str]] = {}
        # 待处理的权限请求: tool_use_id -> Future
        self.pending_permissions: Dict[str, asyncio.Future] = {}

    async def connect_cli(self, websocket: WebSocket, session_id: str) -> bool:
        """CLI 客户端连接"""
        await websocket.accept()
        self.cli_connections[session_id] = websocket
        logger.info(f"CLI connected: session={session_id}")
        return True

    def disconnect_cli(self, session_id: str):
        """CLI 客户端断开"""
        if session_id in self.cli_connections:
            del self.cli_connections[session_id]
            logger.info(f"CLI disconnected: session={session_id}")

        # 清理待处理的权限请求
        to_remove = [k for k in self.pending_permissions if k.startswith(f"{session_id}:")]
        for key in to_remove:
            future = self.pending_permissions.pop(key)
            if not future.done():
                future.set_result({'behavior': 'allow'})  # 默认允许

    def subscribe_mobile(self, conn_id: str, session_id: str):
        """移动端订阅 CLI 会话"""
        if session_id not in self.mobile_subscribers:
            self.mobile_subscribers[session_id] = set()
        self.mobile_subscribers[session_id].add(conn_id)
        logger.info(f"Mobile {conn_id} subscribed to CLI session {session_id}")

    def unsubscribe_mobile(self, conn_id: str, session_id: str):
        """移动端取消订阅"""
        if session_id in self.mobile_subscribers:
            self.mobile_subscribers[session_id].discard(conn_id)
            if not self.mobile_subscribers[session_id]:
                del self.mobile_subscribers[session_id]

    async def send_to_cli(self, session_id: str, data: dict) -> bool:
        """发送消息到 CLI"""
        if session_id not in self.cli_connections:
            return False
        try:
            await self.cli_connections[session_id].send_json(data)
            return True
        except Exception as e:
            logger.error(f"Failed to send to CLI {session_id}: {e}")
            self.disconnect_cli(session_id)
            return False

    async def broadcast_to_mobile(self, session_id: str, data: dict):
        """广播消息到订阅的移动端"""
        subscribers = self.mobile_subscribers.get(session_id, set()).copy()
        for conn_id in subscribers:
            await manager.send_to_connection(conn_id, {
                "cli_session_id": session_id,
                **data
            })

    async def request_permission(
        self,
        session_id: str,
        tool_use_id: str,
        permission_data: dict,
        timeout: float = 300.0
    ) -> dict:
        """
        请求权限并等待响应

        Args:
            session_id: 会话 ID
            tool_use_id: 工具使用 ID
            permission_data: 权限请求数据
            timeout: 超时时间（秒）

        Returns:
            权限响应
        """
        key = f"{session_id}:{tool_use_id}"
        future = asyncio.get_event_loop().create_future()
        self.pending_permissions[key] = future

        # 广播权限请求到移动端
        await self.broadcast_to_mobile(session_id, {
            "event": "permission_request",
            "data": {
                "tool_use_id": tool_use_id,
                **permission_data,
            }
        })

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Permission request timeout: {key}")
            return {'behavior': 'allow'}  # 超时默认允许
        finally:
            self.pending_permissions.pop(key, None)

    def resolve_permission(self, session_id: str, tool_use_id: str, response: dict):
        """解析权限响应"""
        key = f"{session_id}:{tool_use_id}"
        if key in self.pending_permissions:
            future = self.pending_permissions[key]
            if not future.done():
                future.set_result(response)
                logger.info(f"Permission resolved: {key} -> {response.get('behavior', 'unknown')}")

    def is_cli_connected(self, session_id: str) -> bool:
        """检查 CLI 是否已连接"""
        return session_id in self.cli_connections

    def get_connected_sessions(self) -> list[str]:
        """获取所有已连接的 CLI 会话"""
        return list(self.cli_connections.keys())


cli_manager = CLIConnectionManager()


@router.websocket("/ws/cli")
async def cli_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    CLI WebSocket 连接

    消息格式（CLI -> 服务器）:
    - 初始化: {"type": "cli_init", "session_id": "..."}
    - 消息同步: {"type": "cli_message", "session_id": "...", "message_type": "text|tool_use|...", "data": {...}}
    - 权限请求: {"type": "permission_request", "session_id": "...", "data": {...}}

    消息格式（服务器 -> CLI）:
    - 远程提示: {"type": "remote_prompt", "prompt": "..."}
    - 权限响应: {"type": "permission_response", "tool_use_id": "...", "response": {...}}
    - 中断: {"type": "interrupt"}
    - 心跳: {"type": "pong"}
    """
    # 验证 Token
    if not token or not await verify_ws_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    session_id: Optional[str] = None

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "cli_init":
                # CLI 初始化
                session_id = data.get("session_id")
                if not session_id:
                    session_id = str(uuid4())

                cli_manager.cli_connections[session_id] = websocket
                logger.info(f"CLI initialized: session={session_id}")

                await websocket.send_json({
                    "type": "cli_init_ack",
                    "session_id": session_id,
                })
                continue

            if not session_id:
                await websocket.send_json({
                    "type": "error",
                    "message": "Not initialized. Send cli_init first.",
                })
                continue

            if msg_type == "cli_message":
                # CLI 消息 -> 广播到移动端
                message_type = data.get("message_type", "")
                message_data = data.get("data", {})

                await cli_manager.broadcast_to_mobile(session_id, {
                    "event": f"cli_{message_type}",
                    "data": message_data,
                })

            elif msg_type == "permission_request":
                # 权限请求 -> 转发到移动端
                permission_data = data.get("data", {})
                tool_use_id = permission_data.get("tool_use_id", "")

                # 启动权限请求任务（异步等待响应）
                asyncio.create_task(
                    handle_cli_permission_request(session_id, tool_use_id, permission_data, websocket)
                )

            else:
                logger.debug(f"Unknown CLI message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"CLI disconnected: session={session_id}")
    except Exception as e:
        logger.error(f"CLI WebSocket error: {e}")
    finally:
        if session_id:
            cli_manager.disconnect_cli(session_id)


async def handle_cli_permission_request(
    session_id: str,
    tool_use_id: str,
    permission_data: dict,
    websocket: WebSocket,
):
    """处理 CLI 权限请求"""
    response = await cli_manager.request_permission(
        session_id,
        tool_use_id,
        permission_data,
    )

    # 发送响应回 CLI
    try:
        await websocket.send_json({
            "type": "permission_response",
            "tool_use_id": tool_use_id,
            "response": response,
        })
    except Exception as e:
        logger.error(f"Failed to send permission response: {e}")


@router.get("/api/cli/sessions/active")
async def get_active_cli_sessions():
    """获取所有活动的 CLI 会话"""
    return {
        "sessions": cli_manager.get_connected_sessions(),
        "count": len(cli_manager.cli_connections),
    }


@router.post("/api/cli/sessions/{session_id}/prompt")
async def send_prompt_to_cli(session_id: str, prompt: str):
    """发送提示到 CLI"""
    if not cli_manager.is_cli_connected(session_id):
        return {"error": "CLI not connected", "session_id": session_id}

    success = await cli_manager.send_to_cli(session_id, {
        "type": "remote_prompt",
        "prompt": prompt,
    })

    return {"success": success, "session_id": session_id}


@router.post("/api/cli/sessions/{session_id}/interrupt")
async def interrupt_cli(session_id: str):
    """中断 CLI 任务"""
    if not cli_manager.is_cli_connected(session_id):
        return {"error": "CLI not connected", "session_id": session_id}

    success = await cli_manager.send_to_cli(session_id, {
        "type": "interrupt",
    })

    return {"success": success, "session_id": session_id}


@router.post("/api/cli/sessions/{session_id}/permission/{tool_use_id}")
async def respond_to_permission(session_id: str, tool_use_id: str, behavior: str = "allow", updated_input: Optional[dict] = None):
    """响应权限请求"""
    response = {"behavior": behavior}
    if updated_input:
        response["updatedInput"] = updated_input

    cli_manager.resolve_permission(session_id, tool_use_id, response)

    return {"success": True, "session_id": session_id, "tool_use_id": tool_use_id}
