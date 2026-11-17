"""保存供应商 Key：明文只落本地 .env + 进程内存，接口只回掩码。

守护「添加 Key 无法真正使用」的回归：此前只允许登记 env:NAME，
用户粘贴 Key 无处可存，界面上按钮形同虚设。
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
        self.applied = 0

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
        self.applied += 1


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelService:
    settings = Settings()
    # 落盘目标指向临时 .env，避免污染仓库
    monkeypatch.setattr(Settings, "env_file_path", property(lambda self: tmp_path / ".env"))
    # apply_secret 会改进程环境变量：显式还原，避免污染其它用例
    for name in ("DEEPSEEK_API_KEY", "GLM_API_KEY", "CUSTOM_KEY"):
        monkeypatch.delenv(name, raising=False)
    return ModelService(FakeModelConfigRepo(), settings, FakeSettingsService())  # type: ignore[arg-type]


def test_save_key_sets_env_and_returns_mask(service: ModelService) -> None:
    result = service.save_key("env:deepseek", "sk-abcdef1234567890")

    assert result["configured"] is True
    assert result["api_key_ref"] == "env:DEEPSEEK_API_KEY"
    # 只回显掩码，绝不含明文
    assert result["masked"] == "sk-****7890"
    assert "abcdef" not in str(result)
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-abcdef1234567890"


def test_save_key_makes_provider_configured(service: ModelService) -> None:
    service.save_key("env:deepseek", "sk-abcdef1234567890")
    row = next(item for item in service.list_models() if item["provider"] == "deepseek")
    assert row["configured"] is True


def test_save_key_persists_to_env_file(service: ModelService, tmp_path: Path) -> None:
    result = service.save_key("env:deepseek", "sk-abcdef1234567890", "CUSTOM_KEY")
    assert result["persisted"] is True
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "CUSTOM_KEY=sk-abcdef1234567890" in content


def test_save_key_upserts_existing_env_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=old-value\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr(Settings, "env_file_path", property(lambda self: env_file))
    service = ModelService(FakeModelConfigRepo(), Settings(), FakeSettingsService())  # type: ignore[arg-type]

    service.save_key("env:deepseek", "sk-new-value-123456")

    content = env_file.read_text(encoding="utf-8")
    assert "old-value" not in content
    assert "DEEPSEEK_API_KEY=sk-new-value-123456" in content
    assert "OTHER=1" in content


@pytest.mark.parametrize("bad", ["", "   ", "short", "has space 123456"])
def test_save_key_rejects_invalid_key(service: ModelService, bad: str) -> None:
    with pytest.raises(AppError) as exc:
        service.save_key("env:deepseek", bad)
    assert exc.value.status_code == 400


def test_save_key_rejects_invalid_env_name(service: ModelService) -> None:
    with pytest.raises(AppError) as exc:
        service.save_key("env:deepseek", "sk-abcdef1234567890", "bad-name")
    assert exc.value.status_code == 400


def test_save_key_accepts_omitted_env_name(service: ModelService) -> None:
    """env_name 缺省时必须走供应商默认名，不能 500。"""
    result = service.save_key("env:glm", "glm-abcdef1234567890", None)
    assert result["api_key_ref"] == "env:GLM_API_KEY"
    assert result["configured"] is True


def test_save_key_unknown_model_raises_not_found(service: ModelService) -> None:
    with pytest.raises(AppError) as exc:
        service.save_key("env:nope", "sk-abcdef1234567890")
    assert exc.value.status_code == 404
