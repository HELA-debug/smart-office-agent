"""结构化日志：JSON 输出，自动带 trace_id / run_id（contextvars）。"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import datetime, timedelta, timezone
from typing import Any

TZ = timezone(timedelta(hours=8))

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
run_id_var: ContextVar[str] = ContextVar("run_id", default="")

_EXTRA_KEYS = (
    "event",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "thread_id",
    "run_id",
    "tool",
    "approval_id",
    "artifact_id",
    # 判据命中情况。排障时第一个要回答的是「哪句话被当成了指令」，
    # 混在 message 里只能全文检索，作为字段才能直接筛 `marker=直接生成`。
    "marker",
    "skip",
)


class JsonFormatter(logging.Formatter):
    """只输出可机读字段；异常堆栈放 exc_info 文本。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(TZ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "") or trace_id_var.get(),
            "run_id": getattr(record, "run_id", "") or run_id_var.get(),
        }
        for key in _EXTRA_KEYS:
            value = getattr(record, key, None)
            if value not in (None, ""):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        trace = getattr(record, "trace_id", "") or trace_id_var.get()
        run = getattr(record, "run_id", "") or run_id_var.get()
        base = (
            f"{datetime.now(TZ):%Y-%m-%d %H:%M:%S} {record.levelname:<5} "
            f"[{record.name}] trace={trace or '-'} run={run or '-'} {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 第三方噪声日志降级
    for noisy in ("httpx", "httpcore", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def bind_log_context(trace_id: str = "", run_id: str = "") -> tuple[Token[str], Token[str]]:
    """绑定当前请求/运行的 trace_id、run_id；配合 reset_log_context 使用。"""
    return trace_id_var.set(trace_id), run_id_var.set(run_id)


def reset_log_context(tokens: tuple[Token[str], Token[str]]) -> None:
    """恢复日志上下文；生成器可能在不同 Context 中收尾，重置失败则兜底清空。"""
    trace_token, run_token = tokens
    try:
        trace_id_var.reset(trace_token)
        run_id_var.reset(run_token)
    except ValueError:  # pragma: no cover - SSE 生成器跨 Context 收尾
        trace_id_var.set("")
        run_id_var.set("")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
