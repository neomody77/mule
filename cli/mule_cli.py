#!/usr/bin/env python3
"""
Mule CLI - Claude Code 包装器

用法:
    mule "你的提示"
    mule --server ws://192.168.1.100:8989 "你的提示"
    mule --resume <session_id> "继续之前的任务"
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from .sdk_wrapper import MuleSDKWrapper, MuleMessage
from .websocket_client import MuleWebSocketClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MuleCLI:
    """Mule CLI 主类"""

    def __init__(
        self,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
    ):
        self.server_url = server_url or os.getenv('MULE_SERVER', '')
        self.token = token or os.getenv('MULE_TOKEN', '')
        self.session_id = session_id
        self.cwd = cwd or os.getcwd()

        self._ws_client: Optional[MuleWebSocketClient] = None
        self._sdk_wrapper: Optional[MuleSDKWrapper] = None
        self._is_running = False

    async def start(self, prompt: str) -> None:
        """启动 CLI"""
        self._is_running = True

        try:
            # 连接到 Mule 服务器（如果配置了）
            if self.server_url and self.token:
                await self._connect_to_server()

            # 创建 SDK 包装器
            self._sdk_wrapper = MuleSDKWrapper(
                cwd=self.cwd,
                session_id=self.session_id,
                on_message=self._on_message,
                on_permission_request=self._on_permission_request,
            )

            # 连接到 Claude
            await self._sdk_wrapper.connect()

            # 发送初始提示
            await self._sdk_wrapper.query(prompt)

            # 接收并处理消息
            async for msg in self._sdk_wrapper.receive_messages():
                self._print_message(msg)

                # 结果消息
                if msg.type == 'result':
                    data = msg.data
                    print(f"\n{'='*50}")
                    print(f"Session: {data.get('session_id', 'N/A')}")
                    print(f"Duration: {data.get('duration_ms', 0)/1000:.2f}s")
                    print(f"Turns: {data.get('num_turns', 0)}")
                    if data.get('total_cost_usd'):
                        print(f"Cost: ${data['total_cost_usd']:.4f}")
                    print(f"{'='*50}")
                    break

        except KeyboardInterrupt:
            print("\n中断...")
            if self._sdk_wrapper:
                await self._sdk_wrapper.interrupt()

        finally:
            await self._cleanup()

    async def interactive(self) -> None:
        """交互模式 - 支持多轮对话"""
        self._is_running = True
        print("Mule CLI 交互模式 (输入 'exit' 退出)")
        print(f"工作目录: {self.cwd}")
        if self.server_url:
            print(f"同步服务器: {self.server_url}")
        print("-" * 50)

        try:
            # 连接到服务器
            if self.server_url and self.token:
                await self._connect_to_server()

            # 创建 SDK 包装器
            self._sdk_wrapper = MuleSDKWrapper(
                cwd=self.cwd,
                session_id=self.session_id,
                on_message=self._on_message,
                on_permission_request=self._on_permission_request,
            )

            await self._sdk_wrapper.connect()

            # 启动远程消息接收任务
            remote_task = None
            if self._ws_client:
                remote_task = asyncio.create_task(self._handle_remote_messages())

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

                    # 发送查询
                    await self._sdk_wrapper.query(prompt)

                    # 接收响应
                    async for msg in self._sdk_wrapper.receive_messages():
                        self._print_message(msg)

                except KeyboardInterrupt:
                    print("\n(使用 'exit' 退出)")
                    if self._sdk_wrapper.is_processing:
                        await self._sdk_wrapper.interrupt()

        finally:
            if remote_task:
                remote_task.cancel()
            await self._cleanup()

    async def _connect_to_server(self) -> None:
        """连接到 Mule 服务器"""
        self._ws_client = MuleWebSocketClient(
            server_url=self.server_url,
            token=self.token,
            session_id=self.session_id,
        )

        # 设置回调
        self._ws_client.on_remote_message = self._on_remote_message
        self._ws_client.on_interrupt = self._on_interrupt

        connected = await self._ws_client.connect()
        if connected:
            logger.info("已连接到 Mule 服务器")
        else:
            logger.warning("无法连接到 Mule 服务器，继续本地模式")
            self._ws_client = None

    async def _handle_remote_messages(self) -> None:
        """处理远程消息（来自手机端）"""
        # WebSocket 客户端内部已经有接收循环
        # 这里只需要保持任务运行
        while self._is_running and self._ws_client and self._ws_client.is_connected:
            await asyncio.sleep(1)

    def _on_remote_message(self, data: dict) -> None:
        """处理远程消息回调"""
        prompt = data.get('prompt', '')
        if prompt and self._sdk_wrapper:
            print(f"\n[远程] {prompt}")
            # 在事件循环中执行查询
            asyncio.create_task(self._handle_remote_prompt(prompt))

    async def _handle_remote_prompt(self, prompt: str) -> None:
        """处理远程提示"""
        if not self._sdk_wrapper:
            return

        await self._sdk_wrapper.query(prompt)
        async for msg in self._sdk_wrapper.receive_messages():
            self._print_message(msg)

    def _on_interrupt(self) -> None:
        """处理远程中断请求"""
        if self._sdk_wrapper:
            asyncio.create_task(self._sdk_wrapper.interrupt())

    def _on_message(self, msg: MuleMessage) -> None:
        """消息回调 - 同步到服务器"""
        if self._ws_client and self._ws_client.is_connected:
            asyncio.create_task(
                self._ws_client.send_message(msg.type, msg.data)
            )

    async def _on_permission_request(self, permission_data: dict) -> dict:
        """权限请求回调"""
        tool_name = permission_data.get('tool_name', '')
        tool_input = permission_data.get('tool_input', {})

        # 如果连接了服务器，转发到远程
        if self._ws_client and self._ws_client.is_connected:
            logger.info(f"转发权限请求到远程: {tool_name}")
            response = await self._ws_client.request_permission(permission_data)
            return response

        # 本地模式：在终端询问
        return await self._local_permission_prompt(tool_name, tool_input)

    async def _local_permission_prompt(self, tool_name: str, tool_input: dict) -> dict:
        """本地权限提示"""
        print(f"\n[权限请求] {tool_name}")

        # 显示工具输入
        if tool_name == 'Bash':
            print(f"  命令: {tool_input.get('command', '')}")
        elif tool_name in ('Read', 'Write', 'Edit'):
            print(f"  文件: {tool_input.get('file_path', '')}")
        elif tool_name == 'Glob':
            print(f"  模式: {tool_input.get('pattern', '')}")
        elif tool_name == 'Grep':
            print(f"  搜索: {tool_input.get('pattern', '')}")

        # 获取用户输入
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("允许? (y/n/edit): ")
        )

        if response.lower() in ('y', 'yes', ''):
            return {'behavior': 'allow'}
        elif response.lower() in ('n', 'no'):
            return {'behavior': 'deny'}
        elif response.lower() == 'edit':
            # 编辑模式 - 修改输入
            new_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("新输入 (JSON): ")
            )
            try:
                updated = json.loads(new_input)
                return {'behavior': 'allow', 'updatedInput': updated}
            except json.JSONDecodeError:
                print("无效 JSON，使用原输入")
                return {'behavior': 'allow'}
        else:
            return {'behavior': 'allow'}

    def _print_message(self, msg: MuleMessage) -> None:
        """打印消息到终端"""
        if msg.type == 'text':
            text = msg.data.get('text', '')
            print(text, end='', flush=True)

        elif msg.type == 'thinking':
            thinking = msg.data.get('thinking', '')
            # 显示思考内容（可选）
            if os.getenv('MULE_SHOW_THINKING'):
                print(f"\n[思考] {thinking[:100]}...")

        elif msg.type == 'tool_use':
            name = msg.data.get('name', '')
            tool_input = msg.data.get('input', {})
            desc = self._get_tool_description(name, tool_input)
            print(f"\n[工具] {desc}")

        elif msg.type == 'tool_result':
            is_error = msg.data.get('is_error', False)
            content = msg.data.get('content', '')
            if is_error:
                print(f"\n[错误] {content[:200]}")
            # 成功结果通常不需要显示

        elif msg.type == 'error':
            error = msg.data.get('message', '')
            print(f"\n[错误] {error}")

    def _get_tool_description(self, tool_name: str, tool_input: dict) -> str:
        """生成工具描述"""
        if tool_name == 'Read':
            file_path = tool_input.get('file_path', '')
            filename = Path(file_path).name
            return f"读取 {filename}"
        elif tool_name == 'Write':
            file_path = tool_input.get('file_path', '')
            filename = Path(file_path).name
            return f"写入 {filename}"
        elif tool_name == 'Edit':
            file_path = tool_input.get('file_path', '')
            filename = Path(file_path).name
            return f"编辑 {filename}"
        elif tool_name == 'Bash':
            command = tool_input.get('command', '')
            if len(command) > 50:
                command = command[:47] + '...'
            return f"执行: {command}"
        elif tool_name == 'Glob':
            pattern = tool_input.get('pattern', '')
            return f"搜索文件: {pattern}"
        elif tool_name == 'Grep':
            pattern = tool_input.get('pattern', '')
            return f"搜索内容: {pattern}"
        else:
            return f"{tool_name}..."

    async def _cleanup(self) -> None:
        """清理资源"""
        self._is_running = False

        if self._sdk_wrapper:
            await self._sdk_wrapper.disconnect()

        if self._ws_client:
            await self._ws_client.disconnect()


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(
        description='Mule CLI - Claude Code 包装器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  mule "帮我实现一个 TODO 应用"
  mule --server ws://192.168.1.100:8989 "你的提示"
  mule --interactive
  mule --resume abc123 "继续之前的任务"

环境变量:
  MULE_SERVER    - Mule 服务器地址
  MULE_TOKEN     - 认证 token
  MULE_SHOW_THINKING - 显示思考内容
        """
    )

    parser.add_argument(
        'prompt',
        nargs='?',
        help='提示内容'
    )
    parser.add_argument(
        '-s', '--server',
        help='Mule 服务器地址 (ws://host:port)'
    )
    parser.add_argument(
        '-t', '--token',
        help='认证 token'
    )
    parser.add_argument(
        '-r', '--resume',
        help='恢复的会话 ID'
    )
    parser.add_argument(
        '-d', '--directory',
        help='工作目录',
        default=os.getcwd()
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

    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 创建 CLI 实例
    cli = MuleCLI(
        server_url=args.server,
        token=args.token,
        session_id=args.resume,
        cwd=args.directory,
    )

    # 运行
    if args.interactive:
        asyncio.run(cli.interactive())
    elif args.prompt:
        asyncio.run(cli.start(args.prompt))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
