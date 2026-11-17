"""文档工具：doc.generate_report（唯一的「真实产出」工具，**高风险**：必须已授权才执行）。

默认生成 DOCX：标题 / 摘要 / 本周进展 / 关键数据 / 风险与问题 / 下周计划，
同时落一份同名 .preview.html；模板 weekly 完整，meeting / summary 简化可用。
素材带小节标题时按标题切段，各节只取本节内容。

**文末不挂「来源引用」**：那是给写稿人自己核对用的清单，读文档的人用不到
（用户 2026-11-09 明确要求去掉，别再补回来）。素材来源仍记在产物 `extra.sources`
里供右栏展示，只是不写进正文。

format 参数支持多格式输出（清单见 `domain/formats.py` 的 `OUTPUT_FORMATS`，
当前是 docx / pdf / xlsx / pptx / txt）：前端「产物格式」选择器会把用户选的格式传进来
（默认与上传素材同格式），模型也可在 tool call 里显式指定 format。
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from ...core.security import safe_filename
from ...core.utils import (
    count_chars,
    new_id,
    now_iso,
    sha256_file,
    week_label,
)
from ...domain.entities import Artifact
from ...domain.formats import DEFAULT_OUTPUT_FORMAT, OUTPUT_FORMATS, describe_output_formats
from ...domain.rag import unsupported_facts
from ..spec import EFFECT_OUTPUT, ToolContext, tool

TEMPLATES = ("weekly", "meeting", "summary")

# 支持的产物格式统一由 `domain/formats.py` 定义——这里不再自己维护一份。
# 以前这里写着 docx/pdf/xlsx/txt，工具描述却承诺「还支持 md」，
# 而 `output_format not in OUTPUT_FORMATS` 会把 md 静默降级成 docx。

_SOURCE_TO_HEADING = {
    "summary": "摘要",
    "progress": "本周进展",
    "data": "关键数据",
    "risk": "风险与问题",
    "plan": "下周计划",
}


def _load_custom_templates(path: Path) -> dict[str, dict[str, Any]]:
    """读取 data/templates.json（TemplateService 维护的自定义模板镜像）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class DocSection(TypedDict):
    heading: str
    paragraphs: list[str]
    """配图（只有「图文对照」这类章节才有）：data 是图片字节，caption 是图注。
    图片直接嵌进 docx，纯文本类渲染器退化成一行「（图1 …）」占位。"""
    images: NotRequired[list[dict[str, Any]]]


_DEFAULTS: dict[str, list[str]] = {
    # 以前这里放的是「完成了本周既定任务的梳理与交付」这类凑数句：
    # 素材里没写，文档却写得很满，用户一看就知道是假的（还容易当成事实引用）。
    # 现在一律如实说没写，宁缺毋滥。
    "progress": ["素材里没有「本周进展」这类内容，建议补充工作记录后再生成周报。"],
    "data": ["素材里没有可提取的量化数据。"],
    "risk": ["素材里没有提到风险与问题。"],
    "plan": ["素材里没有提到下一步计划。"],
}

# 图注 / 文件名标签不是数据，别当成「关键数据」列进报告
_FIGURE_LINE = re.compile(r"^(?:图|表)\s*\d+|^照片《|^【[^】]*】$")

# 「下周计划完成压测」这种句子同时含「完成」——会被「进展」的语义词抓走。
# 计划句有很稳的开头（下周 / 后续 / 待办 / 下一步），先认开头再让给它该去的那一节。
_PLAN_LEAD = re.compile(r"^\s*(?:下周|下月|下季度|后续|待办|下一步|接下来|计划|拟)")

# ---------- 小节识别 ----------
_HEADING_PREFIX = re.compile(
    r"^\s*(?:"
    r"#{1,4}\s*"
    r"|(?:[一二三四五六七八九十]+|\d{1,2})\s*[、.．)）]\s*"
    r"|[（(]\s*(?:[一二三四五六七八九十]+|\d{1,2})\s*[)）]\s*"
    r"|【\s*"
    r")"
)

# 小节名词表。这里只做「这一节属于哪一类」的归类，不猜内容——
# 归不进去的行会照原样进正文，不会因为词表没有它就丢内容。
#
# 为什么要铺这么宽：真实素材的写法比模板野得多。同一件事有人写「本周进展」，
# 有人写「本周完成」「主要工作」「交付情况」，还有人直接写「一、做了什么」。
# 词表窄一位，那一节就被当成正文塞进别的小节，用户看到的是「风险与问题」里
# 混进了三条进展——比漏掉更难收拾。
_HEADING_KEYS: tuple[tuple[str, str], ...] = (
    # ---- 进展：本周做了什么 ----
    ("风险与问题", "risk"),
    ("风险与挑战", "risk"),
    ("风险与应对", "risk"),
    ("风险与措施", "risk"),
    ("风险与依赖", "risk"),
    ("问题与风险", "risk"),
    ("本周进展", "progress"),
    ("工作进展", "progress"),
    ("项目进展", "progress"),
    ("研发进展", "progress"),
    ("本周工作", "progress"),
    ("本周完成", "progress"),
    ("本周重点", "progress"),
    ("本周产出", "progress"),
    ("工作内容", "progress"),
    ("主要工作", "progress"),
    ("主要进展", "progress"),
    ("完成情况", "progress"),
    ("完成事项", "progress"),
    ("交付情况", "progress"),
    ("交付内容", "progress"),
    ("阶段成果", "progress"),
    ("里程碑", "progress"),
    ("进展情况", "progress"),
    ("工作回顾", "progress"),
    ("进展", "progress"),
    # ---- 数据：能量化的东西 ----
    ("关键数据", "data"),
    ("关键指标", "data"),
    ("核心数据", "data"),
    ("量化数据", "data"),
    ("数据看板", "data"),
    ("效果数据", "data"),
    ("数据", "data"),
    ("指标", "data"),
    ("数字", "data"),
    # ---- 计划：接下来做什么 ----
    ("下周计划", "plan"),
    ("下周工作", "plan"),
    ("下周安排", "plan"),
    ("下周重点", "plan"),
    ("后续计划", "plan"),
    ("后续安排", "plan"),
    ("下步计划", "plan"),
    ("工作计划", "plan"),
    ("下周承诺", "plan"),
    ("承诺事项", "plan"),
    ("待办事项", "plan"),
    ("待办清单", "plan"),
    ("行动项", "plan"),
    ("行动计划", "plan"),
    ("下一步", "plan"),
    ("待办", "plan"),
    ("计划", "plan"),
    ("安排", "plan"),
    # ---- 会议 ----
    ("议题与讨论", "topics"),
    ("会议议题", "topics"),
    ("会议内容", "topics"),
    ("讨论纪要", "topics"),
    ("讨论", "topics"),
    ("议题", "topics"),
    ("结论与待办", "conclusion"),
    ("讨论与结论", "conclusion"),
    ("会议结论", "conclusion"),
    ("结论", "conclusion"),
    ("决议", "conclusion"),
    ("共识", "conclusion"),
    # ---- 摘要 / 来源 ----
    # 「来源」这一族留着只为**认出来并丢掉**：素材自己带了一节「参考资料」时，
    # 别把它当正文塞进摘要或要点；成稿里也不再输出这一节（见 _sections_from_material）。
    ("来源引用", "sources"),
    ("参考来源", "sources"),
    ("资料来源", "sources"),
    # 「关键文件索引」这类节本质也是出处清单：列一串源码路径给写稿人核对用，
    # 读者用不到。认成 sources 才不会照抄进成稿（用户 2026-11-10 又点了一次）。
    ("关键文件索引", "sources"),
    ("文件索引", "sources"),
    ("代码索引", "sources"),
    ("源码索引", "sources"),
    ("来源", "sources"),
    ("出处", "sources"),
    ("一句话结论", "summary"),
    ("核心结论", "summary"),
    ("总体结论", "summary"),
    ("执行摘要", "summary"),
    ("摘要", "summary"),
    ("概述", "summary"),
    ("概况", "summary"),
    ("总览", "summary"),
    ("背景", "summary"),
    ("总结", "summary"),
)
_HEADING_KEYS_SORTED = tuple(sorted(_HEADING_KEYS, key=lambda item: -len(item[0])))

