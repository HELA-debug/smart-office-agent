"""通用工具：时间/ID/文本/进程信息。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import PROJECT_ROOT
from .paths import RESOURCE_ROOT, is_frozen

TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def now_dt() -> datetime:
    return datetime.now(TZ)


def new_id(prefix: str) -> str:
    if prefix == "r":
        return f"r_{datetime.now(TZ):%Y%m%d}_{uuid.uuid4().hex[:6]}"
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_chars(text: str) -> int:
    return len(re.sub(r"\s", "", text or ""))


def week_label(dt: datetime | None = None) -> str:
    dt = dt or now_dt()
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


DEFAULT_THREAD_TITLES = {
    "",
    "新的会话",
    "新会话",
    "未命名会话",
    "未命名",
    "new chat",
    "new conversation",
}


def is_default_thread_title(title: str | None) -> bool:
    return (title or "").strip().lower() in DEFAULT_THREAD_TITLES


_POLITE_PREFIXES = (
    "麻烦你帮我",
    "麻烦帮我",
    "帮我一下",
    "请帮我",
    "能不能帮我",
    "可以帮我",
    "帮我",
    "麻烦",
    "请你",
    "请",
    "我想让你",
    "我想",
    "帮忙",
)


def derive_thread_title(message: str, limit: int = 24) -> str:
    """规则式标题：去掉客套前缀与结尾标点，压成一行（模型可用时会再优化）。"""
    text = re.sub(r"\s+", " ", message or "").strip()
    if not text:
        return ""
    for prefix in _POLITE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].lstrip("，,、 ")
            break
    # 先削标点再去空白：中文句末常常是「空格 + 感叹号」，只削一次会留下尾空格
    text = text.strip().strip("。！？!?，,；;：:").strip()
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "…"


def read_build_info() -> dict[str, str]:
    """读取打包时写进去的构建信息（packaging/office_agent.spec 生成 build_info.json）。

    源码态没有这个文件，返回空字典。读不到就返回空，不让「版本号显示不出来」变成启动错误。
    """
    try:
        raw = (RESOURCE_ROOT / "build_info.json").read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}


def detect_git_sha() -> str:
    """读取当前 commit（只读，失败返回空串）。

    打包版里没有仓库，改用打包时写进 build_info.json 的 sha：界面「设置 → 关于」要靠它
    判断「跑的是哪一版」，空着就失去意义了。别为了这个字段去 fork git（onefile 启动本来就慢）。
    """
    if is_frozen():
        return read_build_info().get("git_sha", "")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - 只读调用，git 由 PATH 提供
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - 环境差异
        return ""
