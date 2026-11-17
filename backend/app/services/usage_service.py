"""用量服务：按时间范围 / 会话 / 供应商 / 模型聚合 run 的 token、成本与耗时。"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from ..core import pricing
from ..core.logging import get_logger
from ..core.utils import TZ, now_dt
from ..domain.entities import Run
from ..domain.ports import RunRepository
from ..infra.db.ledger import summarize

logger = get_logger("app.services.usage")

_RANGE_DAYS: dict[str, int | None] = {
    "7d": 7,
    "30d": 30,
    "today": 1,
    "all": None,
}


class UsageService:
    def __init__(self, runs: RunRepository, database: Any | None = None):
        self.runs = runs
        # 账本需要独立会话：run 外调用（探测/标题/增强）不经过任何请求事务。
        self.database = database

    @staticmethod
    def parse_range(value: str | None) -> tuple[int | None, str]:
        key = (value or "7d").strip().lower()
        if key not in _RANGE_DAYS:
            key = "7d"
        return _RANGE_DAYS[key], key

    def ledger_summary(self, range_key: str, thread_id: str | None = None) -> dict[str, Any] | None:
        """全量调用账本（含 run 外调用与失败重试）。

        返回 `None` 表示账本不可用（没装数据库的纯单测场景）。**不用空对象
        冒充**：`calls=0` 是一个有意义的事实（真的没调用），和「查不了」混在
        一起，界面就会把「没数据」说成「零消耗」。
        """
        if self.database is None:
            return None
        try:
            return summarize(self.database, range_key=range_key, thread_id=thread_id)
        except Exception as exc:  # 账本查挂了不该让整个审计页 500
            logger.warning(
                "调用账本汇总失败，只返回运行内口径：%s",
                str(exc)[:200],
                extra={"event": "ledger_summary_failed"},
            )
            return None

    def summary(
        self,
        thread_id: str | None = None,
        range_key: str | None = "7d",
        limit: int = 500,
    ) -> dict[str, Any]:
        days, normalized_range = self.parse_range(range_key)
        runs = (
            self.runs.list_by_thread(thread_id, limit=limit)
            if thread_id
            else self.runs.list_recent(limit=limit)
        )
        if days is not None:
            cutoff = (now_dt() - timedelta(days=days)).isoformat(timespec="seconds")
            runs = [run for run in runs if (run.started_at or "") >= cutoff]

        totals: dict[str, float] = defaultdict(float)
        # 成本一律「按现价重算」，不直接用 run 上存的旧值：
        # 价格表改过之后，历史 run 上记的还是旧单价算出来的钱，直接加总会得到
        # 「1M tokens 花 ¥2.25」这种跟官方差几十倍的数——看着就像是编的。
        hit_total = 0
        miss_total = 0
        by_status: dict[str, int] = defaultdict(int)
        by_day_mock: dict[str, int] = defaultdict(int)
        by_provider: dict[str, dict[str, float]] = defaultdict(
            lambda: {"runs": 0, "tokens": 0, "cost_cny": 0.0}
        )
        by_model: dict[str, dict[str, float]] = defaultdict(
            lambda: {"runs": 0, "tokens": 0, "cost_cny": 0.0}
        )
        by_day: dict[str, dict[str, float]] = defaultdict(
            lambda: {"runs": 0, "tokens": 0, "cost_cny": 0.0, "elapsed_ms": 0, "calls": 0}
        )
        for run in runs:
            elapsed_ms = int((run.extra or {}).get("elapsed_ms", 0))
            totals["runs"] += 1
            totals["elapsed_ms"] += elapsed_ms
            by_status[run.status] += 1
            # mock 运行的 tokens / 成本都是本地估算出来的，从没花过钱。
            # 混进「用量」里会让人拿这个数去供应商控制台对账，越对越怀疑——
            # 成本与 token 只统计真实调用，mock 单独给个数。
            if _is_mock_run(run):
                totals["mock_runs"] += 1
                by_day_mock[(run.started_at or "")[:10] or "unknown"] += 1
                continue
            parts = run_usage(run)
            hit_total += parts["cache_hit_tokens"]
            miss_total += parts["cache_miss_tokens"]
            totals["real_runs"] += 1
            totals["tokens"] += parts["tokens"]
            totals["cost_cny"] += parts["cost_cny"]
            # 请求数按「实际发出去并被记下来的调用」累加，不是按 run 数。
            # 一次运行里理解层 + 主循环每一步都是独立请求，用 runs 冒充请求数
            # 会跟供应商控制台差一个数量级（实测 70 次运行对应 153 次记账请求）。
            totals["calls"] += parts["calls"]
            for bucket, key in ((by_provider, run.provider), (by_model, run.model)):
                bucket[key]["runs"] += 1
                bucket[key]["tokens"] += parts["tokens"]
                bucket[key]["cost_cny"] = round(bucket[key]["cost_cny"] + parts["cost_cny"], 6)
            day = (run.started_at or "")[:10] or "unknown"
            by_day[day]["runs"] += 1
            by_day[day]["tokens"] += parts["tokens"]
            by_day[day]["calls"] += parts["calls"]
            by_day[day]["cost_cny"] = round(by_day[day]["cost_cny"] + parts["cost_cny"], 6)
            by_day[day]["elapsed_ms"] += elapsed_ms
        run_count = int(totals["runs"])
        return {
            "thread_id": thread_id,
            "range": normalized_range,
            "since": (now_dt() - timedelta(days=days)).isoformat(timespec="seconds")
            if days
            else None,
            "runs": run_count,  # 真实调用 / 本地 mock 分开数：只有真实调用会产生费用
            "real_runs": int(totals["real_runs"]),
            "mock_runs": int(totals["mock_runs"]),
            "tokens": int(totals["tokens"]),
            # 真实发出的请求数（运行内已记账的）。老记录没有这个字段就是 0。
            "calls": int(totals["calls"]),
            # 成本按「现价 × 实际 token」重算，口径见 core/pricing.py
            "cost_cny": round(totals["cost_cny"], 6),
            "cache_hit_tokens": int(hit_total),
            "cache_miss_tokens": int(miss_total),
            # 全量账本：这一栏才接近供应商控制台的口径（含 run 外调用与失败重试）。
            # 与上面 runs 口径并列而不是替换——「这次运行花了多少」和「这个 Key
            # 一共发了多少请求」是两个问题，混成一个数只会继续对不上账。
            "ledger": self.ledger_summary(normalized_range, thread_id),
            "price_note": pricing_note(),
            "elapsed_ms": int(totals["elapsed_ms"]),
            "avg_elapsed_ms": int(totals["elapsed_ms"] / run_count) if run_count else 0,
            "by_status": dict(by_status),
            "by_provider": [
                {"provider": key, **values} for key, values in sorted(by_provider.items())
            ],
            "by_model": [{"model": key, **values} for key, values in sorted(by_model.items())],
            "by_day": [
                {
                    "date": day,
                    **values,
                    "mock_runs": int(by_day_mock.get(day, 0)),
                }
                for day, values in sorted(by_day.items(), reverse=True)
            ],
        }

    @staticmethod
    def run_public(run: Run) -> dict[str, Any]:
        return {
            "run_id": run.id,
            "thread_id": run.thread_id,
            "status": run.status,
            "mode": run.mode,
            "engine": run.engine,
            "provider": run.provider,
            "model": run.model,
            "tokens": run.tokens,
            "cost_cny": run.cost_cny,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_code": run.error_code,
            "extra": run.extra,
        }

    @staticmethod
    def day_label(offset_days: int = 0) -> str:
        return (now_dt() - timedelta(days=offset_days)).astimezone(TZ).date().isoformat()


def _is_mock_run(run: Run) -> bool:
    """这条运行是不是本地脚本跑的：mock 引擎产出的 token/成本没有账单意义。"""
    mode = (run.mode or "").strip().lower()
    return mode == "mock" or (run.provider or "").strip().lower() == "mock"


def run_usage(run: Run) -> dict[str, float]:
    """取一条真实运行的口径：tokens 拆分 + 请求次数 + 按现价重算的成本。"""
    usage = (run.extra or {}).get("usage") or {}
    try:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        hit = int(usage.get("cache_hit_tokens") or 0)
        miss = usage.get("cache_miss_tokens")
        miss_tokens = int(miss) if miss is not None else max(0, input_tokens - hit)
        # 这次运行向供应商发了几次计费请求。老记录缺这个字段就是 0，
        # 宁可显示偏少，也不按「至少一次」硬凑——凑出来的数拿去对账只会更乱。
        calls = int(usage.get("calls") or 0)
    except (TypeError, ValueError):
        input_tokens = output_tokens = hit = miss_tokens = 0
        calls = 0
    if not input_tokens and not output_tokens:
        # 老 run 只记了总数：当成输入（按未命中价）估，宁可高估
        input_tokens = int(run.tokens or 0)
        miss_tokens = input_tokens
    cost = pricing.cost_for(
        run.provider,
        run.model,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss_tokens,
        output_tokens=output_tokens,
        at=pricing.parse_iso(run.started_at),
    )
    return {
        "tokens": input_tokens + output_tokens,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss_tokens,
        "cost_cny": cost,
        "calls": calls,
    }


def pricing_note() -> str:
    """给界面用的一句话口径说明（闲时基准单价 + 统计范围，改价后自动跟着变）。

    单价固定报**闲时基准**：每条运行的钱是按它自己发生的时间算的（工作日高峰翻倍），
    拿「现在」是闲时还是高峰去描述整个历史区间，只会让对账更糊涂。
    """
    # 21:00 在任何一天都是闲时（高峰只到 18:00，周末全天闲时）。
    off_peak = now_dt().replace(hour=21, minute=0, second=0, microsecond=0)
    price = pricing.price_for("deepseek", "deepseek-flash", at=off_peak)
    return (
        "按官方分时价目表重算（元 / 百万 tokens，闲时基准）："
        f"输入未命中 ¥{price.cache_miss:g}、命中 ¥{price.cache_hit:g}、输出 ¥{price.output:g}；"
        "工作日高峰时段翻倍，逐条按运行发生时间计算。"
        "仅统计应用内已记账的成功调用，不含探测 / 会话标题 / 提示词增强等运行外请求，"
        "也不含失败重试；真实账单以供应商控制台为准（金额通常更高）。"
    )
