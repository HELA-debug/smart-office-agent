from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import Message
from ..models import MessageModel
from ..session import session_scope


def _to_entity(row: MessageModel) -> Message:
    return Message(
        id=row.id,
        thread_id=row.thread_id,
        role=row.role,
        content=row.content,
        run_id=row.run_id,
        created_at=row.created_at,
        extra=dict(row.extra or {}),
    )


class SqlMessageRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def add(self, message: Message) -> Message:
        with session_scope(self._sf) as session:
            session.add(
                MessageModel(
                    id=message.id,
                    thread_id=message.thread_id,
                    role=message.role,
                    content=message.content,
                    run_id=message.run_id,
                    created_at=message.created_at,
                    extra=dict(message.extra),
                )
            )
        return message

    def list_by_thread(self, thread_id: str, include_run_summary: bool = True) -> list[Message]:
        stmt = select(MessageModel).where(MessageModel.thread_id == thread_id)
        if not include_run_summary:
            stmt = stmt.where(MessageModel.role != "run_summary")
        stmt = stmt.order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def count_by_thread(self, thread_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(MessageModel)
            .where(MessageModel.thread_id == thread_id)
            .where(MessageModel.role != "run_summary")
        )
        with session_scope(self._sf) as session:
            return int(session.scalar(stmt) or 0)
