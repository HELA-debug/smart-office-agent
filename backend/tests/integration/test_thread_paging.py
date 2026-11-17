"""会话列表分页（P2-15）：搜索/分页/置顶排序都下推 SQL。

并发跑测试时库里还有其他用例造的会话，因此统一用唯一前缀 q 过滤，
只看本用例自己创建的数据。
"""

from __future__ import annotations

import uuid

import httpx


def _create(client: httpx.Client, title: str) -> str:
    response = client.post("/api/v1/threads", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["thread_id"]


def test_thread_list_pages_with_pinned_first(client: httpx.Client):
    prefix = f"分页-{uuid.uuid4().hex[:8]}"
    ids = [_create(client, f"{prefix}-{index}") for index in range(5)]
    # 把最早创建的一条置顶，验证排序不是单纯按时间
    patched = client.patch(f"/api/v1/threads/{ids[0]}", json={"pinned": True})
    assert patched.status_code == 200, patched.text

    first = client.get("/api/v1/threads", params={"q": prefix, "page": 1, "page_size": 2}).json()
    assert first["total"] == 5
    assert first["page"] == 1
    assert first["page_size"] == 2
    titles = [item["title"] for item in first["threads"]]
    assert titles[0] == f"{prefix}-0"  # 置顶优先
    assert len(titles) == 2

    second = client.get("/api/v1/threads", params={"q": prefix, "page": 2, "page_size": 2}).json()
    third = client.get("/api/v1/threads", params={"q": prefix, "page": 3, "page_size": 2}).json()
    assert len(second["threads"]) == 2
    assert len(third["threads"]) == 1

    collected = [item["thread_id"] for page in (first, second, third) for item in page["threads"]]
    assert len(collected) == len(set(collected)) == 5
    assert set(collected) == set(ids)

    # 越界页返回空列表，total 仍准确
    beyond = client.get("/api/v1/threads", params={"q": prefix, "page": 9, "page_size": 2}).json()
    assert beyond["threads"] == []
    assert beyond["total"] == 5


def test_thread_search_matches_id(client: httpx.Client):
    prefix = f"检索-{uuid.uuid4().hex[:8]}"
    thread_id = _create(client, f"{prefix}-标题")

    by_title = client.get("/api/v1/threads", params={"q": prefix}).json()
    assert [item["thread_id"] for item in by_title["threads"]] == [thread_id]

    by_id = client.get("/api/v1/threads", params={"q": thread_id}).json()
    assert thread_id in [item["thread_id"] for item in by_id["threads"]]
    assert by_id["total"] >= 1


def test_thread_page_size_over_limit_is_rejected(client: httpx.Client):
    # API 层用 Query(ge=1, le=100) 卡上限；service 里的 clamp 只是兜底
    response = client.get("/api/v1/threads", params={"page": 1, "page_size": 500})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"

    zero = client.get("/api/v1/threads", params={"page": 0})
    assert zero.status_code == 400


def test_threads_reorder_endpoint_keeps_given_order(client: httpx.Client):
    """拖动排序：整份顺序传上来，后端按数组下标重写 sort_index。"""
    prefix = f"排序-{uuid.uuid4().hex[:8]}"
    ids = [_create(client, f"{prefix}-{index}") for index in range(3)]

    # 倒过来排：最后创建的最前
    response = client.post("/api/v1/threads/reorder", json={"thread_ids": list(reversed(ids))})
    assert response.status_code == 200, response.text
    assert response.json()["reordered"] == 3

    listed = client.get("/api/v1/threads", params={"q": prefix, "page_size": 10}).json()
    assert [item["thread_id"] for item in listed["threads"]] == list(reversed(ids))

    # 空列表在 schema 层就被挡住（应用把校验错误统一映射成 400），不会清空顺序
    empty = client.post("/api/v1/threads/reorder", json={"thread_ids": []})
    assert empty.status_code == 400