_HEADER_LINE = re.compile(
    r"^\s*(?:时间|地点|参会(?:人员)?|与会(?:人员)?|主持人?|记录人?|日期|"
    r"会议主题|会议名称|列席(?:人员)?)\s*[:：]"
)

#: 词表里没有、但一看就是小节标题的行：中文序号打头（一、／（一））、短、不带句读。
#:
#: 词表铺到 90+ 条也总会有漏的（「六、杂项」「七、附：联系人」）。漏了就整段塞进
#: 上一节，用户在自己的文档里看不到自己写的那一节。所以这里补一条兜底：
#: 中文序号 + 短标题，就当小节。**只认中文序号**——「1. 完成联调」这种多半是
#: 列表项，认成小节会把一份清单拆成十节。
_LOOSE_HEADING = re.compile(
    r"^\s*(?:[一二三四五六七八九十]{1,3}\s*[、.．]|[（(]\s*[一二三四五六七八九十]{1,3}\s*[)）])\s*\S"
)


def _loose_heading(line: str) -> str:
    """词表外的小节标题 → 标题文本；不像标题就返回空串。"""
    if not _LOOSE_HEADING.match(line):
        return ""
    clean = _strip_heading_prefix(line)
    if not clean or len(clean) > 16:
        return ""
    if re.search(r"[。；，,;！？!?]", clean):
        return ""
    return clean


def _strip_heading_prefix(line: str) -> str:
    candidate = line
    for _ in range(2):
        if _HEADING_PREFIX.match(candidate):
            candidate = _HEADING_PREFIX.sub("", candidate, count=1).strip()
        else:
            break
    return candidate


# 素材名结尾常见的日期尾巴：`报告_2026-10-26`、`周记2026年10月` 这类信息已经在文件名后半段
# 出现过（产物的日期），留着只会把真正能区分的部分挤掉。
_DATE_TAIL = re.compile(r"[\s_\-—]*\d{4}\s*[-年./]?\s*\d{1,2}\s*[-月./]?\s*\d{1,2}\s*日?$")
_BRACKETS: tuple[tuple[str, str], ...] = (
    ("（", "）"),
    ("(", ")"),
    ("【", "】"),
    ("《", "》"),
    ("[", "]"),
)


def _trim_bracket(name: str, limit: int) -> str:
    """按字数截断，但不把括号切成一半。

    「24级软件工程（智慧能源」这种半截括号看起来像文件名坏了；
    截断点落在未闭合的左括号里时，退回到括号前再截一次。
    """
    if len(name) <= limit:
        return name
    cut = limit
    for left, right in _BRACKETS:
        if name.rfind(left, 0, cut) > name.rfind(right, 0, cut):
            cut = name.rfind(left, 0, cut)
    return name[:cut].rstrip(" _-—·（(【《[、,，")


def _source_name(source: dict[str, Any], limit: int = 16) -> str:
    """一份素材的可读名：去扩展名、去日期尾巴、截断时不破括号。"""
    name = Path(str(source.get("filename") or "")).stem.strip()
    name = _DATE_TAIL.sub("", name).strip(" _-—·")
    return _trim_bracket(name, limit)


def sources_label(sources: list[dict[str, Any]] | None, limit: int = 16) -> str:
    """素材名标签：一份直接用原名，多份取第一份 + 「等 N 份」。

    放在文件名的**最前面**：右栏窄、从尾部截断，能区分的部分必须落在前半段。
    以前是「摘要_日期」开头，产物列表里每份都以「摘要」打头，看着全一样。
    """
    names = [name for name in (_source_name(source, limit) for source in sources or []) if name]
    if not names:
        return ""
    return names[0] if len(names) == 1 else f"{names[0]}等{len(names)}份"


# 跟模板目录里的内置名保持一致（文件摘要 / 工作周报 / 会议纪要）
TYPE_LABEL = {"weekly": "工作周报", "meeting": "会议纪要", "summary": "文件摘要"}


def doc_title_for(template: str, sources: list[dict[str, Any]] | None) -> str:
    """文档标题（也进文件名）：素材名 · 产物类型，没素材时才退回「类型（日期）」。

    标题里原来只有「文件摘要（2026-10-26）」，一天里出几份就长得一模一样。
    """
    label = TYPE_LABEL.get(template, "素材报告")
    when = f"（{week_label()}）" if template == "weekly" else ""
    name = sources_label(sources)
    if name:
        return f"{name} · {label}{when}"
    return f"{label}（{week_label() if template == 'weekly' else now_iso()[:10]}）"


def _material_title(text: str) -> str:
    """素材首行如果是标题，就把它当标题用。

    「退款率复盘」比「数据分析报告」更像人话——标题该从内容里长出来，不是从
    模板里套出来。判断只认「短、不带句读、不是栏目行、不是图注」这四条：
    首行是「时间：2026-10-20」这种栏目行、或者干脆是小节标题时，都当没有标题。
    """
    for raw in (text or "").splitlines()[:5]:
        line = raw.strip().lstrip("#").strip()
        if not line:
            continue
        if len(line) > 24:
            continue
        if _HEADER_LINE.match(line) or _FIGURE_LINE.match(line):
            continue
        if _HEADING_PREFIX.match(line):
            return ""  # 首行就是「一、本周进展」：这份素材没有标题行
        if re.search(r"[。；，,;！？!?]", line):
            continue
        return line
    return ""


#: 标题里出现这些词、且只有它们时，说明首行是「周报」这种通用名，不是真标题。
_GENERIC_TITLE_WORDS = (
    "周报",
    "月报",
    "日报",
    "纪要",
    "记录",
    "摘要",
    "报告",
    "汇报",
    "总结",
    "方案",
    "通知",
)


def title_from_material(
    template: str,
    sources: list[dict[str, Any]] | None,
    text: str,
) -> str:
    """按素材内容起标题；素材没有标题行时退回「素材名 · 类型」。"""
    fallback = doc_title_for(template, sources)
    name = _material_title(text)
    if not name or name == TYPE_LABEL.get(template):
        return fallback
    if name == sources_label(sources):
        return fallback
    # 「工作周报」这类通用词当标题没有信息量，还不如带素材名
    if any(word in name for word in _GENERIC_TITLE_WORDS) and len(name) <= 6:
        return fallback
    when = f"（{week_label()}）" if template == "weekly" else ""
    return f"{name} · {TYPE_LABEL.get(template, '报告')}{when}"


def _canonical_section(title: str) -> str | None:
    clean = re.sub(r"^[\s\-—–·#【\[]+", "", title.strip())
    clean = re.sub(r"[（(][^）)]*[）)]\s*$", "", clean).strip()
    clean = re.sub(r"^[\s\-—–·#【\[]+", "", clean)
    clean = re.sub(r"[\s：:、.．)）】\]]+$", "", clean)
    if not clean or len(clean) > 16:
        return None
    for key, canonical in _HEADING_KEYS_SORTED:
        if clean == key:
            return canonical
    return None


def _display_heading(text: str, fallback: str) -> str:
    """素材里的原标题 → 能直接当小节名的那一行。

    去掉首尾标点、去掉「（补充）」这类尾巴，太长就截断。标题是读者找东西的锚，
    素材写「退款率复盘」就还叫「退款率复盘」——换成「关键数据」，他反而找不到了。
    """
    clean = text.strip()
    clean = re.sub(r"^[\s\-—–·#【\[]+", "", clean)
    clean = re.sub(r"[\s：:、.．)）】\]]+$", "", clean)
    clean = clean.strip()
    if not clean:
        return fallback
    return clean[:24]


def _split_named(text: str) -> tuple[list[tuple[str, str, list[str]]], str]:
    """按素材自己的小节切，**保留原标题与顺序**：`[(归类键, 原标题, 行), …]`。

    以前只返回 `{归类键: 内容}`：素材写「二、退款率复盘」，归一下类就变成
    「关键数据」——标题被换成了模板词，用户在自己的文档里找不到自己写的那一节。
    结构也不该是模板给的：素材按什么顺序讲，文档就按什么顺序排。
    """
    blocks: list[tuple[str, str, list[str]]] = []
    preamble: list[str] = []
    current: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        stripped = _strip_heading_prefix(line)
        canonical = _canonical_section(stripped)
        if canonical:
            blocks.append((canonical, _display_heading(stripped, canonical), []))
            current = len(blocks) - 1
            continue
        loose = _loose_heading(line)
        if loose:
            blocks.append(("other", _display_heading(loose, "小节"), []))
            current = len(blocks) - 1
            continue
        if current is None:
            preamble.append(line)
        else:
            blocks[current][2].append(line)
    return blocks, "\n".join(preamble)


