"""项目服务：把用户自己的文档文件夹登记成「项目」，供左栏浏览与 Agent 读取。

为什么需要项目（而不是每次都手动传文件）：
用户日常的合同、报告、素材都按文件夹存在本地（比如 `D:/工作/2026合同`）。每次任务都去资源管理器
里挑一遍文件很啰嗦，所以这里登记文件夹路径，前端可以直接浏览其中的文档，发起任务时把选中的
文件作为素材交给本次运行。

边界：
- 只登记本机已存在的目录，路径写进 settings 表（`projects.list`），不搬动、不改名用户文件；
- 扫描只读目录、只列常见文档扩展名，不进隐藏目录、不跟符号链接（避免绕圈与大目录卡死）；
- 目录消失（移动硬盘拔掉 / 用户改名）时不报错，列表里标 `missing=true` 让界面提示重新指定。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..core.config import DATA_ROOT
from ..core.errors import AppError, ErrorCode
from ..core.utils import new_id, now_iso
from ..domain.entities import SettingItem
from ..domain.formats import UPLOAD_EXTS
from ..domain.ports import SettingsRepository

_SETTINGS_KEY = "projects.list"

MAX_PROJECTS = 20
"""最多登记多少个项目：左栏是常驻区域，超过这个数就变成第二个会话列表了。"""

MAX_SCAN_FILES = 400
MAX_SCAN_DEPTH = 3
MAX_STAGE_FILES = 10
"""单次运行最多把多少个项目文件带进素材：与上传接口的单次 10 个保持一致。"""

MAX_STAGE_BYTES = 30 * 1024 * 1024

# 项目里哪些文件算「文档」：直接取上传白名单，扫到的文件才可能被解析成素材。
# 以前这里另外列了 .doc/.xls/.ppt 三种老二进制格式——解析器根本不认，
# 扫进来只会在「读素材」那步报错，不如不收。
DOC_EXTS = frozenset(UPLOAD_EXTS)

# 不允许登记成项目的目录：写死代码仓与产物目录，避免用户误选后 Agent 把源码当素材
_BLOCKED_NAMES = frozenset({"node_modules", ".git", ".venv", "dist", "build"})


def _norm(path: Path) -> str:
    """比较路径用：Windows 大小写不敏感，统一小写 + 去掉尾部分隔符。"""
    text = str(path).rstrip("\\/")
    return text.lower() if os.name == "nt" else text


class ProjectService:
    def __init__(self, repo: SettingsRepository, project_root: Path | None = None):
        self.repo = repo
        # 打包成 exe 后仓库根是只读的解压目录，项目数据跟 DATA_ROOT 走
        self.project_root = (project_root or DATA_ROOT).resolve()

    # ------------------------------------------------------------------ #
    # 存储
    # ------------------------------------------------------------------ #
    def _load(self) -> list[dict[str, Any]]:
        item = self.repo.get(_SETTINGS_KEY)
        if item is None or not isinstance(item.value, list):
            return []
        projects: list[dict[str, Any]] = []
        for raw in item.value:
            if not isinstance(raw, dict):
                continue
            path = str(raw.get("path") or "").strip()
            if not path:
                continue
            projects.append(
                {
                    "id": str(raw.get("id") or new_id("prj")),
                    "name": str(raw.get("name") or Path(path).name or path),
                    "path": path,
                    "created_at": str(raw.get("created_at") or now_iso()),
                    "pinned": bool(raw.get("pinned")),
                }
            )
        return projects

    def _save(self, projects: list[dict[str, Any]]) -> None:
        self.repo.upsert(
            SettingItem(
                key=_SETTINGS_KEY,
                value=projects,
                updated_at=now_iso(),
                scope="global",
                is_secret=False,
            )
        )

    # ------------------------------------------------------------------ #
    # 扫描
    # ------------------------------------------------------------------ #
    def _scan(self, root: Path, limit: int = MAX_SCAN_FILES) -> list[dict[str, Any]]:
        """广度优先扫描文档文件：限制深度与数量，跳过隐藏目录与超链接目录。"""
        found: list[dict[str, Any]] = []
        queue: list[tuple[Path, int]] = [(root, 0)]
        while queue and len(found) < limit:
            current, depth = queue.pop(0)
            try:
                entries = sorted(current.iterdir(), key=lambda item: item.name.lower())
            except OSError:
                continue
            for entry in entries:
                if len(found) >= limit:
                    break
                name = entry.name
                if name.startswith(".") or name in _BLOCKED_NAMES:
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        if depth + 1 <= MAX_SCAN_DEPTH:
                            queue.append((entry, depth + 1))
                        continue
                    if not entry.is_file() or entry.suffix.lower() not in DOC_EXTS:
                        continue
                    stat = entry.stat()
                except OSError:
                    continue
                found.append(
                    {
                        "name": name,
                        "rel_path": str(entry.relative_to(root)).replace("\\", "/"),
                        "ext": entry.suffix.lower().lstrip("."),
                        "size": stat.st_size,
                        "modified_at": _iso_from_ts(stat.st_mtime),
                    }
                )
        found.sort(key=lambda item: item["modified_at"], reverse=True)
        return found

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def list_projects(self) -> list[dict[str, Any]]:
        projects = self._load()
        views: list[dict[str, Any]] = []
        for project in projects:
            path = Path(project["path"])
            exists = path.is_dir()
            files = self._scan(path) if exists else []
            views.append(
                {
                    **project,
                    "file_count": len(files),
                    "missing": not exists,
                    "modified_at": files[0]["modified_at"] if files else None,
                }
            )
        views.sort(key=lambda item: (not item["pinned"], item["name"].lower()))
        return views

    def get(self, project_id: str) -> dict[str, Any]:
        for project in self.list_projects():
            if project["id"] == project_id:
                return project
        raise AppError(ErrorCode.NOT_FOUND, f"项目不存在：{project_id}")

    def project_path(self, project_id: str) -> Path:
        project = self.get(project_id)
        path = Path(project["path"])
        if not path.is_dir():
            raise AppError(ErrorCode.NOT_FOUND, "项目文件夹不存在了，可能被移动或删除，请重新添加")
        return path

    def files(self, project_id: str, query: str | None = None) -> list[dict[str, Any]]:
        path = self.project_path(project_id)
        files = self._scan(path)
        keyword = (query or "").strip().lower()
        if keyword:
            files = [item for item in files if keyword in item["name"].lower()]
        for item in files:
            item["path"] = str(path / item["rel_path"])
        return files

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def add(self, path: str, name: str | None = None) -> dict[str, Any]:
        raw = (path or "").strip()
        if not raw:
            raise AppError(ErrorCode.BAD_REQUEST, "请先选择要添加的文件夹")
        candidate = Path(raw).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise AppError(ErrorCode.BAD_REQUEST, f"这个文件夹打不开：{exc}") from exc
        if not resolved.is_dir():
            raise AppError(ErrorCode.BAD_REQUEST, "只能添加文件夹，不能添加单个文件")
        if resolved == self.project_root or resolved in self.project_root.parents:
            raise AppError(ErrorCode.BAD_REQUEST, "不能把程序目录（或它的上级目录）添加为项目")
        for blocked in (
            self.project_root / "data" / "uploads",
            self.project_root / "data" / "artifacts",
        ):
            if resolved == blocked:
                raise AppError(ErrorCode.BAD_REQUEST, "上传目录与产物目录不能作为项目")

        projects = self._load()
        if len(projects) >= MAX_PROJECTS:
            raise AppError(
                ErrorCode.BAD_REQUEST, f"最多添加 {MAX_PROJECTS} 个项目，先移除不用的再试"
            )
        if any(_norm(Path(item["path"])) == _norm(resolved) for item in projects):
            raise AppError(ErrorCode.CONFLICT, "这个文件夹已经在项目列表里了")

        project = {
            "id": new_id("prj"),
            "name": (name or "").strip() or resolved.name or str(resolved),
            "path": str(resolved),
            "created_at": now_iso(),
            "pinned": False,
        }
        projects.append(project)
        self._save(projects)
        return {**project, "file_count": len(self._scan(resolved)), "missing": False}

    def update(
        self,
        project_id: str,
        name: str | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any]:
        projects = self._load()
        for project in projects:
            if project["id"] != project_id:
                continue
            if name is not None:
                cleaned = name.strip()
                if not cleaned:
                    raise AppError(ErrorCode.BAD_REQUEST, "项目名不能为空")
                project["name"] = cleaned[:60]
            if pinned is not None:
                project["pinned"] = bool(pinned)
            self._save(projects)
            return self.get(project_id)
        raise AppError(ErrorCode.NOT_FOUND, f"项目不存在：{project_id}")

    def remove(self, project_id: str) -> dict[str, Any]:
        projects = self._load()
        kept = [item for item in projects if item["id"] != project_id]
        if len(kept) == len(projects):
            raise AppError(ErrorCode.NOT_FOUND, f"项目不存在：{project_id}")
        self._save(kept)
        return {"removed": True, "project_id": project_id}

    # ------------------------------------------------------------------ #
    # 运行接入
    # ------------------------------------------------------------------ #
    def staging_paths(
        self, project_id: str, rel_paths: list[str] | None = None
    ) -> tuple[dict[str, Any], list[Path]]:
        """取本次运行要带进素材的项目文件：只允许项目目录内的文档，且不超过上限。"""
        project = self.get(project_id)
        root = Path(project["path"])
        if not root.is_dir():
            raise AppError(ErrorCode.NOT_FOUND, "项目文件夹不存在了，请重新指定")
        if rel_paths:
            targets: list[Path] = []
            for rel in rel_paths[:MAX_STAGE_FILES]:
                candidate = (root / rel).resolve()
                if root.resolve() not in candidate.parents or not candidate.is_file():
                    continue
                if candidate.suffix.lower() not in DOC_EXTS:
                    continue
                targets.append(candidate)
            return project, targets
        files = self._scan(root, limit=MAX_STAGE_FILES)
        return project, [root / item["rel_path"] for item in files][:MAX_STAGE_FILES]


def _iso_from_ts(timestamp: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
