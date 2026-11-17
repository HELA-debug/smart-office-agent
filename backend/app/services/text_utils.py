"""text_utils.py —— Agent 处理 .md / .txt 的通用函数库。

为什么 md/txt 也要一层工具库：这两个格式看似「随便读写」，实际最容易翻车的是
编码（Windows 导出常是 GBK）、换行（CRLF 混 CR）、Markdown 结构（标题层级跳级、
表格缺分隔行），以及「把 Markdown 排成 docx 时标题全变成正文」。
这里把识别、规范化、结构解析与导出固定下来。

约定：
- 读：先试 utf-8-sig → utf-8 → gb18030，返回实际用的编码，写回时沿用；
- 写：默认 utf-8 + LF，避免 Windows 记事本打开出现「全在一行」；
- Markdown 只处理「结构」，不做 HTML 渲染（渲染交给最终产物格式）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

try:  # 脚本工作目录里 *_utils.py 是平铺复制的，没有包结构，只能绝对导入
    from .text_lexicon import LINE_WIDTH
except ImportError:  # pragma: no cover - 沙箱里平铺运行时走这条
    from text_lexicon import LINE_WIDTH  # type: ignore[no-redef]

__all__ = [
    "LINE_WIDTH",
    "detect_encoding",
    "heading_tree",
    "md_table",
    "md_to_docx",
    "normalize_markdown",
    "read_text",
    "split_by_heading",
    "txt_stats",
    "txt_wrap",
    "write_text",
]

_ENCODINGS = ("utf-8", "gb18030")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# 规范化时用宽松版：`#标题`（缺空格）也要能认出来并修
_LOOSE_HEADING_RE = re.compile(r"^(#{1,6})\s*(\S.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


# --------------------------------------------------------------------------- #
# 编码与读写
# --------------------------------------------------------------------------- #


def detect_encoding(path: str | Path) -> str:
    """只读前 64KB 探测编码：大文件不必整读，只判断能不能解码。

    BOM 优先：带 BOM 的 UTF-16 用 utf-8 解会直接失败，先看前两字节更准。
    """
    data = Path(path).read_bytes()[: 64 * 1024]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    for codec in _ENCODINGS:
        try:
            data.decode(codec)
            return codec
        except UnicodeDecodeError:
            continue
    return "utf-8"


def read_text(path: str | Path, encoding: str | None = None) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"找不到文件：{target}")
    codec = encoding or detect_encoding(target)
    raw = target.read_text(encoding=codec, errors="replace").lstrip("\ufeff")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    return {
        "file": target.name,
        "encoding": codec,
        "text": text,
        "chars": len(text),
        "lines": text.count("\n") + 1 if text else 0,
    }


def write_text(path: str | Path, text: str, encoding: str = "utf-8") -> dict[str, Any]:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    out.write_text(normalized, encoding=encoding, newline="\n")
    return {"out": str(out), "chars": len(normalized), "lines": normalized.count("\n")}


# --------------------------------------------------------------------------- #
# 统计与排版
# --------------------------------------------------------------------------- #


def txt_stats(text: str) -> dict[str, Any]:
    content = text or ""
    cjk = sum(1 for char in content if "\u4e00" <= char <= "\u9fff")
    paragraphs = [item for item in re.split(r"\n\s*\n", content) if item.strip()]
    return {
        "chars": len(content),
        "chars_no_space": len(re.sub(r"\s", "", content)),
        "cjk_chars": cjk,
        "lines": content.count("\n") + 1 if content else 0,
        "paragraphs": len(paragraphs),
        "words": len(re.findall(r"[A-Za-z0-9']+", content)),
    }


def txt_wrap(text: str, width: int = LINE_WIDTH) -> str:
    """按显示宽度折行：中文 2 宽、西文 1 宽；不打断已有的换行。

    **只给定宽排版用**：ASCII 表格、条形图、要逐行对齐的清单。正文不要调它——
    折行处那句 `rstrip()` 会把断点上的空格吃掉（「组 RunContext」折开再拼回去就成了
    「组RunContext」），而且换个字号、换台机器就错位。正文一段一行、折行交给阅读器，
    这是 2026-11-16 定的规矩（见 text-layout 技能）。日志、逐字稿这类「一行一条」
    的内容也别调，折了就没法按行 grep。

    width 是「半角宽度」，默认 76 ≈ 38 个汉字（见 `text_lexicon.LINE_WIDTH`）。
    """
    width = max(10, int(width))
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        current_width = 0
        for char in paragraph:
            char_width = 2 if ord(char) > 127 else 1
            if current_width + char_width > width * 2 and current:
                lines.append(current.rstrip())
                current = ""
                current_width = 0
            current += char
            current_width += char_width
        if current:
            lines.append(current.rstrip())
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Markdown 结构
# --------------------------------------------------------------------------- #


def heading_tree(text: str) -> list[dict[str, Any]]:
    """标题大纲：给「先看清结构再改」用；同时标出跳级（h1 直接到 h3）。"""
    tree: list[dict[str, Any]] = []
    last_level = 0
    in_fence = False
    for number, line in enumerate((text or "").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(stripped)
        if not match:
            continue
        level = len(match.group(1))
        tree.append(
            {
                "line": number,
                "level": level,
                "text": match.group(2).strip(),
                "skipped": level > last_level + 1 and last_level > 0,
            }
        )
        last_level = level
    return tree


def normalize_markdown(text: str) -> dict[str, Any]:
    """规范化：标题空格、标题层级不跳级、表格补分隔行、多余空行收拢。"""
    fixed_headings = 0
    fixed_tables = 0
    lines = (text or "").replace("\r\n", "\n").split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        match = _LOOSE_HEADING_RE.match(stripped)
        if match:
            normalized = f"{match.group(1)} {match.group(2).strip()}"
            if normalized != stripped:
                fixed_headings += 1
            output.append(normalized)
            index += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            block = [stripped]
            cursor = index + 1
            while cursor < len(lines) and lines[cursor].strip().startswith("|"):
                block.append(lines[cursor].strip())
                cursor += 1
            if len(block) >= 1 and not (len(block) > 1 and _TABLE_SEP_RE.match(block[1])):
                columns = max(1, block[0].count("|") - 1)
                block.insert(1, "|" + "|".join([" --- "] * columns) + "|")
                fixed_tables += 1
            output.extend(block)
            index = cursor
            continue
        output.append(line.rstrip())
        index += 1

    cleaned: list[str] = []
    blank = 0
    in_fence = False
    for line in output:
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        cleaned.append(line)
    result = "\n".join(cleaned).strip() + "\n"
    return {
        "text": result,
        "fixed_headings": fixed_headings,
        "fixed_tables": fixed_tables,
        "chars": len(result),
    }


def md_table(rows: Sequence[Sequence[Any]], headers: Sequence[Any] | None = None) -> str:
    """生成对齐的 Markdown 表格（中文按 2 宽对齐）。"""
    body: list[list[str]] = [["" if cell is None else str(cell) for cell in row] for row in rows]
    head = [str(item) for item in headers] if headers else (body[0] if body else [])
    if headers:
        body = body
    columns = max([len(head)] + [len(row) for row in body]) if (head or body) else 0
    head += [""] * (columns - len(head))
    body = [row + [""] * (columns - len(row)) for row in body]

    def width_of(cell: str) -> int:
        return sum(2 if ord(char) > 127 else 1 for char in cell)

    widths = [
        max([width_of(head[index])] + [width_of(row[index]) for row in body])
        for index in range(columns)
    ]
    widths = [max(3, item) for item in widths]

    def render(row: Sequence[str]) -> str:
        cells = [
            f" {cell}{' ' * (widths[index] - width_of(cell))} " for index, cell in enumerate(row)
        ]
        return "|" + "|".join(cells) + "|"

    lines = [
        render(head),
        "|" + "|".join([" " + "-" * max(3, width - 2) + " " for width in widths]) + "|",
    ]
    lines.extend(render(row) for row in body)
    return "\n".join(lines) + "\n"


def split_by_heading(text: str, level: int = 1) -> list[dict[str, Any]]:
    """按指定层级切分章节，返回 [{title, content}]，方便逐章改写。"""
    prefix = "#" * level
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix + " ") and not stripped.startswith(prefix + "#"):
            if current is not None:
                current["content"] = current["content"].strip() + "\n"
                sections.append(current)
            current = {"title": stripped[len(prefix) + 1 :].strip(), "content": ""}
            continue
        if current is None:
            current = {"title": "", "content": ""}
        current["content"] += line + "\n"
    if current is not None:
        current["content"] = current["content"].strip() + "\n"
        sections.append(current)
    return sections


# --------------------------------------------------------------------------- #
# Markdown → docx（重排一版，不走 HTML 转换）
# --------------------------------------------------------------------------- #


def md_to_docx(
    md_text: str,
    out_path: str | Path,
    title: str = "",
    page_preset: str = "default",
) -> dict[str, Any]:
    """把简单 Markdown 排成 docx：标题层级、项目符号、表格、正文。

    刻意只支持「常见写法」（# 标题、- 列表、| 表格、空行分段、**加粗**），
    复杂语法（脚注、HTML 块、嵌套列表）会被当正文原样保留 —— 不假装支持。
    """
    from docx import Document

    from .docx_utils import PAGE_PRESETS, add_table_simple, apply_body, apply_headings, set_page

    document = Document()
    set_page(document, PAGE_PRESETS.get(page_preset, PAGE_PRESETS["default"]))
    if title:
        document.add_heading(title, level=0)

    table_buffer: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_buffer
        if len(table_buffer) >= 2:
            head = table_buffer[0]
            separator = "|".join(table_buffer[1])
            body = table_buffer[2:] if _TABLE_SEP_RE.match(f"|{separator}|") else table_buffer[1:]
            add_table_simple(document, head, body)
        table_buffer = []

    for raw in (md_text or "").replace("\r\n", "\n").splitlines():
        stripped = raw.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            table_buffer.append(cells)
            continue
        flush_table()
        if not stripped:
            continue
        match = _HEADING_RE.match(stripped)
        if match:
            document.add_heading(match.group(2).strip(), level=min(len(match.group(1)), 4))
            continue
        if stripped.startswith(("- ", "* ")):
            # 不用 Word 的「List Bullet / List Number」样式：这两个内置样式自带
            # 720 twips 左缩进 + 制表位，序号与正文之间会空出两三个字的宽度——
            # 用户 2026-11-09 反馈「间隔太远，很不合理」。
            # 改成普通段落、序号写进行首、后面只跟一个空格，和 docx 渲染器
            # （doc_render.DocxRenderer.items）同一套写法，两处稿子长得一样。
            document.add_paragraph(stripped[2:].strip())
            continue
        if re.match(r"^\d+[.)]\s+", stripped):
            # 保留原编号（素材从「3.」起就还是 3.），只把「）」统一成点
            document.add_paragraph(re.sub(r"^(\d+)[.)]\s+", r"\1. ", stripped))
            continue
        paragraph = document.add_paragraph()
        for chunk in re.split(r"(\*\*.+?\*\*)", stripped):
            if not chunk:
                continue
            bold = chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4
            run = paragraph.add_run(chunk[2:-2] if bold else chunk)
            if bold:
                run.bold = True
    flush_table()

    apply_body(document)
    apply_headings(document)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out))
    return {"out": str(out), "headings": len(heading_tree(md_text)), "chars": len(md_text or "")}


def iter_lines(text: str) -> Iterable[str]:  # pragma: no cover - 兼容旧脚本
    return iter((text or "").splitlines())
