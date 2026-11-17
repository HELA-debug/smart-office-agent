"""素材体检：doc.analyze_material（只读，低风险）。

为什么要单独一个工具：
mock 主链路以前只拿 file.read 的纯文本套模板——docx 里的标题层级、内嵌图片、
表格、图注全丢了，成文时又退回「完成了本周既定任务」这类默认句，产出对用户没用。
这里用真 Python 子进程（python-docx / openpyxl / pypdf）把素材结构读出来，
成文时按真实结构组织：有多少段、多少字、几级标题、几张图、图注是什么、关键句在哪。

只读约束（因此不列进审批规则）：
- 不复制、不修改素材，也不往产物目录写任何文件；
- 子进程环境变量白名单化，不带任何密钥；
- 固定超时 + 输出截断，只读 stdlib 与已装的解析库。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from ..spec import ToolContext, tool

TIMEOUT_SECONDS = 25
MAX_OUTPUT_CHARS = 40_000

# 子进程只沿用跑 Python 必需的环境变量
_ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
)

# 体检脚本：按扩展名分派到 docx / xlsx / pdf / 纯文本，最后汇总成一份 JSON。
_SCRIPT = r"""
import json, os, re, sys

FIGURE = re.compile(r"^(?:图|表)\s*\d+")
CAPTION = re.compile(r"^照片《")
SENTENCE = re.compile(r"[^。；;！!？?]{6,}?[。；;！!？?]?")


def _clean(text):
    return re.sub(r"\s+", "", text or "")


def _sentences(text, limit=6):
    parts = []
    for raw in re.split(r"[\n。；;！!？?]+", text or ""):
        line = raw.strip(" ·-—#*	")
        if 12 <= len(line) <= 120 and not FIGURE.match(line):
            parts.append(line)
        if len(parts) >= limit:
            break
    return parts


def _docx(path):
    from docx import Document

    doc = Document(path)
    paras, headings, figures, sample = [], [], [], []
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue
        style = (p.style.name or "").strip().lower()
        level = 0
        if style.startswith("heading"):
            digits = re.sub(r"[^0-9]", "", style)
            level = int(digits) if digits else 1
        elif style in ("title", "subtitle"):
            level = 1
        if level:
            headings.append({"text": text[:60], "level": level})
        paras.append(text)
        if FIGURE.match(text) or CAPTION.match(text):
            figures.append(text[:60])
        elif len(text) >= 20 and len(sample) < 8:
            sample.append(text[:120])
    images = 0
    try:
        images = len(doc.inline_shapes)
    except Exception:
        images = 0
    return {
        "paragraphs": len(paras),
        "headings": headings,
        "images": images,
        "tables": len(doc.tables),
        "figures": figures[:8],
        "sample": sample,
        "text": "\n".join(paras),
    }


def _xlsx(path):
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    rows, sample = 0, []
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            rows += 1
            cells = [str(c) for c in row if c not in (None, "")]
            if cells and len(sample) < 6:
                sample.append(" | ".join(cells)[:120])
    return {
        "paragraphs": 0,
        "headings": [{"text": name, "level": 1} for name in book.sheetnames],
        "images": 0,
        "tables": len(book.sheetnames),
        "figures": [],
        "sample": sample,
        "text": "\n".join(sample),
        "rows": rows,
    }


def _pdf(path):
    from pypdf import PdfReader

    reader = PdfReader(path)
    chunks = []
    for page in reader.pages[:30]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
    paras = [line.strip() for line in text.splitlines() if line.strip()]
    return {
        "paragraphs": len(paras),
        "headings": [],
        "images": 0,
        "tables": 0,
        "figures": [],
        "sample": [line[:120] for line in paras[:8]],
        "text": text,
        "pages": len(reader.pages),
    }


def _pptx(path):
    # 按页读幻灯片文字。图片、表格、SmartArt 数不出来，所以 images/tables 留 0 而不假装体检过
    import zipfile
    from xml.etree import ElementTree as ET

    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    pages = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        ]
        names.sort(key=lambda name: int("".join(c for c in name.split("/")[-1] if c.isdigit()) or 0))
        for name in names:
            raw = archive.read(name)
            # 上传来的 XML 不装可信输入：slide 里不该有实体声明
            if b"<!DOCTYPE" in raw[:4096].upper() or b"<!ENTITY" in raw[:4096].upper():
                raise ValueError("PPTX 内部 XML 含实体声明，拒绝解析")
            root = ET.fromstring(raw)
            lines = []
            for shape in root.iter(p + "sp"):
                for para in shape.iter(a + "p"):
                    line = "".join(node.text or "" for node in para.iter(a + "t")).strip()
                    if line:
                        lines.append(line)
            pages.append(lines)
    paras = [line for page in pages for line in page]
    return {
        "paragraphs": len(paras),
        "headings": [{"text": page[0][:60], "level": 1} for page in pages if page],
        "images": 0,
        "tables": 0,
        "figures": [],
        "sample": [line[:120] for line in paras[:8]],
        "text": "\n".join(paras),
        "pages": len(pages),
    }


