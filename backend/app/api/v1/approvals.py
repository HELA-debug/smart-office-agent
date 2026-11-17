"""审批接口：提交决议并解除运行挂起。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, status

from ...core.utils import now_iso
from ..deps import ContainerDep
from .schemas import ApprovalDecisionOut, ApprovalRequestIn

router = APIRouter(tags=["approvals"])


@router.post(
    "/threads/{thread_id}/approvals/{approval_id}",
    response_model=ApprovalDecisionOut,
    status_code=status.HTTP_200_OK,
    summary="提交审批决议",
)
async def decide_approval(
    thread_id: str,
    approval_id: str,
    body: ApprovalRequestIn,
    request: Request,
    container: ContainerDep,
) -> dict[str, Any]:
    _, resumed = container.approvals.decide(thread_id, approval_id, body.decision, body.comment)
    return {
        "trace_id": request.state.trace_id,
        "approval_id": approval_id,
        "decision": body.decision,
        "decided_at": now_iso(),
        "resumed": resumed,
    }
