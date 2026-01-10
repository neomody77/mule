"""
Sandbox Agent - Docker 隔离的 Claude Code 执行环境

使用 Docker 容器运行 Claude Code，实现：
- 工作区安全隔离
- 自动传递 Claude 认证信息（每个容器独立的 .claude 目录）
- 支持流式输出
- 容器生命周期管理
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import AsyncGenerator, Optional
import hashlib

from app.services.agent_logger import AgentLogger, agent_logger_manager
from app.services.workspace_manager import workspace_manager
from app.config import settings

logger = logging.getLogger(__name__)

# Docker 镜像名称
SANDBOX_IMAGE = "mule-workspace:latest"

# Claude 认证文件路径 (宿主机)
CLAUDE_CONFIG_DIR = Path.home() / ".claude"
CLAUDE_AUTH_FILE = Path.home() / ".claude.json"
CLAUDE_CREDENTIALS_FILE = CLAUDE_CONFIG_DIR / ".credentials.json"

# 容器数据目录（每个容器独立的 .claude 目录）
CONTAINER_DATA_DIR = settings.data_dir / "containers"


class CredentialsWatcher:
    """监听 .credentials.json 文件变化，同步到所有容器专属目录"""

    def __init__(self):
        self._last_mtime: float = 0
        self._task: Optional[asyncio.Task] = None

    def _get_all_container_dirs(self) -> list[Path]:
        """获取所有容器专属目录"""
        if not CONTAINER_DATA_DIR.exists():
            return []
        return [d / ".claude" for d in CONTAINER_DATA_DIR.iterdir() if d.is_dir()]

    def _sync_credentials(self) -> None:
        """同步 credentials 到所有容器目录"""
        if not CLAUDE_CREDENTIALS_FILE.exists():
            return

        container_dirs = self._get_all_container_dirs()
        if not container_dirs:
            return

        for container_claude_dir in container_dirs:
            dst = container_claude_dir / ".credentials.json"
            if container_claude_dir.exists():
                try:
                    shutil.copy2(CLAUDE_CREDENTIALS_FILE, dst)
                    os.chmod(dst, 0o600)
                    logger.info(f"Synced credentials to {dst}")
                except Exception as e:
                    logger.error(f"Failed to sync credentials to {dst}: {e}")

    async def _watch_loop(self) -> None:
        """监听文件变化的循环"""
        logger.info(f"Starting credentials watcher for {CLAUDE_CREDENTIALS_FILE}")

        while True:
            try:
                if CLAUDE_CREDENTIALS_FILE.exists():
                    mtime = CLAUDE_CREDENTIALS_FILE.stat().st_mtime
                    if mtime > self._last_mtime:
                        if self._last_mtime > 0:  # 不是首次检测
                            logger.info("Credentials file changed, syncing...")
                            self._sync_credentials()
                        self._last_mtime = mtime
            except Exception as e:
                logger.error(f"Error watching credentials: {e}")

            await asyncio.sleep(5)  # 每 5 秒检查一次

    def start(self) -> None:
        """启动监听"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch_loop())

    def stop(self) -> None:
        """停止监听"""
        if self._task and not self._task.done():
            self._task.cancel()


# 全局 credentials 监听器
credentials_watcher = CredentialsWatcher()


