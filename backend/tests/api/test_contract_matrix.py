"""协议层矩阵：每个端点的「外壳」必须一致。

这一层不关心业务，只回答四个问题：
1. 每个端点都在吗（不是 404/405）？
2. 任何响应都带 X-Trace-ID 吗？
3. 被拒绝时是不是统一的 {"trace_id", "error": {"code", "message"}}？
4. 请求体 / 路径参数 / Content-Type 写错时，是 4xx 而不是 5xx 吗？

用例由 matrix.OPS 自动派生，新增端点只要往表里加一行就会被覆盖。
"""

from __future__ import annotations

import pytest
from tests.api.matrix import (
    MATRIX_PREFIX,
    OPS,
    Op,
    fill_path,
    missing_path,
    sample_body,
)

OP_PARAMS = [pytest.param(op, id=op.op_id) for op in OPS]
# 可达性只测「打一万次也不会改变状态」的端点：读与下载。
# 写/删除/流式端点的正向路径由语义矩阵单独覆盖——否则跑一遍可达性就把种子数据删光了。
READ_OPS = [pytest.param(op, id=op.op_id) for op in OPS if op.kind in {"ro", "bin"}]
# 这几个读端点不校验父资源是否存在：查一个不存在的会话的「运行/素材/审计」，
# 语义上就是「空」，返回 200 + 空列表比 404 更贴合前端轮询的需要。
LENIENT_PARENTS = {
    "/api/v1/threads/{thread_id}/runs",
    "/api/v1/threads/{thread_id}/files",
    "/api/v1/threads/{thread_id}/audit",
}
ERROR_PROBE_OPS = [
    pytest.param(op, id=op.op_id)
    for op in OPS
    if (op.path_params or (op.body is not None and op.method in {"post", "put", "patch"}))
    and op.path not in LENIENT_PARENTS
]
BODY_OPS = [
    pytest.param(op, id=op.op_id)
    for op in OPS
    if op.body is not None and not op.is_upload and op.method in {"post", "put", "patch"}
]
REQUIRED_BODY_OPS = [
    pytest.param(op, id=op.op_id) for op in OPS if op.body_required and not op.is_upload
]
PATH_PARAM_CASES = [
    pytest.param(op, name, id=f"{op.method.upper()} {op.path}[{name}]")
    for op in OPS
    for name in op.path_params
    if op.path not in LENIENT_PARENTS
]


def _error_probe(client, op: Op, ids: dict[str, str]):
    """发一个注定被拒的请求。"""
    if op.path_params:
        url = missing_path(op, ids, op.path_params[0])
        return client.request(op.method.upper(), url, json=sample_body(op, ids), timeout=30)
    return client.request(
        op.method.upper(),
        fill_path(op, ids),
        content=b'{"broken": ',
        headers={"content-type": "application/json"},
        timeout=30,
    )


def test_unknown_route_is_json_404(api_client):
    response = api_client.get(f"{MATRIX_PREFIX}/this-route-does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert response.headers["X-Trace-ID"] == body["trace_id"]


@pytest.mark.parametrize("op", READ_OPS)
def test_known_operation_reachable(api_client, seed, op: Op):
    """合法请求不能落到 404（路由存在）或 405（方法对得上）。"""
    url = fill_path(op, seed.ids)
    kwargs: dict[str, object] = {"timeout": 60}
    if op.body is not None and not op.is_upload:
        kwargs["json"] = sample_body(op, seed.ids)
    if op.is_upload:
        response = api_client.post(
            url,
            files={"file": ("矩阵.txt", b"hello\n", "text/plain")},
            timeout=60,
        )
    else:
        response = api_client.request(op.method.upper(), url, **kwargs)
    assert response.status_code not in (404, 405), (
        f"{op.op_id} 路由不可达：{response.status_code} {response.text[:200]}"
    )


@pytest.mark.parametrize("op", ERROR_PROBE_OPS)
def test_trace_header_on_error(api_client, seed, op: Op):
    response = _error_probe(api_client, op, seed.ids)
    assert response.headers.get("X-Trace-ID"), f"{op.op_id} 的错误响应缺 X-Trace-ID"


@pytest.mark.parametrize("op", ERROR_PROBE_OPS)
def test_error_envelope_shape(api_client, seed, op: Op):
    response = _error_probe(api_client, op, seed.ids)
    assert 400 <= response.status_code < 500, (
        f"{op.op_id} 应拒绝非法请求，实际 {response.status_code} {response.text[:200]}"
    )
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"trace_id", "error"}, body
    assert body["error"]["code"]
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["trace_id"] == response.headers["X-Trace-ID"]


