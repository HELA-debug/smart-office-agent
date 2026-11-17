"""B4 验收证据脚本：对运行中的服务走完整真实链路并落盘 JSON 证据（绝不含密钥）。

用法（仓库根）：
    ./.venv/Scripts/python.exe backend/tests/evidence/run_evidence.py \
        --base-url http://127.0.0.1:8001 --label real_deepseek

流程：建会话 -> 上传 docx + txt -> POST /runs/stream（mode=real）-> SSE 事件收集
-> approval.required 时自动批准 -> artifact 下载并用 python-docx 校验 -> 写证据 JSON。
"""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path
from typing import Any

import httpx

EVIDENCE_DIR = Path(__file__).resolve().parent

MATERIAL = """本周进展
1. 完成登录与权限模块联调，覆盖 12 个接口。
2. 工作台三栏布局与 SSE 流式渲染上线。
关键数据
周报生成平均耗时 1.1 秒，DOCX 平均 37KB。
风险与问题
真实模型超时重试策略仍需压测，存在 1 次超时风险。
下周计划
完成真实模型降级链路验证，并补齐审计页。"""


def make_docx() -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("本周工作素材", level=1)
    for line in MATERIAL.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def upload(
    client: httpx.Client, thread_id: str, filename: str, content: bytes, mime: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": (filename, content, mime)},
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"上传失败 {response.status_code}: {response.text[:300]}")
    return response.json()


def run_stream(
    client: httpx.Client, thread_id: str, *, message: str, prefix: str = "/api/v1"
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with client.stream(
        "POST",
        f"{prefix}/threads/{thread_id}/runs/stream",
        json={"message": message, "mode": "real"},
    ) as response:
        if response.status_code != 200:
            raise RuntimeError(f"运行失败 {response.status_code}: {response.text[:300]}")
        current: dict[str, Any] = {}
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                current["seq"] = int(line[len("id:") :].strip())
            elif line.startswith("event:"):
                current["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                current["data"] = json.loads(line[len("data:") :].strip())
            elif line == "" and current.get("event"):
                event = {
                    "seq": current.get("seq"),
                    "event": current["event"],
                    **current.get("data", {}),
                }
                events.append(event)
                if event["event"] == "approval.required":
                    decision = client.post(
                        f"{prefix}/threads/{thread_id}/approvals/{event['approval_id']}",
                        json={"decision": "approved", "comment": "验收脚本自动批准"},
                    )
                    if decision.status_code != 200:
                        raise RuntimeError(f"审批失败: {decision.text[:300]}")
                current = {}
    return events


def summarize(events: list[dict[str, Any]], artifact_bytes: bytes | None) -> dict[str, Any]:
    started = next((event for event in events if event["event"] == "run.started"), {})
    completed = next((event for event in events if event["event"] == "run.completed"), {})
    failed = next((event for event in events if event["event"] == "run.failed"), None)
    tools = [
        {
            "tool": event.get("tool"),
            "ok": event.get("ok"),
            "duration_ms": event.get("duration_ms"),
            "summary": event.get("summary"),
        }
        for event in events
        if event["event"] == "tool.finished"
    ]
    artifact_ids = completed.get("artifact_ids") or []
    docx_paragraphs: list[str] = []
    if artifact_bytes:
        from docx import Document

        document = Document(io.BytesIO(artifact_bytes))
        docx_paragraphs = [p.text for p in document.paragraphs if p.text.strip()][:12]
    return {
        "run_started": {
            "mode": started.get("mode"),
            "engine": started.get("engine"),
            "model": started.get("model"),
            "provider": started.get("provider"),
            "degraded": started.get("degraded"),
        },
        "run_failed": failed,
        "event_sequence": [event["event"] for event in events],
        "event_count": len(events),
        "tools": tools,
        "approval_events": [
            {
                "tool": event.get("tool"),
                "risk": event.get("risk"),
                "approval_id": event.get("approval_id"),
            }
            for event in events
            if event["event"] == "approval.required"
        ],
        "artifact_ids": artifact_ids,
        "docx_paragraphs": docx_paragraphs,
        "run_completed": {
            "status": completed.get("status"),
            "tokens": completed.get("tokens"),
            "cost_cny": completed.get("cost_cny"),
            "elapsed_ms": completed.get("elapsed_ms"),
            "engine": completed.get("engine"),
            "provider": completed.get("provider"),
            "model": completed.get("model"),
            "degraded": completed.get("degraded"),
            "stop_reason": completed.get("stop_reason"),
            "approvals": completed.get("approvals"),
            "usage": completed.get("usage"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--label", default="real_deepseek")
    parser.add_argument(
        "--message", default="把上传素材整理成周报，生成 DOCX，并发我邮箱草稿（需审批）"
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=240, trust_env=False) as client:
        health = client.get("/api/v1/health").json()
        thread = client.post("/api/v1/threads", json={"title": f"B4 {args.label}"}).json()
        thread_id = thread["thread_id"]
        uploads = [
            upload(client, thread_id, "本周素材.txt", MATERIAL.encode("utf-8"), "text/plain"),
            upload(
                client,
                thread_id,
                "会议记录.docx",
                make_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ]
        started_at = time.time()
        events = run_stream(client, thread_id, message=args.message)
        duration = round(time.time() - started_at, 2)

        completed = next((event for event in events if event["event"] == "run.completed"), {})
        artifact_bytes = None
        download_info = None
        if completed.get("artifact_ids"):
            artifact_id = completed["artifact_ids"][0]
            download = client.get(f"/api/v1/artifacts/{artifact_id}/download")
            if download.status_code == 200:
                artifact_bytes = download.content
                download_info = {
                    "artifact_id": artifact_id,
                    "status": download.status_code,
                    "bytes": len(download.content),
                    "content_type": download.headers.get("content-type"),
                }

        evidence = {
            "label": args.label,
            "base_url": args.base_url,
            "health": health,
            "thread_id": thread_id,
            "uploads": uploads,
            "duration_seconds": duration,
            "download": download_info,
            **summarize(events, artifact_bytes),
        }
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        output = EVIDENCE_DIR / f"{args.label}.json"
        output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "evidence": str(output),
                    "run_started": evidence["run_started"],
                    "run_completed": evidence["run_completed"],
                    "tools": [item["tool"] for item in evidence["tools"]],
                    "approval_events": evidence["approval_events"],
                    "download": download_info,
                    "docx_head": evidence["docx_paragraphs"][:3],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
