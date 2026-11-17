"""运行期根目录：把「只读资源」和「可写数据」分开。

源码运行（uvicorn / pytest / scripts/launch.py）时两者是同一个：仓库根目录。
打包成 exe（PyInstaller --onefile）后必须分开，否则会出现最难排的那种 bug：

  - 程序资源（前端 dist、提示词、技能、数据库迁移脚本）躺在 ``sys._MEIPASS``
    解压目录里，进程一退出就被删掉；
  - 用户数据（SQLite 库、上传文件、产物、模板、.env 里的模型 Key）如果也写到这里，
    表现是「今天用得好好的，明天打开全没了」——而且没有任何报错。

所以：

  RESOURCE_ROOT  打包后 = 解压目录（只读），源码态 = 仓库根
  DATA_ROOT      打包后 = %LOCALAPPDATA%\\Office Agent（可用 OA_DATA_DIR 覆盖），源码态 = 仓库根

打包态为什么不写 exe 同目录：exe 常被放到 Program Files、桌面或 U 盘，
没有写权限或换台机器就断，而用户数据应当跟着「这台电脑的这个用户」走。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 注意：这不只是「显示用的产品名」，它就是数据目录的名字。改一个字，程序下次就去
# 新目录里找库 / 上传 / 产物 / .env，老数据还在旧目录却像全丢了。真要改名，
# 必须同时写「旧目录 → 新目录」的迁移，并保留旧名的回退探测。
APP_NAME = "Office Agent"
DATA_DIR_ENV = "OA_DATA_DIR"


def is_frozen() -> bool:
    """全项目唯一的形态判断入口：PyInstaller / cx_Freeze 打包后为 True。

    写成函数而非常量，测试才能 monkeypatch ``sys.frozen`` 模拟打包态。
    业务代码一律调它；别各自去读 sys.frozen，也别拿下面的快照去判路径。
    """
    return bool(getattr(sys, "frozen", False))


# 导入时的快照，只为兼容旧引用保留（desktop / build_info 历史上用它判断
# 「这个进程是不是打包版」）。它不随 sys.frozen 变化，动态判断请用 is_frozen()。
IS_FROZEN = is_frozen()


def _source_root() -> Path:
    """backend/app/core/paths.py -> 仓库根（core -> app -> backend -> 根）。"""
    return Path(__file__).resolve().parents[3]


def _bundle_root() -> Path:
    """PyInstaller 解压目录（--onefile 每次启动解压，--onedir 固定目录）。

    cx_Freeze 也会置 sys.frozen，但没有 _MEIPASS；这时退回源码根，
    至少让程序能起来，而不是启动时就 AttributeError。
    """
    return Path(getattr(sys, "_MEIPASS", _source_root()))


def _user_data_dir() -> Path:
    """按平台挑一个「这台电脑归当前用户」的目录，不需要管理员权限。"""
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower().replace(" ", "-")


def resource_root() -> Path:
    """只读资源根：前端 dist、提示词、内置技能、迁移脚本。"""
    return _bundle_root() if is_frozen() else _source_root()


def data_root() -> Path:
    """可写数据根：数据库、上传、产物、模板、.env。"""
    if not is_frozen():
        # 源码态也允许 OA_DATA_DIR 覆盖：测试「数据落哪」不必真的打包一次
        override = os.environ.get(DATA_DIR_ENV, "").strip()
        return Path(override).expanduser() if override else _source_root()
    return _user_data_dir()


# 注意：这两个常量在模块导入时算一次，之后不再变，运行中途改环境变量不会重算。
# config.py 又把它们重导出成自己的模块级绑定，所以测试要 monkeypatch 的是
# app.core.config.DATA_ROOT（改 paths.DATA_ROOT 影响不到 config）。
# 想按当前环境重新算，直接调 data_root() / resource_root()。
RESOURCE_ROOT: Path = resource_root()
DATA_ROOT: Path = data_root()

__all__ = [
    "APP_NAME",
    "DATA_DIR_ENV",
    "DATA_ROOT",
    "IS_FROZEN",
    "RESOURCE_ROOT",
    "data_root",
    "is_frozen",
    "resource_root",
]