def _split_sections(text: str) -> tuple[dict[str, str], str]:
    """`{归类键: 内容}` + 前言。归类键会合并同名小节（老调用方按字典取内容）。"""
    blocks, preamble = _split_named(text)
    if not blocks:
        return {}, text
    merged: dict[str, list[str]] = {}
    for canonical, _heading, lines in blocks:
        merged.setdefault(canonical, []).extend(lines)
    return {key: "\n".join(value) for key, value in merged.items()}, preamble


def _sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in re.split(r"\n+", text):
        line = line.strip().strip("•-*# ")
        if not line or _FIGURE_LINE.match(line):
            continue
        for segment in re.split(r"(?<=[。；;！!？?])|\s{2,}", line):
            segment = segment.strip()
            if len(segment) >= 8:
                parts.append(segment[:160])
    seen: set[str] = set()
    result: list[str] = []
    for sentence in parts:
        if sentence not in seen:
            seen.add(sentence)
            result.append(sentence)
    return result


def _pick(sentences: list[str], keywords: tuple[str, ...], limit: int) -> list[str]:
    return [sentence for sentence in sentences if any(key in sentence for key in keywords)][:limit]


def _data_points(text: str, limit: int = 6) -> list[str]:
    points: list[str] = []
    for line in re.split(r"\n+", text):
        line = line.strip().strip("•-* ")
        if not line or _HEADER_LINE.match(line) or _FIGURE_LINE.match(line):
            continue
        for segment in re.split(r"(?<=[。；;])", line):
            segment = segment.strip()
            if not segment or not re.search(r"\d", segment) or len(segment) < 4:
                continue
            if segment in points:
                continue
            points.append(segment[:120])
            if len(points) >= limit:
                return points
    return points


def _section(parts: dict[str, str], key: str) -> str | None:
    content = (parts.get(key) or "").strip()
    return content or None


def _join_sents(sentences: list[str], limit: int = 2) -> str:
    cleaned = [re.sub(r"[。；;，,、\s]+$", "", sentence) for sentence in sentences[:limit]]
    return "；".join(item for item in cleaned if item)


def _stats_lines(facts: dict[str, Any] | None) -> list[str]:
    """脚本体检出来的真实结构，写成「关键数据」能直接读的一行句话。"""
    totals = (facts or {}).get("totals") or {}
    if not totals.get("files"):
        return []
    files = int(totals.get("files") or 0)
    paras = int(totals.get("paragraphs") or 0)
    chars = int(totals.get("chars") or 0)
    lines = [f"素材 {files} 份，正文 {paras} 段，合计 {chars:,} 字。"]
    extras: list[str] = []
    if totals.get("images"):
        extras.append(f"内嵌图片 {int(totals['images'])} 张")
    if totals.get("tables"):
        extras.append(f"表格 {int(totals['tables'])} 张")
    if totals.get("headings"):
        extras.append(f"标题 {int(totals['headings'])} 处")
    if extras:
        lines.append("结构：" + "、".join(extras) + "。")
    captions = _figure_captions(facts)
    if captions:
        lines.append("图注：" + "、".join(captions[:6]) + "。")
    return lines


def _figure_captions(facts: dict[str, Any] | None) -> list[str]:
    captions: list[str] = []
    for item in (facts or {}).get("files") or []:
        for caption in item.get("figures") or []:
            text = str(caption).strip()
            if text and text not in captions:
                captions.append(text)
    # 有「图1 / 表2」这种编号图注时就用它，别把「照片《…》感悟」这类标签也列一遍
    numbered = [text for text in captions if re.match(r"^[图表]\s*\d+", text)]
    return numbered or captions


def _key_points(text: str, limit: int = 6) -> list[str]:
    """要点：原文档里有内容的段落，各取一句，不加工、不改写。"""
    points: list[str] = []
    for raw in re.split(r"\n+", text or ""):
        line = raw.strip().strip("•-* ")
        if len(line) < 12 or _FIGURE_LINE.match(line):
            continue
        if _canonical_section(_strip_heading_prefix(line)):
            continue
        first = re.split(r"(?<=[。；;！!？?])", line)[0].strip()
        first = first[:80] + ("…" if len(first) > 80 else "")
        if first and first not in points:
            points.append(first)
        if len(points) >= limit:
            break
    return points


# ---------------- 结构识别（摘要用） ----------------
# 摘要不是「取前两句」，而是先看清文档结构：标题、图注、每组图下的正文，再按结构成文。
# 这些判定都只用可验证的文本特征，不猜语义——猜出来的「总结」比不写更糟。

_CAPTION_LINE = re.compile(r"^(?:图|表)\s*[0-9一二三四五六七八九十]+")
_PHOTO_LABEL = re.compile(r"^照片《[^》]{1,24}》")
_SENTENCE_TAIL = re.compile(r"[。！？!?…]$")


def _norm_text(text: str) -> str:
    """判重用的归一化：去掉空白与标点，只留字词。"""
    return re.sub(r"[\s，。；、！？：,.!?:;\"'“”‘’（）()《》【】\[\]\-—–_/\\|]+", "", text or "")


def _split_sentences(paragraph: str) -> list[str]:
    text = (paragraph or "").strip()
    if not text:
        return []
    parts = [seg.strip() for seg in re.split(r"(?<=[。！？!?])", text) if seg.strip()]
    return parts or [text]


def _clip_phrase(sentence: str, limit: int = 60) -> str:
    text = re.sub(r"[。；;，,、\s]+$", "", (sentence or "").strip())
    return text[:limit] + ("…" if len(text) > limit else "")


#: 文末「来源：素材.docx」「依据《x.md》整理」「代码位置沿用…」这类落款行。
#: 都是写稿人自己核对用的出处说明，读者用不到（用户 2026-11-09 / 11-10 两次要求去掉）。
_SOURCE_NOTE = re.compile(
    r"^\s*(?:来源|资料来源|参考来源|参考资料|参考文献|出处|引用)\s*[:：]"
    r"|^\s*(?:依据|根据|整理自|摘录自|改编自|基于)\s*《[^》]+》\s*"
    r"(?:整理|编写|改写|摘录|汇总|而成)"
    r"|^\s*代码位置沿用"
)
#: 「来源引用 / 关键文件索引」这一类小节标题。
#: 可带 markdown 井号，也可带「六、」这种中文编号——素材和模型两种写法都得认出来。
_SOURCE_HEADING = re.compile(
    r"^\s*(?:#{0,6}\s*)?(?:[一二三四五六七八九十]{1,3}\s*[、.．]\s*)?"
    r"(?:来源引用|引用来源|参考来源|资料来源|参考资料|参考文献|"
    r"关键文件索引|文件索引|代码索引|源码索引)\s*#*\s*$"
)
#: 下一节的标题：只有真的是标题才结束「整节丢弃」，免得把正文里一句短句当成新节
_NEXT_HEADING = re.compile(
    r"^\s*#{1,6}\s+\S"
    r"|^\s*(?:[一二三四五六七八九十]{1,3}\s*[、.．]|[（(]\s*[一二三四五六七八九十]{1,3}\s*[)）])\s*\S"
)


def _strip_source_notes(text: str) -> str:
    """删掉「来源引用 / 关键文件索引」整节与「来源：…」「依据《…》整理」落款行。

    这些出处清单是写稿人自己核对用的（哪份素材的第几段、代码在哪个文件），
    读文档的人不会看，也不该占正文一节——用户 2026-11-09 明确要求去掉，
    11-10 又指出带编号的「六、关键文件索引」和「依据《x.md》整理」没被拦住。
    骨架里那节已经不再生成，但正文是模型写的，不同模型时有时无地补一节出处，
    所以按行兜一层。只删「整节标题 + 该节内容」和「整行就是落款」，
    正文里顺带提到「来源」的句子不动。
    """
    kept: list[str] = []
    skipping = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if _SOURCE_HEADING.match(line):
            skipping = True
            continue
        if skipping:
            if _NEXT_HEADING.match(line):
                skipping = False
            else:
                continue
        if _SOURCE_NOTE.match(line):
            continue
        kept.append(raw)
    return "\n".join(kept).strip()


