"""pytest 公共夹具与辅助函数（V2.1 B5 smoke）。

设计原则：
- 纯黑盒：只通过 HTTP 访问后端，不 import backend 代码；
- 默认连 mock 服务 http://127.0.0.1:8004（避免误用真实模型、产生费用）；
- 若后端不是 mock 模式，直接退出并提示，防止 smoke 打到真实供应商；
- 临时文件一律用 tmp_path，测试结束仓库根保持干净。

运行：先起 mock 服务，再 `pytest tests -q`
    MOCK_MODE=true DATABASE_URL=sqlite:///data/b5_mock.db \\
    .venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8004
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Windows 环境 NO_PROXY 含 [::1] 会让 httpx 抛 InvalidURL；导入 httpx 前清理。
for _proxy_var in ("NO_PROXY", "no_proxy"):
    os.environ[_proxy_var] = "localhost,127.0.0.1"

import httpx
import pytest

DEFAULT_BASE_URL = "http://127.0.0.1:8004"
TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOCK_START_HINT = (
    "未检测到 mock 服务（{base}/api/v1/health）。请先启动：\n"
    "  MOCK_MODE=true DATABASE_URL=sqlite:///data/b5_mock.db \\\n"
    "  UPLOAD_DIR=./data/b5/uploads ARTIFACT_DIR=./data/b5/artifacts OUTBOX_DIR=./data/b5/outbox \\\n"
    "  .venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8004\n"
    "或使用 make smoke（自动起停 mock 服务）。"
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--base-url",
        action="store",
        default=None,
        help="后端地址，默认取环境变量 BASE_URL 或 http://127.0.0.1:8004",
    )


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    return (
        request.config.getoption("--base-url")
        or os.environ.get("BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


@pytest.fixture(scope="session")
def client(base_url: str) -> httpx.Client:
    # trust_env=False：不读系统代理变量（Windows NO_PROXY=[::1] 问题，见 KNOWN_ISSUES）
    with httpx.Client(
        base_url=base_url, timeout=httpx.Timeout(30.0, read=180.0), trust_env=False
    ) as c:
        yield c


def _health_or_exit(client: httpx.Client) -> dict[str, Any]:
    try:
        resp = client.get("/api/v1/health")
    except httpx.HTTPError as exc:
        pytest.exit(MOCK_START_HINT.format(base=client.base_url) + f"\n原因：{exc}", returncode=2)
    if resp.status_code != 200:
        pytest.exit(
            f"/api/v1/health 返回 {resp.status_code}：{resp.text[:200]}\n"
            + MOCK_START_HINT.format(base=client.base_url),
            returncode=2,
        )
    return resp.json()


@pytest.fixture(scope="session", autouse=True)
def require_mock_backend(client: httpx.Client) -> None:
    """后端不在线或不是 mock 模式时立即退出（绝不污染真实模型调用）。

    例外：显式 RUN_REAL_MODEL_TEST=1 时允许真实模式（仅 tests/test_real_smoke.py 使用）。
    """
    health = _health_or_exit(client)
    if os.environ.get("RUN_REAL_MODEL_TEST") == "1":
        if health.get("mode") != "real":
            pytest.exit(
                "RUN_REAL_MODEL_TEST=1 需要真实模式后端（BASE_URL=http://127.0.0.1:8000）；"
                f"当前 mode={health.get('mode')!r}（{client.base_url}）",
                returncode=2,
            )
        return
    if health.get("mode") != "mock":
        pytest.exit(
            f"当前后端 mode={health.get('mode')!r}，smoke 只允许 mock 模式"
            "（避免真实模型费用与不稳定；真实模型验证用 RUN_REAL_MODEL_TEST=1"
            " + BASE_URL=http://127.0.0.1:8000）。\n"
            + MOCK_START_HINT.format(base=client.base_url),
            returncode=2,
        )


@pytest.fixture()
def thread(client: httpx.Client) -> dict[str, Any]:
    import uuid

    resp = client.post("/api/v1/threads", json={"title": f"smoke-{uuid.uuid4().hex[:8]}"})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def restore_settings(client: httpx.Client) -> dict[str, Any]:
    """快照并恢复可热更新的设置，避免用例间互相污染。"""
    keys = [
        "approval_rules",
        "mock_mode",
        "model_provider",
        "model_name",
        "fallback_chain",
        "mail_to",
        "max_upload_mb",
        "model_timeout_seconds",
        "approval_timeout_seconds",
        "feature_flags",
    ]
    before = client.get("/api/v1/settings").json()
    snapshot = {key: before[key] for key in keys if key in before}
    yield before
    client.put("/api/v1/settings", json=snapshot)


# ---------------------------------------------------------------------------
# HTTP 辅助
# ---------------------------------------------------------------------------


def upload(
    client: httpx.Client,
    thread_id: str,
    filename: str,
    data: bytes,
    content_type: str = "text/plain",
) -> httpx.Response:
    return client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": (filename, data, content_type)},
    )


def decide(
    client: httpx.Client, thread_id: str, approval_id: str, decision: str = "approved"
) -> httpx.Response:
    return client.post(
        f"/api/v1/threads/{thread_id}/approvals/{approval_id}",
        json={"decision": decision, "comment": "smoke"},
    )


def consume_sse(
    client: httpx.Client,
    path: str,
    *,
    method: str = "POST",
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    thread_id: str | None = None,
    auto_decision: str | None = None,
    on_frame: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, dict[str, str], list[dict[str, Any]]]:
    """同步消费 SSE 流；approval.required 时可按 auto_decision 自动提交审批。"""
    frames: list[dict[str, Any]] = []
    with client.stream(method, path, json=json_body, headers=headers) as resp:
        status = resp.status_code
        resp_headers = dict(resp.headers)
        if status != 200:
            raise AssertionError(f"SSE 期望 200，实际 {status}: {resp.read()[:300]!r}")
        event_name: str | None = None
        seq: int | None = None
        for line in resp.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                seq = int(line.split(":", 1)[1].strip())
            elif line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
                frame = {"id": seq, "event": event_name, "data": data}
                frames.append(frame)
                if on_frame is not None:
                    on_frame(frame)
                if event_name == "approval.required" and auto_decision and thread_id:
                    resp_decision = decide(
                        client, thread_id, str(data.get("approval_id")), auto_decision
                    )
                    assert resp_decision.status_code == 200, resp_decision.text
                if event_name in TERMINAL_EVENTS:
                    return status, resp_headers, frames
    return status, resp_headers, frames


class SseReader:
    """后台线程消费 SSE，主线程可在 approval.required / run.started 后再操作。"""

    def __init__(
        self,
        base_url: str,
        path: str,
        *,
        method: str = "POST",
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.path = path
        self.method = method
        self.json_body = json_body
        self.headers = headers
        self.events: list[dict[str, Any]] = []
        self.status_code: int | None = None
        self.error: BaseException | None = None
        self.done = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> "SseReader":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, read=180.0),
                trust_env=False,
            ) as client:
                with client.stream(
                    self.method, self.path, json=self.json_body, headers=self.headers
                ) as resp:
                    self.status_code = resp.status_code
                    if resp.status_code != 200:
                        raise AssertionError(f"SSE HTTP {resp.status_code}: {resp.read()[:300]!r}")
                    event_name: str | None = None
                    seq: int | None = None
                    for line in resp.iter_lines():
                        if line.startswith(":"):
                            continue
                        if line.startswith("id:"):
                            seq = int(line.split(":", 1)[1].strip())
                        elif line.startswith("event:"):
                            event_name = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"):
                            data = json.loads(line.split(":", 1)[1].strip())
                            with self._lock:
                                self.events.append({"id": seq, "event": event_name, "data": data})
                            if event_name in TERMINAL_EVENTS:
                                return
        except BaseException as exc:  # noqa: BLE001 - 交由断言处抛出
            self.error = exc
        finally:
            self.done.set()

    def names(self) -> list[str]:
        with self._lock:
            return [frame["event"] for frame in self.events]

    def get(self, event: str) -> dict[str, Any] | None:
        with self._lock:
            for frame in self.events:
                if frame["event"] == event:
                    return frame["data"]
        return None

    def wait_for(self, event: str, timeout: float = 60.0) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self.get(event)
            if data is not None:
                return data
            if self.done.is_set() and self.error:
                raise self.error
            if self.done.is_set():
                raise AssertionError(f"事件 {event} 未出现；已收到：{self.names()}")
            time.sleep(0.02)
        raise AssertionError(f"等待事件 {event} 超时；已收到：{self.names()}")

    def join(self, timeout: float = 180.0) -> None:
        if not self.done.wait(timeout):
            raise AssertionError(f"SSE 流未在 {timeout}s 内结束；已收到：{self.names()}")
        if self.error:
            raise self.error
        if self._thread is not None:
            self._thread.join(timeout=2)


def run_flow(
    client: httpx.Client,
    thread_id: str,
    *,
    decision: str = "approved",
    message: str = "把素材整理成 600 字周报",
) -> list[dict[str, Any]]:
    """跑一次完整主链路并返回事件帧。"""
    _, _, frames = consume_sse(
        client,
        f"/api/v1/threads/{thread_id}/runs/stream",
        json_body={"message": message, "mode": "mock"},
        thread_id=thread_id,
        auto_decision=decision,
    )
    return frames


def outbox_snapshot() -> list[str] | None:
    """mock 发件箱快照（本地 mock 服务可读时返回；远程服务返回 None 则跳过文件断言）。"""
    candidates = [
        os.environ.get("OUTBOX_DIR"),
        str(PROJECT_ROOT / "data" / "b5" / "outbox"),
        str(PROJECT_ROOT / "data" / "outbox"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        directory = Path(candidate)
        if directory.is_dir():
            return sorted(
                str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()
            )
    return None


def frames_by_name(frames: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [frame["data"] for frame in frames if frame["event"] == name]


def assert_error(resp: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, f"期望 {status}，实际 {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert body.get("error", {}).get("code") == code, body
    assert body.get("trace_id"), "错误体缺少 trace_id"
    return body
