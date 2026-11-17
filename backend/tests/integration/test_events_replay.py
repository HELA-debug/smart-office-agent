"""事件持久化与重放：run_events 落库、?after= / Last-Event-ID 续传。"""

from __future__ import annotations

import httpx
from tests.helpers import read_sse, start_run


def _read_frames(lines) -> list[dict]:
    """带 SSE id 的帧解析（id 必须与 run_events.seq 一致）。"""
    frames: list[dict] = []
    current: dict = {}
    for line in lines:
        if line.startswith(":"):
            continue
        if line.startswith("id:"):
            current["id"] = int(line[len("id:") :].strip())
        elif line.startswith("event:"):
            current["event"] = line[len("event:") :].strip()
        elif line.startswith("data:"):
            import json

            current["data"] = json.loads(line[len("data:") :].strip())
        elif line == "":
            if current.get("event"):
                frames.append(current)
            current = {}
    return frames


def test_event_persistence_and_replay(client: httpx.Client):
    thread_id = client.post("/api/v1/threads", json={"title": "回放"}).json()["thread_id"]
    with start_run(client, thread_id, "整理周报并发邮件") as response:
        lines = response.iter_lines()
        events = read_sse(lines, stop_at="run.completed")
        run_id = events[0][1]["run_id"]

        stored = client.get(f"/api/v1/runs/{run_id}/events").json()["events"]
        assert len(stored) == len(events)
        assert [item["seq"] for item in stored] == list(range(1, len(events) + 1))
        assert stored[-1]["event"] == "run.completed"
    run_id = events[0][1]["run_id"]
    total = len(events)

    stored_all = client.get(f"/api/v1/runs/{run_id}/events").json()["events"]
    assert len(stored_all) == total

    tail = client.get(f"/api/v1/runs/{run_id}/events", params={"after": total - 1}).json()["events"]
    assert len(tail) == 1
    assert tail[0]["event"] == "run.completed"

    # Last-Event-ID 续传（SSE）：只回放 > seq 的事件，且 id 连续
    with client.stream(
        "GET",
        f"/api/v1/runs/{run_id}/events/stream",
        headers={"Last-Event-ID": str(total - 1)},
    ) as response:
        assert response.status_code == 200
        frames = _read_frames(response.iter_lines())
    assert len(frames) == 1
    assert frames[0]["id"] == total
    assert frames[0]["event"] == "run.completed"

    # ?after= 续传（SSE）
    with client.stream(
        "GET", f"/api/v1/runs/{run_id}/events/stream", params={"after": 0}
    ) as response:
        frames = _read_frames(response.iter_lines())
    assert len(frames) == total
    assert [frame["id"] for frame in frames] == list(range(1, total + 1))
    assert frames[-1]["data"]["run_id"] == run_id


def test_replay_unknown_run(client: httpx.Client):
    assert client.get("/api/v1/runs/r_missing/events").status_code == 404
    assert client.get("/api/v1/runs/r_missing/events/stream").status_code == 404
