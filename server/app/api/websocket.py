"""WebSocket 实时通信模块 - 支持服务器级共享连接"""
import asyncio
import json
import logging
from typing import Optional, Set, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.api.auth import verify_ws_token
from app.config import settings
from app.services.claude_agent import ClaudeCodeAgent
from app.services.workspace_manager import workspace_manager
from app.services.title_generator import generate_session_title
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

    async def send_to_session(self, workspace_id: str, session_id: str, data: dict):
        """发送数据到订阅了指定 session 的所有连接"""
        session_key = (workspace_id, session_id)

        # 在响应中添加 session 标识
        data_with_session = {
            "workspace_id": workspace_id,
            "session_id": session_id,
            **data
        }

        subscribers = self.session_subscribers.get(session_key, set()).copy()
        for conn_id in subscribers:
            await self.send_to_connection(conn_id, data_with_session)

    def get_or_create_agent(self, workspace_id: str, session_id: str) -> ClaudeCodeAgent:
        """获取或创建 Agent（每个 session 独立）"""
        if workspace_id not in self.agents:
            self.agents[workspace_id] = {}
        if session_id not in self.agents[workspace_id]:
            workspace_path = settings.get_workspace_path(workspace_id)
            self.agents[workspace_id][session_id] = ClaudeCodeAgent(
                workspace_path=str(workspace_path),
                workspace_id=workspace_id,
                agent_session_id=session_id,
            )
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
                await handle_unified_message(conn_id, data, registered_callbacks, registered_completion_callbacks)
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


