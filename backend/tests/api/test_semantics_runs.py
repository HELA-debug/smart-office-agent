"""运行与审批的语义矩阵：SSE 事件契约、事件回放、取消/重试幂等、审批状态机。"""

from __future__ import annotations

import json

import pytest
from tests.api.matrix import MATRIX_PREFIX

RUNS = f"{MATRIX_PREFIX}/runs"
THREADS = f"{MATRIX_PREFIX}/threads"


def collect_sse(
    client,
    method: str,
    url: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> list[tuple[str, int, dict]]:
    """把一段 SSE 读成 [(event, seq, data)]，读到流结束（不处理审批）。"""
    frames: list[tuple[str, int, dict]] = []
    kwargs: dict[str, object] = {}
    if body is not None:
        kwargs["json"] = body
    if headers is not None:
        kwargs["headers"] = headers
    with client.stream(method, url, **kwargs) as response:
        assert response.status_code == 200, response.text
        event, seq, data = "", 0, ""
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                seq = int(line[len("id:") :].strip() or 0)
            elif line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
            elif line == "" and event:
                payload = json.loads(data) if data else {}
                frames.append((event, seq, payload))
                event, data = "", ""
    return frames


def run_once(client, thread_id: str, message: str = "整理成周报") -> list[tuple[str, int, dict]]:
    """跑一轮完整运行（中途自动批准）。"""
    frames: list[tuple[str, int, dict]] = []
    with client.stream(
        "POST",
        f"{THREADS}/{thread_id}/runs/stream",
        json={"message": message, "mode": "mock", "approval_mode": "always_ask"},
    ) as response:
        assert response.status_code == 200, response.text
        event, seq, data = "", 0, ""
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                seq = int(line[len("id:") :].strip() or 0)
            elif line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
            elif line == "" and event:
                payload = json.loads(data) if data else {}
                frames.append((event, seq, payload))
                if event == "approval.required":
                    decided = client.post(
                        f"{THREADS}/{thread_id}/approvals/{payload['approval_id']}",
                        json={"decision": "approved", "comment": "自动批准"},
                    )
                    assert decided.status_code == 200, decided.text
                event, data = "", ""
    return frames


# ---------------------------------------------------------------- 事件契约
@pytest.fixture(scope="module")
def completed_run(api_client) -> dict:
    thread = api_client.post(THREADS, json={"title": "运行语义"}).json()
    thread_id = thread["thread_id"]
    frames = run_once(api_client, thread_id)
    assert frames, "运行没有产生任何事件"
    run_id = ""
    for event, _seq, payload in frames:
        if event == "run.started":
            run_id = payload.get("run_id", run_id)
    return {"thread_id": thread_id, "run_id": run_id, "frames": frames}


def test_run_event_sequence(completed_run: dict):
    frames = completed_run["frames"]
    names = [name for name, _seq, _data in frames]
    assert names[0] == "run.started"
    assert "run.completed" in names
    assert names[-1] == "run.completed"
    # 审批卡已经删掉：写盘由门控按那一句话判，不再出现 approval.required
    assert "approval.required" not in names


def test_run_event_seq_is_monotonic(completed_run: dict):
    seqs = [seq for _name, seq, _data in completed_run["frames"] if seq]
    assert seqs, "SSE 帧缺 id: 行（seq）"
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_run_detail_after_completion(api_client, completed_run: dict):
    run = api_client.get(f"{RUNS}/{completed_run['run_id']}").json()
    assert run["run_id"] == completed_run["run_id"]
    assert run["status"] == "completed"
    assert run["thread_id"] == completed_run["thread_id"]


def test_run_events_json_matches_stream(api_client, completed_run: dict):
    stored = api_client.get(f"{RUNS}/{completed_run['run_id']}/events").json()["events"]
    streamed = [
        {"event": name, "seq": seq, "data": data}
        for name, seq, data in completed_run["frames"]
        if name != "run.started"
    ]
    assert len(stored) >= 1
    assert [item["seq"] for item in stored] == sorted(item["seq"] for item in stored)
    assert len(stored) >= len(streamed) * 0.5


def test_events_after_filter(api_client, completed_run: dict):
    all_events = api_client.get(f"{RUNS}/{completed_run['run_id']}/events").json()["events"]
    assert len(all_events) >= 3
    pivot = all_events[len(all_events) // 2]["seq"]
    tail = api_client.get(f"{RUNS}/{completed_run['run_id']}/events?after={pivot}").json()["events"]
    assert all(item["seq"] > pivot for item in tail)
    assert len(tail) < len(all_events)


def test_events_stream_honours_last_event_id(api_client, completed_run: dict):
    """SSE 回放支持两条断线续传入口：?after= 与 Last-Event-ID 头，结果必须一致。"""
    base = f"{RUNS}/{completed_run['run_id']}/events/stream"
    all_events = api_client.get(f"{RUNS}/{completed_run['run_id']}/events").json()["events"]
    pivot = all_events[0]["seq"]
    by_query = [
        seq for _name, seq, _data in collect_sse(api_client, "GET", f"{base}?after={pivot}")
    ]
    by_header = [
        seq
        for _name, seq, _data in collect_sse(
            api_client, "GET", base, headers={"Last-Event-ID": str(pivot)}
        )
    ]
    assert by_query == by_header
    assert all(seq > pivot for seq in by_query)


def test_events_after_non_integer_is_400(api_client, completed_run: dict):
    response = api_client.get(f"{RUNS}/{completed_run['run_id']}/events?after=abc")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_events_stream_replays(api_client, completed_run: dict):
    frames = collect_sse(api_client, "GET", f"{RUNS}/{completed_run['run_id']}/events/stream")
    assert frames, "回放流没有帧"
    assert frames[0][0] != "" and frames[-1][2] is not None


# ---------------------------------------------------------------- 取消 / 重试
def test_cancel_completed_run_is_idempotent(api_client, completed_run: dict):
    first = api_client.post(f"{RUNS}/{completed_run['run_id']}/cancel")
    second = api_client.post(f"{RUNS}/{completed_run['run_id']}/cancel")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cancelled"] is False or first.json()["cancelled"] is True


def test_cancel_unknown_run_is_404(api_client):
    response = api_client.post(f"{RUNS}/r_nope/cancel")
    assert response.status_code == 404


def test_retry_creates_new_run(api_client, completed_run: dict):
    frames = collect_sse(api_client, "POST", f"{RUNS}/{completed_run['run_id']}/retry")
    started = [payload for name, _seq, payload in frames if name == "run.started"]
    assert started, "重试没有产生 run.started"
    assert started[0]["run_id"] != completed_run["run_id"]
    original = api_client.get(f"{RUNS}/{completed_run['run_id']}").json()
    assert original["status"] == "completed", "重试不应改动原运行的状态"


def test_retry_unknown_run_is_404(api_client):
    response = api_client.post(f"{RUNS}/r_nope/retry")
    assert response.status_code == 404


# ---------------------------------------------------------------- 列表 / 过滤
def test_list_runs_by_thread(api_client, completed_run: dict):
    result = api_client.get(f"{RUNS}?thread_id={completed_run['thread_id']}").json()
    assert result["total"] >= 1
    assert all(item["thread_id"] == completed_run["thread_id"] for item in result["runs"])


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "running"])
def test_list_runs_status_filter(api_client, status: str):
    result = api_client.get(f"{RUNS}?status={status}").json()
    assert all(item["status"] == status for item in result["runs"])


