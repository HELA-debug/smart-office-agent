"""可选 API Token 认证（纯 ASGI 中间件，默认关闭）。

设计：
- 未配置 API_TOKEN 时中间件透传，本地开发/CI 行为完全不变；
- 配了 API_TOKEN 后，除健康检查与根路由外全部请求必须带
  `X-API-Token: <token>`，否则返回统一错误体（401 UNAUTHORIZED）；
- 用纯 ASGI 而非 BaseHTTPMiddleware，避免缓冲 SSE 事件流；
- 比较用 hmac.compare_digest，防时序侧信道。

注意：这只是单用户桌面场景的兜底鉴权，不是多用户账号体系（V1.0 再做）。
生产部署仍建议只监听回环 + 走本机反向代理。
"""

from __future__ import annotations

import hmac
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..core.config import Settings
from ..core.errors import ErrorCode, error_body
from ..core.utils import new_id

TOKEN_HEADER = "X-API-Token"  # noqa: S105 - 这是请求头名，不是密钥

# 免鉴权路径：容器 healthcheck 与根路由探活需要无凭据访问
PUBLIC_PATHS: frozenset[str] = frozenset({"/", "/api/v1/health", "/api/health"})


def is_public_path(path: str) -> bool:
    """健康检查与根路由免鉴权。"""
    return path.rstrip("/") in PUBLIC_PATHS or path in PUBLIC_PATHS


def verify_token(provided: str | None, expected: str) -> bool:
    """常量时间比较；未配置期望值时视为「未启用鉴权」。"""
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def unauthorized(trace_id: str) -> JSONResponse:
    return JSONResponse(
        error_body(trace_id, ErrorCode.UNAUTHORIZED, f"缺少或错误的 {TOKEN_HEADER}"),
        status_code=401,
    )


class ApiTokenMiddleware:
    """配置 API_TOKEN 后生效；未配置时零开销透传。"""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.token = settings.api_token
        self.enabled = bool(settings.api_token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if not self.enabled or is_public_path(str(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return
        # CORS 预检不带业务头，交给 CORS 中间件处理
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        provided = Headers(scope=scope).get(TOKEN_HEADER)
        if verify_token(provided, self.token):
            await self.app(scope, receive, send)
            return
        state: dict[str, Any] = scope.get("state") or {}
        trace_id = str(state.get("trace_id") or "") or new_id("tr")
        response = unauthorized(trace_id)
        await response(scope, receive, send)


__all__ = [
    "PUBLIC_PATHS",
    "TOKEN_HEADER",
    "ApiTokenMiddleware",
    "is_public_path",
    "unauthorized",
    "verify_token",
]
