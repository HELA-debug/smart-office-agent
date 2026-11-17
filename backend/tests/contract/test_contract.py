"""契约测试：事件 JSON Schema、错误体、OpenAPI 路径。"""

from __future__ import annotations

import json

import httpx
from app.core.events import (
    EVENT_JSON_SCHEMA,
    EVENT_NAMES,
    EVENT_VERSION,
    validate_event_data,
)
from jsonschema import validate


def _frames_with_ids(client: httpx.Client, thread_id: str) -> list[dict]:
    frames: list[dict] = []
    current: dict = {}
    with client.stream(
        "POST",
        f"/api/v1/threads/{thread_id}/runs/stream",
        json={"message": "写一份周报", "mode": "mock"},
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                current["id"] = int(line[len("id:") :].strip())
            elif line.startswith("event:"):
                current["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                current["data"] = json.loads(line[len("data:") :].strip())
            elif line == "":
                if current.get("event"):
                    frames.append(current)
                    if current["event"] == "approval.required":
                        approval_id = current["data"]["approval_id"]
                        decision = client.post(
                            f"/api/v1/threads/{thread_id}/approvals/{approval_id}",
                            json={"decision": "approved"},
                        )
                        assert decision.status_code == 200
                current = {}
    return frames


def test_event_contract_and_sse_ids(client: httpx.Client):
    thread_id = client.post("/api/v1/threads", json={"title": "契约"}).json()["thread_id"]
    frames = _frames_with_ids(client, thread_id)
    assert frames
    assert [frame["id"] for frame in frames] == list(range(1, len(frames) + 1))
    for frame in frames:
        assert frame["event"] in EVENT_NAMES, frame["event"]
        data = frame["data"]
        assert data["version"] == EVENT_VERSION
        validate(instance=data, schema=EVENT_JSON_SCHEMA)
        assert validate_event_data(frame["event"], data) == [], frame["event"]
    assert frames[-1]["event"] == "run.completed"


def test_error_envelope_contract(client: httpx.Client):
    response = client.get("/api/v1/artifacts/art_missing")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"trace_id", "error"}
    assert set(body["error"]) <= {"code", "message", "details"}
    assert body["error"]["code"] == "NOT_FOUND"
    assert response.headers["X-Trace-ID"] == body["trace_id"]


def test_openapi_only_exposes_v1_and_has_paths(client: httpx.Client):
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    assert "/api/v1/health" in paths
    assert "/api/v1/threads/{thread_id}/runs/stream" in paths
    assert "/api/v1/artifacts/{artifact_id}/preview" in paths
    assert not any(path.startswith("/api/") and not path.startswith("/api/v1/") for path in paths)


def test_settings_never_returns_plaintext_keys(client: httpx.Client):
    body = client.get("/api/v1/settings").text
    assert "sk-" not in body
    assert "deepseek_api_key" not in body
