"""测试辅助：SSE 解析、DOCX 校验、运行发起。"""

from __future__ import annotations

import io
import json
from collections.abc import Iterable

import httpx


def read_sse(lines: Iterable[str], stop_at: str | None = None) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event: str | None = None
    data: str | None = None
    for line in lines:
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = line[len("data:") :].strip()
        elif line == "":
            if event and data is not None:
                events.append((event, json.loads(data)))
                if stop_at and event == stop_at:
                    return events
            event, data = None, None
    if event and data is not None:
        events.append((event, json.loads(data)))
    return events


def make_docx(lines: list[str]) -> bytes:
    from docx import Document

    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def docx_parts(content: bytes) -> tuple[list[str], list[str]]:
    """返回 (全部段落文本, 标题样式段落)。"""
    from docx import Document

    document = Document(io.BytesIO(content))
    paragraphs = [
        (paragraph.text or "").strip()
        for paragraph in document.paragraphs
        if (paragraph.text or "").strip()
    ]
    headings = [
        (paragraph.text or "").strip()
        for paragraph in document.paragraphs
        if (paragraph.style.name or "").lower().startswith(("heading", "title"))
    ]
    return paragraphs, headings


def has_heading(headings: list[str], name: str) -> bool:
    """标题里是否有这一节。

    一级标题现在会自动编号（「一、摘要」），所以不能再用 `name in headings` 精确匹配——
    那是断言「排版没编号」，而编号正是我们要的。
    """
    return any(name in heading for heading in headings)


def start_run(
    client: httpx.Client,
    thread_id: str,
    message: str = "把这份材料整理成 600 字周报，发我邮箱草稿",
    *,
    prefix: str = "/api/v1",
):
    """起一轮运行。

    审批卡已经整个删掉了：写产物是这一轮的正事，授权由门控按那句话自己判，
    所以这里不再需要「先等卡片再点批准」的成套动作。
    """
    return client.stream(
        "POST",
        f"{prefix}/threads/{thread_id}/runs/stream",
        json={"message": message, "mode": "mock"},
    )


def approved_flow(
    client: httpx.Client,
    thread_id: str,
    *,
    prefix: str = "/api/v1",
    message: str = "把这份材料整理成 600 字周报，发我邮箱草稿",
) -> list[tuple[str, dict]]:
    """跑完一轮，返回全部事件。

    名字保留（调用方太多），但它已经不再是「批准流程」：现在没有卡片要批，
    一次跑到底。
    """
    with start_run(client, thread_id, message, prefix=prefix) as response:
        assert response.status_code == 200, response.text
        return read_sse(response.iter_lines())