@pytest.mark.parametrize("op", BODY_OPS)
def test_malformed_json_is_400(api_client, seed, op: Op):
    url = fill_path(op, seed.ids)
    response = api_client.request(
        op.method.upper(),
        url,
        content=b'{"title": ',
        headers={"content-type": "application/json"},
        timeout=30,
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.parametrize("op", BODY_OPS)
def test_wrong_content_type_is_400(api_client, seed, op: Op):
    url = fill_path(op, seed.ids)
    response = api_client.request(
        op.method.upper(),
        url,
        content=b'{"a": 1}',
        headers={"content-type": "text/plain"},
        timeout=30,
    )
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("op", REQUIRED_BODY_OPS)
def test_missing_required_body_is_400(api_client, seed, op: Op):
    url = fill_path(op, seed.ids)
    response = api_client.request(op.method.upper(), url, json={}, timeout=30)
    assert response.status_code == 400, response.text
    details = response.json()["error"].get("details")
    assert details, "必填字段缺失时应给出 details 说明缺了什么"


@pytest.mark.parametrize(("op", "param"), PATH_PARAM_CASES)
def test_unknown_path_param_is_404(api_client, seed, op: Op, param: str):
    url = missing_path(op, seed.ids, param)
    kwargs: dict[str, object] = {"timeout": 30}
    if op.body is not None and not op.is_upload:
        kwargs["json"] = sample_body(op, seed.ids)
    response = api_client.request(op.method.upper(), url, **kwargs)
    assert response.status_code in (400, 404, 409), (
        f"{op.op_id} 对不存在的 {param} 返回了 {response.status_code}"
    )
    assert response.json()["error"]["code"] in {"NOT_FOUND", "BAD_REQUEST", "CONFLICT"}


METHODS = ("get", "post", "put", "patch", "delete")
PATHS = sorted({op.path for op in OPS})
# 这两条会被 /threads/{thread_id}、/artifacts/{artifact_id} 的通配路由先接住，
# 用 GET 探会被当成「id 叫 bulk-delete 的会话」返回 404，所以换一个通配路由也不支持的方法。
SHADOWED_PATHS = {"/api/v1/threads/bulk-delete", "/api/v1/artifacts/batch-delete"}


@pytest.mark.parametrize("path", PATHS, ids=PATHS)
def test_method_not_allowed(api_client, path: str):
    allowed = {op.method for op in OPS if op.path == path}
    if path in SHADOWED_PATHS:
        blocked = "put"
    else:
        blocked = next(method for method in METHODS if method not in allowed)
    response = api_client.request(blocked.upper(), path, timeout=30)
    assert response.status_code == 405, (
        f"{path} 的 {blocked.upper()} 应 405，实际 {response.status_code}"
    )
    assert response.headers.get("X-Trace-ID")


@pytest.mark.parametrize("op", OP_PARAMS)
def test_legacy_prefix_alias(api_client, seed, op: Op):
    """双前缀兼容：/api/xxx 与 /api/v1/xxx 行为一致，且老前缀带弃用头。"""
    if op.kind in {"ext", "stream", "bin"}:
        pytest.skip("只比对无副作用的读端点")
    legacy_path = op.path.replace(MATRIX_PREFIX, "/api", 1)
    ids = seed.ids
    for placeholder in op.path_params:
        legacy_path = legacy_path.replace("{" + placeholder + "}", ids.get(placeholder, "nope"))
    response = api_client.get(legacy_path, timeout=30) if op.method == "get" else None
    if response is None:
        pytest.skip("非 GET 的老前缀等价性由集成测试覆盖")
    assert response.status_code == 200
    assert response.headers.get("Deprecation") == "true"
