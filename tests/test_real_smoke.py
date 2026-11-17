"""真实模型 smoke（1 条，默认跳过，避免费用与不稳定）。

仅在显式开启时运行（消耗真实 token）：
    RUN_REAL_MODEL_TEST=1 BASE_URL=http://127.0.0.1:8000 \
    .venv/Scripts/python.exe -m pytest tests/test_real_smoke.py -q -s

断言：真实模式下同一任务完成一次运行，事件带 artifact 与 approval，DOCX 可下载打开。
"""
from __future__ import annotations

import io
import os

import docx
import httpx
import pytest

from conftest import consume_sse, frames_by_name, upload
from samples import make_txt

RUN_REAL = os.environ.get("RUN_REAL_MODEL_TEST") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_REAL,
    reason="真实模型 smoke 默认跳过；设置 RUN_REAL_MODEL_TEST=1 且 BASE_URL=真实模式服务后运行",
)


def test_real_model_end_to_end(client: httpx.Client) -> None:
    health = client.get("/api/v1/health").json()
    assert health["mode"] == "real", f"当前不是真实模式：{health}"
    assert health["provider"], health

    created = client.post("/api/v1/threads", json={"title": "真实模型 smoke"})
    assert created.status_code == 201, created.text
    thread_id = created.json()["thread_id"]
    uploaded = upload(client, thread_id, "真实模型素材.txt", make_txt())
    assert uploaded.status_code == 201, uploaded.text

    _, _, frames = consume_sse(
        client,
        f"/api/v1/threads/{thread_id}/runs/stream",
        json_body={
            "message": (
                "把这份素材整理成 600 字周报，生成 DOCX，"
                "并作为邮件草稿发送（mail.send），发送前需要我审批。"
            )
        },
        thread_id=thread_id,
        auto_decision="approved",
    )
    names = [frame["event"] for frame in frames]
    assert names[0] == "run.started", names
    started = frames_by_name(frames, "run.started")[0]
    assert started["mode"] == "real", started
    assert "approval.required" in names, f"真实模型未触发审批；事件：{names}"
    assert "run.failed" not in names, frames_by_name(frames, "run.failed")
    assert names[-1] == "run.completed", names

    done = frames_by_name(frames, "run.completed")[0]
    assert done["status"] == "completed", done
    assert done["artifact_ids"], done
    assert done["tokens"] > 0
    assert done["cost_cny"] >= 0
    assert done["approvals"] and done["approvals"][0]["decision"] == "approved"

    artifact_id = done["artifact_ids"][0]
    download = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert download.status_code == 200, download.text
    document = docx.Document(io.BytesIO(download.content))
    assert [p.text for p in document.paragraphs if p.text.strip()], "真实模型产物 DOCX 为空"
