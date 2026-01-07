#!/usr/bin/env python3
"""
ACP 功能测试客户端

用于测试权限审批和模式切换功能。

使用方法:
    python scripts/test_acp_client.py --host localhost --port 8000 --token your-token

功能:
    - 连接 WebSocket
    - 发送 prompt
    - 响应权限请求
    - 切换控制模式
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime

try:
    import websockets
except ImportError:
    print("请安装 websockets: pip install websockets")
    sys.exit(1)


class AcpTestClient:
    """ACP 测试客户端"""

    def __init__(self, host: str, port: int, token: str):
        self.host = host
        self.port = port
        self.token = token
        self.ws = None
        self.workspace_id = "default"
        self.session_id = None
        self.pending_permissions = {}

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws?token={self.token}"

    async def connect(self):
        """连接 WebSocket"""
        print(f"[*] Connecting to {self.ws_url}")
        self.ws = await websockets.connect(self.ws_url)
        print("[+] Connected!")

    async def send(self, data: dict):
        """发送消息"""
        msg = json.dumps(data)
        print(f"[>] Sending: {msg[:100]}...")
        await self.ws.send(msg)

    async def subscribe(self, session_id: str):
        """订阅会话"""
        self.session_id = session_id
        await self.send({
            "type": "subscribe",
            "workspace_id": self.workspace_id,
            "session_id": session_id,
        })

    async def send_prompt(self, content: str):
        """发送 prompt"""
        await self.send({
            "type": "prompt",
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "content": content,
        })

    async def respond_permission(self, tool_use_id: str, decision: str):
        """响应权限请求"""
        await self.send({
            "type": "permission_response",
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "tool_use_id": tool_use_id,
            "decision": decision,
        })

    async def switch_mode(self, mode: str):
        """切换模式"""
        await self.send({
            "type": "switch_mode",
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "mode": mode,
        })

    async def get_mode(self):
        """获取当前模式"""
        await self.send({
            "type": "get_mode",
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
        })

    async def cancel(self):
        """取消任务"""
        await self.send({
            "type": "cancel",
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
        })

    async def handle_message(self, message: str):
        """处理收到的消息"""
        try:
            data = json.loads(message)
            event = data.get("event", "")
            event_data = data.get("data", {})

            timestamp = datetime.now().strftime("%H:%M:%S")

            if event == "subscribed":
                print(f"[{timestamp}] [+] Subscribed to session")

            elif event == "text_delta":
                text = event_data.get("text", "")
                print(f"[{timestamp}] [AI] {text}", end="", flush=True)

            elif event == "tool_use_start":
                name = event_data.get("name", "")
                desc = event_data.get("description", "")
                print(f"\n[{timestamp}] [TOOL] {name}: {desc}")

            elif event == "tool_result":
                content = event_data.get("content", "")[:100]
                is_error = event_data.get("is_error", False)
                status = "ERROR" if is_error else "OK"
                print(f"[{timestamp}] [RESULT] [{status}] {content}")

            elif event == "permission_request":
                tool_use_id = event_data.get("tool_use_id", "")
                tool_name = event_data.get("tool_name", "")
                description = event_data.get("description", "")

                self.pending_permissions[tool_use_id] = event_data

                print(f"\n[{timestamp}] [!] PERMISSION REQUEST")
                print(f"    Tool: {tool_name}")
                print(f"    Description: {description}")
                print(f"    ID: {tool_use_id}")
                print("    Commands: /approve, /approve_session, /deny, /abort")

            elif event == "permission_responded":
                tool_use_id = event_data.get("tool_use_id", "")
                decision = event_data.get("decision", "")
                print(f"[{timestamp}] [+] Permission {tool_use_id}: {decision}")

            elif event == "mode_changed":
                mode = event_data.get("mode", "")
                prev = event_data.get("previous_mode", "")
                reason = event_data.get("reason", "")
                print(f"\n[{timestamp}] [MODE] Changed: {prev} -> {mode} ({reason})")

            elif event == "mode_status":
                mode = event_data.get("mode", "")
                connections = event_data.get("remote_connections", 0)
                print(f"[{timestamp}] [MODE] Current: {mode}, Remote connections: {connections}")

            elif event == "message_end":
                is_error = event_data.get("is_error", False)
                result = event_data.get("result", "")
                print(f"\n[{timestamp}] [END] {'Error: ' + result if is_error else 'Done'}")

            elif event == "status":
                status_type = event_data.get("type", "")
                message = event_data.get("message", "")
                print(f"[{timestamp}] [STATUS] {status_type}: {message}")

            elif event == "error":
                message = event_data.get("message", "")
                print(f"[{timestamp}] [ERROR] {message}")

            elif event == "pong":
                pass  # 忽略心跳

            else:
                print(f"[{timestamp}] [{event}] {json.dumps(event_data)[:100]}")

        except json.JSONDecodeError:
            print(f"[?] Invalid JSON: {message[:100]}")

    async def input_loop(self):
        """处理用户输入"""
        import uuid

        print("\n=== ACP Test Client ===")
        print("Commands:")
        print("  /subscribe [session_id]  - Subscribe to session")
        print("  /prompt <text>           - Send prompt")
        print("  /approve [id]            - Approve permission (latest if no id)")
        print("  /approve_session [id]    - Approve for session")
        print("  /deny [id]               - Deny permission")
        print("  /abort [id]              - Abort task")
        print("  /mode local|remote       - Switch mode")
        print("  /status                  - Get mode status")
        print("  /cancel                  - Cancel current task")
        print("  /quit                    - Exit")
        print()

        loop = asyncio.get_event_loop()

        while True:
            try:
                # 使用 run_in_executor 来异步读取输入
                line = await loop.run_in_executor(None, input, "> ")
                line = line.strip()

                if not line:
                    continue

                if line.startswith("/subscribe"):
                    parts = line.split(maxsplit=1)
                    session_id = parts[1] if len(parts) > 1 else str(uuid.uuid4())
                    await self.subscribe(session_id)
                    print(f"[*] Subscribed to session: {session_id}")

                elif line.startswith("/prompt "):
                    content = line[8:]
                    if not self.session_id:
                        print("[!] Please subscribe first: /subscribe")
                    else:
                        await self.send_prompt(content)

                elif line.startswith("/approve_session"):
                    parts = line.split(maxsplit=1)
                    tool_use_id = parts[1] if len(parts) > 1 else self._get_latest_permission()
                    if tool_use_id:
                        await self.respond_permission(tool_use_id, "approved_for_session")
                    else:
                        print("[!] No pending permission")

                elif line.startswith("/approve"):
                    parts = line.split(maxsplit=1)
                    tool_use_id = parts[1] if len(parts) > 1 else self._get_latest_permission()
                    if tool_use_id:
                        await self.respond_permission(tool_use_id, "approved")
                    else:
                        print("[!] No pending permission")

                elif line.startswith("/deny"):
                    parts = line.split(maxsplit=1)
                    tool_use_id = parts[1] if len(parts) > 1 else self._get_latest_permission()
                    if tool_use_id:
                        await self.respond_permission(tool_use_id, "denied")
                    else:
                        print("[!] No pending permission")

                elif line.startswith("/abort"):
                    parts = line.split(maxsplit=1)
                    tool_use_id = parts[1] if len(parts) > 1 else self._get_latest_permission()
                    if tool_use_id:
                        await self.respond_permission(tool_use_id, "abort")
                    else:
                        print("[!] No pending permission")

                elif line.startswith("/mode "):
                    mode = line[6:].strip()
                    if mode in ("local", "remote"):
                        await self.switch_mode(mode)
                    else:
                        print("[!] Mode must be 'local' or 'remote'")

                elif line == "/status":
                    await self.get_mode()

                elif line == "/cancel":
                    await self.cancel()

                elif line == "/quit":
                    print("[*] Goodbye!")
                    break

                else:
                    # 默认作为 prompt 发送
                    if self.session_id:
                        await self.send_prompt(line)
                    else:
                        print("[!] Unknown command. Use /subscribe first, then type your prompt.")

            except EOFError:
                break
            except Exception as e:
                print(f"[!] Error: {e}")

    def _get_latest_permission(self) -> str | None:
        """获取最新的权限请求 ID"""
        if self.pending_permissions:
            return list(self.pending_permissions.keys())[-1]
        return None

    async def receive_loop(self):
        """接收消息循环"""
        try:
            async for message in self.ws:
                await self.handle_message(message)
        except websockets.ConnectionClosed:
            print("\n[!] Connection closed")

    async def run(self):
        """运行客户端"""
        await self.connect()

        # 并行运行接收和输入循环
        receive_task = asyncio.create_task(self.receive_loop())
        input_task = asyncio.create_task(self.input_loop())

        # 等待任一任务完成
        done, pending = await asyncio.wait(
            [receive_task, input_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # 取消未完成的任务
        for task in pending:
            task.cancel()

        await self.ws.close()


def main():
    parser = argparse.ArgumentParser(description="ACP Test Client")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--token", required=True, help="API token")

    args = parser.parse_args()

    client = AcpTestClient(args.host, args.port, args.token)

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\n[*] Interrupted")


if __name__ == "__main__":
    main()
