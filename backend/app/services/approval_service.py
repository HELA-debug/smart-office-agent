"""审批服务：实现 ApprovalGate 端口 + 审批决议落库/幂等校验。

时序：引擎 create() 落库并注册 asyncio.Event -> 事件 approval.required -> 引擎 wait()
-> POST /approvals/{aid} 调 decide() 写库 + set() 事件 -> wait 返回 Decision。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.logging import get_logger
from ..core.utils import new_id, now_iso
from ..domain.entities import Approval
from ..domain.enums import Decision
from ..domain.ports import ApprovalRepository

POLICY_VERSION = "v1"
logger = get_logger(__name__)


class ApprovalService:
    def __init__(self, approvals: ApprovalRepository, settings: Settings):
        self.approvals = approvals
        self.settings = settings
        self._events: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, Decision] = {}

    # ---------- ApprovalGate 端口 ----------
    async def create(
        self,
        thread_id: str,
        run_id: str,
        tool: str,
        payload: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> Approval:
        approval = Approval(
            id=new_id("a"),
            thread_id=thread_id,
            run_id=run_id,
            tool=tool,
            payload=dict(payload),
            created_at=now_iso(),
            policy_version=POLICY_VERSION,
            extra=dict(extra or {}),
        )
        self.approvals.add(approval)
        self._events[approval.id] = asyncio.Event()
        return approval

    async def wait(self, approval_id: str, timeout_seconds: float) -> Decision | None:
        """等决议；超时返回 None。

        ## 这里的每一行都可能炸，而它不该炸

        `wait()` 是引擎那条等待链的最后一环（`_wait_for_approval` → 本函数 →
        审批仓储）。它抛出去，用户看到的就是「服务内部错误」加一整轮运行丢失。
        两处以前会抛：

        - 没有内存事件时回查落库结果：库忙/连接断 → 异常；
        - 超时分支里写 `timed_out` 标记：**写在 except 里**，一失败就把真正的
          超时结局盖掉，变成一次莫名其妙的运行失败。

        现在两处都降级：查不到就当"没有决议"，写不上就只记一条日志——超时
        这个事实本身已经成立，标记是给审计看的，不是给流程用的。
        """
        event = self._events.get(approval_id)
        if event is None:
            # 已超时/已决议/服务重启：直接返回落库结果
            try:
                approval = self.approvals.get(approval_id)
            except Exception:  # 库不可用：按"没有决议"处理，别把异常抛进引擎
                logger.warning("回查审批失败 approval=%s", approval_id, exc_info=True)
                return None
            if approval is None or not approval.decision:
                return None
            try:
                return Decision(approval.decision)
            except ValueError:
                logger.warning(
                    "审批决议值无法识别 approval=%s decision=%s",
                    approval_id,
                    approval.decision,
                )
                return None
        try:
            await asyncio.wait_for(event.wait(), timeout=max(1.0, float(timeout_seconds)))
        except TimeoutError:
            with contextlib.suppress(Exception):
                self.approvals.update_extra(approval_id, {"timed_out": True})
            return None
        finally:
            self._events.pop(approval_id, None)
        return self._decisions.pop(approval_id, None)

    # ---------- 审批决议 ----------
    def decide(
        self,
        thread_id: str,
        approval_id: str,
        decision: str,
        comment: str | None = None,
    ) -> tuple[Approval, bool]:
        if decision not in (Decision.APPROVED.value, Decision.REJECTED.value):
            raise AppError(ErrorCode.BAD_REQUEST, "decision 只能是 approved 或 rejected")
        approval = self.approvals.get(approval_id)
        if approval is None or approval.thread_id != thread_id:
            raise AppError(ErrorCode.NOT_FOUND, f"审批不存在：{approval_id}")
        extra = approval.extra or {}
        if approval.decision is not None or extra.get("timed_out") or extra.get("cancelled"):
            raise AppError(ErrorCode.APPROVAL_ALREADY_DECIDED, "该审批已处理，不能重复提交")
        decided_at = now_iso()
        updated = self.approvals.decide(approval_id, decision, comment, decided_at)
        if not updated:
            raise AppError(ErrorCode.APPROVAL_ALREADY_DECIDED, "该审批已处理，不能重复提交")
        event = self._events.get(approval_id)
        resumed = event is not None
        if event is not None:
            self._decisions[approval_id] = Decision(decision)
            event.set()
        approval.decision = decision
        approval.comment = comment
        approval.decided_at = decided_at
        return approval, resumed

    def list_by_thread(self, thread_id: str, run_id: str | None = None) -> list[Approval]:
        return self.approvals.list_by_thread(thread_id, run_id)

    def public(self, approval: Approval) -> dict[str, Any]:
        return {
            "approval_id": approval.id,
            "thread_id": approval.thread_id,
            "run_id": approval.run_id,
            "tool": approval.tool,
            "risk": "high",
            "payload": approval.payload,
            "decision": approval.decision,
            "comment": approval.comment,
            "created_at": approval.created_at,
            "decided_at": approval.decided_at,
            "policy_version": approval.policy_version,
            "extra": approval.extra,
        }