def _is_heading_line(line: str) -> bool:
    """短、不带句末标点、不像图注 —— 按标题处理。"""
    if _CAPTION_LINE.match(line):
        return False
    # 「照片《杉道晴光》感悟」是一组图文的标签，不是图注本身
    if _PHOTO_LABEL.match(line):
        return True
    if _HEADING_PREFIX.match(line):
        return True
    return (
        len(line) <= 24 and not _SENTENCE_TAIL.search(line) and not re.search(r"[，,；;、]", line)
    )


def _strip_source_headers(text: str, sources: list[dict[str, Any]]) -> str:
    """去掉 file.read 拼进去的「【文件名】」分隔行。

    它是多份素材之间的分隔标记，不是文档标题；留着会被当成第一个小标题，
    摘要开头就变成「《【24级…docx】》是一篇图文稿」——读起来像文件名坏了。
    """
    headers = {f"【{str(source.get('filename') or '').strip()}】" for source in sources}
    headers.discard("【】")
    if not headers:
        return text
    return "\n".join(line for line in text.splitlines() if line.strip() not in headers)


def _doc_blocks(text: str) -> list[tuple[str, str]]:
    """把素材正文切成 (标题 / 图注 / 正文) 三类块，并去掉重复段。

    解析器给的是纯文本，没有样式信息，只能按可判定的特征分类。
    判重按「去标点后相同」：同一份材料重复上传时，摘要与要点会整段重复。
    """
    blocks: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("#").strip()
        if not line:
            continue
        key = _norm_text(line)
        if not key or key in seen:
            continue
        seen.add(key)
        if _CAPTION_LINE.match(line):
            kind = "caption"
        elif _is_heading_line(line):
            kind = "heading"
        else:
            kind = "body"
        blocks.append((kind, line))
    return blocks


def _doc_groups(blocks: list[tuple[str, str]]) -> list[dict[str, str]]:
    """图注 → 该组图下的正文（感悟）。

    既认「照片《杉道晴光》感悟」这种小标题，也认紧随图注的正文；
    小标题就是文档标题时不算（那只是文章名，不是这一组的标签）。
    """
    title = next((line for kind, line in blocks if kind == "heading"), "")
    groups: list[dict[str, str]] = []
    for index, (kind, line) in enumerate(blocks):
        if kind != "caption":
            continue
        label = ""
        for prev_kind, prev in reversed(blocks[:index]):
            if prev_kind == "heading":
                label = "" if prev == title else prev
                break
            if prev_kind == "caption":
                break
        body = ""
        for next_kind, nxt in blocks[index + 1 :]:
            if next_kind == "body":
                body = nxt
                break
            if next_kind == "caption":
                break
        groups.append({"caption": line, "label": label, "body": body})
    return groups


def _summary_overview(
    title: str,
    groups: list[dict[str, str]],
    bodies: list[str],
) -> str:
    """摘要：一句「这是什么 + 有多大」，一到两句「分别写了什么」。

    以前是「取正文前两句」，于是散文摘要永远停在开头的场景描写上——
    后续内容（第二组照片、作者的感受）全部丢失，读者看完不知道文章写了什么。
    """
    chars = sum(len(body) for body in bodies)
    captions = [group["caption"] for group in groups[:4]]

    if groups:
        first = (
            f"《{title}》是一篇图文稿，收录 {len(groups)} 组「照片 + 感悟」"
            f"（{'、'.join(captions)}），{len(bodies)} 段正文"
        )
        first += f"、{chars:,} 字。" if chars else "。"
    elif len(bodies) > 1:
        first = f"《{title}》共 {len(bodies)} 段正文" + (f"、{chars:,} 字。" if chars else "。")
    else:
        first = f"《{title}》" + (f"共 {chars:,} 字。" if chars else "。")
    sentences = [first]

    leads: list[str] = []
    if groups:
        for group in groups[:4]:
            first = _split_sentences(group["body"])[0] if group["body"] else ""
            if first:
                leads.append(f"{group['caption']}：{_clip_phrase(first, 52)}")
    else:
        for paragraph in bodies[:2]:
            first = _split_sentences(paragraph)[0]
            if first:
                leads.append(_clip_phrase(first, 60))
    if leads:
        sentences.append("；".join(leads) + "。")
    return "".join(sentences)


def _summary_stats(
    sources: list[dict[str, Any]],
    groups: list[dict[str, str]],
    bodies: list[str],
    figures: list[dict[str, Any]],
    facts: dict[str, Any] | None,
) -> list[str]:
    """素材构成：按「去重之后」的真实结构计数。

    以前直接用脚本体检的数字，而脚本数的是上传份数——
    同一份材料传了三次就写成「正文 7 段」，可实际只有 2 段，看着像漏读了内容。
    """
    if not bodies and not groups:
        return []
    chars = sum(len(body) for body in bodies)
    unique = (
        len({_norm_text(str(source.get("text") or "")) for source in sources}) if sources else 0
    )
    head = f"素材 {len(sources)} 份"
    if unique and unique < len(sources):
        # 同一份稿子重复上传时，段数按去重后算，但要说明「份数少在哪」，否则用户以为漏读
        head += f"（{len(sources) - unique} 份内容重复，已按正文去重）"
    lines = [f"{head}，正文 {len(bodies)} 段，合计 {chars:,} 字。"]
    extras: list[str] = []
    if figures:
        extras.append(f"内嵌图片 {len(figures)} 张")
    tables = int(((facts or {}).get("totals") or {}).get("tables") or 0)
    if tables:
        extras.append(f"表格 {tables} 张")
    if extras:
        lines.append("结构：" + "、".join(extras) + "。")
    captions = [group["caption"] for group in groups[:6]]
    if captions:
        lines.append("图注：" + "、".join(captions) + "。")
    return lines


def _summary_points(groups: list[dict[str, str]], bodies: list[str], limit: int = 6) -> list[str]:
    """要点：每组图/每段取「除摘要已引用之外」的那句，按组标注，不按句子序号乱切。

    摘要引了每组的第一句（场景），要点就给这一组的落点句（作者的感受/结论），
    两处不重复，读起来才是「摘要 + 要点」而不是同一段话被切两半。
    """
    points: list[str] = []
    if groups:
        for group in groups:
            sentences = _split_sentences(group["body"])
            if not sentences:
                continue
            pick = sentences[-1] if len(sentences) > 1 else sentences[0]
            points.append(f"{group['caption']}：{_clip_phrase(pick, 80)}")
        return points[:limit]

    seen: set[str] = set()
    for paragraph in bodies:
        first = _split_sentences(paragraph)[0]
        key = _norm_text(first)
        if not first or key in seen:
            continue
        seen.add(key)
        points.append(_clip_phrase(first, 80))
        if len(points) >= limit:
            break
    return points


def _apply_outline(sections: list[DocSection], outline: dict[str, Any] | None) -> list[DocSection]:
    """模型自己写的摘要/要点优先（它读过全文，比规则抽取更准）。

    只允许替换「摘要 / 要点」两节的正文，章节骨架仍由模板决定：
    模型少给、给错类型都不至于把文档结构搞乱。
    """
    if not isinstance(outline, dict) or not outline:
        return sections
    summary = outline.get("摘要") or outline.get("summary")
    points = outline.get("要点") or outline.get("points")
    for section in sections:
        if section["heading"] == "摘要" and isinstance(summary, str) and summary.strip():
            section["paragraphs"] = [summary.strip()[:600]]
        elif section["heading"] == "要点" and isinstance(points, list):
            cleaned = [str(item).strip()[:200] for item in points if str(item).strip()]
            if cleaned:
                section["paragraphs"] = cleaned[:8]
    return sections


