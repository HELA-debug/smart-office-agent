"""领域枚举（与接口错误码、事件名、状态机一致）。"""

from __future__ import annotations

from enum import StrEnum


class Risk(StrEnum):
    LOW = "low"
    HIGH = "high"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Decision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    RUN_SUMMARY = "run_summary"
    SYSTEM = "system"


class ArtifactType(StrEnum):
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"
    XLSX = "xlsx"
    PPTX = "pptx"
    UPLOAD = "upload"


class EngineKind(StrEnum):
    MOCK = "mock"
    REAL = "real"


class EventName(StrEnum):
    RUN_STARTED = "run.started"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    PLAN_UPDATED = "plan.updated"
    TOOL_STARTED = "tool.started"
    TOOL_FINISHED = "tool.finished"
    APPROVAL_REQUIRED = "approval.required"
    ARTIFACT_READY = "artifact.ready"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    HEARTBEAT = "heartbeat"


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    APPROVAL_ALREADY_DECIDED = "APPROVAL_ALREADY_DECIDED"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_PARSE_ERROR = "FILE_PARSE_ERROR"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    TOOL_ERROR = "TOOL_ERROR"
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
    INTERNAL = "INTERNAL"
