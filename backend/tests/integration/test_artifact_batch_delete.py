"""产物批量软删接口：部分成功语义、去重、上限校验、软删后不可下载。"""

from __future__ import annotations

import httpx


def _make_thread(client: httpx.Client, title: str) -> str:
    response = client.post("/api/v1/threads", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["thread_id"]


def _upload(client: httpx.Client, thread_id: str, filename: str, text: str = "批量删除测试") -> str:
    response = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["artifact_id"]


def test_batch_delete_removes_all_and_trashes_files(client: httpx.Client):
    thread_id = _make_thread(client, "批量删除-全部成功")
    first = _upload(client, thread_id, "批量A.txt")
    second = _upload(client, thread_id, "批量B.txt")

    response = client.post(
        "/api/v1/artifacts/batch-delete",
        json={"artifact_ids": [first, second]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trace_id"]
    assert body["requested"] == 2
    assert body["deleted"] == 2
    assert body["failed"] == []
    assert len(body["trashed"]) >= 2

    # 软删后：元数据/下载均 404，列表不再返回
    assert client.get(f"/api/v1/artifacts/{first}").status_code == 404
    assert client.get(f"/api/v1/artifacts/{first}/download").status_code == 404
    listed = client.get(f"/api/v1/artifacts?thread_id={thread_id}").json()["artifacts"]
    assert all(item["artifact_id"] not in {first, second} for item in listed)


def test_batch_delete_partial_success_reports_failed_ids(client: httpx.Client):
    thread_id = _make_thread(client, "批量删除-部分失败")
    keep = _upload(client, thread_id, "保留.txt")

    response = client.post(
        "/api/v1/artifacts/batch-delete",
        json={"artifact_ids": [keep, "art_not_exist"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requested"] == 2
    assert body["deleted"] == 1
    assert [item["artifact_id"] for item in body["failed"]] == ["art_not_exist"]
    assert body["failed"][0]["deleted"] is False
    assert "art_not_exist" in body["failed"][0]["message"]


def test_batch_delete_dedupes_ids(client: httpx.Client):
    thread_id = _make_thread(client, "批量删除-去重")
    artifact_id = _upload(client, thread_id, "重复.txt")

    response = client.post(
        "/api/v1/artifacts/batch-delete",
        json={"artifact_ids": [artifact_id, artifact_id, f"  {artifact_id}  "]},
    )
    body = response.json()
    assert body["requested"] == 1
    assert body["deleted"] == 1
    assert body["failed"] == []


def test_batch_delete_empty_list_is_noop(client: httpx.Client):
    response = client.post("/api/v1/artifacts/batch-delete", json={"artifact_ids": []})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requested"] == 0
    assert body["deleted"] == 0
    assert body["failed"] == []
    assert body["trashed"] == []


def test_batch_delete_rejects_more_than_limit(client: httpx.Client):
    response = client.post(
        "/api/v1/artifacts/batch-delete",
        json={"artifact_ids": [f"art_{index}" for index in range(201)]},
    )
    # 统一错误处理把请求体校验失败映射为 400 + BAD_REQUEST（见 core/errors.py）
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BAD_REQUEST"