def _plain(path):
    raw = None
    for encoding in ("utf-8", "utf-16", "gb18030"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                raw = handle.read()
            break
        except (UnicodeError, OSError):
            continue
    text = raw or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return {
        "paragraphs": len(lines),
        "headings": [],
        "images": 0,
        "tables": 0,
        "figures": [],
        "sample": [line[:120] for line in lines[:8]],
        "text": text,
    }


def main():
    inputs = json.loads(os.environ.get("OA_INPUTS") or "[]")
    files, errors, bodies = [], [], []
    totals = {"files": 0, "chars": 0, "paragraphs": 0, "images": 0, "tables": 0, "headings": 0}
    for item in inputs:
        path = item.get("path") or ""
        name = item.get("filename") or os.path.basename(path)
        ext = (item.get("ext") or os.path.splitext(path)[1]).lower().lstrip(".")
        try:
            if ext == "docx":
                detail = _docx(path)
            elif ext in ("xlsx", "xlsm"):
                detail = _xlsx(path)
            elif ext == "pdf":
                detail = _pdf(path)
            elif ext == "pptx":
                detail = _pptx(path)
            else:
                detail = _plain(path)
        except Exception as exc:
            errors.append({"filename": name, "error": str(exc)[:200]})
            continue
        text = detail.pop("text", "")
        bodies.append(text)
        detail["filename"] = name
        detail["ext"] = ext
        detail["chars"] = len(_clean(text))
        detail["sentences"] = _sentences(text)
        files.append(detail)
        totals["files"] += 1
        totals["chars"] += detail["chars"]
        totals["paragraphs"] += detail.get("paragraphs", 0)
        totals["images"] += detail.get("images", 0)
        totals["tables"] += detail.get("tables", 0)
        totals["headings"] += len(detail.get("headings") or [])

    # 关键词数要按全文算：只看样例句会把「一、本周进展」这类短标题漏掉
    all_text = "".join(bodies)
    keywords = {
        "本周": all_text.count("本周"),
        "进展": all_text.count("进展"),
        "下周": all_text.count("下周"),
        "计划": all_text.count("计划"),
        "风险": all_text.count("风险"),
        "数据": all_text.count("数据"),
    }
    weekly = keywords["进展"] + keywords["下周"] + keywords["本周"] >= 2
    print("OA_JSON:" + json.dumps(
        {
            "files": files,
            "totals": totals,
            "keywords": keywords,
            "signals": {"weekly": weekly},
            "errors": errors,
        },
        ensure_ascii=False,
    ))


main()
"""


def _child_env(inputs: list[dict[str, Any]]) -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "OA_INPUTS": json.dumps(inputs, ensure_ascii=False),
        }
    )
    return env


def _summary(facts: dict[str, Any]) -> str:
    totals = facts.get("totals") or {}
    if not totals.get("files"):
        return "脚本没读到可解析的素材"
    bits = [f"{totals.get('files')} 份素材", f"正文 {totals.get('paragraphs')} 段"]
    bits.append(f"{totals.get('chars')} 字")
    if totals.get("images"):
        bits.append(f"内嵌图片 {totals['images']} 张")
    if totals.get("tables"):
        bits.append(f"表格 {totals['tables']} 张")
    if totals.get("headings"):
        bits.append(f"标题 {totals['headings']} 处")
    return "python 脚本解析完成：" + " / ".join(str(item) for item in bits)


@tool(
    "doc.analyze_material",
    "用本机 Python 脚本（python-docx / openpyxl / pypdf）解析会话素材的真实结构："
    "段落数、字数、标题层级、内嵌图片、表格、图注与关键句，供后续成文按真实结构组织。"
    "只读：不写任何文件，也不会改动素材",
    risk="low",
)
def analyze_material(ctx: ToolContext, files: list[str] | None = None) -> dict[str, Any]:
    uploads = ctx.find_uploads(files)
    if not uploads:
        return {"ok": False, "files": [], "totals": {}, "_summary": "当前会话没有可解析的素材"}

    inputs = [
        {
            "filename": upload.filename,
            "path": upload.path,
            "ext": upload.ext,
            "chars": upload.chars,
        }
        for upload in uploads
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - 固定脚本、只读、环境变量白名单
            [sys.executable, "-c", _SCRIPT],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=_child_env(inputs),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "files": [],
            "totals": {},
            "error": f"解析超时（>{TIMEOUT_SECONDS}s）",
            "_summary": "素材解析超时，改用纯文本兜底",
        }
    except OSError as exc:
        return {
            "ok": False,
            "files": [],
            "totals": {},
            "error": str(exc),
            "_summary": f"无法启动 Python 解释器：{exc}",
        }

    stdout = (completed.stdout or "")[:MAX_OUTPUT_CHARS]
    payload = ""
    for line in stdout.splitlines():
        if line.startswith("OA_JSON:"):
            payload = line[len("OA_JSON:") :]
    if not payload:
        return {
            "ok": False,
            "files": [],
            "totals": {},
            "stdout": stdout[-1200:],
            "stderr": (completed.stderr or "")[-1200:],
            "_summary": "脚本没有返回结构化结果，改用纯文本兜底",
        }
    try:
        facts = json.loads(payload)
    except ValueError:
        return {
            "ok": False,
            "files": [],
            "totals": {},
            "_summary": "脚本返回的结果不是合法 JSON，改用纯文本兜底",
        }

    return {
        "ok": True,
        "files": facts.get("files") or [],
        "totals": facts.get("totals") or {},
        "keywords": facts.get("keywords") or {},
        "signals": facts.get("signals") or {},
        "errors": facts.get("errors") or [],
        "python": sys.version.split()[0],
        "_summary": _summary(facts),
    }
