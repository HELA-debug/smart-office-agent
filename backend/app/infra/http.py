"""统一 HTTP 客户端工厂。

Windows 本机环境坑：NO_PROXY 中含 `[::1]` 时，httpx 在 trust_env=True 下会抛
`InvalidURL: Invalid port: ':1]'`。因此所有外部调用（模型 / IMAP / 其它）都用本工厂：
`trust_env=False` + 显式 proxy=HTTPS_PROXY，避免读取系统代理环境变量。
"""

from __future__ import annotations

import os

import httpx

from ..core.config import Settings

_PROXY_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def resolve_proxy(settings: Settings) -> str | None:
    """优先 Settings（.env / env），其次进程环境；值非法时返回 None。"""
    candidates = [settings.https_proxy, settings.http_proxy]
    candidates += [os.environ.get(key, "") for key in _PROXY_ENV_KEYS]
    for value in candidates:
        value = (value or "").strip()
        if value.lower().startswith(("http://", "https://")):
            return value
    return None


def build_http_client(
    settings: Settings,
    *,
    timeout: float | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        trust_env=False,
        proxy=resolve_proxy(settings),
        timeout=httpx.Timeout(timeout or settings.model_timeout_seconds, connect=5.0),
        headers={"User-Agent": "office-agent-backend/0.2"},
    )


def sanitize_no_proxy_env() -> None:
    """删除 NO_PROXY 中带方括号的 IPv6 项（Windows 环境常见的 httpx 崩溃源）。

    只影响本进程 os.environ，不写回系统设置。
    """
    for key in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(key)
        if not raw:
            continue
        kept = [item for item in raw.split(",") if "[" not in item and "]" not in item]
        os.environ[key] = ",".join(kept)
