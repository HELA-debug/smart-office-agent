"""审批服务：等决议这条链不许自己炸。

审批是**外部端口**：落库、内存事件、前端那张卡片，任何一环都可能失败。
`wait()` 是引擎等待链的最后一环——它抛出去，用户看到的是「服务内部错误」
加整轮运行丢失。所以这里逐条钉住"坏掉时返回什么"，而不是"坏掉时抛什么"。

尤其是超时分支里那句 `update_extra`：它写在 `except TimeoutError` 里，
一旦它自己失败，就把真正的超时结局盖成一次莫名其妙的运行失败。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.errors import AppError
from app.domain.entities import Approval
from app.domain.enums import Decision
from app.services.approval_service import ApprovalService


class _Repo:
    """最小可用的审批仓储：能存能取，也能按需要炸掉。"""

    def __init__(self, *, fail_get: bool = False, fail_extra: bool = False) -> None:
        self.items: dict[str, Approval] = {}
        self.fail_get = fail_get
        self.fail_extra = fail_extra

    def add(self, approval: Approval) -> Approval:
        self.items[approval.id] = approval
        return approval

    def get(self, approval_id: str) -> Approval | None:
        if self.fail_get:
            raise RuntimeError("db is down")
        return self.items.get(approval_id)

    def decide(self, approval_id: str, decision: str, comment: str | None, decided_at: str) -> bool:
        approval = self.items.get(approval_id)
        if approval is None or approval.decision is not None:
            return False
        approval.decision = decision
        return True

    def update_extra(self, approval_id: str, patch: dict[str, Any]) -> None:
        if self.fail_extra:
            raise RuntimeError("db is locked")
        approval = self.items.get(approval_id)
        if approval is not None:
            approval.extra.update(patch)

    def list_by_thread(self, thread_id: str, run_id: str | None = None) -> list[Approval]:
        return [item for item in self.items.values() if item.thread_id == thread_id]


def _service(repo: _Repo) -> ApprovalService:
    return ApprovalService(repo, SimpleNamespace())  # type: ignore[arg-type]


def test_wait_returns_the_decision_after_decide() -> None:
    repo = _Repo()
    service = _service(repo)

    async def scenario() -> Decision | None:
        approval = await service.create("th", "r", "file.delete", {"tool": "file.delete"})
        waiter = asyncio.create_task(service.wait(approval.id, 2))
        await asyncio.sleep(0)
        service.decide("th", approval.id, "approved")
        return await waiter

    assert asyncio.run(scenario()) is Decision.APPROVED


def test_wait_survives_a_dead_database_when_looking_up_a_missing_event() -> None:
    """没有内存事件（服务重启过）时回查落库：库炸了也不能把异常抛进引擎。"""
    repo = _Repo(fail_get=True)
    service = _service(repo)
    assert asyncio.run(service.wait("a_missing", 1)) is None


def test_wait_timeout_is_not_masked_by_a_failing_marker_write() -> None:
    """超时分支里写 `timed_out` 标记失败，不能把超时变成本轮运行失败。

    这是最阴的一处：`update_extra` 写在 `except TimeoutError` 里面，
    它一抛，`wait()` 抛出去的就不是 None 而是一个新的异常——引擎那边
    只能当成"服务内部错误"，整轮丢掉。标记是给审计看的，不是流程用的。
    """
    repo = _Repo(fail_extra=True)
    service = _service(repo)

    async def scenario() -> Decision | None:
        approval = await service.create("th", "r", "file.delete", {"tool": "file.delete"})
        return await service.wait(approval.id, 0.01)

    assert asyncio.run(scenario()) is None


def test_wait_ignores_an_unrecognisable_stored_decision() -> None:
    """库里出现认不出的决议值：按"没有决议"处理，别抛 ValueError。"""
    repo = _Repo()
    service = _service(repo)
    repo.add(
        Approval(
            id="a_1",
            thread_id="th",
            run_id="r",
            tool="file.delete",
            payload={},
            decision="approved-ish",
            created_at="2026-11-07T00:00:00+08:00",
            policy_version="v1",
        )
    )
    assert asyncio.run(service.wait("a_1", 1)) is None


def test_decide_rejects_unknown_values_and_repeats() -> None:
    repo = _Repo()
    service = _service(repo)
    approval = asyncio.run(service.create("th", "r", "file.delete", {}))

    with pytest.raises(AppError):
        service.decide("th", approval.id, "maybe")
    with pytest.raises(AppError):
        service.decide("other-thread", approval.id, "approved")

    service.decide("th", approval.id, "approved")
    with pytest.raises(AppError):
        service.decide("th", approval.id, "rejected")
