from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import Approval
from ..models import ApprovalModel
from ..session import session_scope


def _to_entity(row: ApprovalModel) -> Approval:
    return Approval(
        id=row.id,
        thread_id=row.thread_id,
        run_id=row.run_id,
        tool=row.tool,
        payload=dict(row.payload or {}),
        decision=row.decision,
        comment=row.comment,
        policy_version=row.policy_version,
        created_at=row.created_at,
        decided_at=row.decided_at,
        extra=dict(row.extra or {}),
    )


def _extra_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


class SqlApprovalRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def add(self, approval: Approval) -> Approval:
        with session_scope(self._sf) as session:
            session.add(
                ApprovalModel(
                    id=approval.id,
                    thread_id=approval.thread_id,
                    run_id=approval.run_id,
                    tool=approval.tool,
                    payload=dict(approval.payload),
                    decision=approval.decision,
                    comment=approval.comment,
                    policy_version=approval.policy_version,
                    created_at=approval.created_at,
                    decided_at=approval.decided_at,
                    extra=dict(approval.extra),
                )
            )
        return approval

    def get(self, approval_id: str) -> Approval | None:
        with session_scope(self._sf) as session:
            row = session.get(ApprovalModel, approval_id)
            return _to_entity(row) if row is not None else None

    def decide(
        self,
        approval_id: str,
        decision: str,
        comment: str | None,
        decided_at: str,
    ) -> bool:
        with session_scope(self._sf) as session:
            row = session.get(ApprovalModel, approval_id)
            if row is None or row.decision is not None:
                return False
            row.decision = decision
            row.comment = comment
            row.decided_at = decided_at
            return True

    def update_extra(self, approval_id: str, patch: dict[str, Any]) -> None:
        with session_scope(self._sf) as session:
            row = session.get(ApprovalModel, approval_id)
            if row is None:
                return
            extra = _extra_dict(row.extra)
            extra.update(patch)
            row.extra = extra

    def list_by_thread(self, thread_id: str, run_id: str | None = None) -> list[Approval]:
        stmt = select(ApprovalModel).where(ApprovalModel.thread_id == thread_id)
        if run_id:
            stmt = stmt.where(ApprovalModel.run_id == run_id)
        stmt = stmt.order_by(ApprovalModel.created_at.asc())
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]
