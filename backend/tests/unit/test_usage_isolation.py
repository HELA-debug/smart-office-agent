"""并发运行的用量不能串账。

`ModelRouter` 是进程内单例。改造前 `begin_run()` 直接替换 `self._usage`，
`chat_with_tools` 再往 `self._usage` 里累加 —— 两个会话同时跑时，
后开始的那一轮会把先开始那轮已累计的 tokens 清零，之后两轮的调用又都记进同一个桶：
账单按轮核对必然对不上，token 预算也会被误判（少算 → 该停不停，多算 → 该跑不跑）。
"""

from __future__ import annotations

import asyncio

from app.agents.model_router import ChatResult, ModelRouter
from app.core.config import Settings


def _call(tokens: int, provider: str = "deepseek") -> ChatResult:
    return ChatResult(
        text="ok",
        provider=provider,
        model="deepseek-chat",
        prompt_tokens=tokens,
        completion_tokens=0,
        cost_cny=0.001,
    )


def _router() -> ModelRouter:
    # 显式给空 providers，避免探测真实网络
    return ModelRouter(Settings(), providers={})


def test_begin_run_returns_a_dedicated_meter() -> None:
    router = _router()
    meter = router.begin_run()
    meter.add(_call(10))
    assert router.usage_snapshot()["total_tokens"] == 10
    assert meter.calls == 1


def test_sequential_runs_do_not_inherit_previous_usage() -> None:
    router = _router()
    router.begin_run()
    router.current_usage().add(_call(10))
    router.begin_run()
    assert router.usage_snapshot()["total_tokens"] == 0


def test_concurrent_runs_keep_separate_accounts() -> None:
    """A/B 两轮交错累加，各自只应看到自己的用量。"""

    router = _router()

    async def worker(tokens: int, rounds: int) -> int:
        router.begin_run()
        for _ in range(rounds):
            await asyncio.sleep(0)  # 主动让出，制造交错
            router.current_usage().add(_call(tokens))
        await asyncio.sleep(0)
        return int(router.usage_snapshot()["total_tokens"])

    async def main() -> tuple[int, int]:
        return await asyncio.gather(worker(10, 3), worker(100, 2))  # type: ignore[return-value]

    first, second = asyncio.run(main())
    assert (first, second) == (30, 200), "并发运行的用量串账了"


def test_concurrent_runs_report_their_own_provider_split() -> None:
    router = _router()

    async def worker(provider: str, tokens: int) -> dict:
        router.begin_run()
        await asyncio.sleep(0)
        router.current_usage().add(_call(tokens, provider))
        await asyncio.sleep(0)
        return router.usage_snapshot()

    async def main() -> list[dict]:
        return await asyncio.gather(worker("deepseek", 7), worker("qwen", 9))

    snapshots = asyncio.run(main())
    assert [item["total_tokens"] for item in snapshots] == [7, 9]
    assert snapshots[0]["by_provider"][0]["provider"] == "deepseek"
    assert snapshots[1]["by_provider"][0]["provider"] == "qwen"


def test_meter_never_leaks_between_router_instances() -> None:
    """同一进程里可能有多个路由实例（测试夹具、灰度）：不能把别人的计当成自己的。

    反例：只用「当前上下文里那只计」而不校验归属，A 实例 begin_run 之后
    B 实例的调用会记进 A 的桶，B 自己却读到 0。
    """
    first = _router()
    second = _router()

    first.begin_run()
    first.current_usage().add(_call(5))
    assert second.usage_snapshot()["total_tokens"] == 0

    second.begin_run()
    second.current_usage().add(_call(7))
    assert second.usage_snapshot()["total_tokens"] == 7
    assert first.usage_snapshot()["total_tokens"] == 5


def test_receipts_are_recorded_per_call() -> None:
    """每次外部调用都留一条回执：请求 id 是「真的打到官方接口」的凭据。"""
    router = _router()
    meter = router.begin_run()
    meter.add(
        ChatResult(
            text="ok",
            provider="deepseek",
            model="deepseek-flash",
            prompt_tokens=9,
            completion_tokens=1,
            cost_cny=0.00001,
            request_id="2137b38e-4d07-4e32-906b-a9fad3615ac8",
            latency_ms=467,
        )
    )
    # 自建网关经常吞掉回执：这一笔要标成「未经验证」，不能混进已验证
    meter.add(_call(5))

    snapshot = router.usage_snapshot()
    detail = snapshot["calls_detail"]
    assert len(detail) == 2
    assert detail[0]["request_id"] == "2137b38e-4d07-4e32-906b-a9fad3615ac8"
    assert detail[0]["verified"] is True
    assert detail[0]["latency_ms"] == 467
    assert detail[1]["verified"] is False
    assert snapshot["verified_calls"] == 1
