"""主链路 smoke（15 条）：SSE 全链路、审批、取消/重试、重放、产物中心、审计、旧接口。

纯黑盒；mock 服务；临时文件只写 tmp_path。
"""
from __future__ import annotations

import io
import json
import time
from typing import Any

import docx
import httpx
import pytest

from conftest import (
    SseReader,
    assert_error,
    consume_sse,
    decide,
    frames_by_name,
    outbox_snapshot,
    run_flow,
    upload,
)
from samples import make_txt

V1 = "/api/v1"
DOCX_HEADINGS = {"摘要", "本周进展", "关键数据", "风险与问题", "下周计划", "来源引用"}


def _upload_txt(client: httpx.Client, thread_id: str) -> dict[str, Any]:
    resp = upload(client, thread_id, "周报素材.txt", make_txt())
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stream_path(thread_id: str, legacy: bool = False) -> str:
    prefix = "/api" if legacy else V1
    return f"{prefix}/threads/{thread_id}/runs/stream"


def _assert_event_envelope(frames: list[dict[str, Any]]) -> set[str]:
    assert frames, "未收到任何 SSE 事件"
    assert [frame["id"] for frame in frames] == list(range(1, len(frames) + 1))
    run_ids = {frame["data"].get("run_id") for frame in frames}
    assert len(run_ids) == 1, f"同一运行 run_id 不一致：{run_ids}"
    for frame in frames:
        assert frame["data"].get("version") == 1, frame
        assert frame["data"].get("run_id") in run_ids, frame
    return run_ids


# 16. SSE 全链路：批准 → 产物下载 + 结构校验
def test_sse_full_flow_approve(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)

    events = run_flow(client, thread_id, decision="approved")
    _assert_event_envelope(events)
    names = [frame["event"] for frame in events]
    assert names[0] == "run.started"
    assert names[-1] == "run.completed"
    assert "approval.required" in names
    assert "artifact.ready" in names
    assert "run.failed" not in names
    assert names.index("message.delta") < names.index("approval.required")
    assert names.index("artifact.ready") < names.index("approval.required")
    assert names.index("approval.required") < names.index("run.completed")

    started = frames_by_name(events, "run.started")[0]
    assert started["mode"] == "mock"
    approval = frames_by_name(events, "approval.required")[0]
    assert approval["tool"] == "mail.send" and approval["risk"] == "high"
    assert (approval["preview"] or {}).get("to", "").endswith("@example.com")

    done = frames_by_name(events, "run.completed")[0]
    assert done["status"] == "completed"
    assert done["tokens"] > 0
    assert done["cost_cny"] >= 0
    assert done["artifact_ids"]
    assert [item["decision"] for item in done["approvals"]] == ["approved"]

    mail_frames = [item for item in frames_by_name(events, "tool.finished") if item["tool"] == "mail.send"]
    assert mail_frames and mail_frames[-1]["ok"] is True
    assert mail_frames[-1]["output"].get("external_send") is False

    # 运行详情 / 列表
    run = client.get(f"{V1}/runs/{done['run_id']}").json()
    assert run["run_id"] == done["run_id"] and run["status"] == "completed"
    runs = client.get(f"{V1}/runs", params={"thread_id": thread_id}).json()
    assert any(item["run_id"] == done["run_id"] for item in runs["runs"])

    # 产物元数据 / 下载（python-docx 打开）/ 预览
    artifact_id = done["artifact_ids"][0]
    meta = client.get(f"{V1}/artifacts/{artifact_id}").json()
    assert meta["artifact_id"] == artifact_id
    assert meta["type"] == "docx"
    assert len(meta["sha256"]) == 64
    assert meta["download_url"].endswith("/download")
    assert meta["preview_url"].endswith("/preview")

    download = client.get(meta["download_url"])
    assert download.status_code == 200, download.text
    assert len(download.content) > 1000
    document = docx.Document(io.BytesIO(download.content))
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    assert paragraphs
    headings = {
        p.text.strip()
        for p in document.paragraphs
        if (p.style.name or "").lower().startswith(("heading", "title"))
    }
    missing = DOCX_HEADINGS - headings
    assert not missing, f"DOCX 缺小节：{missing}；实际：{headings}"

    preview = client.get(meta["preview_url"])
    assert preview.status_code == 200, preview.text
    assert "html" in preview.headers.get("content-type", "").lower()
    assert "<" in preview.text and len(preview.text) > 50


