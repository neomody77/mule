#!/usr/bin/env python3
"""
Mule CLI - 通过后端 WebSocket 执行 Claude Agent

与手机端使用相同的后端处理方式：
- 通过 WebSocket 连接到 Mule 服务器
- 发送 prompt 到后端执行（在 Docker 容器中）
- 接收流式响应并显示

用法:
    mule "你的提示"
    mule --server http://192.168.1.100:8080 --workspace my-project "你的提示"
    mule --interactive
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import websockets
from websockets.client import WebSocketClientProtocol

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MuleCLI:
    """Mule CLI 主类 - 通过后端 WebSocket 执行"""

    def __init__(
        self,
        server_url: str,
        token: str,
        workspace_id: str = "default",
        session_id: Optional[str] = None,
    ):
        self.server_url = server_url.rstrip('/')
        self.token = token
        self.workspace_id = workspace_id
        self.session_id = session_id or self._generate_session_id()

        self._ws: Optional[WebSocketClientProtocol] = None
        self._is_connected = False
        self._is_running = False
        self._current_text = ""

    def _generate_session_id(self) -> str:
        """生成新的 session ID"""
        import uuid
        return str(uuid.uuid4())

    @property
    def ws_url(self) -> str:
        """构建 WebSocket URL"""
        url = self.server_url
        if url.startswith('http://'):
            url = 'ws://' + url[7:]
        elif url.startswith('https://'):
            url = 'wss://' + url[8:]
        elif not url.startswith('ws://') and not url.startswith('wss://'):
            url = 'ws://' + url

        return f"{url}/ws?token={self.token}"

    async def connect(self) -> bool:
        """连接到服务器"""
        try:
            logger.info(f"Connecting to {self.ws_url}")
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=25,
                ping_timeout=10,
            )
            self._is_connected = True
            logger.info("Connected to Mule server")

            # 订阅 session
            await self._send({
                "type": "subscribe",
                "workspace_id": self.workspace_id,
                "session_id": self.session_id,
            })

            # 等待订阅确认
            response = await self._ws.recv()
            data = json.loads(response)
            if data.get("event") == "subscribed":
                logger.info(f"Subscribed to {self.workspace_id}:{self.session_id[:8]}")
                return True
            else:
                logger.error(f"Subscribe failed: {data}")
                return False

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        self._is_connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Disconnected")

    async def _send(self, message: dict) -> None:
        """发送消息"""
        if self._ws:
            await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def send_prompt(self, prompt: str) -> None:
        """发送提示到后端执行"""
        await self._send({
            "type": "prompt",
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "content": prompt,
        })
        logger.info(f"Prompt sent: {prompt[:50]}...")

    async def cancel_task(self) -> None:
        """取消当前任务"""
        await self._send({
            "type": "cancel",
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
        })
        logger.info("Cancel requested")

    async def receive_events(self):
        """接收并处理事件流"""
        async for message in self._ws:
            try:
                data = json.loads(message)
                event = data.get("event", "")
                event_data = data.get("data", {})

                # 跳过 ping/pong
                if event in ("ping", "pong"):
                    if event == "ping":
                        await self._send({"type": "ping"})
                    continue

                # 处理各种事件
                yield (event, event_data)

                # 任务结束
                if event == "message_end":
                    break

            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON: {message[:100]}")

    def _print_event(self, event: str, data: dict) -> None:
        """打印事件到终端"""
        if event == "text_delta":
            text = data.get("text", "")
            print(text, end="", flush=True)
            self._current_text += text

        elif event == "tool_use_start":
            name = data.get("name", "")
            desc = data.get("description", "")
            print(f"\n[工具] {desc or name}", flush=True)

        elif event == "tool_result":
            is_error = data.get("is_error", False)
            if is_error:
                content = data.get("content", "")[:200]
                print(f"\n[错误] {content}", flush=True)

        elif event == "status":
            status_type = data.get("type", "")
            message = data.get("message", "")
            if status_type == "thinking":
                print(f"\n[思考中...]", flush=True)
            elif status_type == "task_start":
                print(f"\n[开始执行]", flush=True)
            elif status_type == "cancelled":
                print(f"\n[已取消]", flush=True)

        elif event == "message_end":
            session_id = data.get("session_id", "")
            duration = data.get("duration_ms", 0)
            turns = data.get("num_turns", 0)
            print(f"\n{'='*50}")
            print(f"Session: {session_id[:8] if session_id else 'N/A'}")
            print(f"Duration: {duration/1000:.2f}s")
            print(f"Turns: {turns}")
            print(f"{'='*50}")

        elif event == "error":
            message = data.get("message", "")
            print(f"\n[错误] {message}", flush=True)

        elif event == "user_message":
            # 用户消息回显（来自其他客户端）
            content = data.get("content", "")
            # 只在非本地发送时显示
            pass

        elif event == "prompt_queued":
            position = data.get("position", 0)
            print(f"\n[排队] 位置: {position}", flush=True)

        elif event == "prompt_dequeued":
            count = data.get("count", 0)
            print(f"\n[开始处理队列中的 {count} 条消息]", flush=True)

    async def run_once(self, prompt: str) -> None:
        """执行单次提示"""
        self._is_running = True
        self._current_text = ""

        try:
            if not await self.connect():
                print("无法连接到服务器", file=sys.stderr)
                return

            await self.send_prompt(prompt)

            async for event, data in self.receive_events():
                self._print_event(event, data)

        except KeyboardInterrupt:
            print("\n中断...")
            await self.cancel_task()

        finally:
            await self.disconnect()

    async def interactive(self) -> None:
        """交互模式 - 支持多轮对话"""
        self._is_running = True
        print("Mule CLI 交互模式 (输入 'exit' 退出)")
        print(f"服务器: {self.server_url}")
        print(f"Workspace: {self.workspace_id}")
        print(f"Session: {self.session_id[:8]}")
        print("-" * 50)

        try:
            if not await self.connect():
                print("无法连接到服务器", file=sys.stderr)
                return

            # 启动接收任务
            receive_task = asyncio.create_task(self._receive_loop())

            # 交互循环
            while self._is_running:
                try:
                    # 获取用户输入
                    prompt = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("\n> ")
                    )

                    if prompt.lower() in ('exit', 'quit', 'q'):
                        break

                    if not prompt.strip():
                        continue

                    # 发送提示
                    self._current_text = ""
                    await self.send_prompt(prompt)

                except KeyboardInterrupt:
                    print("\n(使用 'exit' 退出，Ctrl+C 取消当前任务)")
                    await self.cancel_task()

        finally:
            self._is_running = False
            receive_task.cancel()
            await self.disconnect()

    async def _receive_loop(self) -> None:
        """接收事件循环（用于交互模式）"""
        try:
            async for event, data in self.receive_events():
                self._print_event(event, data)

                # 任务结束后继续等待下一个任务
                if event == "message_end":
                    self._current_text = ""
                    # 不退出，继续接收
                    continue

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Receive loop error: {e}")


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(
        description='Mule CLI - 通过后端执行 Claude Agent',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  mule "帮我实现一个 TODO 应用"
  mule --server http://192.168.1.100:8080 "你的提示"
  mule --workspace my-project "你的提示"
  mule --interactive

环境变量:
  MULE_SERVER    - Mule 服务器地址 (如 http://192.168.1.100:8080)
  MULE_TOKEN     - 认证 token
  MULE_WORKSPACE - 默认 workspace ID
        """
    )

    parser.add_argument(
        'prompt',
        nargs='?',
        help='提示内容'
    )
    parser.add_argument(
        '-s', '--server',
        default=os.getenv('MULE_SERVER', 'http://localhost:8080'),
        help='Mule 服务器地址'
    )
    parser.add_argument(
        '-t', '--token',
        default=os.getenv('MULE_TOKEN', ''),
        help='认证 token'
    )
    parser.add_argument(
        '-w', '--workspace',
        default=os.getenv('MULE_WORKSPACE', 'default'),
        help='Workspace ID (默认: default)'
    )
    parser.add_argument(
        '-r', '--resume',
        help='恢复的会话 ID'
    )
    parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='交互模式'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='详细输出'
    )

    args = parser.parse_args()

    # 检查必需参数
    if not args.token:
        print("错误: 需要认证 token (--token 或 MULE_TOKEN 环境变量)", file=sys.stderr)
        sys.exit(1)

    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    # 创建 CLI 实例
    cli = MuleCLI(
        server_url=args.server,
        token=args.token,
        workspace_id=args.workspace,
        session_id=args.resume,
    )

    # 运行
    if args.interactive:
        asyncio.run(cli.interactive())
    elif args.prompt:
        asyncio.run(cli.run_once(args.prompt))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
