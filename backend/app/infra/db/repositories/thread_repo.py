from __future__ import annotations

from typing import Any

from sqlalchemy import Select, case, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import Thread
from ..models import ThreadModel
from ..session import session_scope


def _to_entity(row: ThreadModel) -> Thread:
    return Thread(
        id=row.id,
        title=row.title,
        pinned=bool(row.pinned),
        sort_index=row.sort_index,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        extra=dict(row.extra or {}),
    )


class SqlThreadRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def add(self, thread: Thread) -> Thread:
        with session_scope(self._sf) as session:
            session.add(
                ThreadModel(
                    id=thread.id,
                    title=thread.title,
                    pinned=thread.pinned,
                    sort_index=thread.sort_index,
                    deleted_at=thread.deleted_at,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                    extra=dict(thread.extra),
                )
            )
        return thread

    def get(self, thread_id: str, include_deleted: bool = False) -> Thread | None:
        with session_scope(self._sf) as session:
            row = session.get(ThreadModel, thread_id)
            if row is None or (row.deleted_at and not include_deleted):
                return None
            return _to_entity(row)

    def list(
        self,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
        q: str | None = None,
    ) -> list[Thread]:
        """置顶优先 → 手动顺序 → 最近更新；关键词过滤与分页都下推到 SQL。

        手动顺序（sort_index）只有用户拖过才有值：有值的一律排在没值的前面，
        没有值的（从没拖过）仍按最近更新排。新建会话拿「最小值 - 1」，所以永远在最前面；
        拖过的不会被新消息顶走——这正是「手动排过」的意思。
        一份从没拖过的库全是 NULL，顺序跟以前完全一样。
        """
        stmt = self._filtered(include_deleted, q)
        stmt = (
            stmt.order_by(
                ThreadModel.pinned.desc(),
                case((ThreadModel.sort_index.is_(None), 1), else_=0),
                ThreadModel.sort_index.asc(),
                ThreadModel.updated_at.desc(),
                ThreadModel.id.desc(),
            )
            .limit(limit)
            .offset(max(0, offset))
        )
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def count(self, include_deleted: bool = False, q: str | None = None) -> int:
        stmt = select(func.count()).select_from(self._filtered(include_deleted, q).subquery())
        with session_scope(self._sf) as session:
            return int(session.scalar(stmt) or 0)

    def _filtered(self, include_deleted: bool, q: str | None) -> Select[Any]:
        stmt = select(ThreadModel)
        if not include_deleted:
            stmt = stmt.where(ThreadModel.deleted_at.is_(None))
        keyword = (q or "").strip()
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(or_(ThreadModel.title.like(pattern), ThreadModel.id.like(pattern)))
        return stmt

    def update(self, thread: Thread) -> Thread:
        with session_scope(self._sf) as session:
            row = session.get(ThreadModel, thread.id)
            if row is None:
                raise ValueError(f"thread not found: {thread.id}")
            row.title = thread.title
            row.pinned = thread.pinned
            row.sort_index = thread.sort_index
            row.deleted_at = thread.deleted_at
            row.updated_at = thread.updated_at
            row.extra = dict(thread.extra)
        return thread

    def min_sort_index(self) -> float | None:
        """当前最小的手动序号：新建会话要插到它前面（再减 1）。"""
        stmt = select(func.min(ThreadModel.sort_index)).where(
            ThreadModel.sort_index.is_not(None),
            ThreadModel.deleted_at.is_(None),
        )
        with session_scope(self._sf) as session:
            value = session.scalar(stmt)
        return float(value) if value is not None else None

    def reorder(self, thread_ids: list[str]) -> int:
        """按传入顺序重写 sort_index（0,1,2…），一次提交。

        整份列表重编号而不是「取前后中点」：前端拖完会把完整顺序一起传上来，
        重编号后数值永远是连续整数，翻页、置顶、删会话都不会把顺序拖乱。
        不存在的 ID 直接跳过（会话可能刚被别处删掉），不让整次请求失败。
        """
        ids = [thread_id for thread_id in dict.fromkeys(thread_ids) if thread_id]
        if not ids:
            return 0
        updated = 0
        with session_scope(self._sf) as session:
            for index, thread_id in enumerate(ids):
                result = session.execute(
                    update(ThreadModel)
                    .where(ThreadModel.id == thread_id, ThreadModel.deleted_at.is_(None))
                    .values(sort_index=float(index))
                )
                updated += int(result.rowcount or 0)
        return updated

    def soft_delete(self, thread_id: str, deleted_at: str) -> None:
        with session_scope(self._sf) as session:
            row = session.get(ThreadModel, thread_id)
            if row is not None:
                row.deleted_at = deleted_at
                row.updated_at = deleted_at

    def soft_delete_many(self, thread_ids: list[str], deleted_at: str) -> int:
        """批量软删：一条 UPDATE 搞定，返回真正被改到的行数。

        不逐条 `get` + 抛 404：批量清理要的是「点一次少一批」，某个会话已经被别人删掉
        不该让整批失败（前端拿 deleted 数对账就够了）。
        """
        ids = [thread_id for thread_id in dict.fromkeys(thread_ids) if thread_id]
        if not ids:
            return 0
        stmt = (
            update(ThreadModel)
            .where(ThreadModel.id.in_(ids), ThreadModel.deleted_at.is_(None))
            .values(deleted_at=deleted_at, updated_at=deleted_at)
        )
        with session_scope(self._sf) as session:
            result = session.execute(stmt)
            return int(result.rowcount or 0)