# 17. 审批拒绝：运行正常结束、产物保留、无外部写操作
def test_sse_reject_flow(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)
    outbox_before = outbox_snapshot()

    events = run_flow(client, thread_id, decision="rejected")
    names = [frame["event"] for frame in events]
    assert names[-1] == "run.completed"
    assert "run.failed" not in names
    done = frames_by_name(events, "run.completed")[0]
    assert done["status"] == "rejected"
    assert done["artifact_ids"], "拒绝后产物应保留"

    mail_frames = [item for item in frames_by_name(events, "tool.finished") if item["tool"] == "mail.send"]
    assert mail_frames and mail_frames[-1]["ok"] is False
    assert mail_frames[-1]["output"].get("skipped") is True
    assert mail_frames[-1]["output"].get("external_send") is False

    outbox_after = outbox_snapshot()
    if outbox_before is not None and outbox_after is not None:
        assert outbox_after == outbox_before, "审批拒绝后 mock 发件箱不应新增文件"

    # 产物仍可下载
    artifact_id = done["artifact_ids"][0]
    download = client.get(f"{V1}/artifacts/{artifact_id}/download")
    assert download.status_code == 200, download.text
    assert docx.Document(io.BytesIO(download.content)).paragraphs

    # 审计记录 rejected
    audit = client.get(f"{V1}/threads/{thread_id}/audit").json()
    assert audit["runs"] and audit["runs"][-1]["status"] == "rejected"
    assert audit["approvals"][-1]["decision"] == "rejected"


# 18. 重复审批 → 409
def test_approval_duplicate_409(
    client: httpx.Client, thread: dict, base_url: str
) -> None:
    thread_id = thread["thread_id"]
    reader = SseReader(base_url, _stream_path(thread_id), json_body={"message": "写周报"}).start()
    approval = reader.wait_for("approval.required")
    approval_id = approval["approval_id"]

    first = decide(client, thread_id, approval_id, "approved")
    assert first.status_code == 200, first.text
    second = decide(client, thread_id, approval_id, "approved")
    body = assert_error(second, 409, "APPROVAL_ALREADY_DECIDED")
    assert body["error"]["message"]

    reader.join()
    assert (reader.get("run.completed") or {}).get("status") == "completed"


# 19. 审批超时 → run.failed(APPROVAL_TIMEOUT)
def test_approval_timeout_failed(
    client: httpx.Client, thread: dict, restore_settings: dict
) -> None:
    thread_id = thread["thread_id"]
    client.put(f"{V1}/settings", json={"approval_timeout_seconds": 2})
    _, _, frames = consume_sse(
        client,
        _stream_path(thread_id),
        json_body={"message": "写周报"},
        thread_id=thread_id,
        auto_decision=None,
    )
    last = frames[-1]
    assert last["event"] == "run.failed", [frame["event"] for frame in frames]
    assert last["data"]["error"]["code"] == "APPROVAL_TIMEOUT"
    assert last["data"]["error"]["retryable"] is True
    run = client.get(f"{V1}/runs/{last['data']['run_id']}").json()
    assert run["status"] == "failed"


# 20. 取消运行 → run.cancelled + 幂等
def test_cancel_run(client: httpx.Client, thread: dict, base_url: str) -> None:
    thread_id = thread["thread_id"]
    reader = SseReader(base_url, _stream_path(thread_id), json_body={"message": "写长周报"}).start()
    started = reader.wait_for("run.started")
    run_id = started["run_id"]

    resp = client.post(f"{V1}/runs/{run_id}/cancel")
    assert resp.status_code == 200, resp.text
    cancelled = resp.json()
    assert cancelled["cancelled"] is True
    assert cancelled["status"] == "cancelled"
    assert cancelled["idempotent"] is False

    reader.join()
    assert "run.cancelled" in reader.names()
    assert reader.get("run.cancelled")["reason"] == "cancelled_by_user"
    assert client.get(f"{V1}/runs/{run_id}").json()["status"] == "cancelled"

    again = client.post(f"{V1}/runs/{run_id}/cancel")
    assert again.status_code == 200, again.text
    assert again.json()["idempotent"] is True
    assert again.json()["cancelled"] is False


# 21. 重试运行 → 新 run 跑通
def test_retry_run(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)
    events = run_flow(client, thread_id, decision="approved")
    original_run = frames_by_name(events, "run.completed")[0]["run_id"]

    _, _, retry_frames = consume_sse(
        client,
        f"{V1}/runs/{original_run}/retry",
        thread_id=thread_id,
        auto_decision="approved",
    )
    retry_done = retry_frames[-1]
    assert retry_done["event"] == "run.completed"
    assert retry_done["data"]["run_id"] != original_run
    assert retry_done["data"]["status"] == "completed"
    assert retry_done["data"]["artifact_ids"]


