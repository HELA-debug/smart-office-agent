"""取消的运行也要记账。

背景：一次运行内部要跑十几轮「模型 → 工具 → 模型」，每轮都是一次独立计费请求。
用户中途点停止时，供应商那边照常扣钱，但原来的收尾逻辑只写了 `elapsed_ms: 0`，
一个 token 都没记。结果是本地账本 10 次 / 官方账单 398 次，越看越像数据丢了。

这里锁住三件事：
1. 取消时把引擎已消耗的用量写进 run；
2. 快照取不到也不能让取消本身失败（否则用户点停止会收到 500）；
3. 聚合层把「请求次数」和「运行次数」分开算——它们是两个口径。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.domain.entities import Run
from app.services.run_service import RunService
from app.services.usage_service import UsageService, run_usage

SNAPSHOT: dict[str, Any] = {
    "input_tokens": 900,
    "output_tokens": 100,
    "cache_hit_tokens": 600,
    "cache_miss_tokens": 300,
    "total_tokens": 1000,
    "cost_cny": 0.004,
    "calls": 4,
    "by_provider": [],
    "calls_detail": [],
    "verified_calls": 4,
}


class _RunRepo:
    def __init__(self, runs: list[Run] | None = None) -> None:
        self.runs = runs or []
        self.updated: list[Run] = []

    def add(self, run: Run) -> Run:
        self.runs.append(run)
        return run

    def get(self, run_id: str) -> Run | None:
        return next((run for run in self.runs if run.id == run_id), None)

    def update(self, run: Run) -> Run:
        self.updated.append(run)
        return run

    def list_recent(
        self, limit: int = 100, offset: int = 0, status: str | None = None
    ) -> list[Run]:
        return self.runs[:limit]

    def list_by_thread(
        self, thread_id: str, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[Run]:
        return [run for run in self.runs if run.thread_id == thread_id][:limit]

    def count(self, thread_id: str | None = None, status: str | None = None) -> int:
        return len(self.runs)


def _run(**overrides: Any) -> Run:
    base = {
        "id": "run-1",
        "thread_id": "th-1",
        "status": "running",
        "mode": "real",
        "engine": "real",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "started_at": "2026-11-01T10:00:00+08:00",
    }
    base.update(overrides)
    return Run(**base)


def _service(snapshot: Any = SNAPSHOT, *, raises: bool = False) -> tuple[RunService, _RunRepo]:
    repo = _RunRepo()

    def _snap() -> dict[str, Any]:
        if raises:
            raise RuntimeError("boom")
        return snapshot

    service = RunService.__new__(RunService)  # 只测收尾逻辑，不装配整套依赖
    service.runs = repo  # type: ignore[attr-defined]
    service._engine_selection = SimpleNamespace(engine=SimpleNamespace(usage_snapshot=_snap))
    return service, repo


def test_cancelled_run_keeps_usage_it_already_spent() -> None:
    service, repo = _service()
    run = _run()
    service._finish_cancelled(run, service._engine_selection)  # type: ignore[attr-defined]

    assert run.status == "cancelled"
    assert run.tokens == 1000
    assert run.cost_cny == 0.004
    assert run.extra["usage"]["calls"] == 4
    assert run.extra["partial"] is True
    assert repo.updated == [run]


def test_cancelled_run_without_snapshot_still_finishes() -> None:
    """拿不到快照就记 0，但取消流程必须走完——否则用户点停止会看到报错。"""
    service, _ = _service(raises=True)
    run = _run()
    service._finish_cancelled(run, service._engine_selection)  # type: ignore[attr-defined]

    assert run.status == "cancelled"
    assert run.tokens == 0
    assert run.extra["partial"] is True
    assert "usage" not in run.extra


def test_cancelled_run_accepts_selection_without_usage_api() -> None:
    """MockEngine 之类的引擎没有 usage_snapshot，不能因此炸掉。"""
    service, _ = _service()
    run = _run()
    service._finish_cancelled(run, SimpleNamespace(engine=object()))  # type: ignore[attr-defined]
    assert run.status == "cancelled"
    assert run.tokens == 0


def test_usage_summary_separates_calls_from_runs() -> None:
    """运行数是「点了几次开始」，请求次数才是官方账单上的那个数。"""
    completed = _run(
        id="run-ok",
        status="completed",
        tokens=1200,
        cost_cny=0.005,
        extra={
            "usage": {
                **SNAPSHOT,
                "input_tokens": 1100,
                "output_tokens": 100,
                "total_tokens": 1200,
                "calls": 6,
            }
        },
        finished_at="2026-11-01T10:01:00+08:00",
    )
    cancelled = _run(
        id="run-cancel",
        status="cancelled",
        tokens=1000,
        cost_cny=0.004,
        extra={"usage": SNAPSHOT, "partial": True, "reason": "cancelled_by_user"},
        finished_at="2026-11-01T10:05:00+08:00",
    )
    summary = UsageService(_RunRepo([completed, cancelled])).summary(range_key="all")

    assert summary["runs"] == 2
    assert summary["real_runs"] == 2
    assert summary["api_calls"] == 10  # 6 + 4
    assert summary["cancelled_runs"] == 1
    assert summary["cancelled_tokens"] == 1000
    # 取消那笔钱是花了钱的，必须计入合计，否则总额会少一块
    assert summary["tokens"] == 2200
    assert summary["cancelled_cost_cny"] > 0


def test_run_usage_reports_calls_and_falls_back_for_old_records() -> None:
    legacy = _run(extra={"usage": {"input_tokens": 100, "output_tokens": 20}})
    parts = run_usage(legacy)
    assert parts["calls"] == 0  # 老记录没存请求数：宁可显示偏少，也不按 1 硬凑
    assert parts["tokens"] == 120


def test_by_day_carries_request_count() -> None:
    run = _run(
        status="completed",
        tokens=500,
        extra={"usage": {**SNAPSHOT, "total_tokens": 500, "calls": 3}},
    )
    summary = UsageService(_RunRepo([run])).summary(range_key="all")
    assert summary["by_day"][0]["calls"] == 3
