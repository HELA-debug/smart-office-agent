"""消息处理：规范化、附件归属单轮、附件快照、重试复原现场。

改造前 `_uploads(thread_id)` 把整会话的上传全塞给每一轮，`message.extra` 一直是空的，
重试只能拿回纯文本。这里逐条把新契约钉死。
"""

from __future__ import annotations

from app.core.config import Settings
from app.domain.entities import Artifact, Message
from app.services.conversation_service import (
    MAX_MESSAGE_CHARS,
    ConversationService,
    normalize_message,
)


class FakeMessages:
    def __init__(self, items: list[Message] | None = None) -> None:
        self.items = list(items or [])

    def add(self, message: Message) -> Message:
        self.items.append(message)
        return message

    def list_by_thread(self, thread_id: str, include_run_summary: bool = True) -> list[Message]:
        return [
            item
            for item in self.items
            if item.thread_id == thread_id and (include_run_summary or item.role != "run_summary")
        ]

    def count_by_thread(self, thread_id: str) -> int:
        return len([item for item in self.items if item.thread_id == thread_id])


class FakeArtifacts:
    def __init__(self, items: list[Artifact]) -> None:
        self.items = items

    def list(self, **kwargs: object) -> list[Artifact]:
        thread_id = kwargs.get("thread_id")
        want_type = kwargs.get("type")
        return [
            item
            for item in self.items
            if (thread_id is None or item.thread_id == thread_id)
            and (want_type is None or item.type == want_type)
            and not item.deleted_at
        ]


def _upload(artifact_id: str, filename: str, chars: int = 100) -> Artifact:
    return Artifact(
        id=artifact_id,
        thread_id="t1",
        type="upload",
        filename=filename,
        path=f"artifacts/{filename}",
        size=10,
        sha256="x",
        created_at="2026-10-30T21:00:00+08:00",
        extra={"ext": "docx", "chars": chars, "parsed": True},
    )


def _service(messages: list[Message] | None = None, artifacts: list[Artifact] | None = None):
    return ConversationService(
        Settings(),
        FakeMessages(messages),  # type: ignore[arg-type]
        FakeArtifacts(artifacts or []),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- 规范化
def test_normalize_message_keeps_indentation_but_collapses_blank_lines() -> None:
    raw = "\n\n  第一行\n\n\n\n    code  \n\n"
    assert normalize_message(raw) == "第一行\n\n    code"


def test_normalize_message_caps_runaway_input() -> None:
    text = normalize_message("啊" * (MAX_MESSAGE_CHARS + 500))
    assert len(text) < MAX_MESSAGE_CHARS + 100
    assert text.endswith("（消息过长已截断）")


def test_normalize_message_of_whitespace_is_empty() -> None:
    assert normalize_message("  \n\n\t ") == ""


# ---------------------------------------------------------------- 附件归属
def test_uploads_default_to_whole_thread_for_backward_compat() -> None:
    service = _service(artifacts=[_upload("a1", "周报素材.docx"), _upload("a2", "旧素材.docx")])
    assert [item.artifact_id for item in service.uploads_for("t1")] == ["a1", "a2"]


def test_uploads_are_scoped_to_given_attachment_ids() -> None:
    service = _service(artifacts=[_upload("a1", "周报素材.docx"), _upload("a2", "旧素材.docx")])
    uploads = service.uploads_for("t1", ["a2"])
    assert [item.artifact_id for item in uploads] == ["a2"]
    assert uploads[0].chars == 100


def test_missing_attachments_reports_unknown_ids() -> None:
    service = _service(artifacts=[_upload("a1", "周报素材.docx")])
    assert service.missing_attachments("t1", ["a1"]) == []
    assert service.missing_attachments("t1", ["a1", "ghost"]) == ["ghost"]
    assert service.missing_attachments("t1", None) == []


# ---------------------------------------------------------------- 一轮请求
def test_prepare_builds_history_from_previous_turns() -> None:
    history = [
        Message(
            id="m1",
            thread_id="t1",
            role="user",
            content="把素材整理成周报",
            run_id="r0",
            created_at="2026-10-30T20:00:00+08:00",
        ),
        Message(
            id="m2",
            thread_id="t1",
            role="assistant",
            content="已生成周报.docx",
            run_id="r0",
            created_at="2026-10-30T20:01:00+08:00",
        ),
    ]
    service = _service(messages=history)
    turn = service.prepare("t1", "把它改成八号字")
    assert turn.message == "把它改成八号字"
    assert [item["role"] for item in turn.plan.messages] == ["user", "assistant"]
    assert turn.plan.messages[0]["content"] == "把素材整理成周报"
    assert turn.plan.compacted is False


def test_record_user_writes_attachment_snapshot() -> None:
    service = _service(artifacts=[_upload("a1", "周报素材.docx")])
    turn = service.prepare("t1", "整理成周报")
    saved = service.record_user(turn, "r1")

    assert saved.run_id == "r1"
    assert saved.extra["attachment_ids"] == ["a1"]
    assert saved.extra["uploads"] == [
        {
            "artifact_id": "a1",
            "filename": "周报素材.docx",
            "ext": "docx",
            "chars": 100,
            "parsed": True,
        }
    ]
    # 落库后再查，能原样还原这一轮带了哪些附件
    assert service.attachments_of_run("r1", "t1") == ["a1"]


def test_attachments_of_run_is_empty_when_run_has_no_snapshot() -> None:
    service = _service()
    turn = service.prepare("t1", "没有附件的任务")
    service.record_user(turn, "r9")
    assert service.attachments_of_run("r9", "t1") == []


def test_prepare_does_not_leak_previously_recorded_message_into_history() -> None:
    """第二轮跑之前，第一轮那条用户消息 + 助手答复应当进历史，但本轮自己不能提前出现。"""
    service = _service()
    first = service.prepare("t1", "第一轮问题")
    service.record_user(first, "r1")
    service.messages.add(  # type: ignore[attr-defined]
        Message(
            id="m-assistant-1",
            thread_id="t1",
            role="assistant",
            content="第一轮答复",
            run_id="r1",
            created_at="2026-10-30T21:00:01+08:00",
        )
    )
    second = service.prepare("t1", "第二轮问题")
    assert [item["content"] for item in second.plan.messages] == ["第一轮问题", "第一轮答复"]
