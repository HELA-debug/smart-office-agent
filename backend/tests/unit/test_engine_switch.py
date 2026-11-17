"""执行引擎与演示模式必须是同一个开关。

真实踩到的：设置页把「执行引擎」选成真实模型，「演示模式」开关还开着，保存后 DB 里
留下 engine=real + mock_mode=true。重启后账号其实一直在跑 mock：设置页写着「真实模型」，
顶栏徽标写着「mock 连接器」，两处各说各话，用户只能怀疑「你根本没调大模型」。
"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.config import Settings
from app.services.settings_service import SettingsService


class FakeSettingsRepo:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self.items: dict[str, Any] = dict(initial or {})

    def list_all(self) -> list[Any]:
        return [_Item(key, value) for key, value in self.items.items()]

    def upsert(self, item: Any) -> Any:
        self.items[item.key] = item.value
        return item


class _Item:
    def __init__(self, key: str, value: Any) -> None:
        self.key = key
        self.value = value
        self.scope = "global"
        self.is_secret = False
        self.updated_at = "2026-10-31T12:00:00+08:00"


def make_settings(**patch: Any) -> Settings:
    # 不要读仓库里的 .env：用例要自己控制 ENGINE / MOCK_MODE
    base: dict[str, Any] = {
        "engine": "real",
        "mock_mode": True,
        "model_provider": "deepseek",
        "model_name": "deepseek-flash",
        "deepseek_api_key": "sk-test",
        "deepseek_base_url": "https://api.deepseek.com/v1",
    }
    base.update(patch)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_saving_real_engine_clears_mock_mode() -> None:
    repo = FakeSettingsRepo({"engine": "real", "mock_mode": True})
    service = SettingsService(repo, make_settings())
    service.apply_persisted()

    effective = service.update({"engine": "real"})

    assert effective["engine"] == "real"
    assert effective["mock_mode"] is False
    # 两个键必须一起落库，否则下次启动又是一对矛盾的值
    assert repo.items["mock_mode"] is False
    assert repo.items["engine"] == "real"


def test_saving_mock_engine_turns_mock_mode_on() -> None:
    repo = FakeSettingsRepo({"engine": "real", "mock_mode": False})
    service = SettingsService(repo, make_settings(mock_mode=False))
    service.apply_persisted()

    effective = service.update({"engine": "mock"})

    assert effective["engine"] == "mock"
    assert effective["mock_mode"] is True
    assert repo.items["mock_mode"] is True


def test_demo_toggle_also_flips_engine() -> None:
    """老客户端只会传 mock_mode：也要把 engine 一起改掉。"""
    repo = FakeSettingsRepo({"engine": "real", "mock_mode": False})
    service = SettingsService(repo, make_settings(mock_mode=False))
    service.apply_persisted()

    effective = service.update({"mock_mode": True})

    assert effective["engine"] == "mock"
    assert effective["mock_mode"] is True


def test_contradictory_rows_heal_on_load() -> None:
    """DB 里已经存在的矛盾组合，启动时按 engine 为准修好，不再无声跑 mock。"""
    repo = FakeSettingsRepo({"engine": "real", "mock_mode": True})
    settings = make_settings()
    service = SettingsService(repo, settings)

    service.apply_persisted()

    assert settings.engine == "real"
    assert settings.mock_mode is False
    # 修好的值写回 DB：否则下次保存又把矛盾带回来
    assert repo.items["mock_mode"] is False
    # 真实模型可用：Key 与 base_url 都在
    assert settings.real_model_configured is True


def test_health_reason_explains_mock_when_forced_by_switch() -> None:
    """真实模型被开关挡住时，/health 必须给出人话原因，不能只说「mode=mock」。"""
    from app.api.v1.health import _engine_reason

    class _Runtime:
        degraded = False
        degraded_reason = ""

    class _Container:
        runtime = _Runtime()
        settings = make_settings(mock_mode=True)  # 环境变量 MOCK_MODE=true

    reason = _engine_reason(_Container(), "real", "mock")  # type: ignore[arg-type]
    assert "MOCK_MODE=true" in reason


def test_health_reason_names_missing_key() -> None:
    from app.api.v1.health import _engine_reason

    class _Runtime:
        degraded = False
        degraded_reason = ""

    class _Container:
        runtime = _Runtime()
        settings = make_settings(mock_mode=False, deepseek_api_key="")

    reason = _engine_reason(_Container(), "real", "mock")  # type: ignore[arg-type]
    assert "API Key" in reason


def test_health_reason_empty_when_real() -> None:
    from app.api.v1.health import _engine_reason

    class _Runtime:
        degraded = False
        degraded_reason = ""

    class _Container:
        runtime = _Runtime()
        settings = make_settings(mock_mode=False)

    assert _engine_reason(_Container(), "real", "real") == ""  # type: ignore[arg-type]


@pytest.mark.parametrize("engine", ["real", "mock", "deepagents"])
def test_engine_and_mock_mode_never_disagree(engine: str) -> None:
    service = SettingsService(FakeSettingsRepo(), make_settings())
    effective = service.update({"engine": engine})
    assert (effective["engine"] == "mock") == bool(effective["mock_mode"])
