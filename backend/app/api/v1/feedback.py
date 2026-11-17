"""意见反馈接口：把「用户的意见」变成「一封可以发出去的邮件」。

产品是本机部署的，没有中心服务器收反馈，所以这里不发任何网络请求：
后端只负责 ① 在本机存档 ② 拼好邮件标题/正文/mailto 链接，剩下的交给用户的邮件客户端。
开发者邮箱来自配置 `FEEDBACK_EMAIL`，留空时 `target`/`mailto` 为空，前端退化成复制粘贴。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...core.errors import AppError, ErrorCode
from ..deps import ContainerDep
from .schemas import FeedbackIn, FeedbackOut

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackOut, summary="提交意见反馈（本机存档 + 生成邮件）")
async def submit_feedback(
    payload: FeedbackIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    try:
        result = container.feedback.submit(
            kind=payload.kind,
            message=payload.message,
            contact=payload.contact,
            include_diagnostics=payload.include_diagnostics,
            client=payload.client,
        )
    except ValueError as exc:
        raise AppError(ErrorCode.BAD_REQUEST, str(exc)) from exc
    return {"trace_id": request.state.trace_id, **result}
