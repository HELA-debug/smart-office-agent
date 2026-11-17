"""集成测试：健康检查、会话、上传、错误体、双前缀兼容。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest
from tests.helpers import make_docx, read_sse


def test_health_v1_fields(client: httpx.Client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.2.0"
    assert body["git_sha"]
    # 第五十七轮：进程载入的版本与仓库当前 HEAD 分开报，界面才能分清「重建」还是「重启」
    assert body["git_sha_live"] == body["git_sha"]
    assert body["mode"] == "mock"
    assert body["provider"] == "mock"
    assert body["model"] == "mock-scripted"
    assert body["degraded"] is False
    assert body["tools"] >= 6
    assert body["subagents"] == 3
    # 只断言内置那个技能在：技能库里的技能可以一键装进 app/skills，
    # 装完这里会多几条，用相等断言会让「装过技能的环境」全部挂掉。
    assert "weekly-report" in body["skills"]
    assert body["trace_id"]
    assert response.headers["X-Trace-ID"] == body["trace_id"]


def test_health_separates_boot_sha_from_live_head(
    client: httpx.Client, monkeypatch: pytest.MonkeyPatch
):
    """老进程跨了提交还在跑时，界面要能分清是「后端旧」还是「前端没重建」。

    `git_sha` 是进程启动那一刻的快照（运行期间不变），`git_sha_live` 每次现读仓库 HEAD。
    少了后者，界面只能看到两个不相等的 sha，会误判成「前端没重新构建」，让人去
    `npm run build`——而真正该做的是重启进程。
    """
    # 注意模块名：应用是以 `app.*` 导入的（backend/ 在 sys.path 上），写成 backend.app.*
    # 会拿到另一份模块对象，patch 了也不生效
    from app.agents import runtime as runtime_module

    boot = client.get("/api/v1/health").json()["git_sha"]
    monkeypatch.setattr(runtime_module, "detect_git_sha", lambda: "fffffff")
    body = client.get("/api/v1/health").json()
    assert body["git_sha"] == boot  # 快照不跟着变
    assert body["git_sha_live"] == "fffffff"  # 现读的那个会变


def test_legacy_alias_and_deprecation_header(client: httpx.Client):
    legacy = client.get("/api/health")
    assert legacy.status_code == 200
    assert legacy.headers["Deprecation"] == "true"
    assert legacy.headers["Link"].startswith("</api/v1>")
    assert legacy.json()["status"] == "ok"

    modern = client.get("/api/v1/health")
    assert "Deprecation" not in modern.headers


def test_thread_crud(client: httpx.Client):
    created = client.post("/api/v1/threads", json={"title": "整理周报"})
    assert created.status_code == 201
    thread = created.json()
    thread_id = thread["thread_id"]
    assert thread_id.startswith("th_")
    assert thread["title"] == "整理周报"
    assert thread["message_count"] == 0

    listed = client.get("/api/v1/threads").json()["threads"]
    assert any(item["thread_id"] == thread_id for item in listed)

    patched = client.patch(
        f"/api/v1/threads/{thread_id}", json={"title": "重命名后的会话", "pinned": True}
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "重命名后的会话"
    assert patched.json()["pinned"] is True

    detail = client.get(f"/api/v1/threads/{thread_id}").json()
    assert detail["messages"] == []
    assert detail["artifacts"] == []

    deleted = client.delete(f"/api/v1/threads/{thread_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/threads/{thread_id}").status_code == 404
    assert all(
        item["thread_id"] != thread_id for item in client.get("/api/v1/threads").json()["threads"]
    )


def test_thread_bulk_delete(client: httpx.Client):
    """左栏「批量清理」：一次请求删一批，混入不存在/已删的 ID 不算失败。"""
    ids = [
        client.post("/api/v1/threads", json={"title": f"批量清理 {index}"}).json()["thread_id"]
        for index in range(3)
    ]

    response = client.post(
        "/api/v1/threads/bulk-delete",
        json={"thread_ids": [*ids, "th_missing"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"]
    # 只算真正删掉的：th_missing 不参与计数，但也不让整批 404
    assert body["deleted"] == 3

    for thread_id in ids:
        assert client.get(f"/api/v1/threads/{thread_id}").status_code == 404
    listed = {item["thread_id"] for item in client.get("/api/v1/threads").json()["threads"]}
    assert not listed & set(ids)

    # 再删一次：全都已经删过 → deleted=0，接口仍是 200（幂等）
    again = client.post("/api/v1/threads/bulk-delete", json={"thread_ids": ids})
    assert again.status_code == 200
    assert again.json()["deleted"] == 0


def test_thread_bulk_delete_rejects_empty_list(client: httpx.Client):
    # 全局把 pydantic 校验错误统一成 400 BAD_REQUEST（见 core/errors.py）
    response = client.post("/api/v1/threads/bulk-delete", json={"thread_ids": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_not_found_error_body(client: httpx.Client):
    response = client.get("/api/v1/threads/th_not_exist")
    assert response.status_code == 404
    body = response.json()
    assert body["trace_id"]
    assert body["error"]["code"] == "NOT_FOUND"
    assert "th_not_exist" in body["error"]["message"]


def test_output_format_rejects_removed_formats(client: httpx.Client):
    """csv / html 已从产物格式下线：接口直接 400，提示里不再列出它们。"""
    thread_id = client.post("/api/v1/threads", json={}).json()["thread_id"]
    for removed in ("csv", "html"):
        response = client.post(
            f"/api/v1/threads/{thread_id}/runs/stream",
            json={"message": "整理成周报", "mode": "mock", "output_format": removed},
        )
        assert response.status_code == 400
        message = response.json()["error"]["message"]
        supported = message.split("仅支持：")[-1]
        assert "docx" in supported
        assert "csv" not in supported
        assert "html" not in supported


def test_default_thread_title_backfill(client: httpx.Client):
    thread_id = client.post("/api/v1/threads", json={}).json()["thread_id"]
    long_message = "  把这份材料整理成 600 字周报，\n发我邮箱草稿，并标注来源文件  "
    with client.stream(
        "POST",
        f"/api/v1/threads/{thread_id}/runs/stream",
        json={"message": long_message, "mode": "mock"},
    ) as response:
        assert response.status_code == 200
        lines = response.iter_lines()
        assert read_sse(lines, stop_at="run.started")[0][0] == "run.started"

    title = client.get(f"/api/v1/threads/{thread_id}").json()["title"]
    assert title.startswith("把这份材料整理成")
    assert title.endswith("…")
    assert len(title) == 25
    assert "\n" not in title

    with client.stream(
        "POST",
        f"/api/v1/threads/{thread_id}/runs/stream",
        json={"message": "换成会议纪要模板重做", "mode": "mock"},
    ) as response:
        read_sse(response.iter_lines(), stop_at="run.started")
    assert client.get(f"/api/v1/threads/{thread_id}").json()["title"] == title

    custom = client.post("/api/v1/threads", json={"title": "自定义标题"}).json()
    with client.stream(
        "POST",
        f"/api/v1/threads/{custom['thread_id']}/runs/stream",
        json={"message": "另一个任务", "mode": "mock"},
    ) as response:
        read_sse(response.iter_lines(), stop_at="run.started")
    assert client.get(f"/api/v1/threads/{custom['thread_id']}").json()["title"] == "自定义标题"


def test_upload_txt_and_files_list(client: httpx.Client, thread: dict):
    thread_id = thread["thread_id"]
    response = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={
            "file": ("进展材料.txt", "本周完成登录联调。\n风险：接口延期。".encode(), "text/plain")
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file_id"].startswith("art_")
    assert body["filename"] == "进展材料.txt"
    assert body["type"] == "txt"
    assert body["chars"] > 0
    assert body["parsed"] is True

    files = client.get(f"/api/v1/threads/{thread_id}/files").json()["files"]
    assert files and files[0]["file_id"] == body["file_id"]

    meta = client.get(f"/api/v1/artifacts/{body['file_id']}").json()
    assert meta["download_url"].endswith("/download")
    preview = client.get(f"/api/v1/artifacts/{body['file_id']}/preview")
    assert preview.status_code == 200
    assert "text/html" in preview.headers["content-type"]
    assert "本周完成" in preview.text
    download = client.get(f"/api/v1/artifacts/{body['file_id']}/download")
    assert download.content.decode("utf-8") == "本周完成登录联调。\n风险：接口延期。"
    # 默认是下载（attachment）；预览 iframe 用 inline=1 才不会让浏览器直接落盘
    assert download.headers["content-disposition"].startswith("attachment")
    inline = client.get(f"/api/v1/artifacts/{body['file_id']}/download?inline=1")
    assert inline.status_code == 200
    assert inline.headers["content-disposition"].startswith("inline")


def test_upload_docx(client: httpx.Client, thread: dict):
    thread_id = thread["thread_id"]
    content = make_docx(["本周完成登录模块联调，覆盖 12 个接口。", "风险：支付联调延期。"])
    response = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={
            "file": (
                "会议记录.docx",
                content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["type"] == "docx"
    assert response.json()["chars"] > 10


def test_upload_rejections(client: httpx.Client, thread: dict):
    thread_id = thread["thread_id"]
    unsupported = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": ("x.exe", b"MZ", "application/octet-stream")},
    )
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    # magic bytes 校验失败（伪造扩展名）→ 415
    broken = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": ("坏文件.docx", b"not a docx", "application/octet-stream")},
    )
    assert broken.status_code == 415
    assert broken.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    # 空文件 → 422 解析失败
    empty = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": ("空.txt", b"", "text/plain")},
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "FILE_PARSE_ERROR"
    # 解析失败不崩，会话仍可用
    assert client.get(f"/api/v1/threads/{thread_id}").status_code == 200


def test_settings_models_and_extensions(client: httpx.Client):
    settings = client.get("/api/v1/settings").json()
    assert "approval_rules" in settings
    assert all(key not in str(settings["secrets"]) for key in ("sk-",))
    updated = client.put("/api/v1/settings", json={"max_upload_mb": 30})
    assert updated.status_code == 200
    assert updated.json()["max_upload_mb"] == 30

    models = client.get("/api/v1/models").json()["models"]
    assert isinstance(models, list)
    assert all("api_key" not in item for item in models), "不得返回明文 Key 字段"

    tools = client.get("/api/v1/tools").json()["tools"]
    assert {tool["name"] for tool in tools} >= {"file.read", "doc.generate_report", "file.delete"}
    subagents = client.get("/api/v1/subagents").json()["subagents"]
    assert {item["name"] for item in subagents} == {"doc_agent", "sheet_agent", "research_agent"}
    skills = client.get("/api/v1/skills").json()["skills"]
    # 技能目录就是运行时真实目录，用户可能在界面上装/卸技能，别把顺序和数量写死
    assert "weekly-report" in {item["name"] for item in skills}

    usage = client.get("/api/v1/usage/summary").json()
    for key in ("runs", "tokens", "cost_cny", "avg_elapsed_ms", "by_day"):
        assert key in usage


def test_sqlite_has_eight_tables(client: httpx.Client, data_dir: Path):
    client.post("/api/v1/threads", json={"title": "建表检查"})
    database = data_dir / "app.db"
    assert database.exists()
    connection = sqlite3.connect(str(database))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert {
        "threads",
        "messages",
        "runs",
        "run_events",
        "approvals",
        "artifacts",
        "settings",
        "model_configs",
    } <= tables
