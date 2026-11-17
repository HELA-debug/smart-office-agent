"""核心 smoke（10 条）：health / 会话 / 设置 / 模型与扩展点。

纯黑盒：只通过 /api/v1/* HTTP 契约断言（mock 服务）。
"""
from __future__ import annotations

import uuid

import httpx

from conftest import assert_error

V1 = "/api/v1"


# 1. health（v1）
def test_health_v1(client: httpx.Client) -> None:
    resp = client.get(f"{V1}/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mode"] == "mock"
    assert body["mock"] is True
    assert body["version"].startswith("0.2.")
    assert body["tools"] >= 6
    assert "mock" in body["engines"]
    assert body["trace_id"] == resp.headers["X-Trace-ID"]


# 2. 旧 /api 兼容 + Deprecation 头
def test_health_legacy_deprecation(client: httpx.Client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("Deprecation") == "true"
    assert "successor-version" in resp.headers.get("Link", "")
    assert resp.json()["mode"] == "mock"
    assert resp.json()["trace_id"] == resp.headers["X-Trace-ID"]


# 3. 建会话 + 详情
def test_thread_create_and_detail(client: httpx.Client) -> None:
    resp = client.post(f"{V1}/threads", json={"title": "冒烟-建会话"})
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["thread_id"].startswith("th_")
    assert created["title"] == "冒烟-建会话"
    assert created["trace_id"]

    detail = client.get(f"{V1}/threads/{created['thread_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["thread_id"] == created["thread_id"]
    assert isinstance(body["messages"], list)
    assert isinstance(body["artifacts"], list)
    assert body["message_count"] == 0


# 4. 会话列表：搜索 + 分页
def test_thread_list_search_pagination(client: httpx.Client) -> None:
    token = f"smoke-search-{uuid.uuid4().hex[:8]}"
    ids = [
        client.post(f"{V1}/threads", json={"title": f"{token}-{index}"}).json()["thread_id"]
        for index in range(3)
    ]
    page1 = client.get(f"{V1}/threads", params={"q": token, "page": 1, "page_size": 2})
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert body1["total"] == 3
    assert len(body1["threads"]) == 2
    assert body1["page"] == 1 and body1["page_size"] == 2
    assert all(token in item["title"] for item in body1["threads"])

    page2 = client.get(f"{V1}/threads", params={"q": token, "page": 2, "page_size": 2}).json()
    assert page2["total"] == 3
    assert len(page2["threads"]) == 1
    assert {item["thread_id"] for item in page2["threads"]} <= set(ids)


# 5. 会话重命名 + 置顶
def test_thread_update_rename_pin(client: httpx.Client) -> None:
    token = f"smoke-rename-{uuid.uuid4().hex[:8]}"
    thread_id = client.post(f"{V1}/threads", json={"title": token}).json()["thread_id"]
    resp = client.patch(
        f"{V1}/threads/{thread_id}", json={"title": f"{token}-改名", "pinned": True}
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["title"] == f"{token}-改名"
    assert updated["pinned"] is True

    detail = client.get(f"{V1}/threads/{thread_id}").json()
    assert detail["title"] == f"{token}-改名"
    assert detail["pinned"] is True


# 6. 会话软删
def test_thread_soft_delete(client: httpx.Client) -> None:
    token = f"smoke-del-{uuid.uuid4().hex[:8]}"
    thread_id = client.post(f"{V1}/threads", json={"title": token}).json()["thread_id"]
    resp = client.delete(f"{V1}/threads/{thread_id}")
    assert resp.status_code == 204, resp.text
    assert_error(client.get(f"{V1}/threads/{thread_id}"), 404, "NOT_FOUND")
    listed = client.get(f"{V1}/threads", params={"q": token}).json()
    assert listed["total"] == 0


# 7. 设置生效值：来源 + 密钥只返回引用
def test_settings_effective_and_secret_refs(client: httpx.Client) -> None:
    resp = client.get(f"{V1}/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "approval_rules",
        "mock_mode",
        "model_provider",
        "model_name",
        "fallback_chain",
        "sources",
        "env_hints",
        "secrets",
        "database_url",
        "upload_dir",
        "artifact_dir",
    ):
        assert key in body, f"设置缺字段 {key}: {body}"
    assert body["mock_mode"] is True
    assert all(value in {"db", "env", "default"} for value in body["sources"].values())
    for name, secret in body["secrets"].items():
        assert isinstance(secret["configured"], bool), name
        assert secret["ref"].startswith("env:") or secret["ref"] == "", secret
    raw = resp.text
    assert "sk-" not in raw
    assert "-----BEGIN" not in raw


# 8. 设置热更新（保存即生效）
def test_settings_hot_update(client: httpx.Client, restore_settings: dict) -> None:
    resp = client.put(
        f"{V1}/settings",
        json={"approval_rules": "mail.send", "feature_flags": {"smoke": True}, "max_upload_mb": 19},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["approval_rules"] == ["mail.send"]
    assert body["feature_flags"]["smoke"] is True
    assert body["max_upload_mb"] == 19
    assert body["sources"]["approval_rules"] == "db"

    again = client.get(f"{V1}/settings").json()
    assert again["approval_rules"] == ["mail.send"]
    assert again["feature_flags"]["smoke"] is True


# 9. 设置校验：未知字段 / 越界
def test_settings_validation_errors(client: httpx.Client) -> None:
    assert_error(client.put(f"{V1}/settings", json={"unknown_field": 1}), 400, "BAD_REQUEST")
    assert_error(client.put(f"{V1}/settings", json={"max_upload_mb": 0}), 400, "BAD_REQUEST")
    assert_error(
        client.put(f"{V1}/settings", json={"model_timeout_seconds": "not-a-number"}),
        400,
        "BAD_REQUEST",
    )


# 10. 模型列表/脱敏探测 + 工具/子智能体/技能
def test_extensions_models_tools_skills_subagents(client: httpx.Client) -> None:
    # ---- 模型：只返回引用，不返回明文 Key ----
    models_resp = client.get(f"{V1}/models")
    assert models_resp.status_code == 200, models_resp.text
    models = models_resp.json()["models"]
    assert len(models) >= 4
    for model in models:
        assert model["api_key_ref"].startswith("env:"), model
        assert isinstance(model["configured"], bool)
    assert "sk-" not in models_resp.text

    # ---- 模型探测：注册一个必然没有 Key 的模型，走「未配置」分支（不联网、无费用）----
    created = client.post(
        f"{V1}/models",
        json={
            "provider": "custom",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "none",
            "api_key_ref": "env:SMOKE_NO_SUCH_KEY",
            "priority": 999,
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    probe = client.post(f"{V1}/models/{model_id}/test")
    assert probe.status_code == 200, probe.text
    probe_body = probe.json()
    assert probe_body["ok"] is False
    assert probe_body["reason"]
    assert "sk-" not in probe.text

    # ---- 工具注册表（含 schema/risk）----
    tools = client.get(f"{V1}/tools").json()["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert {"file.read", "doc.generate_report", "mail.send"} <= tool_names
    mail = next(tool for tool in tools if tool["name"] == "mail.send")
    assert mail["risk"] == "high"
    assert isinstance(mail["schema"], dict) and mail["schema"].get("type") == "object"

    # ---- 子智能体：1 实现 + 2 占位 ----
    subagents = client.get(f"{V1}/subagents").json()["subagents"]
    assert len(subagents) == 3
    statuses = {item["status"] for item in subagents}
    assert "implemented" in statuses and "placeholder" in statuses

    # ---- 技能启停：prompt_chars 立即变化，测试后恢复 ----
    skills_resp = client.get(f"{V1}/skills").json()
    assert any(skill["name"] == "weekly-report" for skill in skills_resp["skills"])
    before_chars = skills_resp["prompt_chars"]
    disabled = client.patch(f"{V1}/skills/weekly-report", json={"enabled": False}).json()
    assert disabled["enabled"] is False
    assert disabled["prompt_chars"] < before_chars
    try:
        enabled = client.patch(f"{V1}/skills/weekly-report", json={"enabled": True}).json()
        assert enabled["enabled"] is True
        assert enabled["prompt_chars"] == before_chars
    finally:
        client.patch(f"{V1}/skills/weekly-report", json={"enabled": True})
