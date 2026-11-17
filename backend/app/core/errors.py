"""统一错误体：{"trace_id", "error": {"code", "message", "details"}}。

所有可预期错误用 AppError 抛出；HTTP 层统一注册处理器（见 api 层 wiring）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger

logger = get_logger("app.errors")


# 错误码目录（OpenAPI 描述与前端错误提示共用；新增错误码请同步 main.py 的 API 描述）
ERROR_CODE_CATALOG: dict[str, str] = {
    "BAD_REQUEST": "参数缺失或格式错误",
    "NOT_FOUND": "会话/运行/审批/产物/模板/技能不存在",
    "CONFLICT": "资源冲突（如模板 ID 重复）",
    "APPROVAL_ALREADY_DECIDED": "审批已处理、已超时或已随运行取消",
    "UNSUPPORTED_FILE_TYPE": "上传扩展名/MIME/magic bytes 校验失败",
    "FILE_PARSE_ERROR": "文件解析失败或内容为空",
    "PAYLOAD_TOO_LARGE": "上传文件超过大小限制",
    "MODEL_TIMEOUT": "模型调用超时",
    "MODEL_RATE_LIMIT": "模型限流",
    "TOOL_ERROR": "工具执行失败（运行不中断）",
    "APPROVAL_TIMEOUT": "审批超时导致运行终止",
    "UNAUTHORIZED": "缺少或错误的 API Token（X-API-Token）",
    "INTERNAL": "未预期内部错误",
}


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    APPROVAL_ALREADY_DECIDED = "APPROVAL_ALREADY_DECIDED"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_PARSE_ERROR = "FILE_PARSE_ERROR"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    TOOL_ERROR = "TOOL_ERROR"
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL = "INTERNAL"


_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.APPROVAL_ALREADY_DECIDED: 409,
    ErrorCode.UNSUPPORTED_FILE_TYPE: 415,
    ErrorCode.FILE_PARSE_ERROR: 422,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.MODEL_TIMEOUT: 504,
    ErrorCode.MODEL_RATE_LIMIT: 429,
    ErrorCode.APPROVAL_TIMEOUT: 504,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.TOOL_ERROR: 500,
    ErrorCode.INTERNAL: 500,
}

_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.BAD_REQUEST,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_FILE_TYPE,
    422: ErrorCode.FILE_PARSE_ERROR,
    429: ErrorCode.MODEL_RATE_LIMIT,
    500: ErrorCode.INTERNAL,
    504: ErrorCode.MODEL_TIMEOUT,
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        details: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code or _STATUS_BY_CODE.get(code, 500)
        self.details = details


def error_body(trace_id: str, code: ErrorCode, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "trace_id": trace_id,
        "error": {"code": code.value, "message": message},
    }
    if details is not None:
        body["error"]["details"] = details
    return body


def _trace(request: Request) -> str:
    return str(getattr(request.state, "trace_id", "") or "")


def _jsonable(value: Any) -> Any:
    """把校验错误里的任意对象转成可 JSON 序列化的形态。

    FastAPI 的 `RequestValidationError.errors()` 会带两类不可序列化的东西：
    - `input`：请求体解析失败时是原始 bytes；
    - `ctx.error`：pydantic 塞进去的异常实例。
    直接 json.dumps 会抛 TypeError，把本该 400 的请求变成 500。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            error_body(_trace(request), exc.code, exc.message, exc.details),
            status_code=exc.status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.BAD_REQUEST)
        return JSONResponse(
            error_body(_trace(request), code, str(exc.detail)),
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            error_body(
                _trace(request),
                ErrorCode.BAD_REQUEST,
                "参数校验失败",
                details=_jsonable(exc.errors()[:3]),
            ),
            status_code=400,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "未处理异常",
            extra={"event": "unhandled_error", "trace_id": _trace(request)},
        )
        return JSONResponse(
            error_body(_trace(request), ErrorCode.INTERNAL, "服务内部错误"),
            status_code=500,
        )
