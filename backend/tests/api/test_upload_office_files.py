"""xlsx / txt 当素材上传：收得下、立刻读出文字、不是「识别中」。

用户 2026-11-10 报「Excel、txt 拖进会话框识别不了」。这两类走的不是识别链路
（不是图片/录音），上传时**同步解析**，所以只要解析器认得出，返回就该是
`parsed=true / status=ready`。这里从 API 层把这条钉死：以后再改动上传或解析，
坏了能立刻看出来，而不是等用户拖一个文件才发现。
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

API = "/api/v1"
THREADS = f"{API}/threads"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "成绩表"
    sheet.append(["姓名", "语文", "数学"])
    sheet.append(["张伟", 88, 92])
    sheet.append(["李娜", 79, 85])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_xlsx_upload_is_parsed_immediately(api_client: TestClient, fresh_thread: str) -> None:
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("成绩表.xlsx", _xlsx_bytes(), XLSX_MIME)},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    # 表格不是媒体素材：不该挂「识别中」，上传完当场就有文字
    assert body["parsed"] is True
    assert body["status"] == "ready"
    assert body["chars"] > 0
    assert body["media"] is None
    assert "张伟" in (body["text_preview"] or "")


def test_txt_upload_reads_gbk_text(api_client: TestClient, fresh_thread: str) -> None:
    """记事本存的中文 txt 多是 GBK，别因为不是 UTF-8 就当解析失败。"""
    data = "会议纪要\n一、本周进展\n1. 完成接口联调\n".encode("gbk")
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("纪要.txt", data, "text/plain")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parsed"] is True
    assert body["status"] == "ready"
    assert "本周进展" in (body["text_preview"] or "")


def test_txt_upload_appears_in_thread_files(api_client: TestClient, fresh_thread: str) -> None:
    """上传完要能从素材列表读回来——前端拖拽后就是靠这个接口刷新列表。"""
    data = "项目周报\n本周完成：上传链路联调\n".encode()
    uploaded = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("周报.txt", data, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["file_id"]

    listing = api_client.get(f"{THREADS}/{fresh_thread}/files")
    assert listing.status_code == 200, listing.text
    names = [item["filename"] for item in listing.json()["files"]]
    assert "周报.txt" in names
    matched = next(item for item in listing.json()["files"] if item["file_id"] == file_id)
    assert matched["parsed"] is True
