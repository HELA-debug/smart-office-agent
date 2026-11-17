from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import Run
from ..models import RunModel
from ..session import session_scope


def _to_entity(row: RunModel) -> Run:
    return Run(
        id=row.id,
        thread_id=row.thread_id,
        status=row.status,
        mode=row.mode,
        engine=row.engine,
        provider=row.provider,
        model=row.model,
        tokens=row.tokens,
        cost_cny=row.cost_cny,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_code=row.error_code,
        extra=dict(row.extra or {}),
    )


class SqlRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def add(self, run: Run) -> Run:
        with session_scope(self._sf) as session:
            session.add(
                RunModel(
                    id=run.id,
                    thread_id=run.thread_id,
                    status=run.status,
                    mode=run.mode,
                    engine=run.engine,
                    provider=run.provider,
                    model=run.model,
                    tokens=run.tokens,
                    cost_cny=run.cost_cny,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    error_code=run.error_code,
                    extra=dict(run.extra),
                )
            )
        return run

    def get(self, run_id: str) -> Run | None:
        with session_scope(self._sf) as session:
            row = session.get(RunModel, run_id)
            return _to_entity(row) if row is not None else None

    def update(self, run: Run) -> Run:
        with session_scope(self._sf) as session:
            row = session.get(RunModel, run.id)
            if row is None:
                raise ValueError(f"run not found: {run.id}")
            row.status = run.status
            row.mode = run.mode
            row.engine = run.engine
            row.provider = run.provider
            row.model = run.model
            row.tokens = run.tokens
            row.cost_cny = run.cost_cny
            row.finished_at = run.finished_at
            row.error_code = run.error_code
            row.extra = dict(run.extra)
        return run

    def list_by_thread(
        self,
        thread_id: str,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[Run]:
        stmt = select(RunModel).where(RunModel.thread_id == thread_id)
        if status:
            stmt = stmt.where(RunModel.status == status)
        stmt = (
            stmt.order_by(RunModel.started_at.desc(), RunModel.id.desc())
            .limit(limit)
            .offset(max(0, offset))
        )
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def list_recent(
        self, limit: int = 100, offset: int = 0, status: str | None = None
    ) -> list[Run]:
        stmt = select(RunModel)
        if status:
            stmt = stmt.where(RunModel.status == status)
        stmt = (
            stmt.order_by(RunModel.started_at.desc(), RunModel.id.desc())
            .limit(limit)
            .offset(max(0, offset))
        )
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def count(self, thread_id: str | None = None, status: str | None = None) -> int:
        """分页总数用 SQL COUNT，避免 list_recent(limit=2000) 把历史全量读进内存。"""
        stmt = select(func.count()).select_from(RunModel)
        if thread_id:
            stmt = stmt.where(RunModel.thread_id == thread_id)
        if status:
            stmt = stmt.where(RunModel.status == status)
        with session_scope(self._sf) as session:
            return int(session.scalar(stmt) or 0)
