"""真实 DeepSeek 集成测试（B4 验收）：默认跳过，需显式开启。

运行方式（Key 从项目根 .env / 环境变量读取，绝不打印）：

    cd backend
    RUN_REAL_MODEL_TEST=1 ../.venv/Scripts/python.exe -m pytest tests/e2e/test_real_deepseek.py -q -s

断言目标：真实模型在 ReAct 循环中**自主**调用工具（file.read / doc.generate_report），
产生 artifact 与 DOCX（可被 python-docx 打开），run.started 含 provider=deepseek，
run.completed 携带真实的 tokens/cost/usage。审批若被模型触发则自动批准。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.core.config import Settings

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(
        os.environ.get("RUN_REAL_MODEL_TEST") != "1",
        reason="真实模型集成测试默认跳过；设置 RUN_REAL_MODEL_TEST=1 才运行",
    ),
]


def _real_settings(tmp_path: Path) -> Settings:
    base = Settings()
    if not base.real_model_configured:
        pytest.skip("未配置真实模型（MOCK_MODE=true 或缺少 DeepSeek Key），跳过真模型测试")
    return base.model_copy(
        update={
            "mock_mode": False,
            "model_provider": "deepseek",
            "model_name": "deepseek-chat",
            "model_fallback_chain": "deepseek,qwen,glm,mock",
            "approval_rules": "doc.generate_report,file.delete",
            "approval_timeout_seconds": 120,
            "serve_frontend": False,
            "model_timeout_seconds": 60,
            "model_max_steps": 12,
            "mock_model_speed": 0,
            "database_url": f"sqlite:///{tmp_path / 'real.db'}",
            "upload_dir": str(tmp_path / "uploads"),
            "artifact_dir": str(tmp_path / "artifacts"),
            "log_level": "WARNING",
            "log_format": "text",
        }
    )


def _start_server(app: Any) -> Iterator[str]:
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn 未能启动"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _upload_text(client: httpx.Client, thread_id: str, filename: str, text: str) -> None:
    response = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code in (200, 201), response.text


def test_real_deepseek_react_weekly_report(tmp_path: Path) -> None:
    from app.main import create_app

    settings = _real_settings(tmp_path / "data")
    settings.ensure_dirs()
    app = create_app(settings)
    server_gen = _start_server(app)
    base_url = next(server_gen)
    try:
        with httpx.Client(base_url=base_url, timeout=180, trust_env=False) as client:
            thread = client.post("/api/v1/threads", json={"title": "真实模型周报"}).json()
            thread_id = thread["thread_id"]
            material = (
                "本周进展\n"
                "1. 完成登录与权限模块联调，覆盖 12 个接口。\n"
                "2. 工作台三栏布局与 SSE 流式渲染上线。\n"
                "关键数据\n"
                "周报生成平均耗时 1.1 秒，DOCX 平均 37KB。\n"
                "风险与问题\n"
                "真实模型超时重试策略仍需压测，存在 1 次超时风险。\n"
                "下周计划\n"
                "完成真实模型降级链路验证，并补齐审计页。"
            )
            _upload_text(client, thread_id, "本周素材.txt", material)

            events: list[dict[str, Any]] = []
            with client.stream(
                "POST",
                f"/api/v1/threads/{thread_id}/runs/stream",
                json={
                    "message": "把这份素材整理成周报，生成 DOCX，并发我邮箱草稿",
                    "mode": "real",
                },
            ) as response:
                assert response.status_code == 200
                current: dict[str, Any] = {}
                for line in response.iter_lines():
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        current["event"] = line[len("event:") :].strip()
                    elif line.startswith("data:"):
                        current["data"] = json.loads(line[len("data:") :].strip())
                    elif line == "" and current.get("event"):
                        payload = {"event": current["event"], **current.get("data", {})}
                        events.append(payload)
                        if payload["event"] == "approval.required":
                            decision = client.post(
                                f"/api/v1/threads/{thread_id}/approvals/{payload['approval_id']}",
                                json={"decision": "approved", "comment": "真实模型测试自动批准"},
                            )
                            assert decision.status_code == 200, decision.text
                        current = {}

            started = next(event for event in events if event["event"] == "run.started")
            assert started["mode"] == "real", started
            assert started["engine"] == "real", started
            assert started["provider"] == "deepseek", started

            completed = next(event for event in events if event["event"] == "run.completed")
            assert completed["status"] in ("completed", "rejected"), completed
            assert completed["tokens"] > 0, completed
            assert completed["usage"]["input_tokens"] > 0
            assert completed["usage"]["output_tokens"] > 0
            assert completed["provider"] == "deepseek"
            assert completed["model"], completed
            assert completed["artifact_ids"], "真实模型未产出 artifact"

            tools_called = [
                event
                for event in events
                if event["event"] == "tool.finished" and event.get("ok") is True
            ]
            tool_names = [event["tool"] for event in tools_called]
            assert any(name in ("file.read", "file_list") for name in tool_names), tool_names
            assert any(
                name in ("doc.generate_report", "doc_generate_report") for name in tool_names
            ), tool_names

            artifact_id = completed["artifact_ids"][0]
            download = client.get(f"/api/v1/artifacts/{artifact_id}/download")
            assert download.status_code == 200
            from docx import Document

            document = Document(io.BytesIO(download.content))
            paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
            assert any("周报" in text for text in paragraphs), paragraphs[:3]
            # 证据落盘（不含任何密钥）
            evidence = {
                "base_url": base_url,
                "thread_id": thread_id,
                "event_sequence": [event["event"] for event in events],
                "tools": tool_names,
                "run_started": started,
                "run_completed": completed,
                "docx_paragraphs": paragraphs[:8],
            }
            evidence_path = Path("tests/evidence/real_deepseek_run.json")
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("\n[real] event_sequence =", evidence["event_sequence"])
            print("[real] tools =", tool_names)
            print(
                "[real] tokens/cost =",
                completed["tokens"],
                completed["cost_cny"],
                completed["usage"],
            )
            print("[real] artifact =", completed["artifact_ids"], paragraphs[:3])
    finally:
        with contextlib.suppress(StopIteration):
            next(server_gen)
