"""对话链路语义：附件按轮归属、快照落库、重试复原现场、越界附件提前拒绝。

改造前每轮都会把会话里**所有**上传交给模型，`message.extra` 恒为空（没法回答
「这条消息当时带了哪些文件」），重试只能拿回纯文本。这里从 API 层把新契约钉死。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"
THREADS = f"{API}/threads"


def _upload(client: TestClient, thread_id: str, filename: str, content: str) -> str:
    response = client.post(
        f"{THREADS}/{thread_id}/files",
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return str(body.get("artifact_id") or body.get("file_id") or "")


def _run(client: TestClient, thread_id: str, body: dict[str, object]) -> tuple[str, list[str]]:
    """跑一轮，返回 (run_id, 事件名列表)。"""
    run_id = ""
    names: list[str] = []
    with client.stream("POST", f"{THREADS}/{thread_id}/runs/stream", json=body) as response:
        assert response.status_code == 200
        current, payload = "", ""
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current = line[len("event:") :].strip()
                names.append(current)
            elif line.startswith("data:"):
                payload = line[len("data:") :].strip()
            elif line == "" and current:
                if current == "run.started":
                    run_id = str(json.loads(payload).get("run_id") or run_id)
                if current == "approval.required":
                    approval_id = json.loads(payload).get("approval_id")
                    client.post(
                        f"{THREADS}/{thread_id}/approvals/{approval_id}",
                        json={"decision": "approved", "comment": "自动批准"},
                    )
                current, payload = "", ""
    return run_id, names


def _user_messages(client: TestClient, thread_id: str) -> list[dict]:
    detail = client.get(f"{THREADS}/{thread_id}").json()
    return [item for item in detail["messages"] if item["role"] == "user"]


@pytest.fixture()
def thread(api_client: TestClient) -> str:
    return api_client.post(THREADS, json={"title": "上下文语义"}).json()["thread_id"]


def test_run_only_uses_attachments_of_this_turn(api_client: TestClient, thread: str) -> None:
    first = _upload(api_client, thread, "本周素材.txt", "本周完成登录联调，接口覆盖 12 个。")
    second = _upload(api_client, thread, "旧素材.txt", "上一版素材，与本次无关。")

    run_id, names = _run(
        api_client,
        thread,
        {"message": "整理成周报", "mode": "mock", "attachment_ids": [first]},
    )
    assert names and names[0] == "run.started"
    assert "run.completed" in names

    message = next(item for item in _user_messages(api_client, thread) if item["run_id"] == run_id)
    assert message["extra"]["attachment_ids"] == [first]
    assert [item["filename"] for item in message["extra"]["uploads"]] == ["本周素材.txt"]
    assert second not in json.dumps(message["extra"], ensure_ascii=False)


def test_run_without_attachment_ids_falls_back_to_whole_thread(
    api_client: TestClient, thread: str
) -> None:
    """老客户端（前端暂未下发 attachment_ids）行为不变：整会话素材都可用。"""
    first = _upload(api_client, thread, "甲.txt", "甲素材")
    second = _upload(api_client, thread, "乙.txt", "乙素材")

    run_id, _names = _run(api_client, thread, {"message": "整理成周报", "mode": "mock"})
    message = next(item for item in _user_messages(api_client, thread) if item["run_id"] == run_id)
    assert sorted(message["extra"]["attachment_ids"]) == sorted([first, second])


def test_foreign_attachment_id_is_rejected_before_running(
    api_client: TestClient, thread: str
) -> None:
    _upload(api_client, thread, "本周素材.txt", "本周完成登录联调。")
    response = api_client.post(
        f"{THREADS}/{thread}/runs/stream",
        json={"message": "整理成周报", "mode": "mock", "attachment_ids": ["art_not_exists"]},
    )
    assert response.status_code == 400
    assert "附件" in response.json()["error"]["message"]


def test_retry_restores_the_original_attachments(api_client: TestClient, thread: str) -> None:
    first = _upload(api_client, thread, "本周素材.txt", "本周完成登录联调。")
    _upload(api_client, thread, "无关素材.txt", "与本次任务无关。")

    original_run, _ = _run(
        api_client,
        thread,
        {"message": "整理成周报", "mode": "mock", "attachment_ids": [first]},
    )

    with api_client.stream("POST", f"{API}/runs/{original_run}/retry") as response:
        assert response.status_code == 200
        for _line in response.iter_lines():
            pass

    retried = [
        item
        for item in _user_messages(api_client, thread)
        if item["run_id"] and item["run_id"] != original_run
    ]
    assert retried, "重试没有产生新的用户消息"
    assert retried[-1]["extra"]["attachment_ids"] == [first]


def test_context_compaction_event_fires_when_history_overflows(
    api_client: TestClient, thread: str
) -> None:
    """历史超出窗口时，先发 context.compacted 再跑：运维能看出「模型看到的历史被裁过」。"""
    settings = api_client.app.state.container.settings
    original = settings.context_max_turns
    settings.context_max_turns = 1  # 只保留最近 1 轮，第三轮必然触发压缩
    try:
        _run(api_client, thread, {"message": "第一轮：出周报", "mode": "mock"})
        _run(api_client, thread, {"message": "第二轮：改字号", "mode": "mock"})
        run_id, names = _run(api_client, thread, {"message": "第三轮：换模板", "mode": "mock"})
    finally:
        settings.context_max_turns = original

    assert "context.compacted" in names
    events = api_client.get(f"{API}/runs/{run_id}/events").json()["events"]
    compacted = next(item for item in events if item["event"] == "context.compacted")
    assert compacted["data"]["dropped_turns"] >= 1
    assert compacted["data"]["kept_turns"] == 1
    assert compacted["data"]["summary_chars"] > 0
