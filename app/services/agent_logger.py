"""
Agent 活动日志服务

记录 Agent 的所有文件和网络访问操作，用于安全审计。
"""
import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from app.config import settings


class ActionType(str, Enum):
    """操作类型"""
    # 文件操作
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_EDIT = "file_edit"
    FILE_DELETE = "file_delete"
    FILE_GLOB = "file_glob"
    FILE_GREP = "file_grep"

    # 命令执行
    BASH_EXEC = "bash_exec"

    # 网络操作
    NET_HTTP_REQUEST = "net_http_request"
    NET_WEBSOCKET = "net_websocket"
    NET_DOWNLOAD = "net_download"

    # Session 生命周期
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TASK_START = "task_start"
    TASK_END = "task_end"


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"           # 读取操作
    MEDIUM = "medium"     # 写入操作
    HIGH = "high"         # 命令执行、网络访问
    CRITICAL = "critical" # 敏感文件/危险命令


class AgentActivityLog:
    """Agent 活动日志条目"""

    def __init__(
        self,
        workspace_id: str,
        session_id: str,
        action_type: ActionType,
        target: str,
        details: dict[str, Any] | None = None,
        risk_level: RiskLevel = RiskLevel.LOW,
        success: bool = True,
        error: str | None = None,
    ):
        self.timestamp = datetime.utcnow()
        self.workspace_id = workspace_id
        self.session_id = session_id
        self.action_type = action_type
        self.target = target
        self.details = details or {}
        self.risk_level = risk_level
        self.success = success
        self.error = error

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "action_type": self.action_type.value,
            "target": self.target,
            "details": self.details,
            "risk_level": self.risk_level.value,
            "success": self.success,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class AgentLogger:
    """Agent 活动日志记录器"""

    # 敏感文件模式
    SENSITIVE_PATTERNS = [
        ".env", ".env.*",
        "*.pem", "*.key", "*.crt",
        "*password*", "*secret*", "*credential*",
        ".ssh/*", ".aws/*", ".gnupg/*",
        "/etc/passwd", "/etc/shadow",
    ]

    # 危险命令关键词
    DANGEROUS_COMMANDS = [
        "rm -rf", "dd if=", "mkfs",
        "> /dev/", "chmod 777",
        "curl | sh", "wget | sh",
        "eval", "exec",
        "nc -l", "netcat",
        "ssh ", "scp ",
    ]

    def __init__(self, workspace_id: str, session_id: str):
        self.workspace_id = workspace_id
        self.session_id = session_id
        self.logger = logging.getLogger(f"agent.{workspace_id}.{session_id}")

        # 确保日志目录存在
        self.log_dir = settings.data_dir / "logs" / "agent"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 设置文件日志处理器
        log_file = self.log_dir / f"{workspace_id}_{session_id}.jsonl"
        self.file_handler = logging.FileHandler(log_file, encoding='utf-8')
        self.file_handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(self.file_handler)
        self.logger.setLevel(logging.INFO)

        # 主日志
        self.main_logger = logging.getLogger("agent_activity")

    def _is_sensitive_file(self, path: str) -> bool:
        """检查是否为敏感文件"""
        path_lower = path.lower()
        for pattern in self.SENSITIVE_PATTERNS:
            if "*" in pattern:
                # 简单通配符匹配
                base = pattern.replace("*", "")
                if base in path_lower:
                    return True
            elif pattern in path_lower:
                return True
        return False

    def _is_dangerous_command(self, command: str) -> bool:
        """检查是否为危险命令"""
        cmd_lower = command.lower()
        for dangerous in self.DANGEROUS_COMMANDS:
            if dangerous in cmd_lower:
                return True
        return False

    def _get_file_risk_level(self, action: ActionType, path: str) -> RiskLevel:
        """获取文件操作的风险等级"""
        if self._is_sensitive_file(path):
            return RiskLevel.CRITICAL

        if action == ActionType.FILE_READ:
            return RiskLevel.LOW
        elif action in (ActionType.FILE_GLOB, ActionType.FILE_GREP):
            return RiskLevel.LOW
        elif action in (ActionType.FILE_WRITE, ActionType.FILE_EDIT):
            return RiskLevel.MEDIUM
        elif action == ActionType.FILE_DELETE:
            return RiskLevel.HIGH

        return RiskLevel.LOW

    def _log(self, log: AgentActivityLog):
        """记录日志"""
        json_log = log.to_json()

        # 写入 session 专用日志文件
        self.logger.info(json_log)

        # 同时输出到主日志（根据风险等级）
        log_msg = f"[{log.action_type.value}] {log.target}"
        if log.risk_level == RiskLevel.CRITICAL:
            self.main_logger.warning(f"⚠️  CRITICAL: {log_msg} | {log.details}")
        elif log.risk_level == RiskLevel.HIGH:
            self.main_logger.warning(f"🔶 HIGH: {log_msg}")
        elif log.risk_level == RiskLevel.MEDIUM:
            self.main_logger.info(f"🔵 {log_msg}")
        else:
            self.main_logger.debug(f"⚪ {log_msg}")

    # === 文件操作日志 ===

    def log_file_read(self, file_path: str, size: int | None = None, success: bool = True, error: str | None = None):
        """记录文件读取"""
        risk = self._get_file_risk_level(ActionType.FILE_READ, file_path)
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.FILE_READ,
            target=file_path,
            details={"size": size} if size else {},
            risk_level=risk,
            success=success,
            error=error,
        )
        self._log(log)

    def log_file_write(self, file_path: str, size: int | None = None, is_new: bool = False, success: bool = True, error: str | None = None):
        """记录文件写入"""
        risk = self._get_file_risk_level(ActionType.FILE_WRITE, file_path)
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.FILE_WRITE,
            target=file_path,
            details={"size": size, "is_new": is_new},
            risk_level=risk,
            success=success,
            error=error,
        )
        self._log(log)

    def log_file_edit(self, file_path: str, changes: dict | None = None, success: bool = True, error: str | None = None):
        """记录文件编辑"""
        risk = self._get_file_risk_level(ActionType.FILE_EDIT, file_path)
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.FILE_EDIT,
            target=file_path,
            details=changes or {},
            risk_level=risk,
            success=success,
            error=error,
        )
        self._log(log)

    def log_glob(self, pattern: str, matches_count: int = 0, success: bool = True):
        """记录 Glob 搜索"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.FILE_GLOB,
            target=pattern,
            details={"matches": matches_count},
            risk_level=RiskLevel.LOW,
            success=success,
        )
        self._log(log)

    def log_grep(self, pattern: str, path: str | None = None, matches_count: int = 0, success: bool = True):
        """记录 Grep 搜索"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.FILE_GREP,
            target=pattern,
            details={"path": path, "matches": matches_count},
            risk_level=RiskLevel.LOW,
            success=success,
        )
        self._log(log)

    # === 命令执行日志 ===

    def log_bash_exec(
        self,
        command: str,
        exit_code: int | None = None,
        output_preview: str | None = None,
        success: bool = True,
        error: str | None = None
    ):
        """记录 Bash 命令执行"""
        is_dangerous = self._is_dangerous_command(command)
        risk = RiskLevel.CRITICAL if is_dangerous else RiskLevel.HIGH

        details = {}
        if exit_code is not None:
            details["exit_code"] = exit_code
        if output_preview:
            # 只记录前 200 字符
            details["output_preview"] = output_preview[:200] if len(output_preview) > 200 else output_preview
        if is_dangerous:
            details["dangerous_pattern_detected"] = True

        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.BASH_EXEC,
            target=command[:500],  # 截断过长命令
            details=details,
            risk_level=risk,
            success=success,
            error=error,
        )
        self._log(log)

    # === 网络操作日志 ===

    def log_http_request(
        self,
        method: str,
        url: str,
        status_code: int | None = None,
        success: bool = True,
        error: str | None = None
    ):
        """记录 HTTP 请求"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.NET_HTTP_REQUEST,
            target=url,
            details={"method": method, "status_code": status_code},
            risk_level=RiskLevel.HIGH,
            success=success,
            error=error,
        )
        self._log(log)

    def log_download(self, url: str, save_path: str, size: int | None = None, success: bool = True, error: str | None = None):
        """记录文件下载"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.NET_DOWNLOAD,
            target=url,
            details={"save_path": save_path, "size": size},
            risk_level=RiskLevel.HIGH,
            success=success,
            error=error,
        )
        self._log(log)

    # === Session 生命周期日志 ===

    def log_session_start(self):
        """记录 Session 开始"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.SESSION_START,
            target=f"{self.workspace_id}/{self.session_id}",
            risk_level=RiskLevel.LOW,
        )
        self._log(log)

    def log_session_end(self, duration_ms: int | None = None, num_turns: int | None = None):
        """记录 Session 结束"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.SESSION_END,
            target=f"{self.workspace_id}/{self.session_id}",
            details={"duration_ms": duration_ms, "num_turns": num_turns},
            risk_level=RiskLevel.LOW,
        )
        self._log(log)

    def log_task_start(self, prompt: str):
        """记录任务开始"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.TASK_START,
            target="task",
            details={"prompt_preview": prompt[:200] if len(prompt) > 200 else prompt},
            risk_level=RiskLevel.LOW,
        )
        self._log(log)

    def log_task_end(self, success: bool = True, error: str | None = None):
        """记录任务结束"""
        log = AgentActivityLog(
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.TASK_END,
            target="task",
            risk_level=RiskLevel.LOW,
            success=success,
            error=error,
        )
        self._log(log)

    def close(self):
        """关闭日志处理器"""
        self.logger.removeHandler(self.file_handler)
        self.file_handler.close()


# 全局日志管理器
class AgentLoggerManager:
    """Agent 日志管理器 - 管理多个 session 的日志"""

    def __init__(self):
        self._loggers: dict[str, AgentLogger] = {}

    def get_logger(self, workspace_id: str, session_id: str) -> AgentLogger:
        """获取或创建 Logger"""
        key = f"{workspace_id}:{session_id}"
        if key not in self._loggers:
            self._loggers[key] = AgentLogger(workspace_id, session_id)
        return self._loggers[key]

    def close_logger(self, workspace_id: str, session_id: str):
        """关闭 Logger"""
        key = f"{workspace_id}:{session_id}"
        if key in self._loggers:
            self._loggers[key].close()
            del self._loggers[key]

    def close_all(self):
        """关闭所有 Logger"""
        for logger in self._loggers.values():
            logger.close()
        self._loggers.clear()


# 全局实例
agent_logger_manager = AgentLoggerManager()
