"""意见反馈接口：本机存档 + 邮件素材（不外发任何网络请求）。"""

from __future__ import annotations

from pathlib import Path

import httpx


def test_提交反馈_存档并返回邮件素材(client: httpx.Client):
    response = client.post(
        "/api/v1/feedback",
        json={
            "kind": "bug",
            "message": "导出的 docx 打开后标题是空行",
            "contact": "wx: test",
            "include_diagnostics": True,
            "client": {"window": "独立窗口", "platform": "Windows 11"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trace_id"] == response.headers["X-Trace-ID"]
    assert body["id"].startswith("fb_")
    assert body["saved"] is True
    assert body["kind"] == "bug"
    # 测试环境没配开发者邮箱：不假装发出去，交给前端走「复制内容」兜底
    assert body["target"] == ""
    assert body["mailto"] == ""
    assert "导出的 docx 打开后标题是空行" in body["body"]

    path = Path(body["saved_path"])
    assert path.exists()
    assert "导出的 docx" in path.read_text(encoding="utf-8")


def test_空内容被拒绝(client: httpx.Client):
    """空串走参数校验（400 BAD_REQUEST），纯空白走服务层校验——两条都不能静默存一条空反馈。"""
    empty = client.post("/api/v1/feedback", json={"kind": "idea", "message": ""})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "BAD_REQUEST"

    blank = client.post("/api/v1/feedback", json={"kind": "idea", "message": "   "})
    assert blank.status_code == 400
    assert "不能为空" in blank.json()["error"]["message"]


def test_默认类型是建议(client: httpx.Client):
    response = client.post("/api/v1/feedback", json={"message": "想要深色打印模式"})
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "idea"
