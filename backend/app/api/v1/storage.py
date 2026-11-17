"""本机存储目录：给设置页返回绝对路径，并支持在系统文件管理器里打开。

为什么需要「打开目录」这个接口：
设置页原本只把 `./data/uploads` 这种相对路径当字符串显示，用户点了没反应、也不知道文件到底
落在哪。这里把服务端真实解析出来的绝对路径返回给前端，并提供一次性打开动作（只允许
uploads / artifacts 两个固定目录，不接受任意路径，避免变成任意文件系统访问入口）。
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core.config import Settings
from ..deps import ContainerDep

router = APIRouter(tags=["storage"])

StorageKind = Literal["uploads", "artifacts"]


class StorageRevealIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: StorageKind = Field(description="uploads | artifacts")


class StorageSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: StorageKind = Field(description="uploads | artifacts")
    path: str | None = Field(
        default=None,
        max_length=500,
        description="新的绝对路径；传 null / 空字符串表示恢复默认目录",
    )


class StorageBrowseMkdirIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=500, description="在哪个目录下新建")
    name: str = Field(min_length=1, max_length=80, description="新文件夹名（不能含路径分隔符）")


def _dir_for(settings: Settings, kind: StorageKind) -> Path:
    return settings.uploads_path if kind == "uploads" else settings.artifacts_path


def _count_files(path: Path) -> int:
    try:
        return sum(1 for item in path.rglob("*") if item.is_file())
    except OSError:
        return 0


def _open_in_file_manager(path: Path) -> tuple[bool, str | None]:
    """在系统文件管理器里打开目录；打不开就返回原因，交给前端提示。"""
    try:
        if platform.system() == "Windows":
            startfile = getattr(os, "startfile", None)
            if startfile is None:  # 非 Windows 解释器上没有这个绑定
                return False, "当前平台不支持打开目录"
            startfile(str(path))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603, S607 - 固定命令 + 已校验路径
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607
    except Exception as exc:  # 任何失败都回给界面
        return False, str(exc)
    return True, None


MAX_BROWSE_ENTRIES = 300
"""目录浏览一次最多返回多少个子目录：用户目录里几百个子文件夹时别把界面撑爆。"""


def _roots() -> list[dict[str, str]]:
    """可选的「起点」：Windows 给盘符，其它平台给根目录 + 家目录。"""
    if platform.system() == "Windows":
        roots: list[dict[str, str]] = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
            candidate = Path(f"{letter}:\\")
            try:
                if candidate.exists():
                    roots.append({"name": f"{letter}:", "path": str(candidate)})
            except OSError:
                continue
        return roots
    return [
        {"name": "主目录", "path": str(Path.home())},
        {"name": "/", "path": "/"},
    ]


def _is_hidden_windows_dir(entry: Path) -> bool:
    """Windows 上的隐藏 / 系统目录：`Application Data` 这类其实是 junction，
    点进去会绕回同一个位置，选择器里没有意义，和资源管理器一样默认不显示。"""
    try:
        # 必须用 lstat：stat() 会跟到 target 上，junction 的 reparse 标记就丢了
        attrs = entry.lstat().st_file_attributes  # 只有 Windows 的 stat 结果带这个字段
    except (OSError, AttributeError):
        return False
    hidden = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2)
    system = getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0x4)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & (hidden | system | reparse))


def _subdirs(path: Path) -> tuple[list[dict[str, str]], str | None]:
    """列出直接子目录（不列文件）。读不了就返回原因，不抛 500。"""
    try:
        entries = list(path.iterdir())
    except OSError as exc:
        return [], f"这个文件夹打不开：{exc.strerror or exc}"
    dirs: list[dict[str, str]] = []
    for entry in entries:
        try:
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if platform.system() == "Windows" and _is_hidden_windows_dir(entry):
                continue
        except OSError:
            continue  # 没权限的目录直接跳过，别让整页挂掉
        dirs.append({"name": entry.name, "path": str(entry)})
        if len(dirs) >= MAX_BROWSE_ENTRIES:
            break
    dirs.sort(key=lambda item: item["name"].lower())
    return dirs, None


def _resolve_browse_dir(raw: str | None) -> Path:
    """空的 path 从家目录起步；给了但不存在时也退回最近一个可用的上级。"""
    if not raw or not raw.strip():
        return Path.home()
    candidate = Path(raw.strip()).expanduser()
    try:
        if candidate.is_dir():
            return candidate
        # 用户点了历史路径但目录被删了：往上找到第一个还存在的地方
        for parent in candidate.parents:
            if parent.is_dir():
                return parent
    except OSError:
        pass
    return Path.home()


@router.get(
    "/storage/browse",
    summary="浏览本机文件夹（目录选择器用，只列子目录不列文件）",
    responses={200: {"description": "当前目录、上级目录、子目录列表与可选起点"}},
)
async def browse_storage(
    request: Request,
    path: str | None = None,
) -> dict[str, Any]:
    target = _resolve_browse_dir(path)
    dirs, error = _subdirs(target)
    try:
        parent = target.parent
        parent_path = str(parent) if parent != target else None
    except OSError:
        parent_path = None
    return {
        "trace_id": request.state.trace_id,
        "path": str(target),
        "parent": parent_path,
        "dirs": dirs,
        "roots": _roots(),
        "error": error,
    }


@router.post(
    "/storage/browse/mkdir",
    summary="在指定目录下新建文件夹",
    responses={200: {"description": "ok=false + error 表示没建成（重名 / 无权限）"}},
)
async def make_storage_dir(request: Request, body: StorageBrowseMkdirIn) -> dict[str, Any]:
    name = body.name.strip()
    if not name or name in {".", ".."} or any(sep in name for sep in ("/", "\\")):
        return {
            "trace_id": request.state.trace_id,
            "ok": False,
            "error": "文件夹名不能为空，也不能包含 / 或 \\",
            "path": None,
        }
    target = _resolve_browse_dir(body.path) / name
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        return {
            "trace_id": request.state.trace_id,
            "ok": False,
            "error": "这个位置已经有同名文件夹了",
            "path": str(target),
        }
    except OSError as exc:
        return {
            "trace_id": request.state.trace_id,
            "ok": False,
            "error": f"新建失败：{exc.strerror or exc}",
            "path": None,
        }
    return {
        "trace_id": request.state.trace_id,
        "ok": True,
        "error": None,
        "path": str(target),
    }


@router.get(
    "/storage/paths",
    summary="本机存储目录（绝对路径 / 是否存在 / 文件数）",
)
async def get_storage_paths(request: Request, container: ContainerDep) -> dict[str, Any]:
    settings = container.settings_service.settings
    result: dict[str, Any] = {"trace_id": request.state.trace_id}
    for kind in ("uploads", "artifacts"):
        path = _dir_for(settings, kind)  # type: ignore[arg-type]
        result[kind] = {
            "path": str(path),
            "exists": path.exists(),
            "files": _count_files(path) if path.exists() else 0,
        }
    return result


@router.post(
    "/storage/reveal",
    summary="在系统文件管理器中打开存储目录",
    responses={200: {"description": "opened=true 表示已唤起文件管理器"}},
)
async def reveal_storage(
    request: Request, body: StorageRevealIn, container: ContainerDep
) -> dict[str, Any]:
    path = _dir_for(container.settings_service.settings, body.kind)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "trace_id": request.state.trace_id,
            "kind": body.kind,
            "path": str(path),
            "opened": False,
            "error": f"目录创建失败：{exc}",
        }
    opened, error = _open_in_file_manager(path)
    return {
        "trace_id": request.state.trace_id,
        "kind": body.kind,
        "path": str(path),
        "opened": opened,
        "error": error,
    }


@router.put(
    "/storage/paths",
    summary="修改存储目录（绝对路径；传空表示恢复默认）",
    responses={200: {"description": "返回修改后生效的目录与文件数"}},
)
async def set_storage_paths(
    request: Request, body: StorageSetIn, container: ContainerDep
) -> dict[str, Any]:
    settings = container.settings_service.settings
    raw = (body.path or "").strip()
    try:
        final = settings.set_storage_dir(body.kind, raw or None)
    except OSError as exc:
        return {
            "trace_id": request.state.trace_id,
            "kind": body.kind,
            "ok": False,
            "path": str(_dir_for(settings, body.kind)),
            "error": f"目录不可用：{exc}",
        }
    return {
        "trace_id": request.state.trace_id,
        "kind": body.kind,
        "ok": True,
        "path": str(final),
        "exists": final.exists(),
        "files": _count_files(final) if final.exists() else 0,
        "error": None,
    }
