"""领域实体（dataclass，与持久化实现解耦）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Thread:
    id: str
    title: str
    created_at: str
    updated_at: str
    pinned: bool = False
    # 用户拖出来的顺序（越小越前）；None 表示没手动排过，按最近更新排
    sort_index: float | None = None
    deleted_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    id: str
    thread_id: str
    role: str
    content: str
    created_at: str
    run_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    id: str
    thread_id: str
    status: str
    mode: str
    engine: str
    provider: str
    model: str
    started_at: str
    tokens: int = 0
    cost_cny: float = 0.0
    finished_at: str | None = None
    error_code: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunEventEntity:
    run_id: str
    seq: int
    event: str
    data: dict[str, Any]
    created_at: str
    id: int | None = None


@dataclass
class Approval:
    id: str
    thread_id: str
    run_id: str | None
    tool: str
    payload: dict[str, Any]
    created_at: str
    decision: str | None = None
    comment: str | None = None
    decided_at: str | None = None
    policy_version: str = "v1"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Artifact:
    id: str
    thread_id: str
    type: str
    filename: str
    path: str
    size: int
    sha256: str
    created_at: str
    run_id: str | None = None
    content_type: str = ""
    deleted_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SettingItem:
    key: str
    value: Any
    updated_at: str
    scope: str = "global"
    is_secret: bool = False


@dataclass
class ModelConfigEntity:
    id: str
    provider: str
    base_url: str
    model: str
    api_key_ref: str
    priority: int = 100
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadInfo:
    """上传素材的解析结果快照（供工具上下文使用）。"""

    artifact_id: str
    filename: str
    path: str
    ext: str
    chars: int
    text_path: str = ""
    parsed: bool = True
    #: 素材状态：ready 可用 / processing 识别中（OCR、转写）/ failed 识别失败
    status: str = "ready"
