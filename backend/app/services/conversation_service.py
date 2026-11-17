"""对话消息处理：一轮请求进入引擎前的规范化、附件归属与上下文装配。

## 改造前的问题

`RunService.start()` 把三件事糊在一起：取素材、拼提示词、写消息。三个后果：

1. **附件不按轮归属**：`_uploads(thread_id)` 把会话里所有上传都塞给每一轮，
   第二轮起模型会看到一堆跟当前请求无关的旧素材，越用越吵；
2. **消息没有快照**：`message.extra` 一直是空的，谈不上「这条消息当时带了哪些附件」，
   重试（retry）只能拿到文本，附件全丢；
3. **上下文注入没有落点**：想加历史，只能继续往 `start()` 里堆。

这里把「一轮请求」变成显式的数据对象（`PreparedTurn`），`RunService` 只负责编排运行，
附件解析 / 消息落库 / 上下文计划都收在这一层，可单独测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agents.context_window import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_TURN_CHARS,
    DEFAULT_MAX_TURNS,
    DEFAULT_SUMMARY_CHARS,
    ContextPlan,
    plan_from_messages,
)
from ..core.config import Settings
from ..core.utils import new_id, now_iso
from ..domain.entities import Message, UploadInfo
from ..domain.enums import MessageRole
from ..domain.ports import ArtifactRepository, MessageRepository

MAX_MESSAGE_CHARS = 20_000


def normalize_message(text: str) -> str:
    """规范化用户输入：去首尾空白、压掉连续空行、超长截断。

    只做「形状」上的整理，不改写内容 —— 用户写的代码块、缩进必须原样保留。
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in raw.split("\n")]
    normalized: list[str] = []
    for line in lines:
        if not line and normalized and normalized[-1] == "":
            continue
        normalized.append(line)
    text = "\n".join(normalized).strip()
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS] + "\n…（消息过长已截断）"
    return text


@dataclass(frozen=True)
class PreparedTurn:
    """一轮请求的完整入参（尚未落库、尚未发起运行）。"""

    thread_id: str
    message: str
    uploads: list[UploadInfo] = field(default_factory=list)
    plan: ContextPlan = field(default_factory=ContextPlan)
    message_id: str = ""

    def uploads_snapshot(self) -> list[dict[str, Any]]:
        """写进 `message.extra.uploads` 的快照（对齐文档 §3.4：附件属于消息）。"""
        return [
            {
                "artifact_id": item.artifact_id,
                "filename": item.filename,
                "ext": item.ext,
                "chars": item.chars,
                "parsed": item.parsed,
            }
            for item in self.uploads
        ]


class ConversationService:
    def __init__(
        self,
        settings: Settings,
        messages: MessageRepository,
        artifacts: ArtifactRepository,
    ) -> None:
        self.settings = settings
        self.messages = messages
        self.artifacts = artifacts

    # ---------- 附件 ----------
    def uploads_for(
        self, thread_id: str, attachment_ids: list[str] | None = None
    ) -> list[UploadInfo]:
        """本轮可用素材。

        显式传 `attachment_ids` 就只认这几个（文档 §3.4「运行只使用本次 attachment_ids」）；
        没传则回落到「会话内全部上传」—— 兼容老前端与 curl 用法，行为与改造前一致。
        """
        wanted = {item for item in (attachment_ids or []) if item}
        uploads: list[UploadInfo] = []
        for artifact in self.artifacts.list(thread_id=thread_id, type="upload"):
            if wanted and artifact.id not in wanted:
                continue
            extra = artifact.extra or {}
            media = extra.get("media") or {}
            uploads.append(
                UploadInfo(
                    artifact_id=artifact.id,
                    filename=artifact.filename,
                    path=artifact.path,
                    ext=str(extra.get("ext", "")),
                    chars=int(extra.get("chars", 0)),
                    text_path=str(extra.get("text_path", "")),
                    parsed=bool(extra.get("parsed", False)),
                    status=str(
                        media.get("status") or ("ready" if extra.get("parsed") else "failed")
                    ),
                )
            )
        return uploads

    def missing_attachments(self, thread_id: str, attachment_ids: list[str] | None) -> list[str]:
        """请求里点名了、但不在该会话素材里的 id（用于提前给 400，而不是静默丢掉）。"""
        if not attachment_ids:
            return []
        known = {item.artifact_id for item in self.uploads_for(thread_id)}
        return [item for item in attachment_ids if item and item not in known]

    # ---------- 消息 ----------
    def prepare(
        self,
        thread_id: str,
        message: str,
        *,
        attachment_ids: list[str] | None = None,
        exclude_message_ids: tuple[str, ...] = (),
    ) -> PreparedTurn:
        """规范化消息 + 解析附件 + 生成上下文计划（此时用户消息还没落库）。"""
        text = normalize_message(message)
        uploads = self.uploads_for(thread_id, attachment_ids)
        plan = plan_from_messages(
            self.messages.list_by_thread(thread_id, include_run_summary=False),
            max_turns=int(getattr(self.settings, "context_max_turns", DEFAULT_MAX_TURNS)),
            max_chars=int(getattr(self.settings, "context_max_chars", DEFAULT_MAX_CHARS)),
            max_turn_chars=int(
                getattr(self.settings, "context_max_turn_chars", DEFAULT_MAX_TURN_CHARS)
            ),
            summary_chars=int(
                getattr(self.settings, "context_summary_chars", DEFAULT_SUMMARY_CHARS)
            ),
            exclude_message_ids=exclude_message_ids,
        )
        return PreparedTurn(
            thread_id=thread_id,
            message=text,
            uploads=uploads,
            plan=plan,
            message_id=new_id("m"),
        )

    def record_user(
        self, turn: PreparedTurn, run_id: str, *, attachment_ids: list[str] | None = None
    ) -> Message:
        """落库用户消息，并把本轮附件快照写进 `extra`（重试/审计都靠它还原现场）。"""
        message = Message(
            id=turn.message_id or new_id("m"),
            thread_id=turn.thread_id,
            role=MessageRole.USER.value,
            content=turn.message,
            run_id=run_id,
            created_at=now_iso(),
            extra={
                "uploads": turn.uploads_snapshot(),
                "attachment_ids": [item.artifact_id for item in turn.uploads]
                if attachment_ids is None
                else list(attachment_ids),
            },
        )
        return self.messages.add(message)

    def attachments_of_run(self, run_id: str, thread_id: str) -> list[str]:
        """某次运行的用户消息当时带的附件 id（重试时原样带上，而不是全量重来）。"""
        for message in reversed(self.messages.list_by_thread(thread_id)):
            if message.run_id != run_id or message.role != MessageRole.USER.value:
                continue
            ids = (message.extra or {}).get("attachment_ids")
            if isinstance(ids, list):
                return [str(item) for item in ids if item]
            snapshot = (message.extra or {}).get("uploads")
            if isinstance(snapshot, list):
                return [
                    str(item.get("artifact_id"))
                    for item in snapshot
                    if isinstance(item, dict) and item.get("artifact_id")
                ]
            return []
        return []
