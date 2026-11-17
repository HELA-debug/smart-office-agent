"""审批策略走完整条链路：请求体 → RunContext → 引擎判定 → SSE 事件。

只测「模式有没有真的传下去」，判定矩阵的细节在 unit/test_approval_modes.py。
"""

from __future__ import annotations

import httpx
from tests.helpers import read_sse

PREFIX = "/api/v1"


def _run_events(
    client: httpx.Client, thread_id: str, *, approval_mode: str | None
) -> list[tuple[str, dict]]:
    body: dict[str, object] = {"message": "把这份材料整理成 600 字周报", "mode": "mock"}
    if approval_mode is not None:
        body["approval_mode"] = approval_mode
    with client.stream("POST", f"{PREFIX}/threads/{thread_id}/runs/stream", json=body) as response:
        assert response.status_code == 200, response.text
        return read_sse(response.iter_lines(), stop_at="approval.required")


def test_all_allow_runs_without_approval(client: httpx.Client) -> None:
    thread_id = client.post(f"{PREFIX}/threads", json={}).json()["thread_id"]

    events = _run_events(client, thread_id, approval_mode="all_allow")
    names = [name for name, _ in events]
    assert "approval.required" not in names
    assert "run.started" in names


def test_default_mode_does_not_ask_before_writing(client: httpx.Client) -> None:
    """默认档：他明确让「整理成 600 字周报」，就不再问一遍。

    授权这件事在门控那关已经判过了——那句话本身就是授权。审批再问一次，
    用户看到的就是每生成一份文件点一次按钮；点久了只会变成闭眼点。
    """
    thread_id = client.post(f"{PREFIX}/threads", json={}).json()["thread_id"]

    events = _run_events(client, thread_id, approval_mode=None)
    assert "approval.required" not in [name for name, _ in events]


def test_always_ask_is_a_stricter_gate_not_a_card(client: httpx.Client) -> None:
    """「谨慎」档调的是放行线，不是弹不弹卡——卡片这一层已经没有了。

    同样一句「整理成 600 字周报」在两档下都不该冒出一张卡；差别在于把握度
    不够时谨慎档会先不动（判定矩阵见 unit/test_approval_modes.py）。
    """
    thread_id = client.post(f"{PREFIX}/threads", json={}).json()["thread_id"]

    events = _run_events(client, thread_id, approval_mode="always_ask")
    assert "approval.required" not in [name for name, _ in events]


def test_unknown_mode_falls_back_to_default(client: httpx.Client) -> None:
    thread_id = client.post(f"{PREFIX}/threads", json={}).json()["thread_id"]

    events = _run_events(client, thread_id, approval_mode="放行吧")
    # 拼错的值退回默认档（risky），跟不传一样：不为写盘弹卡，也不静默放行删除
    assert "approval.required" not in [name for name, _ in events]
