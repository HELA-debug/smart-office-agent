"""主链路集成测试：批准 / 拒绝 / 超时 / 审计 / DOCX。"""

from __future__ import annotations

import httpx
from tests.helpers import approved_flow, docx_parts, has_heading, make_docx

SAMPLE = [
    "一、本周进展",
    "完成 V2.1 分层重构，接口双前缀打通。",
    "Agent 主链路联调通过，事件可持久化重放。",
    "二、关键数据",
    "8 张表迁移成功，mock 链路 30 帧事件。",
    "三、风险与问题",
    "真实模型 ReAct 尚未实现，需 B4 补齐。",
    "四、下周计划",
    "完成 B3 基础功能与前端联调。",
]


def prepared_thread(client: httpx.Client) -> dict:
    thread = client.post("/api/v1/threads", json={"title": "周报任务"}).json()
    response = client.post(
        f"/api/v1/threads/{thread['thread_id']}/files",
        files={
            "file": (
                "会议记录.docx",
                make_docx(SAMPLE),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201, response.text
    return thread


def first_index(events: list[tuple[str, dict]], name: str, tool: str | None = None) -> int:
    for index, (event_name, data) in enumerate(events):
        if event_name != name:
            continue
        if tool is None or data.get("tool") == tool:
            return index
    return -1


def tool_events(events: list[tuple[str, dict]]) -> list[dict]:
    return [data for name, data in events if name == "tool.finished"]


def test_full_run_completes_in_one_go(client: httpx.Client):
    thread = prepared_thread(client)
    thread_id = thread["thread_id"]

    events = approved_flow(client, thread_id)
    names = [name for name, _ in events]

    for required in (
        "run.started",
        "message.delta",
        "message.completed",
        "plan.updated",
        "tool.finished",
        "artifact.ready",
        "run.completed",
    ):
        assert required in names, required
    assert all(data.get("version") == 1 and data.get("run_id") for _, data in events)
    run_id = events[0][1]["run_id"]
    assert {data["run_id"] for _, data in events} == {run_id}

    order = [
        first_index(events, "run.started"),
        first_index(events, "message.delta"),
        first_index(events, "plan.updated"),
        first_index(events, "tool.finished", "file.list"),
        first_index(events, "tool.finished", "file.read"),
        first_index(events, "tool.finished", "doc.generate_report"),
        first_index(events, "artifact.ready"),
        first_index(events, "run.completed"),
    ]
    assert all(index >= 0 for index in order), order
    assert order == sorted(order), order

    started = events[0][1]
    assert started["mode"] == "mock" and started["degraded"] is False
    plan = [data for name, data in events if name == "plan.updated"][-1]
    statuses = {item["id"]: item["status"] for item in plan["todos"]}
    assert statuses == {
        "t1": "completed",
        "t2": "completed",
        "t3": "completed",
    }
    read_data = next(data for data in tool_events(events) if data["tool"] == "file.read")
    assert "字" in read_data["summary"] and read_data["output"]["chars"] > 0
    assert read_data["subagent"]["id"] == "doc_agent"
    doc_data = next(data for data in tool_events(events) if data["tool"] == "doc.generate_report")
    assert doc_data["ok"] is True and doc_data["output"]["artifact_id"]

    final = events[-1][1]
    assert final["status"] == "completed"
    assert final["tokens"] > 0 and final["cost_cny"] >= 0 and final["elapsed_ms"] >= 0
    assert len(final["artifact_ids"]) == 1
    assert final["approvals"] == [], "引擎不再发起审批，这里永远是空的"
    artifact_id = final["artifact_ids"][0]

    meta = client.get(f"/api/v1/artifacts/{artifact_id}").json()
    assert meta["type"] == "docx" and meta["size"] > 10000
    content = client.get(meta["download_url"]).content
    paragraphs, headings = docx_parts(content)
    for section in ["摘要", "本周进展", "关键数据", "风险与问题", "下周计划"]:
        assert has_heading(headings, section), headings
    text = "\n".join(paragraphs)
    # 成稿不带出处清单（2026-11-09 用户要求去掉）：正文里不出现「来源引用」与「第 N 段」
    assert "来源引用" not in text
    assert "第 1 段" not in text
    preview = client.get(meta["preview_url"])
    assert preview.status_code == 200 and "text/html" in preview.headers["content-type"]

    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "completed" and run["tokens"] == final["tokens"]

    audit = client.get(f"/api/v1/threads/{thread_id}/audit").json()
    audit_run = next(item for item in audit["runs"] if item["run_id"] == run_id)
    assert audit_run["status"] == "completed"
    assert audit_run["tokens"] == final["tokens"]
    assert audit_run["approvals"] == []  # 审批卡已删，审计里不该再有批准记录
    assert audit_run["artifacts"][0]["artifact_id"] == artifact_id

    # 产物名带素材名、事件和快照都带来源：同一天多份产物，右栏才分得清哪份对哪份
    artifact_event = next(data for name, data in events if name == "artifact.ready")
    assert artifact_event["sources"] == ["会议记录.docx"]
    assert "会议记录" in artifact_event["filename"]
    assert meta["sources"] == ["会议记录.docx"]
    detail = client.get(f"/api/v1/threads/{thread_id}").json()
    generated = [item for item in detail["artifacts"] if item["type"] not in ("upload",)]
    assert generated[0]["sources"] == ["会议记录.docx"]

    replay = client.get(f"/api/v1/runs/{run_id}/events", params={"after": 0}).json()
    assert len(replay["events"]) == len(events)


def test_thread_detail_exposes_uploads_for_right_panel(client: httpx.Client):
    """右栏「本次素材」要文件名 + 解析字数，不能让它去产物列表里猜。"""
    thread = prepared_thread(client)
    detail = client.get(f"/api/v1/threads/{thread['thread_id']}").json()
    uploads = detail["uploads"]
    assert len(uploads) == 1
    assert uploads[0]["filename"] == "会议记录.docx"
    assert uploads[0]["chars"] > 0
    assert uploads[0]["parsed"] is True
    # 素材类型单独给出来，前端靠它把 upload 从产物列表里摘掉
    assert uploads[0]["type"] == "docx"


def test_run_without_upload_still_generates_docx(client: httpx.Client):
    thread_id = client.post("/api/v1/threads", json={"title": "空素材"}).json()["thread_id"]
    events = approved_flow(client, thread_id, message="写一份周报")
    final = events[-1][1]
    assert final["status"] == "completed"
    artifact_id = final["artifact_ids"][0]
    content = client.get(f"/api/v1/artifacts/{artifact_id}/download").content
    _, headings = docx_parts(content)
    # 没有素材时只给干净骨架，不再每节写一句「素材里没有…」
    assert has_heading(headings, "摘要")


ESSAY = [
    "走观秋",
    "照片《杉道晴光》感悟",
    "图1 杉道晴光",
    "秋日午后，我取完快递往回走，无意间抬头，路旁的水杉不知什么时候就黄了。"
    "阳光从枝桠间漏下来，在路面洒下一片光影，落叶静静地躺在路边。",
    "照片《檐下望秋》感悟",
    "图2 檐下望秋",
    "下课铃一响，我无意间瞥见窗外，扇形的窗缝里露出一树金黄的叶子，亮得像一团暖光。",
]


def test_essay_material_uses_script_and_switches_template(client: httpx.Client):
    """没有周报要素的素材：必须先跑脚本解析，再按摘要模板成文，不能编。"""
    thread = client.post("/api/v1/threads", json={"title": "素材整理"}).json()
    upload = client.post(
        f"/api/v1/threads/{thread['thread_id']}/files",
        files={
            "file": (
                "走观秋.docx",
                make_docx(ESSAY),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert upload.status_code == 201, upload.text

    events = approved_flow(client, thread["thread_id"], message="把这份素材整理成周报")
    tools = tool_events(events)

    analyze = next(data for data in tools if data["tool"] == "doc.analyze_material")
    assert analyze["ok"] is True
    assert analyze["output"]["totals"]["files"] == 1
    assert analyze["output"]["totals"]["paragraphs"] >= 5
    # 脚本在文档成文之前跑：这是「有没有真的用脚本」的硬证据
    assert first_index(events, "tool.finished", "doc.analyze_material") < first_index(
        events, "tool.finished", "doc.generate_report"
    )

    final = events[-1][1]
    assert final["status"] == "completed"
    content = client.get(f"/api/v1/artifacts/{final['artifact_ids'][0]}/download").content
    paragraphs, headings = docx_parts(content)
    text = "\n".join(paragraphs)
    # 素材没有进展/数据/计划，不该硬套周报骨架
    assert not has_heading(headings, "本周进展")
    assert has_heading(headings, "素材构成")
    # 内容来自原文，而不是「完成了本周既定任务的梳理与交付」这类模板话
    assert "水杉" in text
    assert "完成了本周既定任务的梳理与交付" not in text
    # 图注不能被当成「关键数据」列出来
    assert not has_heading(headings, "关键数据")


def test_run_requires_message_and_unknown_thread(client: httpx.Client, thread: dict):
    bad = client.post(
        f"/api/v1/threads/{thread['thread_id']}/runs/stream",
        json={"message": "   "},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "BAD_REQUEST"

    missing = client.post("/api/v1/threads/th_missing/runs/stream", json={"message": "测试"})
    assert missing.status_code == 404