async def handle_unified_message(conn_id: str, data: dict, registered_callbacks: dict, registered_completion_callbacks: dict = None):
    """处理统一连接的消息"""
    msg_type = data.get("type")
    workspace_id = data.get("workspace_id")
    session_id = data.get("session_id")

    # 详细记录接收的消息
    session_short = session_id[:8] if session_id else 'N/A'
    logger.info(f"[WS RECV] {conn_id} -> type={msg_type} workspace={workspace_id} session={session_short}")
    logger.debug(f"[WS RECV] {conn_id} -> {json.dumps(data, ensure_ascii=False, default=str)[:500]}")

    if msg_type == "ping":
        await manager.send_to_connection(conn_id, {"event": "pong", "data": {}})
        return

    # 订阅消息
    if msg_type == "subscribe":
        if not workspace_id or not session_id:
            await manager.send_to_connection(conn_id, {
                "event": "error",
                "data": {"message": "workspace_id and session_id required"}
            })
            return

        # 验证工作区存在
        if not workspace_manager.workspace_exists(workspace_id):
            await manager.send_to_connection(conn_id, {
                "event": "error",
                "data": {"message": f"Workspace not found: {workspace_id}"}
            })
            return

        # 总是执行订阅（即使之前已订阅，也返回成功）
        manager.subscribe(conn_id, workspace_id, session_id)

        # 注册任务回调（如果还没注册）
        callback_key = f"{workspace_id}:{session_id}"
        if callback_key not in registered_callbacks:
            async def event_callback(event: dict, ws_id=workspace_id, ss_id=session_id):
                await manager.send_to_session(ws_id, ss_id, event)
            registered_callbacks[callback_key] = event_callback
            task_manager.register_callback(callback_key, event_callback)

        # 注册完成回调（处理队列中的消息 + 生成标题）
        if registered_completion_callbacks is not None and callback_key not in registered_completion_callbacks:
            async def completion_callback(task: Task, key=callback_key, ws_id=workspace_id, ss_id=session_id):
                # 处理队列中的消息
                await manager.process_pending_prompts(key)

                # 如果是首次完成的任务，尝试生成标题
                # 检查是否已有标题
                existing_title = workspace_manager.get_session_title(ws_id, ss_id)
                if not existing_title and task.status == TaskStatus.COMPLETED:
                    try:
                        title = await generate_session_title(
                            user_message=task.prompt,
                            assistant_response=task.assistant_text,
                        )
                        if title:
                            workspace_manager.set_session_title(ws_id, ss_id, title)
                            # 通知客户端标题更新
                            await manager.send_to_session(ws_id, ss_id, {
                                "event": "session_title_updated",
                                "data": {"title": title}
                            })
                            logger.info(f"Generated title for {ws_id}:{ss_id}: {title}")
                    except Exception as e:
                        logger.error(f"Failed to generate title: {e}")

            registered_completion_callbacks[callback_key] = completion_callback
            task_manager.register_completion_callback(callback_key, completion_callback)

        # 总是返回订阅成功
        await manager.send_to_connection(conn_id, {
            "event": "subscribed",
            "data": {"workspace_id": workspace_id, "session_id": session_id}
        })

        # 发送当前任务状态（如果有）
        current_task = task_manager.get_current_task(callback_key)
        if current_task:
            await manager.send_to_session(workspace_id, session_id, {
                "event": "task_info",
                "data": {
                    "task_id": current_task.id,
                    "status": current_task.status.value,
                    "prompt": current_task.prompt,
                    "events_count": len(current_task.events),
                }
            })
            # 不发送历史事件 - 客户端应该已经有了（通过实时回调）
            # 如果客户端需要历史，可以发送 sync 请求
        return

    # 取消订阅消息
    if msg_type == "unsubscribe":
        if not workspace_id or not session_id:
            await manager.send_to_connection(conn_id, {
                "event": "error",
                "data": {"message": "workspace_id and session_id required"}
            })
            return

        manager.unsubscribe(conn_id, workspace_id, session_id)

        # 取消注册任务回调
        callback_key = f"{workspace_id}:{session_id}"
        if callback_key in registered_callbacks:
            task_manager.unregister_callback(callback_key, registered_callbacks[callback_key])
            del registered_callbacks[callback_key]

        await manager.send_to_connection(conn_id, {
            "event": "unsubscribed",
            "data": {"workspace_id": workspace_id, "session_id": session_id}
        })
        return

    # 其他消息需要 workspace_id 和 session_id
    if not workspace_id or not session_id:
        await manager.send_to_connection(conn_id, {
            "event": "error",
            "data": {"message": "workspace_id and session_id required"}
        })
        return

    # 检查是否已订阅（或自动订阅）
    if not manager.is_subscribed(conn_id, workspace_id, session_id):
        # 自动订阅
        if workspace_manager.workspace_exists(workspace_id):
            manager.subscribe(conn_id, workspace_id, session_id)
            callback_key = f"{workspace_id}:{session_id}"
            if callback_key not in registered_callbacks:
                async def event_callback(event: dict, ws_id=workspace_id, ss_id=session_id):
                    await manager.send_to_session(ws_id, ss_id, event)
                registered_callbacks[callback_key] = event_callback
                task_manager.register_callback(callback_key, event_callback)
            # 注册完成回调
            if registered_completion_callbacks is not None and callback_key not in registered_completion_callbacks:
                async def completion_callback(task: Task, key=callback_key):
                    await manager.process_pending_prompts(key)
                registered_completion_callbacks[callback_key] = completion_callback
                task_manager.register_completion_callback(callback_key, completion_callback)
        else:
            await manager.send_to_connection(conn_id, {
                "event": "error",
                "data": {"message": f"Workspace not found: {workspace_id}"}
            })
            return

    task_key = f"{workspace_id}:{session_id}"

    if msg_type == "prompt":
        content = data.get("content", "")
        if not content:
            await manager.send_to_session(workspace_id, session_id, {
                "event": "error",
                "data": {"message": "Empty prompt"}
            })
            return

        current_task = task_manager.get_current_task(task_key)
        if current_task and current_task.status == TaskStatus.RUNNING:
            # 任务执行中，将消息加入队列
            if task_key not in manager.pending_prompts:
                manager.pending_prompts[task_key] = []

            # 生成唯一 ID
            prompt_id = str(uuid4())[:8]
            manager.pending_prompts[task_key].append((prompt_id, content))

            # 通知客户端消息已排队
            await manager.send_to_session(workspace_id, session_id, {
                "event": "prompt_queued",
                "data": {
                    "id": prompt_id,
                    "content": content,
                    "position": len(manager.pending_prompts[task_key]),
                }
            })
            logger.info(f"Prompt {prompt_id} queued for {task_key}, position: {len(manager.pending_prompts[task_key])}")
            return

        task = task_manager.create_task(task_key, content)
        await manager.send_to_session(workspace_id, session_id, {
            "event": "task_info",
            "data": {
                "task_id": task.id,
                "status": task.status.value,
                "prompt": content,
            }
        })

        agent = manager.get_or_create_agent(workspace_id, session_id)
        task_manager.start_task(task, agent)

    elif msg_type == "sync":
        current_task = task_manager.get_current_task(task_key)
        if current_task:
            await manager.send_to_session(workspace_id, session_id, {
                "event": "task_info",
                "data": current_task.to_dict()
            })
            for task_event in current_task.events:
                await manager.send_to_session(workspace_id, session_id, task_event.to_dict())
        else:
            latest_task = task_manager.get_latest_task(task_key)
            if latest_task:
                await manager.send_to_session(workspace_id, session_id, {
                    "event": "task_info",
                    "data": latest_task.to_dict()
                })

    elif msg_type == "cancel":
        current_task = task_manager.get_current_task(task_key)
        if current_task:
            task_manager.cancel_task(current_task.id)
            await manager.send_to_session(workspace_id, session_id, {
                "event": "status",
                "data": {"type": "cancelled", "message": "Task cancelled"}
            })
        else:
            await manager.send_to_session(workspace_id, session_id, {
                "event": "status",
                "data": {"message": "No active task"}
            })

    elif msg_type == "history":
        from_index = data.get("from_index", 0)
        task_id = data.get("task_id")

        if task_id:
            events = task_manager.get_task_events(task_id, from_index)
            await manager.send_to_session(workspace_id, session_id, {
                "event": "history",
                "data": {"task_id": task_id, "events": events}
            })
        else:
            tasks = task_manager.get_workspace_tasks(task_key)
            await manager.send_to_session(workspace_id, session_id, {
                "event": "tasks",
                "data": {"tasks": [t.to_dict() for t in tasks[-10:]]}
            })

    else:
        await manager.send_to_session(workspace_id, session_id, {
            "event": "error",
            "data": {"message": f"Unknown message type: {msg_type}"}
        })


