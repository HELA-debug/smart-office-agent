"""会话服务：创建/列表/详情/重命名/置顶/软删 + 首条消息回填标题。"""

from __future__ import annotations

from typing import Any

from ..core.errors import AppError, ErrorCode
from ..core.utils import (
    derive_thread_title,
    is_default_thread_title,
    new_id,
    now_iso,
)
from ..domain.entities import Thread
from ..domain.ports import ArtifactRepository, MessageRepository, ThreadRepository


class ThreadService:
    def __init__(
        self,
        threads: ThreadRepository,
        messages: MessageRepository,
        artifacts: ArtifactRepository,
    ):
        self.threads = threads
        self.messages = messages
        self.artifacts = artifacts

    def create(self, title: str | None = None) -> Thread:
        now = now_iso()
        # 新会话排最前：拿当前最小序号再减一。用户手动拖过顺序时，
        # 「最近更新」已经让位给「他排的顺序」，新会话仍要出现在最上面。
        lowest = self.threads.min_sort_index()
        thread = Thread(
            id=new_id("th"),
            title=(title or "新会话").strip()[:100] or "新会话",
            created_at=now,
            updated_at=now,
            sort_index=None if lowest is None else lowest - 1.0,
        )
        return self.threads.add(thread)

    def reorder(self, thread_ids: list[str]) -> int:
        """按用户拖出来的顺序重写列表顺序，返回真正被改到的条数。"""
        ids = [thread_id for thread_id in dict.fromkeys(thread_ids) if thread_id]
        if not ids:
            raise AppError(ErrorCode.BAD_REQUEST, "thread_ids 不能为空")
        return self.threads.reorder(ids)

    def list(
        self,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """会话列表：搜索（标题/ID）+ 分页 + 置顶优先、最近更新优先。"""
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        # 搜索与分页都下推 SQL（原实现 list(limit=1000) 后在内存过滤/切片）
        keyword = (q or "").strip()
        total = self.threads.count(q=keyword)
        threads = self.threads.list(limit=page_size, offset=(page - 1) * page_size, q=keyword)
        return {
            "threads": [self._summary(thread) for thread in threads],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def _summary(self, thread: Thread) -> dict[str, Any]:
        return {
            "thread_id": thread.id,
            "title": thread.title,
            "created_at": thread.created_at,
            "updated_at": thread.updated_at,
            "pinned": thread.pinned,
            "message_count": self.messages.count_by_thread(thread.id),
            "artifact_count": self.artifacts.count_by_thread(thread.id),
        }

    def get(self, thread_id: str, include_deleted: bool = False) -> Thread:
        thread = self.threads.get(thread_id, include_deleted=include_deleted)
        if thread is None:
            raise AppError(ErrorCode.NOT_FOUND, f"会话不存在：{thread_id}")
        return thread

    def detail(self, thread_id: str) -> dict[str, Any]:
        thread = self.get(thread_id)
        messages = [
            self._message_dict(message)
            for message in self.messages.list_by_thread(thread_id, include_run_summary=False)
        ]
        artifacts = [self._artifact_dict(artifact) for artifact in self.artifacts.list(thread_id)]
        return {
            **self._summary(thread),
            "messages": messages,
            "artifacts": artifacts,
            # 素材单独给一份：右栏「本次素材」要显示文件名和解析字数，
            # 让它去 artifacts 里按 type=upload 猜太别扭（产物列表也不该混进素材）
            "uploads": self._upload_dicts(thread_id),
        }

    def _upload_dicts(self, thread_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for artifact in self.artifacts.list(thread_id=thread_id, type="upload"):
            extra = artifact.extra or {}
            media = extra.get("media") or None
            rows.append(
                {
                    "file_id": artifact.id,
                    "artifact_id": artifact.id,
                    "filename": artifact.filename,
                    "size": artifact.size,
                    "type": str(extra.get("ext", "")),
                    "ext": str(extra.get("ext", "")),
                    "chars": int(extra.get("chars", 0) or 0),
                    "parsed": bool(extra.get("parsed", False)),
                    # 识别状态与类别必须带上：刷新 / 切回会话后，右栏还要显示
                    # 「识别中 / 已识别 N 字 / 识别失败可重试」，不能只剩 parsed 一个布尔。
                    "status": str(
                        extra.get("status")
                        or (media or {}).get("status")
                        or ("ready" if extra.get("parsed") else "processing")
                    ),
                    "media": media,
                    "text_preview": str(extra.get("text_preview", "")),
                    "created_at": artifact.created_at,
                }
            )
        return rows

    def update(
        self,
        thread_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> Thread:
        thread = self.get(thread_id)
        if title is not None:
            cleaned = title.strip()
            if not cleaned:
                raise AppError(ErrorCode.BAD_REQUEST, "标题不能为空")
            thread.title = cleaned[:100]
        if pinned is not None:
            thread.pinned = bool(pinned)
        thread.updated_at = now_iso()
        return self.threads.update(thread)

    def soft_delete(self, thread_id: str) -> None:
        self.get(thread_id)
        self.threads.soft_delete(thread_id, now_iso())

    def soft_delete_many(self, thread_ids: list[str]) -> int:
        """批量软删（左栏「批量清理」用），返回真正删掉的条数。

        与单条不同：不校验存在性——列表是分页拉的，用户选中的会话可能已经被别处删掉，
        这时整批不该失败，前端按返回的 deleted 数提示即可。
        """
        return self.threads.soft_delete_many(thread_ids, now_iso())

    def ensure_title(self, thread_id: str, message: str) -> bool:
        """默认标题时用首条消息回填（不覆盖用户自定义标题）。

        返回 True 表示标题是这次「自动」取出来的——调用方可以据此在跑完之后
        用更贴题的短标题覆盖它；用户手动改过名的会话永远返回 False。
        """
        thread = self.get(thread_id)
        if not is_default_thread_title(thread.title):
            return False
        derived = derive_thread_title(message)
        if derived and derived != thread.title:
            thread.title = derived
            thread.updated_at = now_iso()
            self.threads.update(thread)
        return True

    def apply_auto_title(self, thread_id: str, title: str) -> str:
        """把自动标题换成更贴题的名字（只在标题仍是自动生成的时候生效）。"""
        cleaned = (title or "").strip().strip("「」《》\"'。，,.")
        if not cleaned:
            return ""
        thread = self.get(thread_id)
        if not cleaned or cleaned == thread.title:
            return thread.title
        thread.title = cleaned[:40]
        thread.updated_at = now_iso()
        self.threads.update(thread)
        return thread.title

    def touch(self, thread_id: str) -> None:
        thread = self.threads.get(thread_id)
        if thread is None:
            return
        thread.updated_at = now_iso()
        self.threads.update(thread)

    @staticmethod
    def _message_dict(message: Any) -> dict[str, Any]:
        return {
            "message_id": message.id,
            "thread_id": message.thread_id,
            "role": message.role,
            "content": message.content,
            "run_id": message.run_id,
            "created_at": message.created_at,
            "extra": message.extra,
        }

    @staticmethod
    def _artifact_dict(artifact: Any) -> dict[str, Any]:
        extra = artifact.extra or {}
        return {
            "artifact_id": artifact.id,
            "type": artifact.type,
            "filename": artifact.filename,
            "size": artifact.size,
            "sha256": artifact.sha256,
            "created_at": artifact.created_at,
            "thread_id": artifact.thread_id,
            "run_id": artifact.run_id,
            "download_url": f"/api/v1/artifacts/{artifact.id}/download",
            "preview_url": f"/api/v1/artifacts/{artifact.id}/preview",
            # 只回吐素材名：右栏要说明「这份产物从哪来」，其它 extra（预览路径等）不往外带
            "sources": [str(name) for name in (extra.get("sources") or [])],
        }
