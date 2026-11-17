"""导入技能的「让模型写一版」接口 + WorkBuddy 供应商出现在模型列表里。

演示模式下（conftest 的 settings）没有可用模型，所以这里断言的是降级路径，
真实模型路径由 tests/unit/test_skill_drafter.py 用假 router 覆盖。
"""

from __future__ import annotations

import httpx


def test_draft_returns_importable_markdown_in_demo_mode(client: httpx.Client) -> None:
    response = client.post(
        "/api/v1/skills/draft", json={"idea": "把录音转成会议纪要，只留结论和待办"}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["source"] == "local"  # 演示模式没有真实模型
    assert body["markdown"].startswith("---")
    assert "name:" in body["markdown"]
    assert body["title"]
    assert body["triggers"]
    assert "把录音转成会议纪要" in body["markdown"]


def test_draft_rejects_empty_idea(client: httpx.Client) -> None:
    response = client.post("/api/v1/skills/draft", json={"idea": ""})
    assert response.status_code in (400, 422)
    assert response.json()["error"]["code"]


def test_workbuddy_listed_without_endpoint(client: httpx.Client) -> None:
    models = {item["provider"]: item for item in client.get("/api/v1/models").json()["models"]}

    assert "workbuddy" in models
    workbuddy = models["workbuddy"]
    # 没有默认端点，也没配 Key：不能假装「已配置」
    assert workbuddy["base_url"] == ""
    assert workbuddy["configured"] is False
    assert workbuddy["api_key_ref"] == "env:WORKBUDDY_API_KEY"
    assert workbuddy["model"] == "workbuddy-chat"


def test_test_connection_explains_missing_endpoint(client: httpx.Client) -> None:
    response = client.post("/api/v1/models/env:workbuddy/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    # 缺地址时给的是「去填接口」的人话，而不是一句 base_url 不安全
    assert "接口地址" in body["reason"]