# ============== 向后兼容：旧的 session 级入口 ==============

@router.websocket("/ws/{workspace_id}/{session_id}")
async def workspace_websocket(
    websocket: WebSocket,
    workspace_id: str,
    session_id: str,
    token: Optional[str] = Query(None),
):
    """
    工作区 WebSocket 连接（向后兼容，内部转换为统一连接）
    """
    # 验证 Token
    if not token or not await verify_ws_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # 验证工作区存在
    if not workspace_manager.workspace_exists(workspace_id):
        await websocket.close(code=4004, reason="Workspace not found")
        return

    conn_id = await manager.connect(websocket)
    manager.subscribe(conn_id, workspace_id, session_id)

    callback_key = f"{workspace_id}:{session_id}"

    async def event_callback(event: dict):
        await manager.send_to_session(workspace_id, session_id, event)

    task_manager.register_callback(callback_key, event_callback)

    try:
        heartbeat_task = asyncio.create_task(heartbeat_loop_unified(conn_id))

        # 发送当前任务状态
        current_task = task_manager.get_current_task(callback_key)
        if current_task:
            await manager.send_to_session(workspace_id, session_id, {
                "event": "task_info",
                "data": {
                    "task_id": current_task.id,
                    "status": current_task.status.value,
                    "prompt": current_task.prompt,
                }
            })
            for task_event in current_task.events:
                await manager.send_to_session(workspace_id, session_id, task_event.to_dict())

        while True:
            try:
                data = await websocket.receive_json()
                # 注入 workspace_id 和 session_id（兼容旧格式）
                data["workspace_id"] = workspace_id
                data["session_id"] = session_id
                await handle_unified_message(conn_id, data, {callback_key: event_callback})
            except json.JSONDecodeError:
                await manager.send_to_session(workspace_id, session_id, {
                    "event": "error",
                    "data": {"message": "Invalid JSON format"}
                })

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: workspace={workspace_id}, session={session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {workspace_id}:{session_id}: {e}")
    finally:
        heartbeat_task.cancel()
        task_manager.unregister_callback(callback_key, event_callback)
        manager.disconnect(conn_id)
