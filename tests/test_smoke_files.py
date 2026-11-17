"""上传 smoke（5 条）：6 格式、多文件、非法类型、magic bytes、素材列表/删除。

所有样例在内存生成并只写 tmp_path（测试卫生要求）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from conftest import assert_error, upload
from samples import SIX_FORMATS, make_md, make_txt

V1 = "/api/v1"


# 11. 6 种合法格式：docx / xlsx / pdf / txt / md / csv
def test_upload_six_formats(
    client: httpx.Client, thread: dict, tmp_path: Path
) -> None:
    thread_id = thread["thread_id"]
    uploaded: list[str] = []
    for filename, builder, content_type in SIX_FORMATS:
        data = builder()
        path = tmp_path / filename
        path.write_bytes(data)
        resp = upload(client, thread_id, filename, data, content_type)
        assert resp.status_code == 201, f"{filename}: {resp.text[:300]}"
        body = resp.json()
        ext = filename.rsplit(".", 1)[1]
        assert body["parsed"] is True, body
        assert body["chars"] > 0, body
        assert body["type"] == ext and body["ext"] == ext, body
        assert body["size"] == len(data), body
        assert body["filename"] == filename
        assert body["artifact_id"] == body["file_id"]
        uploaded.append(filename)

    files = client.get(f"{V1}/threads/{thread_id}/files").json()["files"]
    names = {item["filename"] for item in files}
    assert set(uploaded) <= names
    assert all(item["parsed"] for item in files)


# 12. 多文件上传（multipart 字段 files）
def test_upload_multi_files(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    resp = client.post(
        f"{V1}/threads/{thread_id}/files",
        files=[
            ("files", ("素材A.txt", make_txt(), "text/plain")),
            ("files", ("素材B.md", make_md(), "text/markdown")),
        ],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["files"]) == 2, body
    assert {item["filename"] for item in body["files"]} == {"素材A.txt", "素材B.md"}
    # 兼容 v0.1：顶层字段为第一个文件
    assert body["filename"] == "素材A.txt"
    assert body["parsed"] is True


# 13. 非法类型：扩展名 / MIME
def test_upload_unsupported_type_415(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    exe = upload(client, thread_id, "bad.exe", b"MZfake", "application/octet-stream")
    body = assert_error(exe, 415, "UNSUPPORTED_FILE_TYPE")
    assert body["error"]["details"]["reason"] == "unsupported_type"

    # 扩展名合法但 MIME 不符 → 415 mime_mismatch
    mime = upload(client, thread_id, "ok.txt", b"hello", "image/png")
    body = assert_error(mime, 415, "UNSUPPORTED_FILE_TYPE")
    assert body["error"]["details"]["reason"] == "mime_mismatch"


# 14. 伪造扩展名：magic bytes 校验
def test_upload_fake_magic_415(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    fake_docx = upload(
        client,
        thread_id,
        "fake.docx",
        b"not-a-zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    body = assert_error(fake_docx, 415, "UNSUPPORTED_FILE_TYPE")
    assert body["error"]["details"]["reason"] == "magic_mismatch"

    fake_pdf = upload(client, thread_id, "fake.pdf", b"not-a-pdf", "application/pdf")
    body = assert_error(fake_pdf, 415, "UNSUPPORTED_FILE_TYPE")
    assert body["error"]["details"]["reason"] == "magic_mismatch"


# 15. 素材列表 / 删除 / 上传到不存在会话
def test_files_list_and_delete(client: httpx.Client, thread: dict) -> None:
    thread_id = thread["thread_id"]
    first = upload(client, thread_id, f"a-{uuid.uuid4().hex[:6]}.txt", make_txt()).json()
    second = upload(
        client, thread_id, f"b-{uuid.uuid4().hex[:6]}.md", make_md(), "text/markdown"
    ).json()

    files = client.get(f"{V1}/threads/{thread_id}/files").json()["files"]
    assert {first["file_id"], second["file_id"]} <= {item["file_id"] for item in files}

    deleted = client.delete(f"{V1}/files/{first['file_id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    remaining = client.get(f"{V1}/threads/{thread_id}/files").json()["files"]
    assert first["file_id"] not in {item["file_id"] for item in remaining}
    assert second["file_id"] in {item["file_id"] for item in remaining}

    missing = upload(client, "th_not_exist_000", "x.txt", b"x")
    assert_error(missing, 404, "NOT_FOUND")
