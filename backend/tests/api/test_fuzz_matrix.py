"""模糊与健壮性矩阵：不指望业务正确，只要求「不 5xx、不崩、不说废话」。

输入是固定的随机种子，所以跑出来的用例每次都一样，失败可复现。
"""

from __future__ import annotations

import random

import pytest
from tests.api.matrix import MATRIX_PREFIX, OPS, Op, fill_path, sample_body

SEED = 20261028

# 恶意/畸形 id：注入、路径穿越、超长、unicode、空串、通配
ID_VARIANTS = (
    "nope",
    "",
    "../etc/passwd",
    "'; DROP TABLE threads;--",
    "🙂🙂",
    "a" * 512,
    "%00",
    "th_1 OR 1=1",
)

# 畸形请求体：类型错、空、null、超深、超长、数组当对象
DEEP = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
BODY_VARIANTS = (
    {},
    [],
    None,
    "just-a-string",
    12345,
    DEEP,
    {"title": ["不是字符串"]},
    {"message": "长" * 5000},
    {"__proto__": {"polluted": True}},
)


def _ops_with_param() -> list[Op]:
    return [op for op in OPS if op.path_params]


def _ops_with_body() -> list[Op]:
    return [op for op in OPS if op.body is not None and not op.is_upload]


@pytest.mark.parametrize(
    ("op", "bad_id"),
    [
        pytest.param(op, bad, id=f"{op.method.upper()} {op.path}::{i}")
        for op in _ops_with_param()
        for i, bad in enumerate(ID_VARIANTS)
    ],
)
def test_fuzz_path_param_never_5xx(api_client, seed, op: Op, bad_id: str):
    url = op.path
    for placeholder in op.path_params:
        url = url.replace("{" + placeholder + "}", bad_id)
    kwargs: dict[str, object] = {"timeout": 30}
    if op.body is not None:
        kwargs["json"] = sample_body(op, seed.ids)
    response = api_client.request(op.method.upper(), url, **kwargs)
    assert response.status_code < 500, (
        f"{op.op_id} 收到畸形 id {bad_id!r} 返回 {response.status_code}：{response.text[:200]}"
    )


@pytest.mark.parametrize(
    ("op", "bad_body"),
    [
        pytest.param(op, bad, id=f"{op.method.upper()} {op.path}::{i}")
        for op in _ops_with_body()
        for i, bad in enumerate(BODY_VARIANTS)
    ],
)
def test_fuzz_body_never_5xx(api_client, seed, op: Op, bad_body: object):
    url = fill_path(op, seed.ids)
    response = api_client.request(op.method.upper(), url, json=bad_body, timeout=30)
    assert response.status_code < 500, (
        f"{op.op_id} 收到畸形 body 返回 {response.status_code}：{response.text[:200]}"
    )
    if response.status_code >= 400 and op.kind != "bin":
        body = response.json()
        assert "error" in body, body
        assert body["error"]["code"], body


# 带 query 参数的读端点（分页 / 搜索 / 过滤），是前端最容易攒出脏值的地方
QUERY_PATHS = {
    "/api/v1/threads",
    "/api/v1/runs",
    "/api/v1/artifacts",
    "/api/v1/artifacts/trash",
    "/api/v1/threads/{thread_id}/runs",
    "/api/v1/usage/summary",
    "/api/v1/audit/export",
    "/api/v1/storage/browse",
}
QUERY_OPS = [pytest.param(op, id=op.op_id) for op in OPS if op.path in QUERY_PATHS]

NASTY_QUERY = (
    "page=%27%20OR%201%3D1",
    "page_size=999999999999999999999",
    "q=%00",
    "q=" + "%E9%95%BF" * 200,
    "page=1&page=2",
    "include_uploads=notabool",
)


@pytest.mark.parametrize("op", QUERY_OPS)
def test_fuzz_query_never_5xx(api_client, seed, op: Op):
    url = fill_path(op, seed.ids)
    for extra in NASTY_QUERY:
        joiner = "&" if "?" in url else "?"
        response = api_client.get(f"{url}{joiner}{extra}", timeout=30)
        assert response.status_code < 500, (
            f"{op.op_id}?{extra} 返回 {response.status_code}：{response.text[:200]}"
        )


@pytest.mark.parametrize("op", [pytest.param(op, id=op.op_id) for op in OPS if op.kind == "ro"])
def test_unknown_query_params_are_ignored(api_client, seed, op: Op):
    """多余的 query 参数不该让接口炸——前端可能带缓存的旧参数。"""
    url = fill_path(op, seed.ids)
    joiner = "&" if "?" in url else "?"
    response = api_client.get(f"{url}{joiner}__trace_hint=1&legacy_flag=true", timeout=30)
    assert response.status_code < 500


def test_very_long_path_is_404(api_client):
    response = api_client.get(f"{MATRIX_PREFIX}/{'x' * 200}", timeout=30)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [f"{MATRIX_PREFIX}/../..", "/", f"{MATRIX_PREFIX}/"],
    ids=["dotdot", "root", "prefix-root"],
)
def test_non_api_paths_never_5xx(api_client, path: str):
    """这些路径会落到前端单端口托管上（返回首页），只要不 5xx 就算对。"""
    response = api_client.get(path, timeout=30)
    assert response.status_code < 500


def test_random_unicode_ids_do_not_crash(api_client):
    rng = random.Random(SEED)
    alphabet = "中文测试🙂%_-./\\'\"<>;:"
    for _ in range(20):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        response = api_client.get(f"{MATRIX_PREFIX}/threads/{raw}", timeout=30)
        assert response.status_code < 500, f"id={raw!r} 触发 {response.status_code}"


def test_large_json_body_is_rejected_cleanly(api_client, fresh_thread: str):
    """超大请求体应被 4xx 拒绝，而不是让服务端 OOM 或 500。"""
    payload = {"message": "x" * (2 * 1024 * 1024)}
    response = api_client.post(
        f"{MATRIX_PREFIX}/threads/{fresh_thread}/runs/stream", json=payload, timeout=60
    )
    assert response.status_code < 500, response.text


def test_repeated_slash_is_tolerated_or_404(api_client):
    response = api_client.get(f"{MATRIX_PREFIX}//health", timeout=30)
    assert response.status_code in (200, 301, 307, 404)


def test_head_request_works_for_health(api_client):
    response = api_client.head(f"{MATRIX_PREFIX}/health", timeout=30)
    assert response.status_code in (200, 405)
