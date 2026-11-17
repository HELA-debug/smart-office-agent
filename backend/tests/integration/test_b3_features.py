"""B3 功能集成测试：设置热更新、模型管理、会话、运行、产物、上传、模板/技能、用量审计。"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
from openpyxl import Workbook
from tests.helpers import approved_flow, has_heading, make_docx, read_sse

PREFIX = "/api/v1"


def _stream_with_approval(
    client: httpx.Client, method: str, url: str, **kwargs
) -> list[tuple[str, dict]]:
    """执行 SSE 请求，返回完整事件序列（审批卡已删，一轮跑到底）。"""
    with client.stream(method, url, **kwargs) as response:
        assert response.status_code == 200, response.text
        return read_sse(response.iter_lines())


# ---------- 1. 设置中心 ----------
def test_settings_sources_and_hot_update(client: httpx.Client):
    body = client.get(f"{PREFIX}/settings").json()
    for key in (
        "model_provider",
        "model_name",
        "fallback_chain",
        "approval_rules",
        "mock_mode",
        "max_upload_mb",
        "feature_flags",
        "sources",
        "secrets",
    ):
        assert key in body, key
    assert body["secrets"]["deepseek"]["ref"] == "env:DEEPSEEK_API_KEY"
    assert "sk-" not in client.get(f"{PREFIX}/settings").text

    try:
        updated = client.put(
            f"{PREFIX}/settings",
            json={
                "mock_mode": True,
                "model_provider": "mock",
                "model_name": "mock-scripted",
                "fallback_chain": ["mock"],
                "approval_rules": ["doc.generate_report"],
                "max_upload_mb": 12,
                "feature_flags": {"artifacts_center": True},
            },
        )
        assert updated.status_code == 200, updated.text
        data = updated.json()
        assert data["sources"]["model_provider"] == "db"
        assert data["feature_flags"] == {"artifacts_center": True}
        assert data["max_upload_mb"] == 12

        # 热更新立即反映到 health（无需重启）
        health = client.get(f"{PREFIX}/health").json()
        assert health["mode"] == "mock" and health["model"] == "mock-scripted"

        # 非法白名单外字段 → 400
        bad = client.put(f"{PREFIX}/settings", json={"database_url": "sqlite:///x.db"})
        assert bad.status_code == 400
        assert bad.json()["error"]["code"] == "BAD_REQUEST"
    finally:
        client.put(
            f"{PREFIX}/settings",
            json={
                "mock_mode": True,
                "model_provider": "mock",
                "model_name": "mock-scripted",
                "fallback_chain": ["mock"],
                "approval_rules": ["doc.generate_report"],
                "max_upload_mb": 20,
                "feature_flags": {},
            },
        )


# ---------- 2. 模型管理 ----------
def test_model_registry_and_probe_without_leaking_key(client: httpx.Client):
    created = client.post(
        f"{PREFIX}/models",
        json={
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            # 用官方真名：这个登记会覆盖全局 env:deepseek，写别名会污染同一进程里后续用例
            "model": "deepseek-flash",
            "api_key_ref": "env:DEEPSEEK_API_KEY",
            "priority": 5,
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    model = created.json()
    assert model["api_key_ref"] == "env:DEEPSEEK_API_KEY"
    assert "sk-" not in created.text

    listed = client.get(f"{PREFIX}/models").json()["models"]
    assert any(item["id"] == model["id"] for item in listed)
    assert all("api_key_ref" in item and "api_key" not in item for item in listed)

    # 明文 Key 拒绝
    rejected = client.post(
        f"{PREFIX}/models",
        json={"provider": "openai", "api_key_ref": "sk-plain-text"},
    )
    assert rejected.status_code == 400

    # 探测：引用不存在的环境变量 → 失败但无 Key 泄露
    missing = client.post(
        f"{PREFIX}/models",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key_ref": "env:B3_TEST_MISSING_API_KEY",
        },
    ).json()
    probe = client.post(f"{PREFIX}/models/{missing['id']}/test")
    assert probe.status_code == 200
    result = probe.json()
    assert result["ok"] is False
    assert result["reason"]
    assert "sk-" not in probe.text


# ---------- 3. 会话管理 ----------
def test_thread_search_pagination_and_pin(client: httpx.Client):
    marker = "B3搜索"
    ids = []
    for index in range(3):
        thread = client.post(f"{PREFIX}/threads", json={"title": f"{marker}-{index}"}).json()
        ids.append(thread["thread_id"])
    client.patch(f"{PREFIX}/threads/{ids[-1]}", json={"pinned": True})

    search = client.get(f"{PREFIX}/threads", params={"q": marker}).json()
    assert search["total"] == 3
    assert search["threads"][0]["thread_id"] == ids[-1]  # 置顶优先
    page = client.get(f"{PREFIX}/threads", params={"q": marker, "page": 2, "page_size": 1}).json()
    assert page["total"] == 3 and len(page["threads"]) == 1
    assert page["threads"][0]["thread_id"] != ids[-1]

    client.delete(f"{PREFIX}/threads/{ids[0]}")
    assert client.get(f"{PREFIX}/threads", params={"q": marker}).json()["total"] == 2


# ---------- 4. 运行管理 ----------
def test_run_cancel_and_idempotency(client: httpx.Client):
    """取消是幂等的；跑到终态之后再取消，不该把终态改掉。

    以前这条用例靠审批挂起制造一个「正在跑」的窗口。卡片删掉之后 mock 一轮
    只跑几百毫秒，那个窗口没法稳定复现——所以这里只锁两件能确定的事：
    重复取消幂等，以及终态不被改写。真正「跑一半被取消」的路径由
    `test_semantics_runs` 覆盖。
    """
    thread_id = client.post(f"{PREFIX}/threads", json={"title": "取消测试"}).json()["thread_id"]
    events = approved_flow(client, thread_id, message="整理周报")
    run_id = events[0][1]["run_id"]
    assert events[-1][1]["status"] == "completed"

    first = client.post(f"{PREFIX}/runs/{run_id}/cancel")
    assert first.status_code == 200, first.text
    assert first.json()["cancelled"] is False
    assert first.json()["idempotent"] is True

    again = client.post(f"{PREFIX}/runs/{run_id}/cancel").json()
    assert again["cancelled"] is False and again["idempotent"] is True

    run = client.get(f"{PREFIX}/runs/{run_id}").json()
    assert run["status"] == "completed", "终态不该被一次取消改写"

    replay = client.get(f"{PREFIX}/runs/{run_id}/events").json()["events"]
    assert replay[-1]["event"] == "run.completed"


def test_run_retry_and_filters(client: httpx.Client):
    thread = client.post(f"{PREFIX}/threads", json={"title": "重试测试"}).json()
    thread_id = thread["thread_id"]
    events = approved_flow(client, thread_id, message="写一份周报")
    original_run = events[0][1]["run_id"]
    assert events[-1][1]["status"] == "completed"

    retried = _stream_with_approval(client, "POST", f"{PREFIX}/runs/{original_run}/retry")
    assert retried[0][0] == "run.started"
    assert retried[0][1]["run_id"] != original_run
    assert retried[-1][0] == "run.completed", retried[-3:]
    assert retried[-1][1]["status"] == "completed"

    filtered = client.get(
        f"{PREFIX}/runs", params={"thread_id": thread_id, "status": "completed"}
    ).json()
    assert filtered["total"] >= 2
    assert all(item["status"] == "completed" for item in filtered["runs"])
    detail = client.get(f"{PREFIX}/runs/{original_run}").json()
    assert detail["run_id"] == original_run


# ---------- 5. 上传增强 ----------
def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "进展"
    sheet.append(["模块", "进度", "负责人"])
    sheet.append(["登录", "80%", "张三"])
    sheet.append(["支付", "50%", "李四"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_multi_upload_xlsx_preview_and_delete(client: httpx.Client, data_dir: Path):
    thread_id = client.post(f"{PREFIX}/threads", json={"title": "多文件上传"}).json()["thread_id"]
    response = client.post(
        f"{PREFIX}/threads/{thread_id}/files",
        files=[
            ("files", ("材料.txt", "本周完成登录联调。".encode(), "text/plain")),
            ("files", ("明细.txt", "模块：登录，进度 80%".encode(), "text/plain")),
            (
                "files",
                (
                    "进度.xlsx",
                    _xlsx_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            ),
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["files"]) == 3
    types = {item["type"] for item in body["files"]}
    assert types == {"txt", "xlsx"}
    assert body["text_preview"]
    xlsx_item = next(item for item in body["files"] if item["type"] == "xlsx")
    assert xlsx_item["chars"] > 10

    files = client.get(f"{PREFIX}/threads/{thread_id}/files").json()["files"]
    assert len(files) == 3

    deleted = client.delete(f"{PREFIX}/files/{xlsx_item['file_id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["trashed"]
    assert (data_dir / "trash").exists()
    assert client.get(f"{PREFIX}/artifacts/{xlsx_item['file_id']}").status_code == 404
    # 移除后要真的从会话素材里消失（重进会话不该再出现）
    remaining = client.get(f"{PREFIX}/threads/{thread_id}/files").json()["files"]
    assert all(item["file_id"] != xlsx_item["file_id"] for item in remaining)
    detail = client.get(f"{PREFIX}/threads/{thread_id}").json()
    assert all(item["artifact_id"] != xlsx_item["file_id"] for item in detail.get("artifacts", []))


# ---------- 6. 产物中心 ----------
def test_artifact_pagination_regenerate_and_delete(client: httpx.Client, data_dir: Path):
    thread_id = client.post(f"{PREFIX}/threads", json={"title": "产物中心"}).json()["thread_id"]
    client.post(
        f"{PREFIX}/threads/{thread_id}/files",
        files={
            "file": (
                "会议记录.docx",
                make_docx(["一、本周进展", "完成联调。", "四、下周计划", "补齐测试。"]),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    events = approved_flow(client, thread_id, message="生成周报并发邮件")
    original_artifact = events[-1][1]["artifact_ids"][0]

    listed = client.get(
        f"{PREFIX}/artifacts", params={"thread_id": thread_id, "type": "docx", "page_size": 1}
    ).json()
    assert listed["total"] >= 1 and listed["page_size"] == 1

    regenerated = _stream_with_approval(
        client, "POST", f"{PREFIX}/artifacts/{original_artifact}/regenerate"
    )
    assert regenerated[0][0] == "run.started"
    assert regenerated[-1][0] == "run.completed", regenerated[-3:]
    new_artifact = regenerated[-1][1]["artifact_ids"][0]
    assert new_artifact != original_artifact
    assert client.get(f"{PREFIX}/artifacts/{new_artifact}/download").status_code == 200

    removed = client.delete(f"{PREFIX}/artifacts/{new_artifact}")
    assert removed.status_code == 200
    assert removed.json()["trashed"]
    assert client.get(f"{PREFIX}/artifacts/{new_artifact}").status_code == 404
    assert client.get(f"{PREFIX}/artifacts/{new_artifact}/download").status_code == 404
    assert client.get(f"{PREFIX}/artifacts/{new_artifact}/preview").status_code == 404


# ---------- 7. 模板与技能 ----------
def test_templates_crud_and_render(client: httpx.Client):
    templates = client.get(f"{PREFIX}/templates").json()["templates"]
    builtin_ids = {item["id"] for item in templates}
    assert {"weekly", "meeting", "summary"} <= builtin_ids

    created = client.post(
        f"{PREFIX}/templates",
        json={
            "id": "b3-demo",
            "name": "B3 演示模板",
            "sections": [
                {"heading": "进展速览", "source": "progress"},
                {"heading": "风险提示", "source": "risk"},
            ],
        },
    )
    assert created.status_code == 201, created.text

    thread_id = client.post(f"{PREFIX}/threads", json={"title": "模板生成"}).json()["thread_id"]
    client.post(
        f"{PREFIX}/threads/{thread_id}/files",
        files={"file": ("素材.txt", "完成登录联调。风险：支付延期。".encode(), "text/plain")},
    )
    rendered = client.post(f"{PREFIX}/templates/b3-demo/render", params={"thread_id": thread_id})
    assert rendered.status_code == 200, rendered.text
    artifact = rendered.json()["artifact"]
    assert artifact["type"] == "docx"
    from tests.helpers import docx_parts

    content = client.get(artifact["download_url"]).content
    _, headings = docx_parts(content)
    assert has_heading(headings, "进展速览") and has_heading(headings, "风险提示")

    assert client.delete(f"{PREFIX}/templates/b3-demo").status_code == 204
    assert all(
        item["id"] != "b3-demo" for item in client.get(f"{PREFIX}/templates").json()["templates"]
    )
    assert client.delete(f"{PREFIX}/templates/weekly").status_code == 400


def test_skills_toggle_updates_prompt(client: httpx.Client):
    before = client.get(f"{PREFIX}/skills").json()
    assert before["prompt_chars"] > 0
    weekly = next(item for item in before["skills"] if item["name"] == "weekly-report")
    assert weekly["enabled"] is True

    disabled = client.patch(f"{PREFIX}/skills/weekly-report", json={"enabled": False}).json()
    assert disabled["enabled"] is False
    assert disabled["prompt_chars"] < before["prompt_chars"]
    templates = client.get(f"{PREFIX}/templates").json()["templates"]
    assert next(item for item in templates if item["id"] == "weekly")["enabled"] is False

    restored = client.patch(f"{PREFIX}/skills/weekly-report", json={"enabled": True}).json()
    assert restored["enabled"] is True
    assert restored["prompt_chars"] == before["prompt_chars"]


# ---------- 8. 用量与审计导出 ----------
def test_usage_summary_and_audit_export(client: httpx.Client):
    usage = client.get(f"{PREFIX}/usage/summary", params={"range": "30d"}).json()
    assert usage["range"] == "30d"
    assert "by_provider" in usage and "by_model" in usage and "by_day" in usage

    exported = client.get(f"{PREFIX}/audit/export", params={"format": "json"})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/json")
    assert "attachment" in exported.headers["content-disposition"]
    payload = json.loads(exported.text)
    assert "runs" in payload and "exported_at" in payload

    csv_export = client.get(f"{PREFIX}/audit/export", params={"format": "csv"})
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    text = csv_export.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("run_id,thread_id")


# ---------- 9. OpenAPI ----------
def test_openapi_contains_b3_paths(client: httpx.Client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    for path in (
        "/api/v1/templates",
        "/api/v1/templates/{template_id}/render",
        "/api/v1/skills",
        "/api/v1/skills/{skill_id}",
        "/api/v1/models/{model_id}/test",
        "/api/v1/runs/{run_id}/cancel",
        "/api/v1/runs/{run_id}/retry",
        "/api/v1/artifacts/{artifact_id}/regenerate",
        "/api/v1/audit/export",
        "/api/v1/files/{file_id}",
    ):
        assert path in paths, path
    settings_put = paths["/api/v1/settings"]["put"]
    assert settings_put["summary"]
    assert settings_put["responses"]["200"].get("content")


def test_model_balance_endpoint_reports_support_and_never_leaks_key(client: httpx.Client):
    """余额查询：DeepSeek 支持、其它供应商明说不支持；错误只给脱敏原因。

    这里复用内置登记（id 是 env:<provider>），不新增记录：
    注册表是全局的，往里塞一条跑完就丢的登记会污染后面用例对 deepseek 的判断。
    """
    deepseek = client.get(f"{PREFIX}/models/env:deepseek/balance")
    assert deepseek.status_code == 200, deepseek.text
    assert deepseek.json()["supported"] is True
    assert "sk-" not in deepseek.text

    qwen = client.get(f"{PREFIX}/models/env:qwen/balance")
    assert qwen.status_code == 200, qwen.text
    body = qwen.json()
    assert body["supported"] is False
    assert body["reason"]
    assert "sk-" not in qwen.text
