"""会话与素材的语义矩阵：标题规则、搜索、分页、软删、上传校验。

每个用例都自己建资源（fresh_thread / 新建会话），不与种子数据抢。
"""

from __future__ import annotations

import io
import time

import pytest
from tests.api.matrix import MATRIX_PREFIX
from tests.helpers import make_docx

THREADS = f"{MATRIX_PREFIX}/threads"
DEFAULT_TITLE = "新会话"


def _new_thread(client, title: str | None = None) -> dict:
    payload = {} if title is None else {"title": title}
    response = client.post(THREADS, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------- 创建
TITLE_CASES = [
    pytest.param(None, DEFAULT_TITLE, id="no-body"),
    pytest.param("", DEFAULT_TITLE, id="empty-title"),
    pytest.param("   ", DEFAULT_TITLE, id="blank-title"),
    pytest.param("季度复盘", "季度复盘", id="chinese"),
    pytest.param(" 空格两侧 ", "空格两侧", id="trimmed"),
    pytest.param("a" * 150, "a" * 100, id="too-long-truncated"),
    pytest.param("含/斜杠与#井号", "含/斜杠与#井号", id="punctuation"),
    pytest.param("emoji 🎯 标题", "emoji 🎯 标题", id="emoji"),
]


@pytest.mark.parametrize(("title", "expected"), TITLE_CASES)
def test_create_thread_title_rules(api_client, title: str | None, expected: str):
    thread = _new_thread(api_client, title)
    assert thread["thread_id"].startswith("th_")
    assert thread["title"] == expected
    assert thread["message_count"] == 0
    assert thread["pinned"] is False


def test_create_thread_without_body(api_client):
    response = api_client.post(THREADS)
    assert response.status_code == 201
    assert response.json()["title"] == DEFAULT_TITLE


def test_thread_detail_shape(api_client, fresh_thread: str):
    detail = api_client.get(f"{THREADS}/{fresh_thread}").json()
    assert detail["thread_id"] == fresh_thread
    assert detail["messages"] == []
    assert detail["artifacts"] == []
    assert detail["uploads"] == []


def test_thread_detail_uploads_carry_recognition_fields(api_client):
    """会话详情里的素材必须带 status / media / text_preview。

    只给 parsed 一个布尔的话，刷新或切回会话后右栏就分不清「识别中」「已识别 N 字」
    「识别失败可重试」——素材卡片会退化成一条灰条，用户以为识别结果丢了。
    """
    thread = _new_thread(api_client, "素材字段会话")
    upload = api_client.post(
        f"{THREADS}/{thread['thread_id']}/files",
        files={"file": ("字段素材.txt", "第一行\n第二行\n".encode(), "text/plain")},
    )
    assert upload.status_code in (200, 201), upload.text

    detail = api_client.get(f"{THREADS}/{thread['thread_id']}").json()
    assert len(detail["uploads"]) == 1
    item = detail["uploads"][0]
    assert item["status"] == "ready"
    assert item["media"] is None, "普通文档没有媒体类别"
    assert item["text_preview"].startswith("第一行")
    assert item["chars"] > 0
    assert item["created_at"]


# ---------------------------------------------------------------- 改名 / 置顶
def test_rename_thread(api_client, fresh_thread: str):
    response = api_client.patch(f"{THREADS}/{fresh_thread}", json={"title": "  新名字  "})
    assert response.status_code == 200
    assert response.json()["title"] == "新名字"


@pytest.mark.parametrize("title", ["", "   ", "\n\t "], ids=["empty", "spaces", "whitespace"])
def test_rename_with_blank_title_is_400(api_client, fresh_thread: str, title: str):
    response = api_client.patch(f"{THREADS}/{fresh_thread}", json={"title": title})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_rename_long_title_is_truncated(api_client, fresh_thread: str):
    response = api_client.patch(f"{THREADS}/{fresh_thread}", json={"title": "字" * 300})
    assert response.status_code == 200
    assert len(response.json()["title"]) == 100


def test_pin_moves_thread_to_top(api_client):
    """置顶压过「最近更新」，取消后置顶特权随即失效。

    排序是 `pinned DESC, updated_at DESC, id DESC`：updated_at 只精确到秒、id 是随机串，
    所以「取消置顶后它不再第一」必须靠一条**严格更晚更新**的会话来保证——
    否则同一秒内的先后由随机 id 决定，用例会时红时绿。
    """
    created = _new_thread(api_client, "置顶候选")
    thread_id = created["thread_id"]
    api_client.patch(f"{THREADS}/{thread_id}", json={"pinned": True})
    listed = api_client.get(f"{THREADS}?page_size=100").json()["threads"]
    assert listed[0]["thread_id"] == thread_id

    newer = _new_thread(api_client, "更新的会话")
    api_client.patch(f"{THREADS}/{thread_id}", json={"pinned": False})
    time.sleep(1.1)  # 让「更新的会话」的时间戳严格晚于取消置顶那一刻
    api_client.patch(f"{THREADS}/{newer['thread_id']}", json={"title": "更新的会话（改过标题）"})

    listed = api_client.get(f"{THREADS}?page_size=100").json()["threads"]
    assert listed[0]["thread_id"] == newer["thread_id"]
    assert thread_id in [item["thread_id"] for item in listed]


@pytest.mark.parametrize("pinned", [True, False])
def test_patch_pinned_only_keeps_title(api_client, fresh_thread: str, pinned: bool):
    api_client.patch(f"{THREADS}/{fresh_thread}", json={"title": "保留我"})
    response = api_client.patch(f"{THREADS}/{fresh_thread}", json={"pinned": pinned})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "保留我"
    assert body["pinned"] is pinned


# ---------------------------------------------------------------- 搜索 / 分页
def test_search_by_title_keyword(api_client):
    unique = "矩阵搜索关键字甲"
    _new_thread(api_client, unique)
    result = api_client.get(f"{THREADS}?q={unique}").json()
    assert result["total"] >= 1
    assert all(unique in item["title"] for item in result["threads"])


def test_search_by_thread_id(api_client, fresh_thread: str):
    result = api_client.get(f"{THREADS}?q={fresh_thread}").json()
    assert any(item["thread_id"] == fresh_thread for item in result["threads"])


def test_search_miss_returns_empty(api_client):
    result = api_client.get(f"{THREADS}?q=绝对不存在的标题_zzz").json()
    assert result["total"] == 0
    assert result["threads"] == []


def test_search_ignores_soft_deleted(api_client):
    unique = "矩阵已删关键字"
    thread = _new_thread(api_client, unique)
    api_client.delete(f"{THREADS}/{thread['thread_id']}")
    result = api_client.get(f"{THREADS}?q={unique}").json()
    assert result["total"] == 0


PAGE_CASES = [
    pytest.param(1, 1, id="first-page"),
    pytest.param(1, 20, id="default-size"),
    pytest.param(2, 5, id="second-page"),
    pytest.param(99, 20, id="beyond-last"),
    pytest.param(1, 100, id="max-size"),
]


@pytest.mark.parametrize(("page", "page_size"), PAGE_CASES)
def test_pagination_echo_and_bounds(api_client, page: int, page_size: int):
    result = api_client.get(f"{THREADS}?page={page}&page_size={page_size}").json()
    assert result["page"] == page
    assert result["page_size"] == page_size
    assert len(result["threads"]) <= page_size
    assert result["total"] >= len(result["threads"])


@pytest.mark.parametrize(
    "query",
    ["page=0", "page=-1", "page_size=0", "page_size=101", "page_size=abc", "page=abc"],
    ids=["page-0", "page-neg", "size-0", "size-101", "size-abc", "page-abc"],
)
def test_pagination_rejects_out_of_range(api_client, query: str):
    response = api_client.get(f"{THREADS}?{query}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


# ---------------------------------------------------------------- 删除
def test_delete_thread_is_soft_and_hides(api_client):
    thread = _new_thread(api_client, "待删会话")
    thread_id = thread["thread_id"]
    response = api_client.delete(f"{THREADS}/{thread_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert api_client.get(f"{THREADS}/{thread_id}").status_code == 404
    listed = api_client.get(f"{THREADS}?page_size=100").json()["threads"]
    assert all(item["thread_id"] != thread_id for item in listed)


def test_delete_thread_twice_is_404(api_client):
    thread = _new_thread(api_client, "删两次")
    thread_id = thread["thread_id"]
    api_client.delete(f"{THREADS}/{thread_id}")
    assert api_client.delete(f"{THREADS}/{thread_id}").status_code == 404


def test_bulk_delete_counts_only_existing(api_client):
    first = _new_thread(api_client, "批量甲")["thread_id"]
    second = _new_thread(api_client, "批量乙")["thread_id"]
    response = api_client.post(
        f"{THREADS}/bulk-delete",
        json={"thread_ids": [first, second, "th_not_exist"]},
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 2


def test_bulk_delete_dedupes(api_client):
    thread_id = _new_thread(api_client, "批量去重")["thread_id"]
    response = api_client.post(
        f"{THREADS}/bulk-delete", json={"thread_ids": [thread_id, thread_id, thread_id]}
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 1


@pytest.mark.parametrize("ids", [[], ["x"] * 201], ids=["empty", "over-200"])
def test_bulk_delete_rejects_bad_size(api_client, ids: list[str]):
    response = api_client.post(f"{THREADS}/bulk-delete", json={"thread_ids": ids})
    assert response.status_code == 400


# ---------------------------------------------------------------- 上传
def _make_xlsx() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "指标"
    sheet["B1"] = 1
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _make_pdf() -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    doc = canvas.Canvas(buffer)
    doc.drawString(100, 750, "matrix sample")
    doc.save()
    return buffer.getvalue()


VALID_SAMPLES = {
    "txt": "第一行\n第二行\n".encode(),
    "docx": make_docx(["季度总结", "正文"]),
    "xlsx": _make_xlsx(),
    "pdf": _make_pdf(),
}


@pytest.mark.parametrize("ext", sorted(VALID_SAMPLES), ids=sorted(VALID_SAMPLES))
def test_upload_valid_extensions(api_client, fresh_thread: str, ext: str):
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": (f"素材.{ext}", VALID_SAMPLES[ext], "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file_id"]
    assert body["files"][0]["file_id"] == body["file_id"]


@pytest.mark.parametrize(
    "filename",
    ["恶意.exe", "脚本.js", "run.sh", "noext", "双击.bat"],
    ids=["exe", "js", "sh", "no-extension", "bat"],
)
def test_upload_rejects_disallowed_extension(api_client, fresh_thread: str, filename: str):
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": (filename, b"MZ\x90\x00binary", "application/octet-stream")},
    )
    assert response.status_code == 415, response.text
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_accepts_unknown_extension_that_is_readable_text(api_client, fresh_thread: str):
    """白名单外的后缀不再拒收：日志/配置这类纯文本照样能读出内容。"""
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("运行日志.log", "启动完成\n共 3 条".encode(), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parsed"] is True
    assert body["chars"] > 0
    assert body["note"] is None


def test_upload_keeps_legacy_doc_and_says_how_to_fix_it(api_client, fresh_thread: str):
    """旧版 .doc 收下但读不出字：给一句「另存为 docx」，而不是把人挡在门外。"""
    payload = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 128
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("旧合同.doc", payload, "application/msword")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parsed"] is False
    assert "另存为 .docx" in (body["note"] or "")
    # 状态不能说成 failed：文件确实收下了，刷新后也不该变红
    assert body["status"] == "ready"
    files = api_client.get(f"{THREADS}/{fresh_thread}/files").json()["files"]
    kept = [item for item in files if item["filename"] == "旧合同.doc"]
    assert kept and kept[0]["status"] == "ready"
    assert kept[0]["note"]


def test_legacy_excel_asks_for_xlsx_not_docx(api_client, fresh_thread: str):
    """旧版 .xls 的「下一步」必须是另存为 xlsx。

    一直照 Word 那句说「另存为 .docx」，用户照着做就把表格存成了文档——
    提示指错方向比没有提示更糟。
    """
    payload = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 128
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("成绩表.xls", payload, "application/vnd.ms-excel")},
    )
    assert response.status_code == 201, response.text
    note = response.json()["note"] or ""
    assert "另存为 .xlsx" in note
    assert ".docx" not in note


def test_upload_empty_file_is_422(api_client, fresh_thread: str):
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("空的.txt", b"", "text/plain")},
    )
    assert response.status_code == 422, response.text


def test_upload_without_part_is_400(api_client, fresh_thread: str):
    response = api_client.post(f"{THREADS}/{fresh_thread}/files", data={"note": "没带文件"})
    assert response.status_code in (400, 415, 422), response.text


@pytest.mark.parametrize(
    "filename",
    ["../../逃逸.txt", "..\\..\\逃逸.txt", "C:\\Windows\\system32\\x.txt"],
    ids=["unix-traversal", "win-traversal", "absolute"],
)
def test_upload_sanitizes_traversal_names(api_client, fresh_thread: str, filename: str):
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": (filename, b"payload\n", "text/plain")},
    )
    assert response.status_code == 201, response.text
    stored = api_client.get(f"{THREADS}/{fresh_thread}/files").json()["files"]
    assert stored, "上传后素材列表为空"
    for item in stored:
        assert ".." not in item["filename"]
        assert "/" not in item["filename"]
        assert "\\" not in item["filename"]


