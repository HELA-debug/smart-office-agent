"""API 矩阵：全部 v1 端点的元数据（方法 / 路径 / 是否可安全调用 / 样例请求体）。

这里的表是「手写」而不是从 OpenAPI 现算的，原因是自动化推导不知道哪些端点会
拉起系统窗口（open / reveal）、改仓库里的技能目录、或往开发者本地 .env 写 Key。
把破坏性端点显式标成 `ext`，测试就只会打它们的错误路径。

一句话：读得懂的表 > 聪明的推导。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MATRIX_PREFIX = "/api/v1"

Kind = Literal["ro", "rw", "ext", "bin", "stream"]
"""ro=只读可随意打；rw=写但只影响临时库/临时目录；ext=会碰系统或仓库文件；
bin=返回文件流；stream=SSE。"""

# 路径占位符 -> 种子数据里的键
PLACEHOLDERS: tuple[str, ...] = (
    "thread_id",
    "run_id",
    "artifact_id",
    "file_id",
    "template_id",
    "project_id",
    "skill_id",
    "model_id",
    "approval_id",
)


@dataclass(frozen=True)
class Op:
    method: str
    path: str
    kind: Kind
    body: dict[str, Any] | None = None
    body_required: bool = False
    query: dict[str, Any] = field(default_factory=dict)

    @property
    def op_id(self) -> str:
        return f"{self.method.upper()} {self.path}"

    @property
    def path_params(self) -> list[str]:
        return [name for name in PLACEHOLDERS if "{" + name + "}" in self.path]

    @property
    def is_json(self) -> bool:
        return self.kind in {"ro", "rw", "ext"}

    @property
    def is_upload(self) -> bool:
        return self.path in {"/api/v1/skills/import", "/api/v1/threads/{thread_id}/files"}


# ---------------------------------------------------------------- 端点表
# 顺序与 router 注册一致，方便肉眼对账。
OPS: tuple[Op, ...] = (
    # health
    Op("get", "/api/v1/health", "ro"),
    # threads
    Op("get", "/api/v1/threads", "ro"),
    Op("post", "/api/v1/threads", "rw", body={"title": "矩阵会话"}),
    Op(
        "post",
        "/api/v1/threads/bulk-delete",
        "rw",
        body={"thread_ids": ["__MISSING__"]},
        body_required=True,
    ),
    Op("get", "/api/v1/threads/{thread_id}", "ro"),
    Op("patch", "/api/v1/threads/{thread_id}", "rw", body={"title": "矩阵改名"}),
    Op("delete", "/api/v1/threads/{thread_id}", "rw"),
    Op(
        "post",
        "/api/v1/threads/{thread_id}/approvals/{approval_id}",
        "rw",
        body={"decision": "approved", "comment": "矩阵批准"},
        body_required=True,
    ),
    Op("get", "/api/v1/threads/{thread_id}/audit", "ro"),
    Op("get", "/api/v1/threads/{thread_id}/files", "ro"),
    Op("post", "/api/v1/threads/{thread_id}/files", "rw"),
    Op("get", "/api/v1/threads/{thread_id}/runs", "ro"),
    Op("post", "/api/v1/threads/{thread_id}/runs/stream", "stream", body={"message": "写个周报"}),
    # files
    Op("delete", "/api/v1/files/{file_id}", "rw"),
    # runs
    Op("get", "/api/v1/runs", "ro"),
    Op("get", "/api/v1/runs/{run_id}", "ro"),
    Op("post", "/api/v1/runs/{run_id}/cancel", "rw"),
    Op("get", "/api/v1/runs/{run_id}/events", "ro"),
    Op("get", "/api/v1/runs/{run_id}/events/stream", "stream"),
    Op("post", "/api/v1/runs/{run_id}/retry", "stream"),
    # artifacts
    Op("get", "/api/v1/artifacts", "ro"),
    Op("get", "/api/v1/artifacts/trash", "ro"),
    Op("post", "/api/v1/artifacts/batch-delete", "rw", body={"artifact_ids": []}),
    Op("get", "/api/v1/artifacts/{artifact_id}", "ro"),
    Op("get", "/api/v1/artifacts/{artifact_id}/download", "bin"),
    Op("get", "/api/v1/artifacts/{artifact_id}/preview", "bin"),
    Op("post", "/api/v1/artifacts/{artifact_id}/open", "ext"),
    Op("post", "/api/v1/artifacts/{artifact_id}/regenerate", "ext"),
    Op("post", "/api/v1/artifacts/{artifact_id}/restore", "rw"),
    Op("delete", "/api/v1/artifacts/{artifact_id}", "rw"),
    Op("delete", "/api/v1/artifacts/{artifact_id}/purge", "rw"),
    # settings / models
    Op("get", "/api/v1/settings", "ro"),
    Op("put", "/api/v1/settings", "rw", body={"mock_mode": True}),
    Op("get", "/api/v1/models", "ro"),
    Op(
        "post",
        "/api/v1/models",
        "rw",
        body={"provider": "deepseek", "model": "deepseek-flash", "priority": 50},
        body_required=True,
    ),
    Op(
        "put",
        "/api/v1/models/{model_id}/key",
        "ext",
        body={"api_key": "sk-matrix-0001"},
        body_required=True,
    ),
    Op("post", "/api/v1/models/{model_id}/test", "ext"),
    # templates
    Op("get", "/api/v1/templates", "ro"),
    Op(
        "post",
        "/api/v1/templates",
        "rw",
        body={"name": "矩阵模板", "sections": [{"heading": "本周进展", "source": "progress"}]},
        body_required=True,
    ),
    Op("delete", "/api/v1/templates/{template_id}", "rw"),
    Op("post", "/api/v1/templates/{template_id}/render", "ext"),
    # skills
    Op("get", "/api/v1/skills", "ro"),
    Op("get", "/api/v1/skills/catalog", "ro"),
    Op("post", "/api/v1/skills/catalog/{skill_id}/install", "ext"),
    Op("patch", "/api/v1/skills/{skill_id}", "ext", body={"enabled": False}, body_required=True),
    Op("delete", "/api/v1/skills/{skill_id}", "ext"),
    Op(
        "post",
        "/api/v1/skills/draft",
        "rw",
        body={"idea": "把会议记录整理成待办清单"},
        body_required=True,
    ),
    Op("post", "/api/v1/skills/import", "rw"),
    # storage
    Op("get", "/api/v1/storage/paths", "ro"),
    Op("get", "/api/v1/storage/browse", "ro"),
    Op(
        "post",
        "/api/v1/storage/browse/mkdir",
        "rw",
        body={"path": "", "name": "矩阵目录"},
        body_required=True,
    ),
    Op(
        "put",
        "/api/v1/storage/paths",
        "ext",
        body={"kind": "uploads", "path": ""},
        body_required=True,
    ),
    Op("post", "/api/v1/storage/reveal", "ext", body={"kind": "uploads"}, body_required=True),
    # projects
    Op("get", "/api/v1/projects", "ro"),
    Op("post", "/api/v1/projects", "rw", body={"path": ""}, body_required=True),
    Op("patch", "/api/v1/projects/{project_id}", "rw", body={"name": "矩阵项目"}),
    Op("delete", "/api/v1/projects/{project_id}", "rw"),
    Op("get", "/api/v1/projects/{project_id}/files", "ro"),
    Op("post", "/api/v1/projects/{project_id}/reveal", "ext"),
    # misc
    Op("get", "/api/v1/tools", "ro"),
    Op("get", "/api/v1/subagents", "ro"),
    Op("get", "/api/v1/prompt-packs", "ro"),
    Op("get", "/api/v1/usage/summary", "ro"),
    Op("get", "/api/v1/audit/export", "bin"),
    Op(
        "post",
        "/api/v1/feedback",
        "rw",
        body={"message": "矩阵反馈：都挺好", "kind": "other"},
        body_required=True,
    ),
)


def by_id() -> dict[str, Op]:
    return {op.op_id: op for op in OPS}


def fill_path(op: Op, ids: dict[str, str]) -> str:
    """把 {thread_id} 之类换成真实 id；缺的用 nope 兜底（打不存在的资源）。"""
    path = op.path
    for placeholder in op.path_params:
        path = path.replace("{" + placeholder + "}", ids.get(placeholder, f"nope_{placeholder}"))
    return path


def missing_path(op: Op, ids: dict[str, str], target: str) -> str:
    """只把某一个路径参数换成不存在的值，其余保持真实。"""
    path = op.path
    for placeholder in op.path_params:
        value = f"nope_{placeholder}" if placeholder == target else ids.get(placeholder, "nope")
        path = path.replace("{" + placeholder + "}", value)
    return path


def sample_body(op: Op, ids: dict[str, str]) -> dict[str, Any] | None:
    """把 __MISSING__ 占位换成本次请求该用的 id。"""
    if op.body is None:
        return None
    body = dict(op.body)
    if isinstance(body.get("artifact_ids"), list):
        body["artifact_ids"] = [
            ids.get("artifact_id", "nope") if item == "__MISSING__" else item
            for item in body["artifact_ids"]
        ]
    if isinstance(body.get("thread_ids"), list):
        body["thread_ids"] = [
            ids.get("thread_id", "nope") if item == "__MISSING__" else item
            for item in body["thread_ids"]
        ]
    return body
