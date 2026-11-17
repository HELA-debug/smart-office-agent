"""下载接口的 Content-Type 兜底。

为什么单独测：上传时浏览器给的 `application/octet-stream` 会被原样存进产物，
PDF 带着这个类型进入 iframe，浏览器认不出它是 PDF，就把「预览」变成下载。
"""

from __future__ import annotations

from app.services.artifact_service import _media_type


def test_keeps_explicit_content_type() -> None:
    assert _media_type("a.pdf", "application/pdf") == "application/pdf"
    assert _media_type("a.txt", "text/plain") == "text/plain"


def test_generic_type_falls_back_to_extension() -> None:
    assert _media_type("cet4成绩.pdf", "application/octet-stream") == "application/pdf"
    assert _media_type("cet4成绩.pdf", None) == "application/pdf"


def test_unknown_extension_stays_binary() -> None:
    assert _media_type("data.weird", None) == "application/octet-stream"
