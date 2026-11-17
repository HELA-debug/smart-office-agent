"""ModelRouter 单测：fallback 链、重试、熔断、成本与用量（不访问网络）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from app.agents.model_router import ModelRouter, ModelUnavailableError
from app.core.config import Settings
from app.providers import ErrorCategory, ProviderError, ProviderResult, ToolCall


class FakeProvider:
    """按脚本响应的假供应商（脚本元素为 ProviderResult 或 Exception）。"""

    def __init__(
        self,
        name: str,
        model: str,
        *,
        script: list[Any] | None = None,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = f"https://{name}.example/v1"
        self._configured = configured
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def api_key_ref(self) -> str:
        return f"env:FAKE_{self.name.upper()}_KEY"

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResult:
        self.calls.append({"messages": messages, **kwargs})
        item = self.script.pop(0) if self.script else "default"
        if isinstance(item, Exception):
            raise item
        if item == "default":
            return ProviderResult(
                text="ok",
                tool_calls=(),
                finish_reason="stop",
                model=self.model,
                prompt_tokens=10,
                completion_tokens=5,
            )
        return item

    async def probe(self) -> tuple[bool, str]:
        item = self.script.pop(0) if self.script else True
        if isinstance(item, Exception):
            return False, str(item)
        return bool(item), "" if item else "假探测失败"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mock_mode": False,
        "model_provider": "deepseek",
        "model_name": "deepseek-chat",
        "model_fallback_chain": "deepseek,qwen,mock",
        "deepseek_api_key": "sk-deepseek",
        "model_max_steps": 6,
        "model_max_tokens": 1000,
    }
    base.update(overrides)
    return Settings(**base)


PRICES = {
    "default": {"input": 2.0, "output": 8.0},
    "providers": {
        "deepseek": {
            "default": {"input": 2.0, "output": 8.0},
            "models": {"deepseek-chat": {"input": 2.0, "output": 8.0}},
        },
        "qwen": {"default": {"input": 0.8, "output": 2.0}},
    },
}

MESSAGES = [{"role": "user", "content": "写周报"}]


def build_router(*providers: FakeProvider, settings: Settings | None = None) -> ModelRouter:
    return ModelRouter(
        settings or make_settings(),
        providers={provider.name: provider for provider in providers},
        price_table=PRICES,
        retry_backoff_seconds=0,
        probe_cache_ttl=60,
    )


def test_fallback_on_auth_error_switches_provider() -> None:
    deepseek = FakeProvider(
        "deepseek",
        "deepseek-chat",
        script=[ProviderError(ErrorCategory.AUTH, "bad key", provider="deepseek", status_code=401)],
    )
    qwen = FakeProvider(
        "qwen",
        "qwen-plus",
        script=[
            ProviderResult(
                text="qwen 结果",
                tool_calls=(),
                finish_reason="stop",
                model="qwen-plus",
                prompt_tokens=8,
                completion_tokens=4,
            )
        ],
    )
    router = build_router(deepseek, qwen)

    result = asyncio.run(router.chat_with_tools(MESSAGES))

    assert result.provider == "qwen"
    assert result.text == "qwen 结果"
    assert router.degraded is False
    # 鉴权失败不重试，直接切下一家
    assert len(deepseek.calls) == 1
    assert len(qwen.calls) == 1
    assert [item["provider"] for item in router.last_attempts] == ["deepseek", "qwen"]
    assert router.last_attempts[0]["category"] == "auth"


def test_rate_limit_retries_once_then_succeeds() -> None:
    deepseek = FakeProvider(
        "deepseek",
        "deepseek-chat",
        script=[
            ProviderError(ErrorCategory.RATE_LIMIT, "429", provider="deepseek", status_code=429),
            ProviderResult(
                text="重试成功",
                tool_calls=(),
                finish_reason="stop",
                model="deepseek-chat",
                prompt_tokens=12,
                completion_tokens=6,
            ),
        ],
    )
    qwen = FakeProvider("qwen", "qwen-plus")
    router = build_router(deepseek, qwen)

    result = asyncio.run(router.chat_with_tools(MESSAGES))

    assert result.provider == "deepseek"
    assert len(deepseek.calls) == 2
    assert qwen.calls == []


def test_server_error_switches_without_retry() -> None:
    deepseek = FakeProvider(
        "deepseek",
        "deepseek-chat",
        script=[ProviderError(ErrorCategory.SERVER, "500", provider="deepseek", status_code=500)],
    )
    qwen = FakeProvider("qwen", "qwen-plus")
    router = build_router(deepseek, qwen)
    result = asyncio.run(router.chat_with_tools(MESSAGES))
    assert result.provider == "qwen"
    assert len(deepseek.calls) == 1


def test_all_providers_fail_raises_and_marks_degraded() -> None:
    deepseek = FakeProvider(
        "deepseek",
        "deepseek-chat",
        script=[ProviderError(ErrorCategory.AUTH, "bad", provider="deepseek", status_code=401)],
    )
    qwen = FakeProvider(
        "qwen",
        "qwen-plus",
        script=[
            ProviderError(ErrorCategory.TIMEOUT, "timeout", provider="qwen"),
            ProviderError(ErrorCategory.TIMEOUT, "timeout", provider="qwen"),
        ],
    )
    router = build_router(deepseek, qwen)

    with pytest.raises(ModelUnavailableError) as excinfo:
        asyncio.run(router.chat_with_tools(MESSAGES))

    assert router.degraded is True
    assert excinfo.value.public()["attempts"]
    # 超时类重试 1 次（共 2 次）
    assert len(qwen.calls) == 2


def test_token_and_cost_accumulated_from_price_table() -> None:
    result = ProviderResult(
        text="ok",
        tool_calls=(ToolCall(id="c1", name="file_read", arguments={}),),
        finish_reason="tool_calls",
        model="deepseek-chat",
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
    )
    deepseek = FakeProvider("deepseek", "deepseek-chat", script=[result, result])
    router = build_router(deepseek)
    router.begin_run()
    first = asyncio.run(router.chat_with_tools(MESSAGES))
    second = asyncio.run(router.chat_with_tools(MESSAGES))

    # 2.0 元/M 输入 + 8.0 元/M 输出
    assert first.cost_cny == pytest.approx(6.0)
    assert second.cost_cny == pytest.approx(6.0)
    usage = router.usage_snapshot()
    assert usage["input_tokens"] == 2_000_000
    assert usage["output_tokens"] == 1_000_000
    assert usage["total_tokens"] == 3_000_000
    assert usage["cost_cny"] == pytest.approx(12.0)
    assert usage["calls"] == 2
    assert usage["by_provider"][0]["provider"] == "deepseek"


def test_probe_chain_falls_back_to_available_provider() -> None:
    deepseek = FakeProvider("deepseek", "deepseek-chat", script=[False])
    qwen = FakeProvider("qwen", "qwen-plus", script=[True])
    router = build_router(deepseek, qwen)
    ok_provider, reason = asyncio.run(router.probe_chain())
    assert ok_provider == "qwen"
    assert reason == ""
    assert router.ensure_available() is True
    assert router.active_provider == "qwen"
    assert router.model_for("qwen") == "qwen-plus"


def test_probe_chain_reports_reason_when_all_unavailable() -> None:
    deepseek = FakeProvider("deepseek", "deepseek-chat", script=[False])
    qwen = FakeProvider("qwen", "qwen-plus", script=[False])
    router = build_router(deepseek, qwen)
    ok_provider, reason = asyncio.run(router.probe_chain())
    assert ok_provider is None
    assert "deepseek" in reason and "qwen" in reason
    assert router.ensure_available() is False


def test_providers_listing_has_no_secret_and_priority() -> None:
    router = build_router(
        FakeProvider("deepseek", "deepseek-chat"), FakeProvider("qwen", "qwen-plus")
    )
    rows = router.providers()
    assert [row["provider"] for row in rows] == ["deepseek", "qwen"]
    assert rows[0]["priority"] == 1 and rows[1]["priority"] == 2
    assert rows[0]["enabled"] is True and rows[1]["enabled"] is False
    assert rows[0]["api_key_ref"].startswith("env:")
    dumped = str(rows)
    assert "sk-deepseek" not in dumped


def test_explicit_provider_does_not_fall_back() -> None:
    deepseek = FakeProvider(
        "deepseek",
        "deepseek-chat",
        script=[ProviderError(ErrorCategory.AUTH, "bad", provider="deepseek", status_code=401)],
    )
    qwen = FakeProvider("qwen", "qwen-plus")
    router = build_router(deepseek, qwen)
    with pytest.raises(ModelUnavailableError):
        asyncio.run(router.chat(MESSAGES, provider="deepseek"))
    assert qwen.calls == []


def test_begin_run_resets_usage() -> None:
    deepseek = FakeProvider("deepseek", "deepseek-chat")
    router = build_router(deepseek)
    asyncio.run(router.chat_with_tools(MESSAGES))
    assert router.usage_snapshot()["calls"] == 1
    router.begin_run()
    assert router.usage_snapshot()["calls"] == 0
    assert router.usage_snapshot()["total_tokens"] == 0


def test_price_for_unknown_model_uses_provider_default() -> None:
    router = build_router(FakeProvider("deepseek", "deepseek-chat"))
    price = router.price_for("deepseek", "unknown-model")
    assert (price.cache_miss, price.output) == (2.0, 8.0)
    # 表里没给命中价时按未命中价的一半兜底，不把命中算成免费
    assert price.cache_hit == 1.0 and price.hit_known is False
    qwen = router.price_for("qwen", "qwen-plus")
    assert (qwen.cache_miss, qwen.output) == (0.8, 2.0)
    fallback_price = router.price_for("nobody", "x")
    assert (fallback_price.cache_miss, fallback_price.output) == (2.0, 8.0)


def test_qwen_glm_unconfigured_probe_paths_without_network() -> None:
    """无 Key 时千问/GLM 的 probe 直接返回不可用原因，不发网络请求。"""
    settings = make_settings(
        qwen_api_key="", glm_api_key="", model_fallback_chain="deepseek,qwen,glm,mock"
    )
    router = ModelRouter(settings, price_table=PRICES)
    for provider in ("qwen", "glm"):
        ok, reason = asyncio.run(router.probe(provider))
        assert ok is False
        assert "未配置" in reason
    # fallback 链顺序不变：deepseek -> qwen -> glm
    assert router.chain() == ["deepseek", "qwen", "glm"]


def test_price_table_yaml_is_configurable() -> None:
    """成本表从 backend/config/model_prices.yaml 读取（元/百万 tokens）。"""
    from app.agents.model_router import PRICE_TABLE_PATH, load_price_table

    assert PRICE_TABLE_PATH.exists(), PRICE_TABLE_PATH
    table = load_price_table()
    assert table["currency"] == "CNY"
    assert table["unit"] == "per_million_tokens"
    # 官方口径（闲时价，元/百万）：输入命中 0.02、未命中 1.0、输出 4.0；高峰翻倍
    assert table["providers"]["deepseek"]["models"]["deepseek-flash"] == {
        "input_cache_hit": 0.02,
        "input_cache_miss": 1.0,
        "output": 4.0,
    }
    router = ModelRouter(make_settings(), price_table=table)
    # 周六中午 = 闲时：1M 输入（全未命中）+ 1M 输出 = 1 + 4
    weekend = datetime(2026, 10, 31, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    assert router.estimate_cost(
        "deepseek-flash", "deepseek", 1_000_000, 1_000_000, at=weekend
    ) == pytest.approx(5.0)
    # 工作日 10:00 是高峰，官方价翻倍
    peak = datetime(2026, 10, 28, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    assert router.estimate_cost(
        "deepseek-flash", "deepseek", 1_000_000, 1_000_000, at=peak
    ) == pytest.approx(10.0)
    # 缓存命中按 0.02 计：同样 1M 输入，全命中比全未命中便宜 50 倍
    assert router.estimate_cost(
        "deepseek-flash", "deepseek", 1_000_000, 0, cache_hit_tokens=1_000_000, at=weekend
    ) == pytest.approx(0.02)
    # 旧别名走同一档价，不会掉进 default 的 ¥2/¥8 把账单放大几十倍
    assert router.estimate_cost("deepseek-chat", "deepseek", 1_000_000, 0, at=weekend) == 1.0


def test_reset_providers_picks_up_new_endpoint() -> None:
    """设置页刚填完接口地址：不清缓存就得重启才生效，所以改完必须重建实例。"""
    settings = make_settings(
        model_provider="workbuddy",
        model_name="workbuddy-chat",
        workbuddy_api_key="wb-test-key-1234",
        workbuddy_base_url="https://first.example/v1",
    )
    router = ModelRouter(settings)

    first = router._provider("workbuddy")
    assert first is not None
    assert first.base_url == "https://first.example/v1"

    settings.workbuddy_base_url = "https://second.example/v1"
    router.reset_providers()
    second = router._provider("workbuddy")
    assert second is not None and second is not first
    assert second.base_url == "https://second.example/v1"