# 22. 事件回放（JSON，after=seq）
def test_event_replay_json(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    events = run_flow(client, thread_id, decision="approved")
    run_id = frames_by_name(events, "run.completed")[0]["run_id"]

    full = client.get(f"{V1}/runs/{run_id}/events").json()
    assert full["run_id"] == run_id
    assert len(full["events"]) >= 5
    seqs = [item["seq"] for item in full["events"]]
    assert seqs == sorted(seqs) and seqs[0] == 1
    assert full["events"][-1]["event"] == "run.completed"
    for item in full["events"]:
        assert item["data"]["version"] == 1
        assert item["data"]["run_id"] == run_id

    after = client.get(f"{V1}/runs/{run_id}/events", params={"after": 3}).json()
    assert after["events"], "after=3 应返回后续事件"
    assert all(item["seq"] > 3 for item in after["events"])
    assert after["events"][0]["seq"] == 4


# 23. 断线重放（SSE + Last-Event-ID）
def test_event_replay_sse_last_event_id(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    events = run_flow(client, thread_id, decision="approved")
    run_id = frames_by_name(events, "run.completed")[0]["run_id"]

    status, headers, frames = consume_sse(
        client,
        f"{V1}/runs/{run_id}/events/stream",
        method="GET",
        headers={"Last-Event-ID": "5"},
    )
    assert status == 200
    assert "text/event-stream" in headers.get("content-type", "")
    assert frames, "Last-Event-ID=5 应回放后续事件"
    assert all(frame["id"] > 5 for frame in frames)
    assert frames[-1]["event"] == "run.completed"


# 24. 产物中心：跨会话列表 + 筛选 + 分页
def test_artifact_list_filter(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)
    events = run_flow(client, thread_id, decision="approved")
    docx_id = frames_by_name(events, "run.completed")[0]["artifact_ids"][0]

    listed = client.get(
        f"{V1}/artifacts", params={"thread_id": thread_id, "type": "docx"}
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] >= 1
    assert all(item["type"] == "docx" for item in body["artifacts"])
    assert docx_id in {item["artifact_id"] for item in body["artifacts"]}

    uploads = client.get(f"{V1}/artifacts", params={"thread_id": thread_id, "type": "upload"}).json()
    assert uploads["total"] >= 1
    assert all(item["type"] == "upload" for item in uploads["artifacts"])

    page = client.get(f"{V1}/artifacts", params={"page": 1, "page_size": 1}).json()
    assert page["page"] == 1 and page["page_size"] == 1 and len(page["artifacts"]) <= 1


# 25. 产物软删 → 下载/预览 404
def test_artifact_delete_then_gone(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)
    events = run_flow(client, thread_id, decision="approved")
    artifact_id = frames_by_name(events, "run.completed")[0]["artifact_ids"][0]

    deleted = client.delete(f"{V1}/artifacts/{artifact_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert deleted.json()["artifact_id"] == artifact_id

    assert_error(client.get(f"{V1}/artifacts/{artifact_id}/download"), 404, "NOT_FOUND")
    assert_error(client.get(f"{V1}/artifacts/{artifact_id}/preview"), 404, "NOT_FOUND")
    assert_error(client.get(f"{V1}/artifacts/{artifact_id}"), 404, "NOT_FOUND")
    listed = client.get(f"{V1}/artifacts", params={"thread_id": thread_id}).json()
    assert artifact_id not in {item["artifact_id"] for item in listed["artifacts"]}


# 26. 重新生成产物（SSE，产生新 run/新产物）
def test_artifact_regenerate(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)
    events = run_flow(client, thread_id, decision="approved")
    old_artifact = frames_by_name(events, "artifact.ready")[0]["artifact_id"]

    _, _, regen_frames = consume_sse(
        client,
        f"{V1}/artifacts/{old_artifact}/regenerate",
        thread_id=thread_id,
        auto_decision="approved",
    )
    assert regen_frames[-1]["event"] == "run.completed"
    assert regen_frames[-1]["data"]["status"] == "completed"
    new_artifact = frames_by_name(regen_frames, "artifact.ready")[0]["artifact_id"]
    assert new_artifact != old_artifact
    assert client.get(f"{V1}/artifacts/{new_artifact}").status_code == 200


# 27. 模板：内置渲染 + 自定义模板创建/渲染/删除
def test_templates_create_render(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)

    templates = client.get(f"{V1}/templates").json()["templates"]
    assert {"weekly", "meeting", "summary"} <= {item["id"] for item in templates}
    builtin = next(item for item in templates if item["id"] == "weekly")
    assert builtin["builtin"] is True and builtin["sections"]

    rendered = client.post(f"{V1}/templates/weekly/render", params={"thread_id": thread_id})
    assert rendered.status_code == 200, rendered.text
    rendered_body = rendered.json()
    assert rendered_body["template"] == "weekly"
    assert rendered_body["artifact"]["type"] == "docx"
    assert rendered_body["artifact"]["size"] > 0

    created = client.post(
        f"{V1}/templates",
        json={
            "name": "冒烟自定义模板",
            "description": "B5 smoke",
            "sections": [{"heading": "进展", "source": "progress"}],
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    try:
        custom_render = client.post(f"{V1}/templates/{template_id}/render", params={"thread_id": thread_id})
        assert custom_render.status_code == 200, custom_render.text
        assert custom_render.json()["artifact"]["type"] == "docx"
    finally:
        deleted = client.delete(f"{V1}/templates/{template_id}")
        assert deleted.status_code == 204, deleted.text


# 28. 审计 + 用量汇总
def test_audit_and_usage(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    _upload_txt(client, thread_id)
    events = run_flow(client, thread_id, decision="approved")
    run_id = frames_by_name(events, "run.completed")[0]["run_id"]

    audit = client.get(f"{V1}/threads/{thread_id}/audit")
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["thread_id"] == thread_id
    assert body["runs"], "审计缺运行记录"
    run = next(item for item in body["runs"] if item["run_id"] == run_id)
    for key in ("status", "tokens", "cost_cny", "elapsed_ms", "provider", "model"):
        assert key in run, run
    assert body["approvals"] and body["approvals"][-1]["decision"] == "approved"
    assert body["artifacts"]

    usage = client.get(
        f"{V1}/usage/summary", params={"range": "7d", "thread_id": thread_id}
    )
    assert usage.status_code == 200, usage.text
    summary = usage.json()
    assert summary["runs"] >= 1
    assert summary["tokens"] > 0
    assert "completed" in summary["by_status"]
    assert summary["by_provider"] and summary["by_day"]

    usage30 = client.get(f"{V1}/usage/summary", params={"range": "30d"}).json()
    assert usage30["range"] == "30d"


# 29. 审计导出（JSON / CSV）
def test_audit_export(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    run_flow(client, thread_id, decision="approved")

    exported_json = client.get(f"{V1}/audit/export", params={"format": "json"})
    assert exported_json.status_code == 200, exported_json.text
    assert "application/json" in exported_json.headers.get("content-type", "")
    assert "attachment" in exported_json.headers.get("content-disposition", "")
    payload = exported_json.json()
    assert payload["runs"], payload
    assert payload["runs"][0]["run_id"].startswith("r_")

    exported_csv = client.get(f"{V1}/audit/export", params={"format": "csv"})
    assert exported_csv.status_code == 200, exported_csv.text
    assert "text/csv" in exported_csv.headers.get("content-type", "")
    csv_text = exported_csv.content.decode("utf-8-sig")
    assert csv_text.splitlines()
    assert "run_id" in csv_text.splitlines()[0]
    assert "status" in csv_text.splitlines()[0]


# 30. 旧 /api 兼容：建会话 + 上传 + SSE 全链路
def test_legacy_api_full_flow(client: httpx.Client, thread: dict, base_url: str) -> None:
    thread_id = thread["thread_id"]
    # 旧路径上传
    uploaded = client.post(
        f"/api/threads/{thread_id}/files",
        files={"file": ("素材.txt", make_txt(), "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.headers.get("Deprecation") == "true"

    status, headers, frames = consume_sse(
        client,
        _stream_path(thread_id, legacy=True),
        json_body={"message": "写周报"},
        thread_id=thread_id,
        auto_decision="approved",
    )
    assert status == 200
    assert headers.get("deprecation") == "true"
    assert frames[0]["event"] == "run.started"
    assert frames[-1]["event"] == "run.completed"
    assert frames[-1]["data"]["status"] == "completed"
    assert frames[-1]["data"]["artifact_ids"]
