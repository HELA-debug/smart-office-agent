"""计价与用量口径：钱要能按官方价复算出来，历史账不能被旧价钉死。

背景（这一轮用户直接指着控制台问「你是不是没调模型」）：
控制台 30 天 1.19 亿 tokens 只扣 ¥5.86，看着像 ¥0.05/百万；而本应用 1M tokens
报出 ¥2.25 —— 差 40 倍。两件事都不假：官方是**分时 + 缓存分级**计价，
那 1.19 亿里绝大多数是缓存命中（¥0.02–0.04/百万），本应用几乎全是未命中（¥1–2/百万）。
所以这里锁死三件事：
1. 单价按官方口径（闲时 / 高峰、命中 / 未命中 / 输出）；
2. 成本按 run 发生的时间现算，不受「价格表改过几次」影响；
3. 老数据没有缓存拆分时按「全未命中」估，只能高估不能低报。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core import pricing
from app.domain.entities import Run
from app.services.usage_service import UsageService, run_usage

CST = timezone(timedelta(hours=8))
# 2026-10-28 周三 10:00（高峰）；2026-10-31 周六 12:00（闲时）
PEAK = datetime(2026, 10, 28, 10, 0, tzinfo=CST)
OFFPEAK = datetime(2026, 10, 31, 12, 0, tzinfo=CST)


def test_official_flash_prices_are_tiered() -> None:
    off = pricing.price_for("deepseek", "deepseek-flash", at=OFFPEAK)
    assert (off.cache_hit, off.cache_miss, off.output) == (0.02, 1.0, 4.0)
    assert off.peak is False

    peak = pricing.price_for("deepseek", "deepseek-flash", at=PEAK)
    assert (peak.cache_hit, peak.cache_miss, peak.output) == (0.04, 2.0, 8.0)
    assert peak.peak is True


def test_cost_uses_cache_tiers_and_peak_windows() -> None:
    # 闲时 1M 全未命中输入 = ¥1.0；同一份输入全命中只要 ¥0.02（50 倍差）
    assert (
        pricing.cost_for("deepseek", "deepseek-flash", cache_miss_tokens=1_000_000, at=OFFPEAK)
        == 1.0
    )
    assert (
        pricing.cost_for("deepseek", "deepseek-flash", cache_hit_tokens=1_000_000, at=OFFPEAK)
        == 0.02
    )
    # 高峰翻倍
    assert (
        pricing.cost_for("deepseek", "deepseek-flash", cache_miss_tokens=1_000_000, at=PEAK) == 2.0
    )
    # 命中 + 未命中 + 输出混算：0.02*0.5M + 1*0.5M + 4*0.1M = 0.91
    assert (
        pricing.cost_for(
            "deepseek",
            "deepseek-flash",
            cache_hit_tokens=500_000,
            cache_miss_tokens=500_000,
            output_tokens=100_000,
            at=OFFPEAK,
        )
        == 0.91
    )


def test_legacy_alias_is_not_priced_as_a_different_model() -> None:
    """旧别名 deepseek-chat 走 flash 的价，不能掉进 default 把账单放大。"""
    alias = pricing.price_for("deepseek", "deepseek-chat", at=OFFPEAK)
    flash = pricing.price_for("deepseek", "deepseek-flash", at=OFFPEAK)
    assert alias.as_dict() == flash.as_dict()


def test_unknown_provider_falls_back_high_not_low() -> None:
    """查不到的供应商按高峰全未命中兜底：宁可高估，也别把真花钱的调用说成免费。"""
    price = pricing.price_for("nobody", "whatever", at=OFFPEAK)
    assert price.cache_miss >= 1.0 and price.cache_hit > 0


def test_price_table_reloads_when_file_changes(tmp_path) -> None:
    """改价目表不用重启：这是上一轮「改了价格界面还是旧数」的根因。"""
    path = tmp_path / "prices.yaml"
    path.write_text(
        "default: {input_cache_miss: 1.0, input_cache_hit: 0.02, output: 4.0}\n"
        "providers:\n  deepseek:\n    default: {input_cache_miss: 1.0, output: 4.0}\n",
        encoding="utf-8",
    )
    first = pricing.load_price_table(path)
    assert first["default"]["output"] == 4.0

    path.write_text(
        "default: {input_cache_miss: 2.0, input_cache_hit: 0.04, output: 8.0}\n"
        "providers:\n  deepseek:\n    default: {input_cache_miss: 2.0, output: 8.0}\n",
        encoding="utf-8",
    )
    second = pricing.load_price_table(path)
    assert second["default"]["output"] == 8.0


def _run(**overrides) -> Run:
    base = dict(
        id="r_1",
        thread_id="t_1",
        status="completed",
        mode="real",
        engine="real",
        provider="deepseek",
        model="deepseek-flash",
        started_at=OFFPEAK.isoformat(timespec="seconds"),
        tokens=1_000_000,
        cost_cny=2.25,  # 旧价表算出来的数：正是用户看到「1M tokens 花 ¥2.25」的来源
        extra={
            "usage": {
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "total_tokens": 1_000_000,
                "cost_cny": 2.25,
            }
        },
    )
    base.update(overrides)
    return Run(**base)


class _Repo:
    def __init__(self, runs: list[Run]) -> None:
        self._runs = runs

    def list_recent(self, limit: int = 500, offset: int = 0) -> list[Run]:
        return self._runs[:limit]

    def list_by_thread(self, thread_id: str, limit: int = 500) -> list[Run]:
        return [run for run in self._runs if run.thread_id == thread_id][:limit]


def test_stored_old_price_is_recomputed_with_current_table() -> None:
    parts = run_usage(_run())
    # 闲时全未命中：1M × ¥1 = ¥1.0，不是库里躺着的 ¥2.25
    assert parts["cost_cny"] == 1.0
    assert parts["cache_miss_tokens"] == 1_000_000


def test_summary_aggregates_recomputed_cost() -> None:
    service = UsageService(_Repo([_run()]))  # type: ignore[arg-type]
    summary = service.summary(range_key="all")
    assert summary["real_runs"] == 1
    assert summary["tokens"] == 1_000_000
    assert summary["cost_cny"] == 1.0
    assert summary["by_day"][0]["cost_cny"] == 1.0
    assert "百万 tokens" in summary["price_note"]


def test_summary_counts_requests_not_runs() -> None:
    """审计页的「请求数」必须是实际发出的调用数，不能拿运行数冒充。

    一次运行里理解层 + 主循环每一步都是独立请求；实测 70 次运行对应 153 次
    记账请求，供应商控制台又更高（还有探测 / 标题 / 增强 / 重试）。
    """
    real = _run(
        id="r_1",
        extra={
            "usage": {
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "total_tokens": 1_000_000,
                "cost_cny": 1.0,
                "calls": 7,
            }
        },
    )
    mock = _run(
        id="r_2",
        mode="mock",
        provider="mock",
        model="mock-scripted",
        extra={"usage": {"total_tokens": 500, "calls": 99}},
    )
    summary = UsageService(_Repo([real, mock])).summary(range_key="all")  # type: ignore[arg-type]
    assert summary["runs"] == 2
    assert summary["real_runs"] == 1
    assert summary["calls"] == 7, "mock 的调用不能进请求数，也不能按运行数算"
    assert "账单" in summary["price_note"]


def test_mock_runs_never_enter_the_bill() -> None:
    mock = _run(
        id="r_2",
        mode="mock",
        provider="mock",
        model="mock-scripted",
        cost_cny=3.5,
        extra={"usage": {"input_tokens": 500, "output_tokens": 100, "cost_cny": 3.5}},
    )
    service = UsageService(_Repo([_run(), mock]))  # type: ignore[arg-type]
    summary = service.summary(range_key="all")
    assert summary["real_runs"] == 1
    assert summary["mock_runs"] == 1
    assert summary["cost_cny"] == 1.0
