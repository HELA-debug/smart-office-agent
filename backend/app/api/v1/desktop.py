"""桌面端安装包：存到本机、记住落盘路径、可再打开 / 重新安装。

为什么这件事归后端做：

浏览器下载完只会把文件丢进「下载」目录，页面拿不到真实路径（隐私限制），所以
「下载完告诉我文件在哪、下次还能从这儿找回」在纯前端做不到。这个产品的后端就跑在
用户本机，于是把这一步交给它：复制安装包到目标目录 → 记下绝对路径 → 之后按这个
路径复制、在资源管理器里定位、或直接拉起安装程序。

状态落在 `data/desktop_package.json`（与数据库、上传目录同级），所以刷新页面、
关掉重开都还在；只有「真的存成功」才写，失败或没选目录就留空——宁可没有，也不要
指着一个不存在的路径让人白找。

安全边界：只有 reveal / open 两个动作会碰本机，而它们只认**这份记录里的路径**，
不接受前端传任意路径过来，避免变成「随便打开一个文件」的入口。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core.paths import RESOURCE_ROOT, is_frozen
from ...core.utils import now_iso
from ..deps import ContainerDep

router = APIRouter(tags=["desktop"])

PACKAGE_ENV = "OA_DESKTOP_PACKAGE"
"""显式指定安装包源文件（CI / 内网分发时用），优先于自动探测。"""

DOWNLOAD_DIR_ENV = "OA_DOWNLOAD_DIR"
"""覆盖默认保存目录（测试与「下载目录在别处」的用户）。"""

STATE_NAME = "desktop_package.json"

MAX_DIR_LEN = 500


# ----------------------------------------------------------------------
# 模型
# ----------------------------------------------------------------------


class DesktopSavedOut(BaseModel):
    """一次成功保存的记录（读取时现算文件是否还在）。"""

    path: str = Field(description="保存完成时的绝对路径")
    filename: str = Field(description="文件名")
    size: int = Field(description="字节数")
    saved_at: str = Field(description="保存时间（ISO 8601）")
    exists: bool = Field(description="此刻文件是否还在；被删 / 被移走为 false")
    dir_exists: bool = Field(description="所在目录是否还在")
    error: str | None = Field(default=None, description="exists=false 时的原因说明")


class DesktopPackageOut(BaseModel):
    trace_id: str
    available: bool = Field(description="服务端有没有可交付的安装包")
    filename: str = Field(description="交付时的文件名")
    size: int = Field(description="安装包字节数；没有则为 0")
    platform: str = Field(description="windows / macos / linux")
    default_dir: str = Field(description="不指定目录时的默认保存位置（系统下载目录）")
    saved: DesktopSavedOut | None = Field(default=None, description="上次成功保存的记录")


class DesktopDownloadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_dir: str | None = Field(
        default=None,
        max_length=MAX_DIR_LEN,
        description="保存目录的绝对路径；空表示系统下载目录",
    )


class DesktopDownloadOut(BaseModel):
    trace_id: str
    ok: bool
    path: str | None = Field(default=None, description="成功时的绝对路径")
    saved: DesktopSavedOut | None = None
    error: str | None = None


class DesktopActionOut(BaseModel):
    trace_id: str
    ok: bool
    path: str | None = None
    exists: bool = Field(default=False, description="动作前文件是否还在")
    error: str | None = None


# ----------------------------------------------------------------------
# 安装包来源 / 保存目录
# ----------------------------------------------------------------------


def installer_names() -> tuple[str, ...]:
    """当前平台认的安装包文件名。"""
    if os.name == "nt":
        return ("Office Agent.exe",)
    if sys.platform == "darwin":
        return ("Office Agent.dmg", "Office Agent.pkg")
    return ("Office Agent.AppImage", "Office Agent.deb")


def local_package() -> Path | None:
    """能找到的安装包源文件；找不到返回 None（前端退回旧的下载链接方式）。"""
    raw = os.environ.get(PACKAGE_ENV, "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate
    if is_frozen():
        # 打包版自己就是那个可执行文件：把它复制一份到下载目录，等于「留个备份」，
        # 用户删了桌面快捷方式还能从下载目录里重新拿出来
        exe = Path(sys.executable)
        if exe.is_file():
            return exe
        return None
    for name in installer_names():
        candidate = RESOURCE_ROOT / "dist" / name
        if candidate.is_file():
            return candidate
    return None


def default_download_dir() -> Path:
    """系统下载目录；没有就退回主目录（至少是个能写入的地方）。"""
    override = os.environ.get(DOWNLOAD_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    home = Path.home()
    for name in ("Downloads", "下载", "Downloads ", "Téléchargements"):
        candidate = home / name
        if candidate.is_dir():
            return candidate
    return home


def platform_name() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def resolve_target_dir(raw: str | None) -> tuple[Path | None, str | None]:
    """把前端给的目录收成可用目录；不可用时连原因一起返回。"""
    text = (raw or "").strip()
    if not text:
        target = default_download_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, f"下载目录不可用：{exc.strerror or exc}"
        return target, None
    target = Path(text).expanduser()
    if not target.is_absolute():
        return None, "请给绝对路径"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, f"这个目录用不了：{exc.strerror or exc}"
    if not target.is_dir():
        return None, "这个位置不是文件夹"
    if not os.access(target, os.W_OK):
        return None, "这个目录没有写入权限"
    return target, None


# ----------------------------------------------------------------------
# 状态读写（失败即留空）
# ----------------------------------------------------------------------


def state_file(settings: Any) -> Path:
    """记录文件与数据库、上传目录同级，跟着用户数据一起走。"""
    return Path(settings.upload_dir).parent / STATE_NAME


def read_state(settings: Any) -> dict[str, Any] | None:
    path = state_file(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not str(payload.get("path") or "").strip():
        return None
    return payload


def write_state(settings: Any, path: Path, size: int) -> dict[str, Any]:
    """先写临时文件再替换，避免进程被杀时留下半个 JSON 让下次启动读不出来。"""
    payload = {
        "path": str(path),
        "filename": path.name,
        "size": size,
        "saved_at": now_iso(),
    }
    target = state_file(settings)
    tmp = target.with_suffix(".json.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        # 记不下来不算下载失败：文件确实存好了，只是下次打不开这段记忆
        tmp.unlink(missing_ok=True)
    return payload


def clear_state(settings: Any) -> None:
    """下载失败 / 没选目录 → 清空记录，界面就不会指着一个不存在的路径。"""
    with contextlib.suppress(OSError):
        state_file(settings).unlink(missing_ok=True)


def saved_payload(record: dict[str, Any]) -> dict[str, Any]:
    """把磁盘记录变成带「此刻还在不在」的响应。"""
    raw = str(record.get("path") or "")
    path = Path(raw)
    exists = False
    dir_exists = False
    error: str | None = None
    try:
        exists = path.is_file()
        dir_exists = path.parent.is_dir()
    except OSError as exc:
        error = f"读不到这个路径：{exc.strerror or exc}"
    if not exists and error is None:
        error = (
            "文件已经不在这个位置了（可能被删除或移动）"
            if dir_exists
            else "连所在文件夹都不在了（目录被删除或盘符断开）"
        )
    return {
        "path": raw,
        "filename": str(record.get("filename") or path.name),
        "size": int(record.get("size") or 0),
        "saved_at": str(record.get("saved_at") or ""),
        "exists": exists,
        "dir_exists": dir_exists,
        "error": error,
    }


# ----------------------------------------------------------------------
# 本机动作
# ----------------------------------------------------------------------


def deliver(src: Path, dest: Path) -> str | None:
    """把安装包复制到目标位置；成功返回 None，失败返回原因。"""
    try:
        if dest.exists() and dest.resolve() == src.resolve():
            return None  # 源和目标是同一个文件（用户就选了这个目录），不用动
        if dest.is_file() and dest.stat().st_size == src.stat().st_size:
            return None  # 已经有一份一样大的，别为了「下载」再写 38MB
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    except OSError as exc:
        return f"保存失败：{exc.strerror or exc}"
    return None


def open_in_file_manager(path: Path) -> tuple[bool, str | None]:
    """在系统文件管理器里定位这个文件（文件没了就把目录打开）。"""
    target = path
    if not target.exists():
        parent = path.parent
        if not parent.is_dir():
            return False, "这个位置已经不在了"
        target = parent
    try:
        if os.name == "nt":
            if target.is_dir():
                startfile = getattr(os, "startfile", None)
                if startfile is None:
                    return False, "当前平台不支持打开文件夹"
                startfile(str(target))
            else:
                subprocess.Popen(["explorer", "/select,", str(target)])  # noqa: S603, S607
        elif sys.platform == "darwin":
            args = ["open", "-R", str(target)] if target.is_file() else ["open", str(target)]
            subprocess.Popen(args)  # noqa: S603 - 固定命令 + 本地路径
        else:
            subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])  # noqa: S603, S607
    except Exception as exc:  # 任何失败都回给界面，别让接口 500
        return False, str(exc)
    return True, None


def launch(path: Path) -> tuple[bool, str | None]:
    """跑起安装包 / 程序本身（重新安装、或直接打开桌面端）。"""
    if not path.is_file():
        return False, "安装包不在了，先重新下载一份"
    try:
        if os.name == "nt":
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                return False, "当前平台不支持直接打开"
            startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603, S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607
    except Exception as exc:
        return False, str(exc)
    return True, None


# ----------------------------------------------------------------------
# 接口
# ----------------------------------------------------------------------


def _base_payload(settings: Any) -> dict[str, Any]:
    package = local_package()
    record = read_state(settings)
    return {
        "available": package is not None,
        "filename": package.name if package else installer_names()[0],
        "size": package.stat().st_size if package else 0,
        "platform": platform_name(),
        "default_dir": str(default_download_dir()),
        "saved": saved_payload(record) if record else None,
    }


@router.get(
    "/desktop/package",
    summary="桌面端安装包：可交付状态 + 上次保存的位置",
    responses={200: {"description": "available=false 表示服务端没有安装包，前端退回下载链接"}},
)
async def get_desktop_package(request: Request, container: ContainerDep) -> DesktopPackageOut:
    payload = _base_payload(container.settings_service.settings)
    return DesktopPackageOut(trace_id=request.state.trace_id, **payload)


@router.post(
    "/desktop/package/download",
    summary="把桌面端安装包保存到本机（默认系统下载目录）",
    responses={200: {"description": "ok=false + error 表示没存成，记录会被清空"}},
)
async def download_desktop_package(
    request: Request, body: DesktopDownloadIn, container: ContainerDep
) -> DesktopDownloadOut:
    settings = container.settings_service.settings
    package = local_package()
    if package is None:
        return DesktopDownloadOut(
            trace_id=request.state.trace_id,
            ok=False,
            error="这个服务端没有可直接交付的安装包",
        )
    target_dir, dir_error = resolve_target_dir(body.target_dir)
    if target_dir is None:
        # 目录不可用 = 没存成：不留旧记录，免得界面还指着上一份
        clear_state(settings)
        return DesktopDownloadOut(
            trace_id=request.state.trace_id,
            ok=False,
            error=dir_error,
        )
    dest = target_dir / package.name
    copy_error = deliver(package, dest)
    if copy_error:
        clear_state(settings)
        return DesktopDownloadOut(
            trace_id=request.state.trace_id,
            ok=False,
            error=copy_error,
        )
    record = write_state(settings, dest, dest.stat().st_size)
    return DesktopDownloadOut(
        trace_id=request.state.trace_id,
        ok=True,
        path=str(dest),
        saved=DesktopSavedOut(**saved_payload(record)),
    )


@router.post(
    "/desktop/package/reveal",
    summary="在文件管理器中定位已保存的安装包",
)
async def reveal_desktop_package(request: Request, container: ContainerDep) -> DesktopActionOut:
    record = read_state(container.settings_service.settings)
    if record is None:
        return DesktopActionOut(
            trace_id=request.state.trace_id, ok=False, error="还没有保存过安装包"
        )
    path = Path(str(record.get("path") or ""))
    opened, error = open_in_file_manager(path)
    return DesktopActionOut(
        trace_id=request.state.trace_id,
        ok=opened,
        path=str(path),
        exists=path.is_file(),
        error=error,
    )


@router.post(
    "/desktop/package/open",
    summary="打开已保存的安装包（重新安装 / 再次启动桌面端）",
)
async def open_desktop_package(request: Request, container: ContainerDep) -> DesktopActionOut:
    record = read_state(container.settings_service.settings)
    if record is None:
        return DesktopActionOut(
            trace_id=request.state.trace_id, ok=False, error="还没有保存过安装包"
        )
    path = Path(str(record.get("path") or ""))
    started, error = launch(path)
    return DesktopActionOut(
        trace_id=request.state.trace_id,
        ok=started,
        path=str(path),
        exists=path.is_file(),
        error=error,
    )
