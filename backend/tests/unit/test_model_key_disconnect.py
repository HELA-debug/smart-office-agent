"""断开供应商 Key：进程 env、Settings、本地 .env 三处必须同清。

守护「分享/部署项目后别人还能用我的 Key」的回归：只清内存不清 .env，
那行 Key 会跟着数据目录一起被拷走，费用照记在原主头上。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from app.core.config import Settings
from app.core.errors import AppError
from app.services.model_service import ModelService


class FakeModelConfigRepo:
    def __init__(self) -> None:
        self.items: dict[str, Any] = {}

    def list_all(self) -> list[Any]:
        return list(self.items.values())

    def get(self, config_id: str) -> Any | None:
        return self.items.get(config_id)

    def add(self, config: Any) -> Any:
        self.items[config.id] = config
        return config

    def update(self, config: Any) -> Any:
        self.items[config.id] = config
        return config

    def delete(self, config_id: str) -> None:
        self.items.pop(config_id, None)


class FakeSettingsService:
    def __init__(self) -> None:
        self.router_resets = 0

    def resolve_key_ref(self, ref: str) -> str:
        if not ref.startswith("env:"):
            return ""
        return os.environ.get(ref.split(":", 1)[1], "")

    def provider_key_ref(self, provider: str) -> str:
        return f"env:{provider.upper()}_API_KEY"

    def model_config_public(self, config: Any) -> dict[str, Any]:
        return {
            "id": config.id,
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "api_key_ref": config.api_key_ref,
            "priority": config.priority,
            "enabled": config.enabled,
            "extra": dict(config.extra or {}),
        }

    def apply_persisted(self) -> None:
        pass

    def reset_router(self) -> None:
        self.router_resets += 1


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelService:
    settings = Settings()
    monkeypatch.setattr(Settings, "env_file_path", property(lambda self: tmp_path / ".env"))
    for name in ("DEEPSEEK_API_KEY", "GLM_API_KEY", "CUSTOM_KEY"):
        monkeypatch.delenv(name, raising=False)
    return ModelService(FakeModelConfigRepo(), settings, FakeSettingsService())  # type: ignore[arg-type]


def test_disconnect_clears_env_memory_and_env_file(service: ModelService, tmp_path: Path) -> None:
    """断开后三处同清：进程 env、Settings 字段、.env 里的那一行。"""
    service.save_key("env:deepseek", "sk-abcdef1234567890")
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-abcdef1234567890"
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=sk-abcdef1234567890\nOTHER_SETTING=keep\n",
        encoding="utf-8",
    )

    result = service.disconnect_key("env:deepseek")

    assert result["disconnected"] is True
    assert result["configured"] is False
    assert result["persisted"] is True
    assert os.environ.get("DEEPSEEK_API_KEY") is None
    assert service.settings.deepseek_api_key == ""
    # 别的行不能跟着陪葬
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in content
    assert "OTHER_SETTING=keep" in content


def test_disconnect_makes_provider_unconfigured(service: ModelService) -> None:
    service.save_key("env:deepseek", "sk-abcdef1234567890")
    service.disconnect_key("env:deepseek")
    row = next(item for item in service.list_models() if item["provider"] == "deepseek")
    assert row["configured"] is False


def test_disconnect_keeps_endpoint_and_resets_router(service: ModelService) -> None:
    """接口地址等登记信息保留（换一把 Key 就能接回），路由器缓存必须清。"""
    service.save_key("env:deepseek", "sk-abcdef1234567890")
    row_before = next(item for item in service.list_models() if item["provider"] == "deepseek")
    fake_settings_service = service.settings_service
    assert isinstance(fake_settings_service, FakeSettingsService)

    service.disconnect_key("env:deepseek")

    row_after = next(item for item in service.list_models() if item["provider"] == "deepseek")
    assert row_after["base_url"] == row_before["base_url"]
    assert fake_settings_service.router_resets == 1


def test_disconnect_without_env_file_is_ok(service: ModelService) -> None:
    """.env 本来就不存在（从没落过盘）：断开仍算成功，不能 500。"""
    service.settings.apply_secret("DEEPSEEK_API_KEY", "sk-abcdef1234567890")

    result = service.disconnect_key("env:deepseek")

    assert result["persisted"] is True
    assert os.environ.get("DEEPSEEK_API_KEY") is None


def test_disconnect_clears_stale_probe_status(service: ModelService) -> None:
    """断开前那声「连接正常」不能再挂在列表上，否则像「断了却还能用」。"""
    service._probe_status["env:deepseek"] = {"ok": True}

    service.disconnect_key("env:deepseek")

    assert "env:deepseek" not in service._probe_status


def test_disconnect_unknown_model_raises_not_found(service: ModelService) -> None:
    with pytest.raises(AppError) as exc:
        service.disconnect_key("env:nope")
    assert exc.value.status_code == 404


def test_clear_secret_removes_only_named_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings.clear_secret 是三清的底座：只删点名那行，相邻行原样。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=sk-to-remove\nGLM_API_KEY=keep-me\nQWEN_API_KEY=also-keep\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Settings, "env_file_path", property(lambda self: env_file))
    settings = Settings()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-to-remove")

    assert settings.clear_secret("DEEPSEEK_API_KEY") is True

    assert os.environ.get("DEEPSEEK_API_KEY") is None
    content = env_file.read_text(encoding="utf-8")
    assert "sk-to-remove" not in content
    assert "GLM_API_KEY=keep-me" in content
    assert "QWEN_API_KEY=also-keep" in content
