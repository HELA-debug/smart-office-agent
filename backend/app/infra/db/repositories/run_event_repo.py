from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import RunEventEntity
from ..models import RunEventModel
from ..session import session_scope


def _to_entity(row: RunEventModel) -> RunEventEntity:
    return RunEventEntity(
        id=row.id,
        run_id=row.run_id,
        seq=row.seq,
        event=row.event,
        data=dict(row.data or {}),
        created_at=row.created_at,
    )


class SqlRunEventRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def append(self, event: RunEventEntity) -> RunEventEntity:
        with session_scope(self._sf) as session:
            row = RunEventModel(
                run_id=event.run_id,
                seq=event.seq,
                event=event.event,
                data=dict(event.data),
                created_at=event.created_at,
            )
            session.add(row)
            session.flush()
            event.id = row.id
        return event

    def list_after(
        self, run_id: str, after_seq: int = 0, limit: int = 1000
    ) -> list[RunEventEntity]:
        stmt = (
            select(RunEventModel)
            .where(RunEventModel.run_id == run_id)
            .where(RunEventModel.seq > after_seq)
            .order_by(RunEventModel.seq.asc())
            .limit(limit)
        )
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def max_seq(self, run_id: str) -> int:
        stmt = select(RunEventModel.seq).where(RunEventModel.run_id == run_id)
        with session_scope(self._sf) as session:
            seqs = list(session.scalars(stmt.order_by(RunEventModel.seq.desc()).limit(1)))
        return int(seqs[0]) if seqs else 0