# 只留骨架、不留占位句：没素材时每节写一句「素材里没有…」，用户拿到的是一份
# 处处在提醒他「你什么都没给我」的稿子，既不能交付也没法改。留一个干净的空架子，
# 他能直接往里填，我们也不会把「没读到」写成「没有」。
TEMPLATE_HEADINGS: dict[str, tuple[str, ...]] = {
    "weekly": ("摘要", "本周进展", "关键数据", "风险与问题", "下周计划"),
    "meeting": ("摘要", "议题与讨论", "结论与待办"),
    "summary": ("摘要", "要点"),
}


def _join_named(named: list[tuple[str, str, list[str]]]) -> dict[str, str]:
    """`[(归类键, 原标题, 行)]` → `{归类键: 内容}`（同名小节合并）。"""
    merged: dict[str, list[str]] = {}
    for canonical, _heading, lines in named:
        merged.setdefault(canonical, []).extend(lines)
    return {key: "\n".join(value) for key, value in merged.items()}


def _sections_from_material(
    named: list[tuple[str, str, list[str]]],
    summary: str,
    stats: list[str],
) -> list[DocSection]:
    """按素材自己的小节成文：顺序照抄、标题照抄、没写的节不编。

    这是「结构由素材决定」那一条的实现。素材写「一、退款率复盘」，文档里就是
    「一、退款率复盘」；素材没写风险，就不出现「风险与问题」——不编内容，
    也不留一句「素材里没有」占位。

    文末不再挂「来源引用」：那份出处清单是给写稿人自己核对用的，读者不会去看，
    也不该占正文的一节（用户 2026-11-09 明确要求去掉）。
    """
    lead = next((item for item in named if item[0] == "summary"), None)
    lead_text = _sentences("\n".join(lead[2]))[:2] if lead else []
    sections: list[DocSection] = [
        {"heading": lead[1] if lead else "摘要", "paragraphs": lead_text or [summary]}
    ]
    for canonical, heading, lines in named:
        if canonical in ("summary", "sources"):
            continue
        text = "\n".join(lines)
        if canonical == "data":
            # 脚本体检出来的真实结构排在前面：份数、段数、字数、图片、表格、图注
            paragraphs = stats + _data_points(text)
        elif canonical in ("progress", "risk", "topics", "other"):
            paragraphs = _sentences(text)[:4]
        else:  # plan / conclusion
            paragraphs = _sentences(text)[:3]
        if paragraphs:
            sections.append({"heading": heading, "paragraphs": paragraphs})
    return sections


def _build_sections(
    template: str,
    text: str,
    sources: list[dict[str, Any]],
    llm_text: str,
    facts: dict[str, Any] | None = None,
    figures: list[dict[str, Any]] | None = None,
) -> list[DocSection]:
    if not (text or "").strip() and not sources:
        return [
            {"heading": heading, "paragraphs": []}
            for heading in TEMPLATE_HEADINGS.get(template, TEMPLATE_HEADINGS["weekly"])
        ]
    named, preamble = _split_named(text)
    has_parts = bool(named)
    parts = _join_named(named)
    all_sents = _sentences(text)
    stats = _stats_lines(facts)

    progress_sec = _section(parts, "progress")
    progress_sents = _sentences(progress_sec) if progress_sec else []
    if has_parts:
        progress = progress_sents[:4] or _DEFAULTS["progress"]
    else:
        # 没有小节标题时先按周报语义词挑，挑不到就用原文段落首句——
        # 宁可给「素材原文」，也不拿一句放之四海皆准的假话凑数
        progress = (
            _pick(all_sents, ("完成", "推进", "上线", "交付", "修复", "支持", "整理", "本周"), 4)
            or _key_points(text, 4)
            or _DEFAULTS["progress"]
        )
        # 「下周计划完成压测」也含「完成」，会被上面的语义词抓进「本周进展」。
        # 计划句开头很稳（下周 / 后续 / 待办 / 下一步），按开头让给「下周计划」。
        progress = [line for line in progress if not _PLAN_LEAD.match(line)] or progress

    if llm_text:
        summary = llm_text.strip()[:600]
    elif progress_sents:
        summary = f"本报告基于 {len(sources)} 份素材整理：{_join_sents(progress_sents, 2)[:180]}"
    elif has_parts:
        # 摘要优先用「第一行 / 前言」，没有就退到第一小节的正文——
        # 素材里第一行往往就是标题（「退款率复盘」），短到一句摘要都拼不出来。
        first_body = "\n".join(named[0][2]) if named else ""
        lead_sents = _sentences(preamble) or _sentences(first_body) or _sentences(text)
        if lead_sents:
            summary = f"本报告基于 {len(sources)} 份素材整理：{_join_sents(lead_sents, 2)[:180]}"
        else:
            summary = f"素材共 {len(sources)} 份，未识别到小节标题与正文要点。"
    elif all_sents:
        summary = f"本报告基于 {len(sources)} 份素材整理：{_join_sents(progress, 2)[:180]}"
    else:
        summary = "本次任务未上传素材，以下内容需要补充材料后再生成。"

    data_sec = _section(parts, "data")
    data = _data_points(data_sec) if data_sec else _data_points(text)
    if not data:
        data = _data_points(preamble) if has_parts and preamble else []
    # 脚本体检出来的真实结构排在前面：份数、段数、字数、图片、表格、图注
    data = stats + data
    if not data:
        data = _DEFAULTS["data"]

    risk_sec = _section(parts, "risk")
    if has_parts:
        risk = _sentences(risk_sec)[:4] if risk_sec else _DEFAULTS["risk"]
    else:
        risk = (
            _pick(all_sents, ("风险", "问题", "阻塞", "延期", "不足", "待定", "困难", "依赖"), 4)
            or _DEFAULTS["risk"]
        )

    plan_sec = _section(parts, "plan")
    if has_parts:
        plan = _sentences(plan_sec)[:3] if plan_sec else _DEFAULTS["plan"]
    else:
        plan = (
            _pick(all_sents, ("下周", "计划", "后续", "待办", "下一步", "将", "准备"), 3)
            or _DEFAULTS["plan"]
        )

    if template == "meeting":
        # 素材里有自己的小节：按它的顺序与标题成文（「一、议题」就叫「议题」）
        if has_parts:
            return _sections_from_material(named, summary, stats)
        topics_sec = _section(parts, "topics")
        if has_parts:
            topics = _sentences(topics_sec)[:4] if topics_sec else progress_sents[:4]
        else:
            topics = progress
        topics = topics or _key_points(text, 4) or _DEFAULTS["progress"]
        conclusion_sec = _section(parts, "conclusion")
        if has_parts:
            conclusion = _sentences(conclusion_sec)[:3] if conclusion_sec else plan
        else:
            conclusion = plan
        return [
            {"heading": "摘要", "paragraphs": [summary]},
            {"heading": "议题与讨论", "paragraphs": topics},
            {"heading": "结论与待办", "paragraphs": conclusion},
        ]
    if template == "summary":
        # 摘要模板不套周报骨架：先认清「这是什么文档、由哪几组图文构成」，再按结构成文。
        body_text = _strip_source_headers(text, sources)
        blocks = _doc_blocks(body_text)
        groups = _doc_groups(blocks)
        bodies = [line for kind, line in blocks if kind == "body"]
        headings = [line for kind, line in blocks if kind == "heading"]
        doc_title = headings[0] if headings else (_source_name(sources[0]) if sources else "素材")
        overview = _summary_overview(doc_title or "素材", groups, bodies)
        points = _summary_points(groups, bodies)
        sections: list[DocSection] = [
            {"heading": "摘要", "paragraphs": [overview]},
            # 要点里放的是各组/各段的落点句；一条都没有才退回周报语义词挑出来的句子
            {"heading": "要点", "paragraphs": points or progress or _DEFAULTS["progress"]},
        ]
        structure = _summary_stats(sources, groups, bodies, figures, facts)
        if structure:
            sections.append({"heading": "素材构成", "paragraphs": structure})
        if figures:
            # 图文对照：把源文档里的照片按原顺序搬过来，图注照抄，预览才与原件一致
            sections.append({"heading": "图文对照", "paragraphs": [], "images": figures})
        return sections
    # 素材自己分了小节：结构、顺序、标题都照它的来。
    # 这一条是「文档骨架不能定死」的地方——模板只在素材没有结构时兜底。
    if has_parts:
        return _sections_from_material(named, summary, stats)
    # 素材没分小节（只有大段文字）：按周报语义词归一次类，归不进去的节不输出。
    # 以前这里会写「素材里没有提到风险与问题」，一份稿子五句「没有」——
    # 用户既不能交付也改不动。现在没有这块内容就不出现这一节。
    # 没有小节标题时，同一句原文可能同时被两类规则挑中（带数字的进展句同时命中
    # 「关键数据」）。所以先按语义分段（进展 → 风险 → 计划），最后才分「关键数据」：
    # 反过来的话，数据会把风险句抢走，结果「风险与问题」整节消失。
    pools: dict[str, tuple[str, list[str]]] = {
        "progress": ("本周进展", progress),
        "risk": ("风险与问题", risk),
        "plan": ("下周计划", plan),
        "data": ("关键数据", data),
    }
    used: set[str] = set()
    kept: dict[str, list[str]] = {}
    for key in ("progress", "risk", "plan", "data"):
        paragraphs = pools[key][1]
        if paragraphs == _DEFAULTS[key]:
            continue
        fresh = [line for line in paragraphs if line not in used]
        if fresh:
            used.update(fresh)
            kept[key] = fresh
    sections = [{"heading": "摘要", "paragraphs": [summary]}]
    for key in ("progress", "data", "risk", "plan"):
        if key in kept:
            sections.append({"heading": pools[key][0], "paragraphs": kept[key]})
    return sections