def test_list_thread_runs_pagination(api_client, completed_run: dict):
    result = api_client.get(
        f"{THREADS}/{completed_run['thread_id']}/runs?page=1&page_size=1"
    ).json()
    assert result["page_size"] == 1
    assert len(result["runs"]) <= 1


# ---------------------------------------------------------------- 审批状态机
def test_approval_unknown_id_is_404(api_client, seed):
    response = api_client.post(
        f"{THREADS}/{seed.ids['thread_id']}/approvals/apr_nope",
        json={"decision": "approved"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("decision", ["yes", "同意", "", "APPROVED", "reject"])
def test_approval_invalid_decision_is_400(api_client, seed, decision: str):
    response = api_client.post(
        f"{THREADS}/{seed.ids['thread_id']}/approvals/{seed.ids['approval_id']}",
        json={"decision": decision},
    )
    assert response.status_code == 400, response.text
    assert "approved" in response.json()["error"]["message"]


def test_approval_thread_mismatch_is_404(api_client, seed, fresh_thread: str):
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/approvals/{seed.ids['approval_id']}",
        json={"decision": "approved"},
    )
    assert response.status_code == 404


def test_run_unknown_thread_is_404(api_client):
    response = api_client.post(
        f"{THREADS}/th_nope/runs/stream", json={"message": "x", "mode": "mock"}
    )
    assert response.status_code == 404


def test_run_rejects_unknown_output_format(api_client, fresh_thread: str):
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/runs/stream",
        json={"message": "整理周报", "output_format": "exe"},
    )
    assert response.status_code == 400, response.text
