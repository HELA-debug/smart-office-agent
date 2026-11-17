"""事件契约 v1.4（只追加）：事件名、data 构造、SSE 帧、JSON Schema。

v1 的 8 类事件语义不变；v1.1 追加 run.cancelled / tool.started / heartbeat；
v1.2 追加 thinking.delta / thinking.completed（思考过程流，先于 message.* 下发）；
v1.3 给 message.* 追加可选字段 `channel`（reply=对话里的正式回复，缺省值；
process=中间旁白，前端收进「执行过程」而不再单独起一个气泡）；
v1.4 追加 context.compacted（更早的轮次被挤出上下文窗口并折叠成摘要时的通报帧）。
每帧 data 必带 version 与 run_id；SSE 帧 id 与 run_events.seq 一致。
"""

from __future__ import annotations

import json
from typing import Any

EVENT_VERSION = 1

RUN_STARTED = "run.started"
MESSAGE_DELTA = "message.delta"
MESSAGE_COMPLETED = "message.completed"
THINKING_DELTA = "thinking.delta"
THINKING_COMPLETED = "thinking.completed"
PLAN_UPDATED = "plan.updated"
TOOL_STARTED = "tool.started"
TOOL_FINISHED = "tool.finished"
APPROVAL_REQUIRED = "approval.required"
ARTIFACT_READY = "artifact.ready"
RUN_COMPLETED = "run.completed"
RUN_FAILED = "run.failed"
RUN_CANCELLED = "run.cancelled"
HEARTBEAT = "heartbeat"
# v1.4：上下文被压缩（更早的轮次被挤出窗口并折叠成摘要）。只追加，前端可忽略。
CONTEXT_COMPACTED = "context.compacted"

EVENT_NAMES: tuple[str, ...] = (
    RUN_STARTED,
    MESSAGE_DELTA,
    MESSAGE_COMPLETED,
    THINKING_DELTA,
    THINKING_COMPLETED,
    PLAN_UPDATED,
    TOOL_STARTED,
    TOOL_FINISHED,
    APPROVAL_REQUIRED,
    ARTIFACT_READY,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_CANCELLED,
    HEARTBEAT,
    CONTEXT_COMPACTED,
)

TERMINAL_EVENTS = frozenset({RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED})

# 各事件 data 的必填业务字段（version/run_id 由 build_event 保证）
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    RUN_STARTED: ("thread_id", "mode", "model", "started_at"),
    MESSAGE_DELTA: ("message_id", "delta", "index"),
    MESSAGE_COMPLETED: ("message_id", "content"),
    THINKING_DELTA: ("message_id", "delta", "index"),
    THINKING_COMPLETED: ("message_id", "content"),
    PLAN_UPDATED: ("todos",),
    TOOL_STARTED: ("tool",),
    TOOL_FINISHED: ("tool", "ok", "risk", "summary", "duration_ms", "input", "output"),
    APPROVAL_REQUIRED: ("approval_id", "tool", "risk", "message", "preview"),
    ARTIFACT_READY: (
        "artifact_id",
        "type",
        "filename",
        "size",
        "download_url",
        "preview_url",
    ),
    RUN_COMPLETED: (
        "status",
        "tokens",
        "cost_cny",
        "elapsed_ms",
        "artifact_ids",
        "approvals",
    ),
    RUN_FAILED: ("error",),
    RUN_CANCELLED: ("reason",),
    HEARTBEAT: (),
    CONTEXT_COMPACTED: ("turns_total", "kept_turns", "dropped_turns", "summary_chars"),
}

# 契约测试用的 JSON Schema（只校验公共骨架 + 类型，不追求完备）
EVENT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "RunEventData",
    "type": "object",
    "required": ["version", "run_id"],
    "properties": {
        "version": {"const": EVENT_VERSION},
        "run_id": {"type": "string", "minLength": 1},
        "trace_id": {"type": "string"},
    },
    "additionalProperties": True,
}


def build_event(run_id: str, event: str, **data: Any) -> dict[str, Any]:
    """构造事件 data（不允许覆盖 version/run_id）。"""
    payload: dict[str, Any] = {"version": EVENT_VERSION, "run_id": run_id}
    payload.update(data)
    return payload


def validate_event_data(event: str, data: dict[str, Any]) -> list[str]:
    """返回缺失/非法字段列表，供契约测试与运行期自检使用。"""
    problems: list[str] = []
    if data.get("version") != EVENT_VERSION:
        problems.append("version")
    if not data.get("run_id"):
        problems.append("run_id")
    for field in REQUIRED_FIELDS.get(event, ()):
        if field not in data:
            problems.append(field)
    return problems


def sse_frame(seq: int, event: str, data: dict[str, Any]) -> str:
    """SSE 帧：id / event / data(单行 JSON) + 空行。"""
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {event}\ndata: {body}\n\n"


def sse_comment(text: str = "ping") -> str:
    return f": {text}\n\n"


def parse_last_event_id(value: str | None) -> int | None:
    """解析 Last-Event-ID 头（非数字返回 None）。"""
    if not value:
        return None
    try:
        return max(0, int(value.strip()))
    except ValueError:
        return None