class TokenRefresher:
    """定时刷新 OAuth token

    策略：
    - 每 10 分钟检查一次 token 过期时间
    - 如果距离过期 < 1 小时，直接调用 OAuth refresh API 刷新
    - 刷新成功后同步到所有容器
    """

    # Token 有效期约 8 小时，在最后 1 小时内刷新
    REFRESH_THRESHOLD_SECONDS = 3600  # 1 小时
    CHECK_INTERVAL_SECONDS = 600  # 10 分钟检查一次

    # OAuth API 配置
    # Reference: https://github.com/RavenStorm-bit/claude-token-refresh
    CLAUDE_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
    CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

    def __init__(self):
        self._task: Optional[asyncio.Task] = None

    def _get_token_info(self) -> tuple[float, str]:
        """获取 token 剩余有效时间（秒）和 refresh_token"""
        try:
            import json
            import time
            cred_file = CLAUDE_CREDENTIALS_FILE
            if not cred_file.exists():
                return 0, ""

            with open(cred_file) as f:
                data = json.load(f)

            oauth_data = data.get("claudeAiOauth", {})
            expires_at = oauth_data.get("expiresAt", 0)
            refresh_token = oauth_data.get("refreshToken", "")

            if not expires_at:
                return 0, ""

            remaining = (expires_at / 1000) - time.time()
            return max(0, remaining), refresh_token
        except Exception as e:
            logger.error(f"Error reading token info: {e}")
            return 0, ""

    async def _refresh_token(self) -> bool:
        """使用 OAuth refresh API 刷新 token"""
        import time as _time
        import aiohttp

        try:
            old_remaining, refresh_token = self._get_token_info()
            old_expiry = _time.time() + old_remaining

            if not refresh_token:
                logger.error("[TokenRefresh] No refresh token found")
                return False

            logger.info(f"[TokenRefresh] Calling OAuth refresh API (token remaining: {old_remaining/60:.0f} min, expires: {_time.strftime('%H:%M:%S', _time.localtime(old_expiry))})")

            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.CLAUDE_CLIENT_ID
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.CLAUDE_TOKEN_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        token_data = await response.json()

                        # 更新 credentials 文件
                        await self._update_credentials(token_data)

                        new_remaining, _ = self._get_token_info()
                        new_expiry = _time.time() + new_remaining

                        logger.info(f"[TokenRefresh] Token REFRESHED! New expiry: {_time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime(new_expiry))} (remaining: {new_remaining/60:.0f} min)")

                        # 同步到所有容器
                        credentials_watcher._sync_credentials()

                        # 终止所有容器内的 claude 进程，让它们重新读取新 token
                        await self._kill_claude_processes_in_containers()

                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"[TokenRefresh] API error: HTTP {response.status} - {error_text[:200]}")
                        return False

        except asyncio.TimeoutError:
            logger.error("[TokenRefresh] API request timed out after 30s")
            return False
        except Exception as e:
            logger.error(f"[TokenRefresh] Error: {e}")
            return False

    async def _kill_claude_processes_in_containers(self) -> None:
        """终止所有容器内的 claude 进程

        Token 刷新后，需要终止运行中的 claude 进程，
        下次请求时会重新启动并读取新的 credentials。
        """
        try:
            # 获取所有 mule-sandbox 容器
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=mule-sandbox-"],
                capture_output=True, text=True
            )

            containers = [name.strip() for name in result.stdout.strip().split('\n') if name.strip()]

            if not containers:
                logger.debug("[TokenRefresh] No active sandbox containers to update")
                return

            killed_count = 0
            for container_name in containers:
                try:
                    # 在容器内终止所有 claude 进程
                    kill_result = subprocess.run(
                        ["docker", "exec", container_name, "pkill", "-f", "claude"],
                        capture_output=True, text=True, timeout=5
                    )
                    if kill_result.returncode == 0:
                        killed_count += 1
                        logger.debug(f"[TokenRefresh] Killed claude process in {container_name}")
                except subprocess.TimeoutExpired:
                    logger.warning(f"[TokenRefresh] Timeout killing claude in {container_name}")
                except Exception as e:
                    logger.debug(f"[TokenRefresh] Could not kill claude in {container_name}: {e}")

            if killed_count > 0:
                logger.info(f"[TokenRefresh] Killed claude processes in {killed_count} container(s) - they will restart with new token on next request")

        except Exception as e:
            logger.error(f"[TokenRefresh] Error killing claude processes: {e}")

    async def _update_credentials(self, token_data: dict) -> None:
        """更新 credentials 文件（保持 inode 不变）"""
        import json
        import time

        cred_file = CLAUDE_CREDENTIALS_FILE
        if not cred_file.exists():
            return

        # 读取现有数据
        with open(cred_file, 'r') as f:
            data = json.load(f)

        # 更新 OAuth 数据
        oauth_data = data.get("claudeAiOauth", {})

        # 从响应中获取新 token
        if "access_token" in token_data:
            oauth_data["accessToken"] = token_data["access_token"]
        if "refresh_token" in token_data:
            oauth_data["refreshToken"] = token_data["refresh_token"]
        if "expires_in" in token_data:
            # expires_in 是秒数，转换为毫秒时间戳
            oauth_data["expiresAt"] = int((time.time() + token_data["expires_in"]) * 1000)

        data["claudeAiOauth"] = oauth_data

        # 写回文件（保持 inode 不变，避免影响已打开文件的进程）
        new_content = json.dumps(data, indent=2)
        with open(cred_file, 'r+') as f:
            f.seek(0)
            f.write(new_content)
            f.truncate()  # 截断多余的旧内容

        logger.info(f"[TokenRefresh] Credentials file updated (inode preserved)")

    async def _refresh_loop(self) -> None:
        """定时刷新循环"""
        import time as _time
        logger.info("[TokenRefresh] Starting token refresh loop (using OAuth API)")

        while True:
            try:
                remaining, _ = self._get_token_info()
                expiry = _time.time() + remaining

                if remaining <= 0:
                    # Token 已过期，尝试用 refresh_token 刷新
                    logger.warning("[TokenRefresh] Token EXPIRED! Attempting refresh...")
                    success = await self._refresh_token()
                    if not success:
                        logger.error("[TokenRefresh] Refresh failed, need manual re-login")
                    await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
                    continue

                if remaining < self.REFRESH_THRESHOLD_SECONDS:
                    # 临近过期，刷新 token
                    logger.info(f"[TokenRefresh] Token expiring soon! Remaining: {remaining/60:.0f} min, expires: {_time.strftime('%H:%M:%S', _time.localtime(expiry))}")
                    await self._refresh_token()
                    await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
                else:
                    # 还早，正常检查间隔
                    logger.info(f"[TokenRefresh] Token OK. Remaining: {remaining/60:.0f} min ({remaining/3600:.1f}h), expires: {_time.strftime('%H:%M:%S', _time.localtime(expiry))}. Next check in {self.CHECK_INTERVAL_SECONDS}s")
                    await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                logger.info("[TokenRefresh] Refresh loop cancelled")
                break
            except Exception as e:
                logger.error(f"[TokenRefresh] Loop error: {e}")
                await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    def start(self) -> None:
        """启动定时刷新"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._refresh_loop())

    def stop(self) -> None:
        """停止定时刷新"""
        if self._task and not self._task.done():
            self._task.cancel()


# 全局 token 刷新器
token_refresher = TokenRefresher()


def get_container_name(workspace_id: str) -> str:
    """生成容器名称 - 每个 workspace 一个容器"""
    # 使用 workspace_id 的 hash 作为容器名（避免特殊字符问题）
    hash_value = hashlib.md5(workspace_id.encode()).hexdigest()[:8]
    return f"mule-sandbox-{hash_value}"


class SandboxAgent:
    """Docker 隔离的 Claude Code Agent

    在 Docker 容器中运行 Claude Code，提供安全的代码执行环境。

    容器策略：
    - 每个 workspace 一个容器（多个 session 共享）
    - 同一 workspace 的 session 通过 docker exec 进入同一容器
    - 容器内环境（安装的包等）在 session 间共享

    认证策略：
    - 每个 workspace 容器有独立的 .claude 目录
    - 从宿主机复制认证文件 .credentials.json 和 .claude.json
    - 容器内的 .claude 目录可读写
    """

    def __init__(
        self,
        workspace_path: str,
        workspace_id: str = "",
        agent_session_id: str = "",
    ):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id
        self.container_name = get_container_name(workspace_id)

        # 容器专属的 .claude 目录（持久化，每个 workspace 共享）
        self.container_claude_dir = CONTAINER_DATA_DIR / self.container_name / ".claude"

        # 容器内的会话 ID
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

        self._process: Optional[asyncio.subprocess.Process] = None
        self._is_processing = False
        self._pending_messages: list[str] = []  # 待注入的消息队列
        self._message_lock = asyncio.Lock()  # 消息队列锁

    def _setup_container_claude_dir(self) -> None:
        """准备容器专属的 .claude 目录（在宿主机上）

        策略：
        - .credentials.json: 复制到容器专属目录，watcher 负责后续同步
        - .claude/: 容器专属目录，可读写（projects/ 等）
        - .claude.json: 复制一份到容器专属目录（Claude 需要写入）
        """
        # 创建容器专属目录
        self.container_claude_dir.mkdir(parents=True, exist_ok=True)

        # 复制 .credentials.json 到容器专属目录
        if CLAUDE_CREDENTIALS_FILE.exists():
            dst_credentials = self.container_claude_dir / ".credentials.json"
            shutil.copy2(CLAUDE_CREDENTIALS_FILE, dst_credentials)
            os.chmod(dst_credentials, 0o600)
            logger.info(f"Copied credentials to {dst_credentials}")

        # 复制 .claude.json 到容器专属目录（如果不存在）
        src_claude_json = CLAUDE_AUTH_FILE
        dst_claude_json = self.container_claude_dir / ".claude.json"
        if src_claude_json.exists() and not dst_claude_json.exists():
            shutil.copy2(src_claude_json, dst_claude_json)
            os.chmod(dst_claude_json, 0o666)
            logger.info(f"Copied claude.json to {dst_claude_json}")

        # 设置目录权限
        os.chmod(self.container_claude_dir, 0o777)

    def _container_exists(self) -> bool:
        """检查容器是否存在"""
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        return self.container_name in result.stdout.split('\n')

    def _container_running(self) -> bool:
        """检查容器是否正在运行"""
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        return self.container_name in result.stdout.split('\n')

    def _ensure_container(self) -> None:
        """确保容器存在并运行"""
        if self._container_running():
            logger.info(f"Container {self.container_name} is already running")
            return

        if self._container_exists():
            logger.info(f"Starting existing container: {self.container_name}")
            subprocess.run(["docker", "start", self.container_name], check=True)
            return

        # 准备容器专属的 .claude 目录
        self._setup_container_claude_dir()

        # 创建新容器
        logger.info(f"Creating new sandbox container: {self.container_name}")

        host_uid = os.getuid()
        host_gid = os.getgid()

        # 获取宿主机用户名，用于确定容器内 HOME 目录
        import pwd
        host_user = pwd.getpwuid(host_uid).pw_name
        container_home = f"/home/{host_user}"

        docker_args = [
            "docker", "run", "-d",
            "--name", self.container_name,
            # 资源限制
            "--memory", "2g",
            "--cpus", "1",
            # 注意: 不使用 --security-opt no-new-privileges，因为 sudo 需要 setuid 提权
            # 以宿主机用户身份运行（解决挂载文件权限问题）
            "--user", f"{host_uid}:{host_gid}",
            # 挂载工作区
            "-v", f"{self.workspace_path}:/workspace",
            "-w", "/workspace",
            # .claude/ 目录挂载（可读写，包含 credentials、projects 等）
            "-v", f"{self.container_claude_dir}:{container_home}/.claude",
            # .claude.json 挂载（可读写）
            "-v", f"{self.container_claude_dir / '.claude.json'}:{container_home}/.claude.json",
        ]

        # 禁用遥测和错误报告
        docker_args.extend(["-e", "DISABLE_TELEMETRY=1"])
        docker_args.extend(["-e", "DISABLE_ERROR_REPORTING=1"])

        # 传递 API Key 环境变量（如果有）
        if os.environ.get("ANTHROPIC_API_KEY"):
            docker_args.extend(["-e", "ANTHROPIC_API_KEY"])

        # 传递代理环境变量（如果有）
        for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
            if os.environ.get(proxy_var):
                docker_args.extend(["-e", f"{proxy_var}={os.environ[proxy_var]}"])

        # 传递 GitHub CLI 配置（如果启用）
        if settings.share_gh_config:
            gh_config_dir = Path.home() / ".config" / "gh"
            if gh_config_dir.exists():
                docker_args.extend([
                    "-v", f"{gh_config_dir}:{container_home}/.config/gh:ro"
                ])
                logger.info(f"Mounting gh config from {gh_config_dir}")

        docker_args.extend([
            SANDBOX_IMAGE,
            "sleep", "infinity"
        ])

        subprocess.run(docker_args, check=True)
        logger.info(f"Container {self.container_name} created and started")

    async def execute(self, prompt: str) -> AsyncGenerator[dict, None]:
        """在 Docker 容器中执行 Claude Code"""
        self._is_processing = True

        try:
            # 确保容器运行
            self._ensure_container()

            logger.info(f"Executing prompt in sandbox: {prompt[:100]}...")

            # 记录任务开始
            if self.activity_logger:
                self.activity_logger.log_task_start(prompt)

            yield {
                "event": "status",
                "data": {"type": "task_start", "message": "Starting task in sandbox..."}
            }

            # 构建 claude 命令 - 使用 stream-json 输入模式支持流式输入
            # 注意: --output-format stream-json 需要配合 --verbose 使用
            claude_cmd = [
                "claude", "-p",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--verbose",
                "--dangerously-skip-permissions"
            ]

            # 如果有之前的会话，使用 --resume 继续
            if self.session_id:
                claude_cmd.extend(["--resume", self.session_id])

            # 在容器中执行（容器已以正确 UID 运行，无需 -u）
            # 需要 -i 参数来支持 stdin 输入
            docker_exec = [
                "docker", "exec", "-i", "-w", "/workspace",
                self.container_name,
                "/bin/bash", "-lc",
                " ".join(f'"{arg}"' if " " in arg else arg for arg in claude_cmd)
            ]

            logger.debug(f"Docker exec command: {' '.join(docker_exec)}")

            # 启动进程，需要 stdin 来支持流式输入
            # limit 设置为 128MB，避免大文件内容导致 LimitOverrunError
            self._process = await asyncio.create_subprocess_exec(
                *docker_exec,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=128 * 1024 * 1024,  # 128MB
            )

            # 发送初始消息
            initial_message = json.dumps({
                "type": "user",
                "message": {"role": "user", "content": prompt}
            }) + "\n"
            self._process.stdin.write(initial_message.encode('utf-8'))
            await self._process.stdin.drain()

            # 后台任务持续消费 stderr，避免缓冲区满导致死锁
            stderr_lines: list[str] = []

            async def drain_stderr():
                async for line in self._process.stderr:
                    stderr_lines.append(line.decode('utf-8').rstrip())

            stderr_task = asyncio.create_task(drain_stderr())

            # 处理流式输出
            async for line in self._process.stdout:
                line_text = line.decode('utf-8').strip()
                if not line_text:
                    continue

                try:
                    event = json.loads(line_text)
                    event_type = event.get("type", "")

                    # 转换事件格式
                    if event_type == "assistant":
                        message = event.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if block.get("type") == "text":
                                yield {
                                    "event": "text_delta",
                                    "data": {"text": block.get("text", "")}
                                }
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "")
                                tool_input = block.get("input", {})
                                tool_id = block.get("id", "")

                                if self.activity_logger:
                                    self._log_tool_use(tool_name, tool_input)

                                yield {
                                    "event": "tool_use_start",
                                    "data": {
                                        "id": tool_id,
                                        "name": tool_name,
                                        "input": tool_input,
                                        "description": self._get_tool_description(tool_name, tool_input),
                                    }
                                }

                    elif event_type == "user":
                        message = event.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if block.get("type") == "tool_result":
                                yield {
                                    "event": "tool_result",
                                    "data": {
                                        "id": block.get("tool_use_id", ""),
                                        "content": str(block.get("content", ""))[:300],
                                        "is_error": block.get("is_error", False),
                                    }
                                }

                    elif event_type == "result":
                        session_id = event.get("session_id", "")
                        self.session_id = session_id
                        result_text = event.get("result", "")
                        is_error = event.get("is_error", False)

                        if self.workspace_id and self.agent_session_id and session_id:
                            workspace_manager.set_session_id(
                                self.workspace_id,
                                self.agent_session_id,
                                session_id
                            )

                        if self.activity_logger:
                            self.activity_logger.log_task_end(
                                success=not is_error,
                                error=result_text if is_error else None
                            )

                        # 检测 401 认证错误
                        if is_error and "401" in result_text and "authentication" in result_text.lower():
                            logger.error("OAuth token expired or invalid")
                            yield {
                                "event": "text_delta",
                                "data": {"text": "⚠️ **OAuth token expired or invalid.**\n\nPlease provide new credentials:\n1. Copy `~/.claude/.credentials.json` from another machine, OR\n2. Run `claude` on the host to login and get new tokens\n\nThe credentials watcher will auto-detect changes.\n\n"}
                            }

                        # 提取 usage 信息
                        usage_data = {}
                        raw_usage = event.get("usage")
                        if raw_usage and isinstance(raw_usage, dict):
                            total_input = 0
                            total_output = 0
                            context_window = 200000
                            for model_name, model_usage in raw_usage.items():
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
                                "session_id": session_id,
                                "duration_ms": event.get("duration_ms", 0),
                                "num_turns": event.get("num_turns", 0),
                                "is_error": is_error,
                                "result": result_text,
                                "total_cost_usd": event.get("total_cost_usd", 0),
                                "usage": usage_data,
                            }
                        }

                        # 检查是否有待注入的消息（流式输入）
                        async with self._message_lock:
                            if self._pending_messages and self._process and self._process.stdin:
                                next_prompt = self._pending_messages.pop(0)
                                logger.info(f"Injecting pending message: {next_prompt[:100]}...")

                                # 记录新任务开始
                                if self.activity_logger:
                                    self.activity_logger.log_task_start(next_prompt)

                                # 发送消息到 stdin
                                next_message = json.dumps({
                                    "type": "user",
                                    "message": {"role": "user", "content": next_prompt}
                                }) + "\n"
                                self._process.stdin.write(next_message.encode('utf-8'))
                                await self._process.stdin.drain()

                                # 通知客户端有新消息开始处理
                                yield {
                                    "event": "status",
                                    "data": {"type": "task_start", "message": "Processing next message..."}
                                }
                            elif not self._pending_messages and self._process and self._process.stdin:
                                # 没有待处理消息，关闭 stdin 让进程正常结束
                                self._process.stdin.close()

                    elif event_type == "system":
                        subtype = event.get("subtype", "")
                        if subtype == "init":
                            yield {
                                "event": "status",
                                "data": {"type": "thinking", "message": "Thinking..."}
                            }

                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse JSON: {line_text}")
                    continue

            await self._process.wait()
            return_code = self._process.returncode

            # 等待 stderr 读取完成
            await stderr_task
            stderr_text = ""
            if stderr_lines:
                stderr_text = chr(10).join(stderr_lines)
                logger.warning(f"Sandbox stderr: {stderr_text}")

            # 检查进程退出状态
            if return_code != 0:
                error_msg = f"Claude process exited with code {return_code}"

                # 特殊处理常见错误码
                if return_code == 139:
                    error_msg = "Container crashed (segmentation fault). The container has been removed and will be recreated on next request."
                    # 尝试清理崩溃的容器
                    try:
                        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
                        logger.info(f"Removed crashed container: {self.container_name}")
                    except Exception as cleanup_err:
                        logger.warning(f"Failed to cleanup container: {cleanup_err}")
                elif return_code == 1:
                    if "401" in stderr_text or "authentication" in stderr_text.lower() or "unauthorized" in stderr_text.lower():
                        error_msg = "Authentication failed. OAuth token may have expired."
                    elif stderr_text:
                        error_msg = f"Claude error: {stderr_text[:500]}"
                    else:
                        error_msg = "Claude process failed. Check server logs for details."
                elif return_code == 137:
                    error_msg = "Process was killed (possibly out of memory)."
                elif return_code == 126:
                    error_msg = "Claude command not found or not executable in container."
                elif return_code == 127:
                    error_msg = "Claude command not found in container. Container may need to be rebuilt."

                logger.error(f"Sandbox execution failed: {error_msg} (return_code={return_code}, stderr={stderr_text[:200]})")

                if self.activity_logger:
                    self.activity_logger.log_task_end(success=False, error=error_msg)

                yield {
                    "event": "error",
                    "data": {
                        "message": error_msg,
                        "return_code": return_code,
                    }
                }

        except Exception as e:
            logger.error(f"Sandbox execution error: {e}", exc_info=True)

            if self.activity_logger:
                self.activity_logger.log_task_end(success=False, error=str(e))

            yield {"event": "error", "data": {"message": str(e)}}

        finally:
            self._is_processing = False
            self._process = None

    def _log_tool_use(self, tool_name: str, tool_input: dict) -> None:
        """记录工具使用"""
        if not self.activity_logger:
            return

        log_handlers = {
            "Read": lambda: self.activity_logger.log_file_read(tool_input.get("file_path", "")),
            "Write": lambda: self.activity_logger.log_file_write(
                tool_input.get("file_path", ""),
                size=len(tool_input.get("content", "")),
                is_new=True
            ),
            "Edit": lambda: self.activity_logger.log_file_edit(
                tool_input.get("file_path", ""),
                changes={"old_len": len(tool_input.get("old_string", "")), "new_len": len(tool_input.get("new_string", ""))}
            ),
            "Bash": lambda: self.activity_logger.log_bash_exec(tool_input.get("command", "")),
            "Glob": lambda: self.activity_logger.log_glob(tool_input.get("pattern", "")),
            "Grep": lambda: self.activity_logger.log_grep(tool_input.get("pattern", ""), tool_input.get("path", "")),
        }

        handler = log_handlers.get(tool_name)
        if handler:
            handler()

    def _get_tool_description(self, tool_name: str, tool_input: dict) -> str:
        """生成工具描述"""
        def _truncate(s: str, max_len: int = 50) -> str:
            return s[:max_len - 3] + "..." if len(s) > max_len else s

        def _get_filename(path: str) -> str:
            return path.split("/")[-1] if path else "file"

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

    async def inject_message(self, prompt: str) -> bool:
        """注入消息到当前执行流程

        当任务正在执行时，可以调用此方法添加新消息。
        消息会在当前子任务（如 tool call）结束时被发送。

        Returns:
            bool: 是否成功添加到队列
        """
        if not self._is_processing:
            logger.warning("Cannot inject message: no task is running")
            return False

        async with self._message_lock:
            self._pending_messages.append(prompt)
            logger.info(f"Message queued for injection: {prompt[:100]}... (queue size: {len(self._pending_messages)})")
            return True

    def has_pending_messages(self) -> bool:
        """检查是否有待注入的消息"""
        return len(self._pending_messages) > 0

    async def cancel(self) -> None:
        """取消当前执行"""
        if self._process and self._is_processing:
            logger.info("Cancelling sandbox execution...")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()

    async def compact(self) -> dict:
        """压缩上下文 - 在容器内执行 /compact 命令"""
        if not self.session_id:
            raise ValueError("No active session to compact")

        logger.info(f"Compacting context for session {self.session_id} in sandbox")

        try:
            # 确保容器运行
            self._ensure_container()

            # 在容器中执行 claude --resume session_id -p "/compact"
            claude_cmd = ["claude", "--resume", self.session_id, "-p", "/compact", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]

            docker_exec = [
                "docker", "exec", "-w", "/workspace",
                self.container_name,
                "/bin/bash", "-lc",
                " ".join(f'"{arg}"' if " " in arg else arg for arg in claude_cmd)
            ]

            process = await asyncio.create_subprocess_exec(
                *docker_exec,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if stderr:
                logger.warning(f"Compact stderr: {stderr.decode()}")

            # 解析结果
            result_text = ""
            for line in stdout.decode().strip().split('\n'):
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "result":
                        result_text = event.get("result", "")
                        self.session_id = event.get("session_id", self.session_id)
                except json.JSONDecodeError:
                    continue

            logger.info(f"Compact completed: {result_text}")
            return {
                "success": True,
                "session_id": self.session_id,
                "result": result_text or "Context compacted successfully",
            }

        except Exception as e:
            logger.error(f"Compact failed: {e}")
            raise

    def stop_container(self) -> None:
        """停止容器"""
        if self._container_running():
            logger.info(f"Stopping container: {self.container_name}")
            subprocess.run(["docker", "stop", self.container_name], check=False)

    def remove_container(self) -> None:
        """删除容器"""
        if self._container_exists():
            logger.info(f"Removing container: {self.container_name}")
            subprocess.run(["docker", "rm", "-f", self.container_name], check=False)

    def reset_session(self) -> None:
        """重置会话"""
        self.session_id = None

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._is_processing
