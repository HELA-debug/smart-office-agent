"""意见反馈：本机存档 + 邮件素材。

不联网是产品约束（本地部署，用户数据不出本机），所以这里断言的都是
「存档写对没有」「邮件正文该有的信息有没有」「邮箱没配时别假装发出去了」。
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote, urlparse

from app.core.config import Settings
from app.services.feedback_service import FeedbackService


def make_settings(tmp_path, email: str = "") -> Settings:
    return Settings(
        mock_mode=True,
        engine="mock",
        model_provider="mock",
        model_name="mock-scripted",
        feedback_dir=str(tmp_path / "feedback"),
        feedback_email=email,
        log_level="WARNING",
        log_format="text",
    )


def read_records(tmp_path) -> list[dict]:
    path = tmp_path / "feedback" / "feedback.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_存档一条反馈并返回编号(tmp_path):
    service = FeedbackService(make_settings(tmp_path))
    result = service.submit(
        kind="bug",
        message="  导入技能之后列表不刷新  ",
        contact="me@example.com",
        client={"window": "独立窗口", "platform": "Windows", "screen": "1440x900"},
    )

    assert result["saved"] is True
    assert result["id"].startswith("fb_")
    # 首尾空白去掉：直接复制粘贴进来的内容常带空行
    assert "导入技能之后列表不刷新" in result["body"].splitlines()
    assert "  导入技能之后列表不刷新  " not in result["body"]
    records = read_records(tmp_path)
    assert len(records) == 1
    assert records[0]["message"] == "导入技能之后列表不刷新"
    assert records[0]["contact"] == "me@example.com"
    assert records[0]["kind"] == "bug"


def test_邮箱留空时不拼邮件_只落存档(tmp_path):
    service = FeedbackService(make_settings(tmp_path))
    result = service.submit(kind="idea", message="希望能批量导出")

    assert result["target"] == ""
    assert result["mailto"] == ""
    assert result["saved"] is True
    assert read_records(tmp_path)[0]["message"] == "希望能批量导出"


def test_配了邮箱就给出可用的mailto链接(tmp_path):
    service = FeedbackService(make_settings(tmp_path, email="dev@example.com"))
    result = service.submit(
        kind="idea",
        message="希望周报能自动带上上周的数据",
        include_diagnostics=True,
        client={"window": "独立窗口", "platform": "Windows 11", "theme": "深色"},
    )

    assert result["target"] == "dev@example.com"
    parsed = urlparse(result["mailto"])
    assert parsed.scheme == "mailto"
    assert parsed.path == "dev@example.com"
    query = parse_qs(parsed.query)
    assert query["subject"][0].startswith("[Office Agent] 功能建议")
    body = query["body"][0]
    # 正文里既要有用户写的内容，也要有能定位问题的环境信息
    assert "希望周报能自动带上上周的数据" in body
    assert "反馈编号：" in body
    assert "版本：" in body
    assert "独立窗口" in body
    # 存档不因为拼邮件而丢字段
    assert read_records(tmp_path)[0]["client"]["platform"] == "Windows 11"


def test_不要环境信息时正文只有内容(tmp_path):
    service = FeedbackService(make_settings(tmp_path, email="dev@example.com"))
    result = service.submit(kind="other", message="界面挺好看", include_diagnostics=False)

    body = parse_qs(urlparse(result["mailto"]).query)["body"][0]
    assert "界面挺好看" in body
    assert "反馈编号" not in body
    assert "版本" not in body


def test_未知类型归到其他_超长内容截断(tmp_path):
    service = FeedbackService(make_settings(tmp_path))
    result = service.submit(kind="whatever", message="长" * 4000)

    assert result["kind"] == "other"
    record = read_records(tmp_path)[0]
    assert len(record["message"]) == 1500


def test_正文过长时截断mailto并标记(tmp_path):
    service = FeedbackService(make_settings(tmp_path, email="dev@example.com"))
    result = service.submit(kind="bug", message="长" * 1400, include_diagnostics=True)

    body = parse_qs(urlparse(result["mailto"]).query)["body"][0]
    assert result["truncated"] is True
    assert "完整版已存本机" in body
    # 存档里是完整的 1400 字，被截的只有邮件正文
    assert len(read_records(tmp_path)[0]["message"]) == 1400


def test_空内容直接拒绝(tmp_path):
    service = FeedbackService(make_settings(tmp_path))
    try:
        service.submit(kind="idea", message="   ")
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:  # pragma: no cover - 没抛就是回归
        raise AssertionError("空反馈应该被拒绝")


def test_多条反馈是追加而不是覆盖(tmp_path):
    service = FeedbackService(make_settings(tmp_path))
    service.submit(kind="idea", message="第一条")
    service.submit(kind="bug", message="第二条")

    assert [record["message"] for record in read_records(tmp_path)] == ["第一条", "第二条"]


def test_正文里的中文不会变成乱码(tmp_path):
    service = FeedbackService(make_settings(tmp_path, email="dev@example.com"))
    result = service.submit(kind="idea", message="表格里的「合计」行没有加粗")
    body = parse_qs(urlparse(result["mailto"]).query)["body"][0]
    # quote 过但解回来必须还是原文（防止把已编码的串再编码一次）
    assert unquote(body) == body
    assert "「合计」" in body
