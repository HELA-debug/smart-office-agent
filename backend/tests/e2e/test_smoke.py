"""端到端 smoke：旧 /api 路径全链路 + 文档站点可用。"""

from __future__ import annotations

import httpx
import pytest
from tests.helpers import approved_flow, docx_parts, has_heading

pytestmark = pytest.mark.e2e


def test_legacy_api_full_flow(client: httpx.Client):
    thread = client.post("/api/threads", json={"title": "旧路径联调"}).json()
    thread_id = thread["thread_id"]

    with client.stream(
        "POST",
        f"/api/threads/{thread_id}/runs/stream",
        json={"message": "写一份周报并发我邮箱", "mode": "mock"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["Deprecation"] == "true"
        assert response.headers["content-type"].startswith("text/event-stream")

    events = approved_flow(client, thread_id, message="写一份周报并发我邮箱", prefix="/api")
    final = events[-1][1]
    assert final["status"] == "completed"
    artifact_id = final["artifact_ids"][0]
    meta = client.get(f"/api/artifacts/{artifact_id}").json()
    content = client.get(meta["download_url"]).content
    _, headings = docx_parts(content)
    assert has_heading(headings, "摘要")

    detail = client.get(f"/api/threads/{thread_id}")
    assert detail.status_code == 200
    assert detail.headers["Deprecation"] == "true"
    assert detail.json()["messages"]


def test_docs_and_root(client: httpx.Client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["version"] == "0.2.0"
