"""引擎注册表：id 与展示名分开，/health 的判定只认 id。

以前拿中文 name 当 key，而配置里是 mock / real 这种英文 ID，
engine_supported 永远查不到（恒 False），engines 列表也被塞成了中文名。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.agents.registry import engine_capabilities
from app.api.v1.health import _engine_state


def _container(engine: str) -> SimpleNamespace:
    settings = SimpleNamespace(
        engine_kind=engine,
        real_model_configured=True,
        model_ready=True,
        mock_mode=False,
        configured_provider="deepseek",
        provider_api_key=lambda _provider: "sk-test",
        provider_base_url=lambda _provider: "http://localhost/v1",
    )
    runtime = SimpleNamespace(degraded=False, degraded_reason="")
    return SimpleNamespace(settings=settings, runtime=runtime)


def test_capabilities_keep_id_and_display_name_apart():
    by_id = {item["id"]: item for item in engine_capabilities()}
    assert set(by_id) == {"mock", "real", "deepagents"}
    assert by_id["mock"]["status"] == "implemented"
    assert by_id["real"]["status"] == "implemented"
    assert by_id["deepagents"]["status"] == "planned"
    # name 只给人看，不是判断用的键
    assert by_id["mock"]["name"] != "mock"


def test_engine_supported_uses_id_not_chinese_name():
    assert _engine_state(_container("real"))["engine_supported"] is True
    assert _engine_state(_container("mock"))["engine_supported"] is True
    assert _engine_state(_container("deepagents"))["engine_supported"] is False