# ---------------- 配图搬运 ----------------
_MAX_FIGURES = 4
_MAX_FIGURE_SIDE = 1400
_MAX_FIGURE_BYTES = 900_000


def _shrink_image(blob: bytes) -> bytes:
    """大图先压到「正文里放得下」的尺寸：6MB 的随手拍原图塞进摘要，
    产物会从几十 KB 涨到十几 MB，预览也要多等好几秒。"""
    if len(blob) <= _MAX_FIGURE_BYTES:
        return blob
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(blob))
        image.load()
        if max(image.size) > _MAX_FIGURE_SIDE:
            image.thumbnail((_MAX_FIGURE_SIDE, _MAX_FIGURE_SIDE))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=82, optimize=True)
        shrunk = out.getvalue()
        return shrunk if len(shrunk) < len(blob) else blob
    except Exception:  # 图片破损 / 不支持的编码：按原样嵌入，别让整个产物失败
        return blob


def _docx_figures(path: str, limit: int = _MAX_FIGURES) -> list[dict[str, Any]]:
    """把源 docx 里的图片连同图注一起取出来（图注优先取紧随其后的 Caption 段）。

    这是「文件摘要预览里没有图」的根因：正文抽文本时图片被丢掉了，
    摘要只能拿到文字，预览自然只剩字。这里按正文顺序回读原始图片。
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except Exception:  # pragma: no cover - python-docx 是硬依赖
        return []
    try:
        document = Document(path)
    except Exception:
        return []

    paragraphs = document.paragraphs
    figures: list[dict[str, Any]] = []
    for index, paragraph in enumerate(paragraphs):
        blips = paragraph._p.findall(".//" + qn("a:blip"))
        if not blips:
            continue
        caption = ""
        for neighbour in (index + 1, index - 1):
            if not 0 <= neighbour < len(paragraphs):
                continue
            text = paragraphs[neighbour].text.strip()
            if not text:
                continue
            style = getattr(paragraphs[neighbour].style, "name", "") or ""
            if _CAPTION_LINE.match(text) or _PHOTO_LABEL.match(text) or style == "Caption":
                caption = text
                break
        for blip in blips:
            rel_id = blip.get(qn("r:embed"))
            part = document.part.related_parts.get(rel_id) if rel_id else None
            blob = getattr(part, "blob", b"") or b""
            if not blob:
                continue
            figures.append({"caption": caption, "data": _shrink_image(blob)})
            if len(figures) >= limit:
                return figures
    return figures


def _figures_from_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按素材顺序收集配图；同一张图（字节相同）只放一次。"""
    figures: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    for source in sources:
        path = str(source.get("path") or "")
        if not path.lower().endswith(".docx"):
            continue
        for figure in _docx_figures(path):
            data = figure.get("data") or b""
            if not data or data in seen:
                continue
            seen.add(data)
            figures.append(figure)
            if len(figures) >= _MAX_FIGURES:
                return figures
    return figures


# ---------- 渲染 ----------
def _body_blocks(body: str) -> list[Any]:
    """模型写的整篇正文 → blocks。

    首块如果是 `# 标题` 就丢掉：标题由 `title` 参数决定（也进文件名），
    正文里再出现一遍会变成「一、工作周报 2026-W45」这种把自己当小节的开头。
    """
    from ...services.doc_render import parse_markdown

    blocks = parse_markdown(body)
    if blocks and blocks[0].kind == "heading" and blocks[0].level == 1:
        blocks = blocks[1:]
    return blocks


def _body_headings(body: str) -> list[str]:
    """正文里的小节名，进 `extra.sections`（产物详情/审计按它显示这一篇分了哪几节）。"""
    if not (body or "").strip():
        return []
    from ...services.doc_render import parse_markdown

    return [
        block.text for block in parse_markdown(body) if block.kind == "heading" and block.level > 1
    ]


def render_docx(
    title: str,
    sections: list[DocSection],
    path: Path,
    meta: dict[str, Any],
    *,
    body: str = "",
    subtitle: str = "",
    preset: str = "report",
    line: str = "",
    numbering: str = "",
    style: dict[str, Any] | None = None,
) -> None:
    """写 docx。

    `body` 是模型自己写的整篇 Markdown：给了就按它的标题层级/列表/表格还原，
    没给才用周报最常见的那几节兜底。两条路都经过 `services/doc_render` 那套版式——以前
    这里直接用默认模板的 `add_heading`，出来是宋体 + 蓝色标题，和界面预览对不上。

    `numbering` 是标题编号方案（cn / decimal / article / none）：周报用「一、」，
    论文与方案用「1.1.1」，合同用「第一条」，纪要与手册不编号。空着按 cn。

    `style` 是用户这一轮在「文档格式」里点的那几项（字体/字号/字型/行距/缩进/对齐）：
    他亲手点过的优先，没点的继续跟版式预设走。

    `meta` 仍然收着，但只用于文件属性：以前它会往正文第一段塞一行
    「生成时间 ｜ 模式 ｜ 来源」，那是给我们自己看的，用户拿到手是一句噪声。
    """
    from ...services.doc_render import blocks_from_sections, render_docx_blocks

    blocks = _body_blocks(body) if (body or "").strip() else blocks_from_sections(sections)
    render_docx_blocks(
        path,
        title=title,
        blocks=blocks,
        subtitle=subtitle,
        preset=preset,
        line=line or None,
        numbering=numbering,
        style=style,
    )


def _figure_note(figure: dict[str, Any]) -> str:
    """纯文本 / 表格 / PDF 里的图：给一行占位，图注保留，别让「图文对照」变成空章节。"""
    caption = str(figure.get("caption") or "").strip()
    return f"（图：{caption}）" if caption else "（图：原素材内嵌图片）"


def render_preview_html(
    title: str,
    sections: list[DocSection],
    meta: dict[str, Any],
    *,
    body: str = "",
    subtitle: str = "",
    preset: str = "report",
    numbering: str = "",
    style: dict[str, Any] | None = None,
) -> str:
    """预览 HTML：和 docx 走同一份 blocks，预览里能看到的表格，下载的文件里也有。

    preset 一起传进来：首行缩进这类只在某一档版式里出现的细节，预览也要跟着变，
    否则「预览里顶格、下载下来空两格」，用户会以为是排版出错。

    numbering 同理：预览是「一、摘要」、下载是「1. 摘要」，等于两份文件对不上。
    style（用户点的字体/字号/行距/缩进/对齐）同样要带进来，两条路只认一份设置。
    """
    from ...services.doc_render import blocks_from_sections, blocks_to_html

    blocks = _body_blocks(body) if (body or "").strip() else blocks_from_sections(sections)
    html = blocks_to_html(title, blocks, subtitle, preset=preset, numbering=numbering, style=style)
    return f'<div class="doc-preview">\n{html}\n</div>'


