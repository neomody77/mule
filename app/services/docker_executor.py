"""
Docker Executor - Workspace 隔离执行器

使用 Docker 容器隔离每个 workspace 的代码执行环境：
- 每个 workspace 一个容器
- 只挂载对应的 workspace 目录
- Claude CLI 在容器内执行，无法访问宿主机其他文件
- UID/GID 映射：容器内用户与宿主机相同，避免权限问题
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, AsyncGenerator

import docker
from docker.errors import NotFound, ImageNotFound
from docker.models.containers import Container

logger = logging.getLogger(__name__)

# 容器镜像名称
WORKSPACE_IMAGE = "mule-workspace:latest"

# 获取当前进程的 UID/GID (用于容器内用户映射)
HOST_UID = os.getuid()
HOST_GID = os.getgid()

# 容器配置
CONTAINER_CONFIG = {
    "mem_limit": "2g",           # 内存限制
    "cpu_period": 100000,        # CPU 周期
    "cpu_quota": 100000,         # CPU 配额 (100% 单核)
    "network_mode": "bridge",    # 网络模式 (需要访问 API)
    "security_opt": ["no-new-privileges"],  # 禁止提权
}


class DockerExecutor:
    """Docker 容器执行器"""

    def __init__(self):
        self._client: Optional[docker.DockerClient] = None
        self._containers: dict[str, Container] = {}  # workspace_id -> container

    @property
    def client(self) -> docker.DockerClient:
        """懒加载 Docker 客户端"""
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def _get_container_name(self, workspace_id: str) -> str:
        """获取容器名称"""
        return f"mule-ws-{workspace_id}"

    async def ensure_image(self) -> bool:
        """确保工作区镜像存在"""
        try:
            self.client.images.get(WORKSPACE_IMAGE)
            logger.info(f"Image {WORKSPACE_IMAGE} found")
            return True
        except ImageNotFound:
            logger.warning(f"Image {WORKSPACE_IMAGE} not found, need to build first")
            return False

    async def build_image(self, dockerfile_path: str) -> bool:
        """构建工作区镜像"""
        try:
            dockerfile_dir = Path(dockerfile_path).parent
            logger.info(f"Building image {WORKSPACE_IMAGE} from {dockerfile_path}")

            # 使用线程池执行阻塞的 build 操作
            loop = asyncio.get_event_loop()
            image, logs = await loop.run_in_executor(
                None,
                lambda: self.client.images.build(
                    path=str(dockerfile_dir),
                    dockerfile=Path(dockerfile_path).name,
                    tag=WORKSPACE_IMAGE,
                    rm=True,
                )
            )

            for log in logs:
                if 'stream' in log:
                    logger.debug(log['stream'].strip())

            logger.info(f"Image {WORKSPACE_IMAGE} built successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to build image: {e}")
            return False

    async def get_or_create_container(
        self,
        workspace_id: str,
        workspace_path: str,
        env: Optional[dict] = None
    ) -> Optional[Container]:
        """获取或创建 workspace 容器"""
        container_name = self._get_container_name(workspace_id)

        # 检查缓存
        if workspace_id in self._containers:
            container = self._containers[workspace_id]
            try:
                container.reload()
                if container.status == "running":
                    return container
            except NotFound:
                del self._containers[workspace_id]

        # 查找已存在的容器
        try:
            container = self.client.containers.get(container_name)
            container.reload()

            if container.status != "running":
                logger.info(f"Starting existing container {container_name}")
                container.start()
                container.reload()

            self._containers[workspace_id] = container
            return container

        except NotFound:
            pass

        # 创建新容器
        try:
            # 确保 workspace 目录存在
            Path(workspace_path).mkdir(parents=True, exist_ok=True)

            # 准备环境变量
            environment = env or {}

            # 设置 UID/GID 映射（与宿主机相同）
            environment["USER_UID"] = str(HOST_UID)
            environment["USER_GID"] = str(HOST_GID)

            # 从宿主机继承 API 认证（不继承代理设置）
            inherit_keys = [
                'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY',
                'DISABLE_TELEMETRY',
            ]
            for key in inherit_keys:
                if key in os.environ:
                    environment[key] = os.environ[key]

            logger.info(f"Creating container {container_name} for workspace {workspace_id} (UID={HOST_UID}, GID={HOST_GID})")

            # 准备挂载卷 - 只挂载 workspace 目录
            volumes = {
                workspace_path: {
                    "bind": "/workspace",
                    "mode": "rw"
                }
            }
            # 注意：使用 API Key 认证时不需要挂载 ~/.claude 目录
            # 认证信息通过环境变量传递

            container = self.client.containers.run(
                WORKSPACE_IMAGE,
                name=container_name,
                detach=True,
                volumes=volumes,
                environment=environment,
                working_dir="/workspace",
                **CONTAINER_CONFIG
            )

            self._containers[workspace_id] = container
            logger.info(f"Container {container_name} created and started")

            # 等待 entrypoint 脚本创建 coder 用户
            await asyncio.sleep(1)

            return container

        except Exception as e:
            logger.error(f"Failed to create container: {e}")
            return None

    async def exec_command(
        self,
        workspace_id: str,
        command: list[str],
        workspace_path: str,
        env: Optional[dict] = None,
        timeout: int = 300
    ) -> tuple[int, str, str]:
        """在容器中执行命令

        Args:
            workspace_id: 工作区 ID
            command: 命令列表
            workspace_path: 工作区路径
            env: 额外环境变量
            timeout: 超时时间(秒)

        Returns:
            (exit_code, stdout, stderr)
        """
        container = await self.get_or_create_container(workspace_id, workspace_path, env)
        if not container:
            return (1, "", "Failed to get container")

        try:
            # 合并环境变量
            exec_env = env or {}

            logger.debug(f"Executing in container: {' '.join(command)}")

            # 执行命令
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: container.exec_run(
                        command,
                        environment=exec_env,
                        workdir="/workspace",
                        demux=True,  # 分离 stdout/stderr
                    )
                ),
                timeout=timeout
            )

            exit_code = result.exit_code
            stdout = result.output[0].decode() if result.output[0] else ""
            stderr = result.output[1].decode() if result.output[1] else ""

            return (exit_code, stdout, stderr)

        except asyncio.TimeoutError:
            logger.error(f"Command timed out after {timeout}s")
            return (124, "", f"Command timed out after {timeout} seconds")
        except Exception as e:
            logger.error(f"Exec error: {e}")
            return (1, "", str(e))

    async def exec_claude(
        self,
        workspace_id: str,
        workspace_path: str,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """在容器中执行 Claude CLI (流式输出)

        Yields:
            JSON 行 (stream-json 格式)
        """
        container = await self.get_or_create_container(workspace_id, workspace_path)
        if not container:
            yield '{"type": "error", "error": "Failed to get container"}'
            return

        # 构建命令
        cmd = [
            "claude",
            "--output-format", "stream-json",
            "--verbose",
        ]

        if session_id:
            cmd.extend(["--resume", session_id])

        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        cmd.extend(["-p", prompt])

        try:
            # 创建 exec 实例
            exec_instance = self.client.api.exec_create(
                container.id,
                cmd,
                stdout=True,
                stderr=True,
                workdir="/workspace",
            )

            # 流式读取输出 (使用 demux=True 分离 stdout/stderr)
            output = self.client.api.exec_start(exec_instance['Id'], stream=True, demux=True)

            buffer = ""
            for stdout_chunk, stderr_chunk in output:
                # 只处理 stdout，忽略 stderr（Claude 的 JSON 输出在 stdout）
                if stdout_chunk:
                    chunk = stdout_chunk.decode('utf-8', errors='replace') if isinstance(stdout_chunk, bytes) else stdout_chunk
                    buffer += chunk

                # 按行处理
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        yield line

            # 处理剩余内容
            if buffer.strip():
                yield buffer.strip()

        except Exception as e:
            logger.error(f"Claude exec error: {e}")
            yield f'{{"type": "error", "error": "{str(e)}"}}'

    async def stop_container(self, workspace_id: str) -> bool:
        """停止 workspace 容器"""
        container_name = self._get_container_name(workspace_id)

        try:
            container = self.client.containers.get(container_name)
            container.stop(timeout=10)
            logger.info(f"Container {container_name} stopped")

            if workspace_id in self._containers:
                del self._containers[workspace_id]

            return True
        except NotFound:
            return True
        except Exception as e:
            logger.error(f"Failed to stop container: {e}")
            return False

    async def remove_container(self, workspace_id: str) -> bool:
        """删除 workspace 容器"""
        await self.stop_container(workspace_id)

        container_name = self._get_container_name(workspace_id)

        try:
            container = self.client.containers.get(container_name)
            container.remove(force=True)
            logger.info(f"Container {container_name} removed")
            return True
        except NotFound:
            return True
        except Exception as e:
            logger.error(f"Failed to remove container: {e}")
            return False

    async def cleanup_all(self) -> None:
        """清理所有 mule workspace 容器"""
        try:
            containers = self.client.containers.list(
                all=True,
                filters={"name": "mule-ws-"}
            )

            for container in containers:
                try:
                    container.remove(force=True)
                    logger.info(f"Removed container {container.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove {container.name}: {e}")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")


# 全局单例
docker_executor = DockerExecutor()
