"""测试样例生成器：6 种上传格式（docx / xlsx / pdf / txt / md / csv）。

全部在内存中生成，测试写入 tmp_path，不污染仓库根。
"""
from __future__ import annotations

import io


def make_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("产品周会会议记录", level=1)
    doc.add_paragraph("本周完成主链路联调；风险是真实模型未接入；下周计划补审计。")
    doc.add_paragraph("关键数据：接口 32 个，测试 30 条。")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def make_xlsx() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(["指标", "数值"])
    sheet.append(["接口数", 32])
    sheet.append(["测试数", 30])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def make_pdf(text: str = "Weekly report: done sync, risk time, plan tests.") -> bytes:
    """最小合法 PDF（含可提取文本流，pypdf 可解析）。"""
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
    ]
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("latin-1")
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(output)


def make_txt() -> bytes:
    return "本周完成联调。风险：时间紧。下周计划：补测试。".encode("utf-8")


def make_md() -> bytes:
    return "# 周报素材\n\n本周完成联调，风险是时间紧。\n".encode("utf-8")


def make_csv() -> bytes:
    return "指标,数值\n接口数,32\n测试数,30\n".encode("utf-8")


# (filename, bytes, content-type) —— 与后端 SUPPORTED_UPLOAD_EXTS 一一对应
SIX_FORMATS = [
    (
        "会议记录.docx",
        make_docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    (
        "数据.xlsx",
        make_xlsx,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ("周报.pdf", make_pdf, "application/pdf"),
    ("素材.txt", make_txt, "text/plain"),
    ("说明.md", make_md, "text/markdown"),
    ("数据.csv", make_csv, "text/csv"),
]