# ---------- 多格式渲染 ----------
def render_markdown(title: str, sections: list[DocSection], meta: dict[str, Any]) -> str:
    """Markdown 正文。

    仍然保留，但 `doc.generate_report` 已不产出 md：md 不是产物格式
    （见 `domain/formats.py` 里 can_output=False 的说明）。留着是因为
    「把结构化内容拼成 markdown」这件事在别处还有用（skill 模板、调试输出），
    删掉就得再写一遍。
    """
    lines = [f"# {title}", ""]
    for section in sections:
        lines.append(f"## {section['heading']}")
        lines.append("")
        for text in section.get("paragraphs") or [""]:
            lines.append(text)
        for figure in section.get("images") or []:
            lines.append(_figure_note(figure))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_text(title: str, sections: list[DocSection], meta: dict[str, Any]) -> str:
    """纯文本产物：靠标记与缩进分层（没有字号可用）。

    章节标记从 `text_lexicon` 取：txt / md / 日志三处用同一套【】，用户拿同一份稿子
    导出两次不会觉得工具不稳。

    **正文默认左对齐**：.txt 本身没有对齐属性，纯文本在任何编辑器里都从左边起行，
    这是它唯一说得通的形态。所以这里不收 `doc_style` 里的对齐/字号——用户在「文档格式」
    里点了居中，只对 docx 生效；把 txt 也当排版稿处理，只会在文件里塞进看不见的空格。
    """
    from ...services.text_lexicon import section_mark

    left, right = section_mark("bold")
    lines = [title, ""]
    for section in sections:
        lines.append(f"{left}{section['heading']}{right}")
        for text in section.get("paragraphs") or [""]:
            # 纯文本没有「首行缩进」可用，正文就是一行一段；前面挂「- 」会被预览
            # 当成项目符号（用户明确说过默认不要小圆点）。
            lines.append(text)
        for figure in section.get("images") or []:
            lines.append(_figure_note(figure))
        lines.append("")
    # 纯文本也是「交到用户手上的稿子」：素材里自带的出处节、模型顺手补的落款行
    # 一并兜掉，别让用户以为索引清单是正文的一部分。
    return _strip_source_notes("\n".join(lines).rstrip()) + "\n"


def render_xlsx(title: str, sections: list[DocSection], path: Path, meta: dict[str, Any]) -> None:
    """xlsx 产物：一张「内容」表，章节名单独成行并加粗，方便再加工。"""
    from ...services import xlsx_utils

    rows: list[list[Any]] = []
    for section in sections:
        rows.append([section["heading"]])
        for text in section.get("paragraphs") or [""]:
            rows.append([text])
        for figure in section.get("images") or []:
            rows.append([_figure_note(figure)])
    xlsx_utils.write_table(path, rows, headers=["内容"], sheet="报告", widths={"A": 90})
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("XLSX 保存失败")


def render_pptx(title: str, sections: list[DocSection], path: Path, meta: dict[str, Any]) -> None:
    """pptx 产物：封面 + 每节一页。一节超过六条要点时拆成续页。

    一页塞 12 条要点是做给自己看的——投影出来没人读得完。宁可多一页。
    每页条数从 `slide_lexicon.MAX_BULLETS_PER_SLIDE` 取：这条规矩在版式技能里也写着，
    两处写死两个数字，迟早一边改了另一边没改。
    """
    from ...services import pptx_utils
    from ...services.slide_lexicon import MAX_BULLETS_PER_SLIDE

    pages: list[dict[str, Any]] = [{"title": title, "subtitle": meta.get("source_names") or ""}]
    for section in sections:
        lines = [text for text in (section.get("paragraphs") or []) if text]
        lines.extend(_figure_note(figure) for figure in section.get("images") or [])
        if not lines:
            pages.append({"title": section["heading"], "bullets": []})
            continue
        chunk = MAX_BULLETS_PER_SLIDE
        for start in range(0, len(lines), chunk):
            heading = section["heading"] if start == 0 else f"{section['heading']}（续）"
            pages.append({"title": heading, "bullets": lines[start : start + chunk]})
    pptx_utils.write_deck(path, pages, title=title)
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("PPTX 保存失败")


def render_pdf(
    title: str,
    sections: list[DocSection],
    path: Path,
    meta: dict[str, Any],
    subtitle: str = "",
) -> None:
    """pdf 产物：走 pdf_utils 的统一版式（中文字体、页码、转义都在那一层处理）。"""
    from ...services import pdf_utils

    blocks: list[dict[str, Any]] = []
    for section in sections:
        blocks.append({"type": "h1", "text": section["heading"]})
        for text in section.get("paragraphs") or [""]:
            blocks.append({"type": "p", "text": text})
        for figure in section.get("images") or []:
            # PDF 版式不走图片解码，给一行图注占位，图文对照章节至少不是空的
            blocks.append({"type": "bullet", "text": _figure_note(figure)})
    # 副标题显式传进去：docx 那边也是分开传的，两边要显示同一行字
    pdf_utils.make_pdf(
        path, title=title, blocks=blocks, subtitle=subtitle, footer_text="Office Agent 生成"
    )
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("PDF 保存失败")