def test_upload_many_files_at_once(api_client, fresh_thread: str):
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files=[
            ("files", ("甲.txt", b"a\n", "text/plain")),
            ("files", ("乙.docx", make_docx(["乙"]), "application/octet-stream")),
        ],
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["files"]) == 2


def test_upload_to_unknown_thread_is_404(api_client):
    response = api_client.post(
        f"{THREADS}/th_missing/files",
        files={"file": ("素材.txt", b"x\n", "text/plain")},
    )
    assert response.status_code == 404, response.text


def test_delete_uploaded_file(api_client, fresh_thread: str):
    uploaded = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("待删.txt", b"x\n", "text/plain")},
    ).json()
    file_id = uploaded["file_id"]
    response = api_client.delete(f"{MATRIX_PREFIX}/files/{file_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    remaining = api_client.get(f"{THREADS}/{fresh_thread}/files").json()["files"]
    assert all(item["file_id"] != file_id for item in remaining)


def test_delete_file_twice_is_404(api_client, fresh_thread: str):
    uploaded = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={"file": ("删两次.txt", b"x\n", "text/plain")},
    ).json()
    api_client.delete(f"{MATRIX_PREFIX}/files/{uploaded['file_id']}")
    again = api_client.delete(f"{MATRIX_PREFIX}/files/{uploaded['file_id']}")
    assert again.status_code == 404


def test_upload_docx_is_parseable(api_client, fresh_thread: str):
    """docx 上传后能拿到解析字数：说明服务端真的解了包，而不是只存了个文件。"""
    document = make_docx(["会议记录", "一、结论", "二、待办"])
    response = api_client.post(
        f"{THREADS}/{fresh_thread}/files",
        files={
            "file": (
                "会议.docx",
                document,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201, response.text
    files = api_client.get(f"{THREADS}/{fresh_thread}/files").json()["files"]
    assert files[0]["chars"] >= 5, files[0]
