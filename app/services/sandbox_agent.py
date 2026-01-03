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
    - 如果距离过期 < 1 小时，每 4 分钟调用一次 claude -p "ping" 刷新
    - 刷新成功后同步到所有容器
    """

    # Token 有效期约 8 小时，在最后 1 小时内频繁刷新
    REFRESH_THRESHOLD_SECONDS = 3600  # 1 小时
    CHECK_INTERVAL_SECONDS = 600  # 10 分钟检查一次
    REFRESH_INTERVAL_SECONDS = 240  # 临近过期时 4 分钟刷新一次

    def __init__(self):
        self._task: Optional[asyncio.Task] = None

    def _get_token_remaining_seconds(self) -> float:
        """获取 token 剩余有效时间（秒）"""
        try:
            import json
            import time
            cred_file = CLAUDE_CREDENTIALS_FILE
            if not cred_file.exists():
                return 0

            with open(cred_file) as f:
                data = json.load(f)

            expires_at = data.get("claudeAiOauth", {}).get("expiresAt", 0)
            if not expires_at:
                return 0

            remaining = (expires_at / 1000) - time.time()
            return max(0, remaining)
        except Exception as e:
            logger.error(f"Error reading token expiry: {e}")
            return 0

    async def _refresh_token(self) -> bool:
        """执行一次 token 刷新"""
        try:
            import time as _time
            old_remaining = self._get_token_remaining_seconds()
            old_expiry = _time.time() + old_remaining

            logger.info(f"[TokenRefresh] Calling claude -p ping (token remaining: {old_remaining/60:.0f} min, expires: {_time.strftime('%H:%M:%S', _time.localtime(old_expiry))})")

            process = await asyncio.create_subprocess_exec(
                "claude", "-p", "ping", "--output-format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120
            )

            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            if process.returncode == 0:
                # 解析结果
                import json
                try:
                    result = json.loads(stdout_text)
                    pong_result = result.get("result", "")
                    duration_ms = result.get("duration_ms", 0)
                    logger.info(f"[TokenRefresh] Ping response: '{pong_result}' (took {duration_ms}ms)")
                except:
                    logger.info(f"[TokenRefresh] Ping completed")

                new_remaining = self._get_token_remaining_seconds()
                new_expiry = _time.time() + new_remaining

                # 检查 token 是否被刷新
                if abs(new_remaining - old_remaining) > 60:  # 超过 1 分钟的变化
                    logger.info(f"[TokenRefresh] Token REFRESHED! New expiry: {_time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime(new_expiry))} (remaining: {new_remaining/60:.0f} min)")
                else:
                    logger.info(f"[TokenRefresh] Token unchanged (remaining: {new_remaining/60:.0f} min)")

                # 同步到所有容器
                credentials_watcher._sync_credentials()
                return True
            else:
                # 检查是否是 401 错误
                if "401" in stdout_text or "expired" in stdout_text.lower():
                    logger.error(f"[TokenRefresh] Token EXPIRED! Need re-login")
                else:
                    logger.warning(f"[TokenRefresh] Ping failed: {stderr_text[:200]}")
                return False

        except asyncio.TimeoutError:
            logger.error("[TokenRefresh] Ping timed out after 120s")
            return False
        except Exception as e:
            logger.error(f"[TokenRefresh] Error: {e}")
            return False

    async def _refresh_loop(self) -> None:
        """定时刷新循环"""
        import time as _time
        logger.info("[TokenRefresh] Starting token refresh loop")

        while True:
            try:
                remaining = self._get_token_remaining_seconds()
                expiry = _time.time() + remaining

                if remaining <= 0:
                    # Token 已过期
                    logger.warning(f"[TokenRefresh] Token EXPIRED! Need manual re-login. Next check in {self.CHECK_INTERVAL_SECONDS}s")
                    await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
                    continue

                if remaining < self.REFRESH_THRESHOLD_SECONDS:
                    # 临近过期，频繁刷新
                    logger.info(f"[TokenRefresh] Token expiring soon! Remaining: {remaining/60:.0f} min, expires: {_time.strftime('%H:%M:%S', _time.localtime(expiry))}")
                    await self._refresh_token()
                    logger.info(f"[TokenRefresh] Next refresh in {self.REFRESH_INTERVAL_SECONDS}s")
                    await asyncio.sleep(self.REFRESH_INTERVAL_SECONDS)
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


def get_container_name(workspace_id: str, session_id: str) -> str:
    """生成容器名称"""
    hash_input = f"{workspace_id}:{session_id}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:8]
    return f"mule-sandbox-{hash_value}"


class GlobalLoginManager:
    """全局登录管理器 - 在宿主机上运行登录进程

    特点：
    - 登录进程在宿主机运行，直接更新 ~/.claude/.credentials.json
    - 全局只有一个登录进程，所有容器共享
    - 登录成功后，CredentialsWatcher 会同步到各容器
    """
    _instance: Optional['GlobalLoginManager'] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._process: Optional[asyncio.subprocess.Process] = None
        self._login_url: Optional[str] = None
        self._ready_for_code = False
        self._created_at: float = 0

    async def start_login(self) -> Optional[str]:
        """启动登录流程并返回 URL

        如果已有登录进程在运行，直接返回其 URL
        """
        async with self._lock:
            # 检查是否已有有效的登录进程
            if self._process and self._process.returncode is None:
                if self._login_url:
                    logger.info("Reusing existing login process")
                    return self._login_url

            # 清理旧进程
            if self._process and self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    self._process.kill()

            self._login_url = None
            self._ready_for_code = False
            self._created_at = asyncio.get_event_loop().time()

            # 在宿主机上启动登录进程
            login_script = '''
import pty, os, select, sys, time, re

master, slave = pty.openpty()
pid = os.fork()

if pid == 0:
    os.setsid()
    os.dup2(slave, 0)
    os.dup2(slave, 1)
    os.dup2(slave, 2)
    os.close(master)
    os.close(slave)
    os.execvp("claude", ["claude", "/login"])
else:
    os.close(slave)
    all_output = b""
    steps_done = set()
    start = time.time()
    url_printed = False
    auth_submit_time = 0

    while time.time() - start < 300:
        r, _, _ = select.select([master, sys.stdin], [], [], 0.3)

        if master in r:
            try:
                data = os.read(master, 4096)
                if not data:
                    break
                all_output += data
                text = all_output.decode("utf-8", errors="ignore")

                # 输出所有接收到的文本（用于调试）
                if "auth_submitted" in steps_done:
                    new_text = data.decode("utf-8", errors="ignore")
                    if new_text.strip():
                        # 移除 ANSI 转义码
                        clean = re.sub(r"\\x1b\\[[0-9;]*[A-Za-z]", "", new_text)
                        if clean.strip():
                            print(f"DEBUG_OUTPUT:{repr(clean[:100])}", flush=True)

                if "trust" not in steps_done and "Yes, proceed" in text:
                    time.sleep(0.3)
                    os.write(master, b"\\r")
                    steps_done.add("trust")

                if "login_method" not in steps_done and "Claude account with subscription" in text:
                    time.sleep(0.3)
                    os.write(master, b"\\r")
                    steps_done.add("login_method")

                if not url_printed:
                    urls = re.findall(r"https://claude\\.ai[^\\s\\x1b\\]\\)]+", text)
                    if urls:
                        print("URL:" + urls[-1].rstrip("."), flush=True)
                        url_printed = True

                if "Paste code" in text and "ready" not in steps_done:
                    print("READY_FOR_CODE", flush=True)
                    steps_done.add("ready")

                if "auth_submitted" in steps_done:
                    lower_text = text.lower()
                    # 检测各种成功信息
                    if any(x in lower_text for x in ["logged in", "login successful", "authenticated"]):
                        print("LOGIN_SUCCESS", flush=True)
                        # 如果显示 "Press Enter to continue"，再按一次 Enter
                        if "press enter" in lower_text:
                            time.sleep(0.3)
                            os.write(master, b"\\r")
                        time.sleep(1)  # 等待 credentials 写入完成
                        os.kill(pid, 9)
                        sys.exit(0)
                    # 检查是否出现错误
                    if "invalid" in lower_text or "error" in lower_text or "expired" in lower_text:
                        print(f"LOGIN_ERROR:{text[-200:]}", flush=True)

            except Exception as e:
                print(f"ERROR:{e}", flush=True)
                break

        if sys.stdin in r:
            try:
                auth_code = sys.stdin.readline().strip()
                if auth_code:
                    print(f"RECEIVED_CODE:{auth_code[:20]}...", flush=True)
                    # 写入 auth code 并按 Enter
                    written = os.write(master, (auth_code + "\\r").encode())
                    print(f"WRITTEN_BYTES:{written}", flush=True)
                    # 等待一下再按一次 Enter 确认提交
                    time.sleep(0.5)
                    os.write(master, b"\\r")
                    steps_done.add("auth_submitted")
                    auth_submit_time = time.time()
            except Exception as e:
                print(f"STDIN_ERROR:{e}", flush=True)

        # 如果提交后超过 30 秒还没成功，打印当前状态
        if auth_submit_time > 0 and time.time() - auth_submit_time > 30:
            print(f"STILL_WAITING:steps={steps_done}", flush=True)
            auth_submit_time = time.time()  # 重置以避免重复打印

    os.kill(pid, 9)
    print("LOGIN_TIMEOUT", flush=True)
'''
            # 在宿主机上运行（不是在容器里）
            self._process = await asyncio.create_subprocess_exec(
                "python3", "-c", login_script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # 读取输出直到获得 URL
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < 60:
                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=1.0
                    )
                    if not line:
                        break

                    line_text = line.decode('utf-8').strip()
                    logger.debug(f"Login process output: {line_text}")

                    if line_text.startswith("URL:"):
                        url = line_text[4:]
                        # 只移除无效 scope，保持 URL 编码
                        url = url.replace("org%3Acreate_api_key+", "")
                        url = url.replace("+org%3Acreate_api_key", "")
                        self._login_url = url

                    elif line_text == "READY_FOR_CODE":
                        self._ready_for_code = True
                        if self._login_url:
                            return self._login_url

                except asyncio.TimeoutError:
                    if self._login_url and self._ready_for_code:
                        return self._login_url
                    continue

            if self._login_url:
                return self._login_url

            logger.warning("Failed to get login URL")
            return None

    async def submit_auth_code(self, auth_code: str) -> bool:
        """提交 auth code"""
        if not self._process or self._process.returncode is not None:
            logger.error("No login process running")
            return False

        try:
            # 获取 credentials 的当前 mtime
            cred_file = CLAUDE_CREDENTIALS_FILE
            old_mtime = cred_file.stat().st_mtime if cred_file.exists() else 0
            logger.info(f"Credentials mtime before: {old_mtime}")

            # 发送 auth code
            self._process.stdin.write((auth_code + "\n").encode())
            await self._process.stdin.drain()
            logger.info("Sent auth code to login process")

            # 等待 credentials 更新，同时持续读取进程输出
            for i in range(30):  # 增加到 30 秒
                await asyncio.sleep(1)

                # 读取所有可用的输出
                while True:
                    try:
                        line = await asyncio.wait_for(
                            self._process.stdout.readline(),
                            timeout=0.1
                        )
                        if line:
                            line_text = line.decode('utf-8').strip()
                            logger.info(f"Login output: {line_text}")

                            if line_text == "LOGIN_SUCCESS":
                                logger.info("Login successful!")
                                credentials_watcher._sync_credentials()
                                return True
                            elif line_text.startswith("LOGIN_ERROR:"):
                                logger.error(f"Login error: {line_text}")
                                return False
                        else:
                            break
                    except asyncio.TimeoutError:
                        break

                # 检查文件是否更新
                if cred_file.exists():
                    new_mtime = cred_file.stat().st_mtime
                    if new_mtime > old_mtime:
                        logger.info(f"Credentials file updated! mtime: {old_mtime} -> {new_mtime}")
                        # 触发同步到容器
                        credentials_watcher._sync_credentials()
                        return True

                # 每 5 秒打印一次状态
                if i > 0 and i % 5 == 0:
                    logger.info(f"Still waiting for login... ({i}s)")

            logger.warning("Login timed out after 30s")
            return False

        except Exception as e:
            logger.error(f"Error submitting auth code: {e}")
            return False

    def cleanup(self):
        """清理登录进程"""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            self._login_url = None
            self._ready_for_code = False


# 全局登录管理器
_login_manager: Optional[GlobalLoginManager] = None


def get_login_manager() -> GlobalLoginManager:
    """获取全局登录管理器"""
    global _login_manager
    if _login_manager is None:
        _login_manager = GlobalLoginManager()
    return _login_manager


class SandboxAgent:
    """Docker 隔离的 Claude Code Agent

    在 Docker 容器中运行 Claude Code，提供安全的代码执行环境。

    认证策略：
    - 每个容器有独立的 .claude 目录（避免 projects/ 冲突）
    - 从宿主机复制认证文件 .credentials.json 和 .claude.json
    - 容器内的 .claude 目录可读写
    """

    def __init__(self, workspace_path: str, workspace_id: str = "", agent_session_id: str = ""):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_id = workspace_id
        self.agent_session_id = agent_session_id
        self.container_name = get_container_name(workspace_id, agent_session_id)

        # 容器专属的 .claude 目录（持久化）
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
        self._waiting_for_auth_code = False

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
            # 检查是否是 auth code（用户回复登录验证码）
            if self._waiting_for_auth_code:
                auth_code = prompt.strip()
                # auth code 通常是一段较长的字符串
                if len(auth_code) > 20 and " " not in auth_code:
                    logger.info(f"Detected auth code, submitting...")
                    yield {
                        "event": "status",
                        "data": {"type": "logging_in", "message": "Submitting auth code..."}
                    }

                    login_manager = get_login_manager()
                    success = await login_manager.submit_auth_code(auth_code)

                    if success:
                        self._waiting_for_auth_code = False
                        yield {
                            "event": "text_delta",
                            "data": {"text": "✅ Login successful! You can now continue using Claude.\n\n"}
                        }
                        yield {
                            "event": "message_end",
                            "data": {"is_error": False, "result": "Login successful"}
                        }
                    else:
                        yield {
                            "event": "text_delta",
                            "data": {"text": "❌ Login failed. Please try again with a new code.\n\n"}
                        }
                        # 重新获取登录链接
                        login_url = await login_manager.start_login()
                        if login_url:
                            yield {
                                "event": "text_delta",
                                "data": {"text": f"🔗 Please login again:\n\n{login_url}\n\nPaste the authentication code here after logging in.\n\n"}
                            }
                        yield {
                            "event": "message_end",
                            "data": {"is_error": True, "result": "Login failed"}
                        }
                    return

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

            # 构建 claude 命令
            # 注意: --output-format stream-json 需要配合 --verbose 使用
            claude_cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]

            # 如果有之前的会话，使用 --resume 继续
            if self.session_id:
                claude_cmd.extend(["--resume", self.session_id])

            # 在容器中执行（容器已以正确 UID 运行，无需 -u）
            docker_exec = [
                "docker", "exec", "-w", "/workspace",
                self.container_name,
                "/bin/bash", "-lc",
                " ".join(f'"{arg}"' if " " in arg else arg for arg in claude_cmd)
            ]

            logger.debug(f"Docker exec command: {' '.join(docker_exec)}")

            # 启动进程
            # limit 设置为 128MB，避免大文件内容导致 LimitOverrunError
            self._process = await asyncio.create_subprocess_exec(
                *docker_exec,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=128 * 1024 * 1024,  # 128MB
            )

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
                            logger.error("OAuth token expired, triggering re-login...")

                            # 使用全局登录管理器
                            login_manager = get_login_manager()
                            login_url = await login_manager.start_login()

                            if login_url:
                                self._waiting_for_auth_code = True
                                yield {
                                    "event": "text_delta",
                                    "data": {"text": f"⚠️ **OAuth token expired. Please login:**\n\n{login_url}\n\n📋 After logging in, paste the **Authentication Code** here to complete login.\n\n"}
                                }
                                yield {
                                    "event": "message_end",
                                    "data": {
                                        "session_id": session_id,
                                        "is_error": False,  # 不算错误，等待用户输入
                                        "result": "Waiting for authentication code",
                                    }
                                }
                                return  # 不继续执行，等待用户输入 auth code

                        yield {
                            "event": "message_end",
                            "data": {
                                "session_id": session_id,
                                "duration_ms": event.get("duration_ms", 0),
                                "num_turns": event.get("num_turns", 0),
                                "is_error": is_error,
                                "result": result_text,
                                "total_cost_usd": event.get("total_cost_usd", 0),
                            }
                        }

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

            # 等待 stderr 读取完成
            await stderr_task
            if stderr_lines:
                stderr_text = chr(10).join(stderr_lines)
                logger.warning(f"Sandbox stderr: {stderr_text}")

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