@tool(
    "doc.generate_report",
    "根据会话素材与模板生成报告文件（weekly/meeting/summary），登记产物并返回路径。"
    f"format 支持 {describe_output_formats()}，缺省 {DEFAULT_OUTPUT_FORMAT}；"
    "用户指定过格式时按用户格式输出，没指定就别自己换。"
    "**正文用 body 传**：把你写好的整篇内容按 Markdown 交进来——`## 一节` 是小节（自动编号一、二、三），"
    "`### 一小节` 是下级，`| 表头 |` 加一行 `|---|---|` 就是表格，`> ` 是引用，`**加粗**` 会保留。"
    "`- ` 开头的行会排成正文段落（中文稿不带项目符号，靠空两格分句）；"
    "`1. ` 开头的行把序号写进行首。给了 body 就照它的结构排版（标题层级、表格都如实还原）。"
    "标题里已经写了「2.1」这类序号也没关系：会按 doc_type 那套编号重排，全篇只用一套。"
    "不给 body 时按素材自己的小节成文：素材写「一、退款率复盘」就是「一、退款率复盘」，"
    "素材没写的节不出现；连小节标题都没有才用最常见的周报分节（摘要/进展/数据/风险/下周计划）。"
    "结构由这一次的素材决定，不要每篇都套同一套。"
    "title 从内容里起（「退款率复盘」而不是「数据分析报告」），空着会取素材首行标题或素材名。"
    "subtitle 是标题下面那行小字（如「登录模块联调 · 结论先行」），空着就不显示。"
    "layout 选版式：report（默认，就是大标题居中、小节标题左起分档、正文空两格那种）/ "
    "gongwen（公文）/ compact（紧凑：排版规则和默认一样，只是字更小、行更紧、页边距更窄，"
    "一页能装更多，资料和说明书才用）。"
    "用户没提「紧凑 / 扁平 / 密排」就用默认的，别主动换。"
    "doc_type 是文档类型（周报 / 会议纪要 / 技术方案 / 论文 / 公文 / 合同…），只用来挑标题编号："
    "周报是「一、（一）1.」，论文与技术方案是「1. / 1.1 / 1.1.1」，合同是「第一条」，"
    "纪要和手册不编号。空着就从标题里认（标题写着「周报」就按周报排）。"
    "line_spacing 单独改正文行距：单倍 / 1.15 / 1.5（默认）/ 双倍 / 固定值28磅，空着跟版式走。"
    "用户在输入区「文档格式」里点过字体/字号/字型/行距/首行缩进/对齐的，那几项已经自动生效，"
    "不用再靠 layout 或 line_spacing 去猜——他点的优先。"
    "facts 填 doc.analyze_material 返回的结构数据：份数/段数/字数/图片/表格/图注会写进「关键数据」，"
    "缺了就只能按正文猜。"
    "summary 模板可直接用 outline 传入自己写的摘要与要点（读过全文才写得准）："
    'outline={"摘要": "两句话讲清这是什么文档、整体写了什么", '
    '"要点": ["每条一句话，抓落点而不是抄原句", "按小节/图片分组列，3-5 条"]}；'
    "不给则按素材结构自动抽取。源文档里的照片会随「图文对照」章节一起搬进产品文档",
    risk="high",
    # 只往产物目录写一份新文件，不会动已有文件——和「删 / 覆盖」不是一个门槛。
    effect=lambda _args: EFFECT_OUTPUT,
)
def generate_report(
    ctx: ToolContext,
    title: str = "",
    template: str = "weekly",
    files: list[str] | None = None,
    format: str = "",
    facts: dict[str, Any] | None = None,
    outline: dict[str, Any] | None = None,
    body: str = "",
    subtitle: str = "",
    layout: str = "",
    line_spacing: str = "",
    doc_type: str = "",
) -> dict[str, Any]:
    custom_templates = _load_custom_templates(ctx.settings.templates_path)
    custom = custom_templates.get(template)
    # 入参优先；没给就用本轮脚本体检的结果（mock 主链路就是这么传的）
    facts = facts or (ctx.material_facts or None)
    if template not in TEMPLATES and custom is None:
        template = "weekly"
    today = now_iso()
    sources = ctx.material_sources
    # 标题默认带素材名：产物列表里「素材摘要（2026-10-26）」这种名字一天能撞出好几份。
    # 素材首行本身就是标题时优先用它——「退款率复盘」比「数据分析报告」更像人话。
    doc_title = (title or "").strip() or title_from_material(
        template, sources, ctx.material_text or ""
    )

    if not ctx.material_text:
        from .file import read_files

        read_files(ctx, files)

    # 只搬 docx 素材里的图：其它格式没有稳定的图片读取路径，宁可不放也不放错
    figures = _figures_from_sources(sources) if template == "summary" else []

    body = _strip_source_notes((body or "").strip())
    # 模型写的摘要里也可能粘一句「来源：…」：成稿不要再出现出处
    llm_text = _strip_source_notes(ctx.llm_text or "")
    subtitle = (subtitle or "").strip()
    # 没素材、模型也没自己写正文：给一个干净的空架子，并在标题下留一行说明。
    # 以前这里每节都写「素材里没有…」，一份周报五句「没有」，用户既不能交付也改不动。
    if not body and not (ctx.material_text or "").strip() and not sources:
        subtitle = subtitle or f"{TYPE_LABEL.get(template, '报告')}框架 · 待补素材"
    preset = layout.strip().lower() if layout else "report"
    line = (line_spacing or "").strip()
    # 编号方案：显式给了 doc_type 就用它，没给就从标题里认（「W46 周报」→ 周报）。
    # 只取「编号」这一项，不动字号与行距——类型判错一档，代价应该只是编号款式不对，
    # 不该让整份文档的排版跟着全歪。
    from ...services.doc_lexicon import guess_doc_type, resolve_numbering

    numbering = resolve_numbering((doc_type or "").strip() or guess_doc_type(doc_title))

    sections: list[DocSection]
    if custom is not None:
        base = _build_sections("weekly", ctx.material_text, sources, llm_text, facts)
        base_map = {section["heading"]: section["paragraphs"] for section in base}
        sections = [
            DocSection(
                heading=str(section.get("heading", "小节")),
                paragraphs=base_map.get(
                    _SOURCE_TO_HEADING.get(str(section.get("source", "")), ""), [""]
                ),
            )
            for section in (custom.get("sections") or [])
            if isinstance(section, dict)
        ]
    else:
        sections = _build_sections(template, ctx.material_text, sources, llm_text, facts, figures)
        sections = _apply_outline(sections, outline)

    output_format = (format or "").strip().lower()
    if output_format not in OUTPUT_FORMATS:
        output_format = DEFAULT_OUTPUT_FORMAT
    format_spec = OUTPUT_FORMATS[output_format]

    prefix = TYPE_LABEL.get(template, safe_filename(str((custom or {}).get("name") or "自定义")))
    date_part = week_label() if template == "weekly" else today[:10]
    # 顺序：素材名_类型_日期。素材名打头，产物列表里一眼就知道是哪份材料出的稿
    stem = safe_filename(
        "_".join(part for part in (sources_label(sources), prefix, date_part) if part)
    )
    path = ctx.storage.new_artifact_path(f"{stem}.{output_format}")
    meta = {
        "generated_at": today,
        "mode": ctx.mode,
        "source_names": "、".join(source["filename"] for source in sources),
    }

    if output_format == "docx":
        render_docx(
            doc_title,
            sections,
            path,
            meta,
            body=body,
            subtitle=subtitle,
            preset=preset,
            line=line,
            numbering=numbering,
            style=ctx.doc_style,
        )
    elif output_format == "pdf":
        render_pdf(doc_title, sections, path, meta, subtitle=subtitle)
    elif output_format == "xlsx":
        render_xlsx(doc_title, sections, path, meta)
    elif output_format == "pptx":
        render_pptx(doc_title, sections, path, meta)
    else:
        # 只剩纯文本一种：md 已经从产物格式里摘掉了（不再承诺做不到的事）
        ctx.storage.write_text(path, render_text(doc_title, sections, meta))

    extra: dict[str, Any] = {
        "template": template,
        "title": doc_title,
        "chars": count_chars(ctx.material_text),
        "sections": _body_headings(body) or [section["heading"] for section in sections],
        "sources": [source["filename"] for source in sources],
        "format": output_format,
        # 有脚本体检数据时，产物里的数字才可信；没有就只是按正文猜的骨架
        "analyzed": bool(facts),
    }
    # 预览策略：docx 落 HTML 预览；xlsx/pdf/pptx 落纯文本预览；其余文本格式直接读原文件
    if output_format == "docx":
        preview_path = ctx.storage.preview_path(path)
        ctx.storage.write_text(
            preview_path,
            render_preview_html(
                doc_title,
                sections,
                meta,
                body=body,
                subtitle=subtitle,
                preset=preset,
                numbering=numbering,
                style=ctx.doc_style,
            ),
        )
        extra["preview_path"] = str(preview_path)
    elif output_format in ("xlsx", "pdf", "pptx"):
        text_preview = path.with_suffix(".preview.txt")
        ctx.storage.write_text(text_preview, render_text(doc_title, sections, meta))
        extra["text_path"] = str(text_preview)

    sha = sha256_file(path)
    size = path.stat().st_size

    # 落地自检：产物正文里的数字，素材里到底有没有出处。
    # 模板抽取出来的数字当然都来自素材，正常情况下这里是空的；一旦非空，说明
    # 有内容是模型顺手写进 llm_text 的、或者模板自带了示例值——这两类都是会
    # 被用户当成真数据的编造。只报告不阻断：把「12000」写成「1.2 万」这种等价
    # 表述也会被抓出来，硬拦就会把正常交付打回。
    body_text = body or "\n".join(
        f"{section['heading']}\n" + "\n".join(section["paragraphs"]) for section in sections
    )
    unverified = unsupported_facts(body_text, sources)
    if unverified:
        extra["unverified_numbers"] = unverified

    artifact = Artifact(
        id=new_id("art"),
        thread_id=ctx.thread_id,
        run_id=ctx.run_id,
        type=format_spec["artifact_type"],
        filename=path.name,
        path=str(path),
        size=size,
        sha256=sha,
        content_type=format_spec["content_type"],
        created_at=today,
        extra=extra,
    )
    ctx.artifacts.add(artifact)
    ctx.register_artifact(artifact)

    summary = (
        f"已生成 {format_spec['label']}《{artifact.filename}》，"
        f"{len(sections)} 个章节，{size:,} 字节"
    )
    if unverified:
        places = "、".join(item["value"] for item in unverified[:5])
        summary += (
            f"；有 {len(unverified)} 处数字在素材里找不到出处（{places}），交付前要核实或删掉"
        )
    return {
        "artifact_id": artifact.id,
        "filename": artifact.filename,
        "path": str(path),
        "size": size,
        "sha256": sha,
        "template": template,
        "format": output_format,
        "sections": _body_headings(body) or [section["heading"] for section in sections],
        "source_count": len(sources),
        "unverified_numbers": unverified,
        "_summary": summary,
    }
