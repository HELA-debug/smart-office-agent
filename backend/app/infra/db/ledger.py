"""调用账本的落库实现与只读汇总。

写入走独立短会话（`Database.session()`）：账本要能被**任何**调用方记录，
包括不属于任何请求的探测和标题生成，所以不能依赖某个正在进行的会话——
那样要么漏记，要么把长期事务拖长。

汇总口径只有一条原则：**账本里的每一行都是供应商真的收到过一次的请求**。
因此 `status=failed` 也计入次数（对面收了请求、可能也计了费），但金额为 0
（失败回执没有 usage，硬估一个数只会让账更乱）。
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from ...core import pricing
from ...core.call_journal import CallEntry, current_scope
from ...core.utils import now_dt
from .models import ModelCallModel
from .session import Database


class DbCallJournal:
    """`CallJournal` 的数据库实现。"""

    def __init__(self, database: Database):
        self.database = database

    def record(self, entry: CallEntry) -> None:
        with self.database.session() as session:
            session.add(
                ModelCallModel(
                    id=f"mc_{uuid.uuid4().hex[:20]}",
                    run_id=entry.run_id,
                    thread_id=entry.thread_id,
                    purpose=entry.purpose,
                    provider=entry.provider,
                    model=entry.model or "",
                    request_id=entry.request_id,
                    status=entry.status,
                    finish_reason=entry.finish_reason,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    cache_hit_tokens=entry.cache_hit_tokens,
                    cache_miss_tokens=entry.cache_miss_tokens,
                    cost_cny=entry.cost_cny,
                    peak=entry.peak,
                    latency_ms=entry.latency_ms,
                    attempt=entry.attempt,
                    error_code=entry.error_code,
                    error_message=(entry.error_message or None),
                    created_at=entry.created_at,
                )
            )


def _since_cutoff(range_key: str) -> str | None:
    days = {"today": 1, "7d": 7, "30d": 30}.get((range_key or "").strip().lower())
    if days is None:
        return None
    return (now_dt() - timedelta(days=days)).isoformat(timespec="seconds")


def summarize(
    database: Database, range_key: str = "30d", thread_id: str | None = None
) -> dict[str, Any]:
    """按用途 / 供应商 / 模型 / 日期汇总账本。返回结构与 `UsageOut.ledger` 对齐。"""
    cutoff = _since_cutoff(range_key)
    with database.session() as session:
        query = select(ModelCallModel)
        if cutoff:
            query = query.where(ModelCallModel.created_at >= cutoff)
        if thread_id:
            query = query.where(ModelCallModel.thread_id == thread_id)
        rows = list(session.scalars(query))

        # 覆盖到的时段：账本从哪一刻开始有数据。前端用它说明「为什么更早的对不上」。
        first_at = session.scalar(select(func.min(ModelCallModel.created_at)))

    totals = {
        "calls": len(rows),
        "failed_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
        "cost_cny": 0.0,
    }
    by_purpose: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, Any]] = {}

    for row in rows:
        cost = _row_cost(row)
        totals["input_tokens"] += int(row.input_tokens or 0)
        totals["output_tokens"] += int(row.output_tokens or 0)
        totals["cache_hit_tokens"] += int(row.cache_hit_tokens or 0)
        totals["cache_miss_tokens"] += int(row.cache_miss_tokens or 0)
        totals["cost_cny"] += cost
        if row.status != "ok":
            totals["failed_calls"] += 1

        _bump(by_purpose, row.purpose, row, cost)
        _bump(by_provider, row.provider, row, cost)
        _bump(by_day, (row.created_at or "")[:10] or "unknown", row, cost)

    return {
        "calls": totals["calls"],
        "failed_calls": totals["failed_calls"],
        "tokens": totals["input_tokens"] + totals["output_tokens"],
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "cache_hit_tokens": totals["cache_hit_tokens"],
        "cache_miss_tokens": totals["cache_miss_tokens"],
        "cost_cny": round(totals["cost_cny"], 6),
        "since": first_at,
        "by_purpose": [
            {"purpose": key, **_public(value)} for key, value in sorted(by_purpose.items())
        ],
        "by_provider": [
            {"provider": key, **_public(value)} for key, value in sorted(by_provider.items())
        ],
        "by_day": [
            {"date": key, **_public(value)} for key, value in sorted(by_day.items(), reverse=True)
        ],
    }


def _row_cost(row: ModelCallModel) -> float:
    """按**现价**重算这一笔的钱。

    写入时不算金额：单价改过一次，历史账就会自相矛盾（`UsageService` 出于
    同样的理由也是重算）。失败行没有 usage，金额恒为 0——硬估一个只会更乱。
    """
    input_tokens = int(row.input_tokens or 0)
    output_tokens = int(row.output_tokens or 0)
    if input_tokens <= 0 and output_tokens <= 0:
        return 0.0
    hit = int(row.cache_hit_tokens or 0)
    miss = int(row.cache_miss_tokens or 0)
    if miss <= 0 and input_tokens > hit:
        # 供应商没给「未命中」字段时按 prompt - hit 推，别把输入算成免费
        miss = input_tokens - hit
    try:
        return pricing.cost_for(
            row.provider,
            row.model,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            output_tokens=output_tokens,
            at=pricing.parse_iso(row.created_at),
        )
    except Exception:  # 价格表里没有这个模型：保留写入时的值（通常是 0）
        return float(row.cost_cny or 0.0)


def _bump(bucket: dict[str, dict[str, Any]], key: str, row: ModelCallModel, cost: float) -> None:
    item = bucket.setdefault(
        key,
        {
            "calls": 0,
            "failed_calls": 0,
            "tokens": 0,
            "cost_cny": 0.0,
        },
    )
    item["calls"] += 1
    if row.status != "ok":
        item["failed_calls"] += 1
    item["tokens"] += int(row.input_tokens or 0) + int(row.output_tokens or 0)
    item["cost_cny"] = round(item["cost_cny"] + cost, 6)


def _public(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (round(value, 6) if isinstance(value, float) else value) for key, value in item.items()
    }


def scope_snapshot() -> dict[str, Any]:
    """当前上下文的运行归属（诊断用）。"""
    scope = current_scope()
    return {"run_id": scope.run_id, "thread_id": scope.thread_id, "purpose": scope.purpose}
