"""B3P 收尾：模型 Key 解析一致性、ENGINE 配置、runs 实际 provider/usage、OpenAPI 别名。"""

from __future__ import annotations

import json

import httpx
from tests.helpers import make_docx, read_sse

PREFIX = "/api/v1"


def _model(client: httpx.Client, model_id: str) -> dict:
    for item in client.get(f"{PREFIX}/models").json()["models"]:
        if item["id"] == model_id:
            return item
    raise AssertionError(f"model not found: {model_id}")


def test_models_configured_matches_provider_key_rules(client: httpx.Client):
    """测试环境：只有 OPENAI_API_KEY；deepseek 兼容复用，qwen/glm 不得显示 configured。"""
    body = client.get(f"{PREFIX}/models").text
    assert "sk-" not in body
    deepseek = _model(client, "env:deepseek")
    qwen = _model(client, "env:qwen")
    glm = _model(client, "env:glm")
    assert deepseek["configured"] is True
    assert deepseek["api_key_ref"] == "env:DEEPSEEK_API_KEY"
    assert qwen["configured"] is False
    assert qwen["api_key_ref"] == "env:DASHSCOPE_API_KEY"
    assert glm["configured"] is False
    assert glm["api_key_ref"] == "env:GLM_API_KEY"


def test_models_default_names_per_provider_and_registration_override(client: httpx.Client):
    """默认模型名必须按 provider（qwen-plus/glm-4-plus/gpt-4o-mini），登记后以登记值为准。"""
    deepseek = _model(client, "env:deepseek")
    qwen = _model(client, "env:qwen")
    glm = _model(client, "env:glm")
    openai = _model(client, "env:openai")
    assert deepseek["model"] == "deepseek-flash"
    assert qwen["model"] == "qwen-plus"
    assert glm["model"] == "glm-4-plus"
    assert openai["model"] == "gpt-4o-mini"

    registered = client.post(
        f"{PREFIX}/models",
        json={
            "provider": "qwen",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-max",
            "api_key_ref": "env:DASHSCOPE_API_KEY",
        },
    )
    assert registered.status_code == 201, registered.text
    qwen_after = _model(client, "env:qwen")
    assert qwen_after["model"] == "qwen-max"
    assert qwen_after["builtin"] is False


def test_settings_secrets_follow_provider_rules(client: httpx.Client):
    body = client.get(f"{PREFIX}/settings").json()
    secrets = body["secrets"]
    assert secrets["deepseek"]["configured"] is True
    assert secrets["deepseek"]["ref"] == "env:DEEPSEEK_API_KEY"
    assert secrets["deepseek"].get("via") == "env:OPENAI_API_KEY"
    assert secrets["qwen"]["configured"] is False
    assert secrets["qwen"]["ref"] == "env:DASHSCOPE_API_KEY"
    assert secrets["glm"]["configured"] is False
    assert "sk-" not in json.dumps(secrets)


def test_engine_setting_read_write_and_health(client: httpx.Client):
    try:
        settings = client.get(f"{PREFIX}/settings").json()
        assert settings["engine"] == "mock"  # 测试 fixture 显式配置
        assert settings["sources"]["engine"] in ("env", "db")

        real = client.put(f"{PREFIX}/settings", json={"engine": "real"})
        assert real.status_code == 200, real.text
        assert real.json()["engine"] == "real"
        assert real.json()["sources"]["engine"] == "db"

        health = client.get(f"{PREFIX}/health").json()
        assert health["engine"] == "real"
        # 测试环境 mock_mode=true 无真实 Key → 自动降级 mock
        assert health["engine_effective"] == "mock"
        assert health["engine_supported"] is True
        assert health["mode"] == "mock"

        deepagents = client.put(f"{PREFIX}/settings", json={"engine": "deepagents"}).json()
        assert deepagents["engine"] == "deepagents"
        health = client.get(f"{PREFIX}/health").json()
        assert health["engine"] == "deepagents"
        assert health["engine_supported"] is False
        assert health["engine_effective"] == "mock"

        invalid = client.put(f"{PREFIX}/settings", json={"engine": "langgraph"})
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "BAD_REQUEST"
    finally:
        client.put(f"{PREFIX}/settings", json={"engine": "mock"})


def test_run_records_actual_provider_and_usage(client: httpx.Client):
    thread_id = client.post(f"{PREFIX}/threads", json={"title": "B3P provider"}).json()["thread_id"]
    with client.stream(
        "POST",
        f"{PREFIX}/threads/{thread_id}/runs/stream",
        json={"message": "写一份周报", "mode": "mock"},
    ) as response:
        events = read_sse(response.iter_lines(), stop_at="run.completed")
        run_id = events[0][1]["run_id"]
    completed = events[-1][1]
    assert completed["status"] == "completed"

    run = client.get(f"{PREFIX}/runs/{run_id}").json()
    assert run["provider"] == "mock"  # 实际引擎供应商，而非启动探测值
    assert run["tokens"] == completed["tokens"] > 0
    assert run["cost_cny"] == completed["cost_cny"]


def test_openapi_v1_alias(client: httpx.Client):
    alias = client.get(f"{PREFIX}/openapi.json")
    assert alias.status_code == 200
    assert "application/json" in alias.headers["content-type"]
    schema = alias.json()
    assert "/api/v1/health" in schema["paths"]
    root_schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == set(root_schema["paths"])


def test_upload_docx_still_works_for_regression(client: httpx.Client):
    """回归：B3P 改动未影响上传/审批主链路。"""
    thread_id = client.post(f"{PREFIX}/threads", json={"title": "B3P 回归"}).json()["thread_id"]
    docx = make_docx(["一、本周进展", "完成联调。", "四、下周计划", "补齐测试。"])
    uploaded = client.post(
        f"{PREFIX}/threads/{thread_id}/files",
        files={
            "file": (
                "记录.docx",
                docx,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["parsed"] is True
