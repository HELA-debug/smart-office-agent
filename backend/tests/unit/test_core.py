"""core 层单元测试：事件契约、安全工具、配置、标题派生。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.events import (
    APPROVAL_REQUIRED,
    EVENT_JSON_SCHEMA,
    RUN_STARTED,
    build_event,
    parse_last_event_id,
    sse_frame,
    validate_event_data,
)
from app.core.security import (
    ensure_within,
    mask_email,
    safe_filename,
    sanitize,
)
from app.core.utils import (
    count_chars,
    derive_thread_title,
    is_default_thread_title,
    new_id,
)
from jsonschema import validate


def test_event_envelope_matches_json_schema():
    data = build_event(
        "r_001",
        RUN_STARTED,
        thread_id="th_001",
        mode="mock",
        model="mock-scripted",
        started_at="2026-10-23T10:00:00+08:00",
    )
    validate(instance=data, schema=EVENT_JSON_SCHEMA)
    assert validate_event_data(RUN_STARTED, data) == []
    assert data["version"] == 1


def test_event_required_fields_detection():
    missing = validate_event_data(APPROVAL_REQUIRED, {"version": 1, "run_id": "r_x"})
    assert "approval_id" in missing and "preview" in missing


def test_sse_frame_format():
    frame = sse_frame(7, RUN_STARTED, {"version": 1, "run_id": "r_1"})
    assert frame.startswith("id: 7\nevent: run.started\ndata: ")
    assert frame.endswith("\n\n")
    assert "\n" not in frame.split("data: ", 1)[1].strip()


def test_parse_last_event_id():
    assert parse_last_event_id("12") == 12
    assert parse_last_event_id(None) is None
    assert parse_last_event_id("abc") is None


def test_title_derivation_and_defaults():
    assert is_default_thread_title("新会话")
    assert is_default_thread_title(" New Chat ")
    assert not is_default_thread_title("我的周报")
    long_message = "  把这份材料整理成 600 字周报，\n发我邮箱草稿，并标注来源文件  "
    title = derive_thread_title(long_message)
    assert title.startswith("把这份材料整理成")
    assert title.endswith("…")
    assert len(title) == 25
    assert "\n" not in title


def test_security_helpers(tmp_path: Path):
    assert sanitize({"api_key": "abc", "name": "ok"}) == {"api_key": "***", "name": "ok"}
    assert mask_email("someone@example.com") == "so***@example.com"
    assert safe_filename("../a/b:?.docx") == "b_.docx"
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        ensure_within(root / ".." / "escape.txt", root)
    assert count_chars("a b\nc") == 3
    assert new_id("th").startswith("th_")


def test_settings_paths_and_redaction(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'x.db'}",
        upload_dir=str(tmp_path / "u"),
        artifact_dir=str(tmp_path / "a"),
        mock_mode=True,
        model_provider="mock",
    )
    settings.ensure_dirs()
    assert settings.uploads_path.exists() and settings.artifacts_path.exists()
    assert settings.sqlite_path == tmp_path / "x.db"
    redacted = settings.redacted()
    assert "deepseek_api_key" not in redacted
    assert redacted["model_provider"] == "mock"


def test_provider_key_resolution_matches_providers_base():
    """与 app/providers/base.resolve_api_key 对齐：deepseek 兼容 OPENAI，qwen/glm 不复用。"""
    only_openai = Settings(
        deepseek_api_key="",
        qwen_api_key="",
        glm_api_key="",
        openai_api_key="sk-openai",
    )
    assert only_openai.provider_api_key("deepseek") == "sk-openai"
    assert only_openai.provider_api_key("openai") == "sk-openai"
    assert only_openai.provider_api_key("qwen") == ""
    assert only_openai.provider_api_key("glm") == ""

    dashscope = Settings(
        qwen_api_key="",
        dashscope_api_key="sk-dashscope",
        deepseek_api_key="sk-deepseek",
        glm_api_key="sk-glm",
    )
    assert dashscope.qwen_api_key == "sk-dashscope"
    assert dashscope.provider_api_key("qwen") == "sk-dashscope"
    assert dashscope.provider_api_key("glm") == "sk-glm"


def test_engine_kind_normalization():
    # 显式传值，别用 Settings() 去断言默认档：它会读本机 .env，而开发机为了
    # 不烧钱把它设成 mock、生产环境却是 real。那样测的是这台机器的配置，
    # 不是归一化逻辑本身。
    assert Settings(engine="real").engine_kind == "real"
    assert Settings(engine="mock").engine_kind == "mock"
    assert Settings(engine="deepagents").engine_kind == "deepagents"
    assert Settings(engine="unknown").engine_kind == "real"


def test_run_usage_and_actual_provider_helpers():
    from app.services.run_service import RunService

    data = {
        "provider": "deepseek",
        "usage": {
            "total_tokens": 500,
            "cost_cny": 0.02,
            "by_provider": [
                {"provider": "qwen", "input_tokens": 10, "output_tokens": 5},
                {"provider": "deepseek", "input_tokens": 300, "output_tokens": 185},
            ],
        },
    }
    assert RunService._usage_metrics(data) == (500, 0.02)
    assert RunService._actual_provider(data, "deepseek", "real") == "deepseek"
    assert (
        RunService._actual_provider(
            {"usage": {"by_provider": [{"provider": "glm", "input_tokens": 1}]}},
            "deepseek",
            "real",
        )
        == "glm"
    )
    # mock 引擎（fallback 后）记录实际 mock
    assert RunService._actual_provider({}, "deepseek", "mock") == "mock"
    # 无 usage 时回退事件顶层字段
    assert RunService._usage_metrics({"tokens": 9, "cost_cny": 0.1}) == (9, 0.1)
