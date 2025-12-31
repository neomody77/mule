"""
工作区管理服务

管理工作区的创建、删除、文件操作等
"""
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models.workspace import WorkspaceInfo


class WorkspaceManager:
    """工作区管理器"""

    def __init__(self):
        self.base_dir = settings.workspace_base_dir
        self.meta_file = ".workspace_meta.json"

    def _get_workspace_path(self, workspace_id: str) -> Path:
        """获取工作区路径"""
        return self.base_dir / workspace_id

    def _get_meta_path(self, workspace_id: str) -> Path:
        """获取元数据文件路径"""
        return self._get_workspace_path(workspace_id) / self.meta_file

    def _load_meta(self, workspace_id: str) -> Optional[dict]:
        """加载工作区元数据"""
        meta_path = self._get_meta_path(workspace_id)
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        return None

    def _save_meta(self, workspace_id: str, meta: dict):
        """保存工作区元数据"""
        meta_path = self._get_meta_path(workspace_id)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    def workspace_exists(self, workspace_id: str) -> bool:
        """检查工作区是否存在"""
        workspace_path = self._get_workspace_path(workspace_id)
        return workspace_path.exists() and workspace_path.is_dir()

    def create_workspace(
        self,
        name: str,
        description: Optional[str] = None
    ) -> WorkspaceInfo:
        """创建新工作区"""
        settings.ensure_workspace_base_dir()

        workspace_id = str(uuid.uuid4())[:8]
        workspace_path = self._get_workspace_path(workspace_id)

        if workspace_path.exists():
            raise ValueError(f"Workspace already exists: {workspace_id}")

        workspace_path.mkdir(parents=True)

        # 创建 .claudeignore 文件，忽略系统文件
        claudeignore_path = workspace_path / ".claudeignore"
        claudeignore_path.write_text(".workspace_meta.json\n.claudeignore\n")

        now = datetime.now()
        meta = {
            "id": workspace_id,
            "name": name,
            "description": description,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        self._save_meta(workspace_id, meta)

        return WorkspaceInfo(
            id=workspace_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
            path=str(workspace_path),
        )

    def get_workspace(self, workspace_id: str, include_deleted: bool = False) -> Optional[WorkspaceInfo]:
        """获取工作区信息"""
        if not self.workspace_exists(workspace_id):
            return None

        meta = self._load_meta(workspace_id)
        workspace_path = self._get_workspace_path(workspace_id)

        if meta:
            # 检查是否已删除
            is_deleted = meta.get("deleted", False)
            if is_deleted and not include_deleted:
                return None

            # 有元数据文件，使用元数据
            deleted_at = None
            if meta.get("deleted_at"):
                deleted_at = datetime.fromisoformat(meta["deleted_at"])

            return WorkspaceInfo(
                id=meta["id"],
                name=meta["name"],
                description=meta.get("description"),
                created_at=datetime.fromisoformat(meta["created_at"]),
                updated_at=datetime.fromisoformat(meta["updated_at"]),
                path=str(workspace_path),
                deleted=is_deleted,
                deleted_at=deleted_at,
            )
        else:
            # 没有元数据文件，自动识别并创建元数据
            return self._auto_recognize_workspace(workspace_id)

    def _auto_recognize_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        """自动识别工作区（没有元数据的目录）"""
        workspace_path = self._get_workspace_path(workspace_id)

        if not workspace_path.exists() or not workspace_path.is_dir():
            return None

        # 使用目录名作为工作区名称
        name = workspace_id

        # 尝试从常见配置文件获取项目名称
        project_name = self._detect_project_name(workspace_path)
        if project_name:
            name = project_name

        # 尝试获取描述
        description = self._detect_project_description(workspace_path)

        # 获取目录的创建/修改时间
        stat = workspace_path.stat()
        created_at = datetime.fromtimestamp(stat.st_ctime)
        updated_at = datetime.fromtimestamp(stat.st_mtime)

        # 自动创建元数据文件
        meta = {
            "id": workspace_id,
            "name": name,
            "description": description,
            "created_at": created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
            "auto_detected": True,  # 标记为自动检测
        }
        self._save_meta(workspace_id, meta)

        return WorkspaceInfo(
            id=workspace_id,
            name=name,
            description=description,
            created_at=created_at,
            updated_at=updated_at,
            path=str(workspace_path),
        )

    def _detect_project_name(self, workspace_path: Path) -> Optional[str]:
        """从项目配置文件检测项目名称"""
        # package.json (Node.js)
        package_json = workspace_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                if "name" in data:
                    return data["name"]
            except:
                pass

        # pyproject.toml (Python)
        pyproject = workspace_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                # 简单解析 name = "xxx"
                for line in content.split("\n"):
                    if line.strip().startswith("name"):
                        parts = line.split("=")
                        if len(parts) >= 2:
                            name = parts[1].strip().strip('"').strip("'")
                            if name:
                                return name
            except:
                pass

        # Cargo.toml (Rust)
        cargo_toml = workspace_path / "Cargo.toml"
        if cargo_toml.exists():
            try:
                content = cargo_toml.read_text()
                for line in content.split("\n"):
                    if line.strip().startswith("name"):
                        parts = line.split("=")
                        if len(parts) >= 2:
                            name = parts[1].strip().strip('"').strip("'")
                            if name:
                                return name
            except:
                pass

        # pubspec.yaml (Flutter/Dart)
        pubspec = workspace_path / "pubspec.yaml"
        if pubspec.exists():
            try:
                content = pubspec.read_text()
                for line in content.split("\n"):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                        if name:
                            return name
            except:
                pass

        # go.mod (Go)
        go_mod = workspace_path / "go.mod"
        if go_mod.exists():
            try:
                content = go_mod.read_text()
                first_line = content.split("\n")[0]
                if first_line.startswith("module"):
                    module_path = first_line.split()[1]
                    # 取最后一个路径段作为名称
                    return module_path.split("/")[-1]
            except:
                pass

        return None

    def _detect_project_description(self, workspace_path: Path) -> Optional[str]:
        """从项目配置文件检测项目描述"""
        # package.json
        package_json = workspace_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                if "description" in data:
                    return data["description"]
            except:
                pass

        # 检查是否有 README
        for readme_name in ["README.md", "README.txt", "README", "readme.md"]:
            readme = workspace_path / readme_name
            if readme.exists():
                try:
                    content = readme.read_text()
                    # 取第一行非空内容作为描述
                    for line in content.split("\n"):
                        line = line.strip().lstrip("#").strip()
                        if line and not line.startswith("!") and not line.startswith("["):
                            return line[:200]  # 截断
                except:
                    pass
                break

        return None

    def list_workspaces(self, include_deleted: bool = False) -> list[WorkspaceInfo]:
        """列出所有工作区"""
        settings.ensure_workspace_base_dir()

        workspaces = []
        for item in self.base_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                workspace = self.get_workspace(item.name, include_deleted=include_deleted)
                if workspace:
                    workspaces.append(workspace)

        # 按更新时间排序
        workspaces.sort(key=lambda w: w.updated_at, reverse=True)
        return workspaces

    def delete_workspace(self, workspace_id: str, permanent: bool = False) -> bool:
        """删除工作区（软删除，可恢复）"""
        if not self.workspace_exists(workspace_id):
            return False

        if permanent:
            # 永久删除
            workspace_path = self._get_workspace_path(workspace_id)
            shutil.rmtree(workspace_path)
            return True

        # 软删除 - 标记 metadata
        meta = self._load_meta(workspace_id)
        if not meta:
            # 如果没有 metadata，先自动识别创建
            self._auto_recognize_workspace(workspace_id)
            meta = self._load_meta(workspace_id)

        if meta:
            meta["deleted"] = True
            meta["deleted_at"] = datetime.now().isoformat()
            self._save_meta(workspace_id, meta)
            return True

        return False

    def restore_workspace(self, workspace_id: str) -> Optional[WorkspaceInfo]:
        """恢复已删除的工作区"""
        if not self.workspace_exists(workspace_id):
            return None

        meta = self._load_meta(workspace_id)
        if not meta:
            return None

        if not meta.get("deleted", False):
            # 未删除，直接返回
            return self.get_workspace(workspace_id)

        # 恢复
        meta["deleted"] = False
        meta["deleted_at"] = None
        meta["updated_at"] = datetime.now().isoformat()
        self._save_meta(workspace_id, meta)

        return self.get_workspace(workspace_id)

    def list_deleted_workspaces(self) -> list[WorkspaceInfo]:
        """列出所有已删除的工作区（回收站）"""
        settings.ensure_workspace_base_dir()

        workspaces = []
        for item in self.base_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                workspace = self.get_workspace(item.name, include_deleted=True)
                if workspace and workspace.deleted:
                    workspaces.append(workspace)

        # 按删除时间排序
        workspaces.sort(key=lambda w: w.deleted_at or w.updated_at, reverse=True)
        return workspaces

    def update_workspace(
        self,
        workspace_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[WorkspaceInfo]:
        """更新工作区信息"""
        meta = self._load_meta(workspace_id)
        if not meta:
            return None

        if name:
            meta["name"] = name
        if description is not None:
            meta["description"] = description

        meta["updated_at"] = datetime.now().isoformat()
        self._save_meta(workspace_id, meta)

        return self.get_workspace(workspace_id)

    def list_files(self, workspace_id: str, relative_path: str = "") -> list[dict]:
        """列出工作区中的文件"""
        workspace_path = self._get_workspace_path(workspace_id)
        target_path = (workspace_path / relative_path).resolve()

        # 安全检查
        if not str(target_path).startswith(str(workspace_path.resolve())):
            raise ValueError("Path escape attempt")

        if not target_path.exists():
            raise ValueError(f"Path not found: {relative_path}")

        if not target_path.is_dir():
            raise ValueError(f"Not a directory: {relative_path}")

        files = []
        for item in sorted(target_path.iterdir()):
            # 跳过元数据文件
            if item.name == self.meta_file:
                continue

            rel_path = str(item.relative_to(workspace_path))
            files.append({
                "name": item.name,
                "path": rel_path,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
                "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
            })

        return files

    def read_file(self, workspace_id: str, relative_path: str) -> str:
        """读取文件内容"""
        workspace_path = self._get_workspace_path(workspace_id)
        file_path = (workspace_path / relative_path).resolve()

        # 安全检查
        if not str(file_path).startswith(str(workspace_path.resolve())):
            raise ValueError("Path escape attempt")

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")

        if file_path.is_dir():
            raise ValueError(f"Path is a directory: {relative_path}")

        return file_path.read_text(encoding="utf-8")


    def ensure_default_workspace(self) -> WorkspaceInfo:
        """确保默认工作空间存在（用于后台任务、临时任务等）"""
        default_id = "default"
        default_name = "Default Workspace"
        default_desc = "Default workspace for background tasks, temporary operations, and general use"

        # 检查是否已存在
        workspace = self.get_workspace(default_id)
        if workspace:
            return workspace

        # 创建默认工作空间（使用固定 ID）
        settings.ensure_workspace_base_dir()
        workspace_path = self._get_workspace_path(default_id)

        if not workspace_path.exists():
            workspace_path.mkdir(parents=True)

        # 创建 .claudeignore 文件
        claudeignore_path = workspace_path / ".claudeignore"
        if not claudeignore_path.exists():
            claudeignore_path.write_text(".workspace_meta.json\n.claudeignore\n")

        now = datetime.now()
        meta = {
            "id": default_id,
            "name": default_name,
            "description": default_desc,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "is_default": True,  # 标记为默认工作空间
        }
        self._save_meta(default_id, meta)

        return WorkspaceInfo(
            id=default_id,
            name=default_name,
            description=default_desc,
            created_at=now,
            updated_at=now,
            path=str(workspace_path),
        )


# 全局实例
workspace_manager = WorkspaceManager()
