"""pptx_utils.py —— Agent 操作 .pptx 的通用函数库（读 + 生成）。

环境装不了 python-pptx（离线），所以这里直接写 OOXML：`.pptx` 本质是一个
zip 包，里面若干 XML part 用 rels 串起来。生成端只做「标题 + 要点」这一种
最稳的版式——版式越花，PowerPoint 报「需要修复」的概率越高。

生成出来的文件结构（缺一个 part PowerPoint 就会拒开）：

    [Content_Types].xml                    每个 part 的类型声明
    _rels/.rels                            → presentation
    ppt/presentation.xml                   幻灯片尺寸 + 页序
    ppt/_rels/presentation.xml.rels        → master / theme / 各页
    ppt/slideMasters/slideMaster1.xml      母版（含 clrMap）
    ppt/slideMasters/_rels/…rels           → layout / theme
    ppt/slideLayouts/slideLayout1.xml      空白版式
    ppt/slideLayouts/_rels/…rels           → master
    ppt/theme/theme1.xml                   配色 / 字体 / 效果
    ppt/slides/slideN.xml                  每一页
    ppt/slides/_rels/…rels                 → layout
    docProps/core.xml, docProps/app.xml    属性

读取端只取文字（`<a:t>`），按 `<p:sp>` 分组：一个形状一段。图片、表格、
SmartArt 不做解析，读不到就说读不到。

函数清单见 `__all__`；不确定签名就先 `import pptx_utils; print(pptx_utils.__all__)`。
"""

from __future__ import annotations

import io
import shutil
import zipfile
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

try:  # 脚本工作目录里 *_utils.py 是平铺复制的，没有包结构，只能绝对导入
    from .slide_lexicon import (
        FONT_SIZES,
        MAX_BULLETS_PER_SLIDE,
        SLIDE_SIZES,
    )
except ImportError:  # pragma: no cover - 沙箱里平铺运行时走这条
    from slide_lexicon import (  # type: ignore[no-redef]
        FONT_SIZES,
        MAX_BULLETS_PER_SLIDE,
        SLIDE_SIZES,
    )

__all__ = [
    "SLIDE_4_3",
    "SLIDE_16_9",
    "backup",
    "deck_text",
    "extract_slides",
    "make_deck",
    "read_report",
    "slide_records",
    "write_deck",
]

#: 幻灯片尺寸（EMU，1 英寸 = 914400 EMU）。默认 16:9。
#: 数字在 `slide_lexicon.SLIDE_SIZES` 里，这里只是给脚本留两个好记的名字。
SLIDE_16_9 = SLIDE_SIZES["16:9"]
SLIDE_4_3 = SLIDE_SIZES["4:3"]

_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"

_FONT = "Microsoft YaHei"
_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

#: 版面留白与标题区高度（EMU）。
_MARGIN_X = 838200  # 0.92 英寸
_TITLE_TOP = 457200
_TITLE_H = 900000
_GAP = 180000


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 读取


def _parse_xml(data: bytes) -> ET.Element:
    """解析上传来的 slide XML。

    这份字节来自用户上传的文件，不能直接当可信输入：
    OOXML 的 slide 里不该出现 DOCTYPE / ENTITY 声明，出现就是有人在做
    实体展开（billion laughs），先拒掉再解析。ElementTree 默认也不加载外部实体。
    """
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ValueError("PPTX 内部 XML 含实体声明，拒绝解析")
    return ET.fromstring(data)  # noqa: S314 - 已在上面拒绝实体声明


def _read_slide_texts(data: bytes) -> list[list[str]]:
    """从单个 slide 的 XML 里按形状取文字。

    按 `<p:sp>` 切而不是按 `<a:t>` 直接抓：一个形状里有多个 run（加粗片段、
    换行）时要拼成一段，否则「本周退款 47 单」会被拆成两条要点。
    """
    root = _parse_xml(data)
    blocks: list[list[str]] = []
    for shape in root.iter(f"{{{_NS_P}}}sp"):
        lines: list[str] = []
        for para in shape.iter(f"{{{_NS_A}}}p"):
            runs = [node.text or "" for node in para.iter(f"{{{_NS_A}}}t")]
            line = "".join(runs).strip()
            if line:
                lines.append(line)
        if lines:
            blocks.append(lines)
    return blocks


#: 读取端接受的三种来源：磁盘路径、Path、内存字节。
#: 内存字节这条是给上传解析用的——解析器手上是 `UploadInfo.data`，
#: 为读一份文件先落盘再删，纯属自找麻烦。
Source = str | Path | bytes


def _open_deck(source: Source) -> zipfile.ZipFile:
    if isinstance(source, (bytes, bytearray)):
        return zipfile.ZipFile(io.BytesIO(source))
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    return zipfile.ZipFile(path)


def _label(source: Source) -> str:
    """报告里的 path 字段：内存来源没有路径，给个能看懂的占位。"""
    return "<内存中的 pptx>" if isinstance(source, (bytes, bytearray)) else str(source)


def extract_slides(source: Source) -> list[dict[str, Any]]:
    """按页读出幻灯片：`[{index, title, bullets}]`。

    第一段当标题（PPT 里标题框总是第一个形状），其余段落当要点。
    页序按 slideN.xml 的数字排，不按 zip 里的顺序——zip 顺序是按写入来的。
    """
    pages: list[tuple[int, list[list[str]]]] = []
    with _open_deck(source) as archive:
        for name in archive.namelist():
            if not (name.startswith("ppt/slides/slide") and name.endswith(".xml")):
                continue
            digits = "".join(ch for ch in Path(name).stem if ch.isdigit())
            index = int(digits) if digits else len(pages) + 1
            pages.append((index, _read_slide_texts(archive.read(name))))
    pages.sort(key=lambda item: item[0])

    slides: list[dict[str, Any]] = []
    for index, blocks in pages:
        flat = [line for block in blocks for line in block]
        title = blocks[0][0] if blocks and blocks[0] else ""
        bullets = [line for line in flat if line != title]
        slides.append({"index": index, "title": title, "bullets": bullets, "shapes": len(blocks)})
    return slides


def deck_text(source: Source) -> str:
    """整份演示文稿拼成纯文本（一页一段，`【第 N 页】` 打头）。"""
    parts: list[str] = []
    for page in extract_slides(source):
        head = f"【第 {page['index']} 页】{page['title']}".rstrip()
        parts.append("\n".join([head, *page["bullets"]]))
    return "\n\n".join(parts)


def read_report(source: Source) -> dict[str, Any]:
    """体检：页数、每页标题与字数、有没有读不到的东西。

    和 docx_utils.read_report 同一套返回口径（`ok` / `kind` / `pages` 等），
    这样 Agent 换格式时不用改调用方式。
    """
    slides = extract_slides(source)
    chars = sum(len(page["title"]) + sum(len(line) for line in page["bullets"]) for page in slides)
    empty = [page["index"] for page in slides if not page["title"] and not page["bullets"]]
    notes: list[str] = []
    if empty:
        notes.append(f"第 {', '.join(map(str, empty))} 页没有可提取的文字（可能是纯图片页）")
    if not slides:
        notes.append("没有找到幻灯片（文件可能不是 pptx，或结构不完整）")
    return {
        "ok": bool(slides),
        "kind": "pptx",
        "path": _label(source),
        "pages": len(slides),
        "chars": chars,
        "titles": [page["title"] for page in slides],
        "empty_pages": empty,
        "notes": notes,
        "slides": slides,
    }


def slide_records(source: Source) -> list[dict[str, Any]]:
    """压平成记录：`[{page, shape, order, text}]`，便于排序/筛选后再写回。"""
    records: list[dict[str, Any]] = []
    for page in extract_slides(source):
        text_lines = ([page["title"]] if page["title"] else []) + page["bullets"]
        for order, text in enumerate(text_lines):
            records.append(
                {
                    "page": page["index"],
                    "shape": 0 if order == 0 else 1,
                    "order": order,
                    "text": text,
                }
            )
    return records


def backup(path: str | Path, suffix: str = ".bak") -> Path:
    """原文件旁边留一份副本（改写前先备份，和其它 utils 一样）。"""
    path = Path(path)
    target = path.with_name(path.stem + suffix + path.suffix)
    shutil.copy2(path, target)
    return target


# ---------------------------------------------------------------- 生成

_PRESENTATION = """{decl}<p:presentation xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}" saveSubsetFonts="1">
<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
<p:sldIdLst>{slide_ids}</p:sldIdLst>
<p:sldSz cx="{cx}" cy="{cy}"/>
<p:notesSz cx="6858000" cy="9144000"/>
<p:defaultTextStyle><a:defPPr><a:defRPr lang="zh-CN"/></a:defPPr></p:defaultTextStyle>
</p:presentation>
"""

_PRESENTATION_RELS = """{decl}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
{slide_rels}</Relationships>
"""

_SLIDE_MASTER = """{decl}<p:sldMaster xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}">
<p:cSld>
<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>
<p:spTree>{tree_head}</p:spTree>
</p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
<p:txStyles>
<p:titleStyle><a:lvl1pPr algn="l"><a:defRPr sz="4000" b="1"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mj-lt"/><a:ea typeface="+mj-ea"/></a:defRPr></a:lvl1pPr></p:titleStyle>
<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2000"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/></a:defRPr></a:lvl1pPr></p:bodyStyle>
<p:otherStyle><a:lvl1pPr><a:defRPr lang="zh-CN"/></a:lvl1pPr></p:otherStyle>
</p:txStyles>
</p:sldMaster>
"""

_SLIDE_LAYOUT = """{decl}<p:sldLayout xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}" type="blank" preserve="1">
<p:cSld name="空白"><p:spTree>{tree_head}</p:spTree></p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>
"""

_THEME = """{decl}<a:theme xmlns:a="{a}" name="OA">
<a:themeElements>
<a:clrScheme name="OA">
<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="1F2933"/></a:dk2>
<a:lt2><a:srgbClr val="F3F4F6"/></a:lt2>
<a:accent1><a:srgbClr val="2563EB"/></a:accent1>
<a:accent2><a:srgbClr val="0F766E"/></a:accent2>
<a:accent3><a:srgbClr val="B45309"/></a:accent3>
<a:accent4><a:srgbClr val="7C3AED"/></a:accent4>
<a:accent5><a:srgbClr val="BE123C"/></a:accent5>
<a:accent6><a:srgbClr val="475569"/></a:accent6>
<a:hlink><a:srgbClr val="0563C1"/></a:hlink>
<a:folHlink><a:srgbClr val="954F72"/></a:folHlink>
</a:clrScheme>
<a:fontScheme name="OA">
<a:majorFont><a:latin typeface="{font}"/><a:ea typeface="{font}"/><a:cs typeface=""/></a:majorFont>
<a:minorFont><a:latin typeface="{font}"/><a:ea typeface="{font}"/><a:cs typeface=""/></a:minorFont>
</a:fontScheme>
<a:fmtScheme name="OA">
<a:fillStyleLst>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
</a:fillStyleLst>
<a:lnStyleLst>
<a:ln w="9525" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>
<a:ln w="25400" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>
<a:ln w="38100" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>
</a:lnStyleLst>
<a:effectStyleLst>
<a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle>
</a:effectStyleLst>
<a:bgFillStyleLst>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
</a:bgFillStyleLst>
</a:fmtScheme>
</a:themeElements>
<a:objectDefaults/>
<a:extraClrSchemeLst/>
</a:theme>
"""

_TREE_HEAD = (
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
)

_SLIDE = """{decl}<p:sld xmlns:a="{a}" xmlns:r="{r}" xmlns:p="{p}">
<p:cSld><p:spTree>{tree_head}{shapes}</p:spTree></p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
"""

_SHAPE = """<p:sp>
<p:nvSpPr><p:cNvPr id="{sid}" name="Shape{sid}"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>
<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:noAutofit/></a:bodyPr>
<a:lstStyle/>{paragraphs}</p:txBody>
</p:sp>
"""

_PARAGRAPH = """<a:p><a:pPr marL="{mar_l}" indent="{indent}" algn="l">
<a:lnSpc><a:spcPct val="{line_pct}"/></a:lnSpc>
<a:spcBef><a:spcPts val="{space_before}"/></a:spcBef>{bullet}</a:pPr>
<a:r><a:rPr lang="zh-CN" sz="{size}" b="{bold}" dirty="0">
<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>
<a:latin typeface="{font}"/><a:ea typeface="{font}"/></a:rPr><a:t>{text}</a:t></a:r></a:p>
"""

_CONTENT_TYPES = """{decl}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
{slide_overrides}<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

_ROOT_RELS = """{decl}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

_MASTER_RELS = """{decl}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
"""

_LAYOUT_RELS = """{decl}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>
"""

_SLIDE_RELS = """{decl}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>
"""

_CORE = """{decl}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>{title}</dc:title>
<dc:creator>OA Agent</dc:creator>
<cp:lastModifiedBy>OA Agent</cp:lastModifiedBy>
<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>
<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>
</cp:coreProperties>
"""

_APP = """{decl}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
<Application>OA Agent</Application>
<Slides>{count}</Slides>
</Properties>
"""


def _shape_xml(
    sid: int,
    text_lines: Sequence[str],
    *,
    x: int,
    y: int,
    cx: int,
    cy: int,
    size: int,
    bold: bool,
    color: str,
    bullet: bool,
    anchor: str = "t",
    line_pct: int = 100000,
    space_before: int = 600,
) -> str:
    """一个文本框。`anchor` 决定文字贴框顶还是框底——

    标题框用 `b`（底部对齐）：字号是估的，框高也是估的，底部对齐时标题永远
    落在正文上方固定位置，不会因为字号变大把中间撑出一道空白。
    """
    paragraphs: list[str] = []
    for line in text_lines:
        paragraphs.append(
            _PARAGRAPH.format(
                mar_l=285750 if bullet else 0,
                indent=-285750 if bullet else 0,
                bullet='<a:buFont typeface="Arial"/><a:buChar char="•"/>'
                if bullet
                else "<a:buNone/>",
                line_pct=line_pct,
                space_before=space_before,
                size=size,
                bold="1" if bold else "0",
                color=color,
                font=_FONT,
                text=escape(line),
            )
        )
    if not paragraphs:  # 空文本框：PowerPoint 允许，但补一个空段更稳
        paragraphs.append(
            _PARAGRAPH.format(
                mar_l=0,
                indent=0,
                bullet="<a:buNone/>",
                line_pct=line_pct,
                space_before=0,
                size=size,
                bold="0",
                color=color,
                font=_FONT,
                text="",
            )
        )
    return _SHAPE.format(
        sid=sid, x=x, y=y, cx=cx, cy=cy, anchor=anchor, paragraphs="".join(paragraphs)
    )


def _slide_xml(
    width: int, height: int, title: str, bullets: Sequence[str], *, subtitle: str = ""
) -> str:
    """一页 = 标题框 + 正文框。

    没有要点的页（封面 / 分节）不参与「算出来居中」：标题固定在页面上四分之一处，
    副标题紧跟其下。这样副标题长短不影响标题位置，多份文件并排看标题都在同一条线上。
    """
    shapes: list[str] = []
    # 字号从 slide_lexicon 取（pt × 100 = XML 的 sz 值），不在这里写 3600/2000：
    # 「标题多大」是版式问题，改一次要三处一起改。封面页没有要点，用更大的一档。
    title_pt = int((FONT_SIZES["cover_title"] if not bullets else FONT_SIZES["title"]) * 100)
    body_pt = int(FONT_SIZES["body"] * 100)
    if bullets:
        title_top = _TITLE_TOP
        body_top = title_top + _TITLE_H + _GAP
    else:
        # 封面不精确居中：标题落在页面四分之一处，视觉上比"算出来居中"更稳，
        # 而且副标题长短不影响标题位置。
        title_top = height // 4
        body_top = title_top + _TITLE_H + _GAP
    shapes.append(
        _shape_xml(
            2,
            [title],
            x=_MARGIN_X,
            y=title_top,
            cx=width - _MARGIN_X * 2,
            cy=_TITLE_H,
            size=title_pt,
            bold=True,
            color="1F2933",
            bullet=False,
            anchor="b",
        )
    )
    if bullets:
        shapes.append(
            _shape_xml(
                3,
                list(bullets),
                x=_MARGIN_X,
                y=body_top,
                cx=width - _MARGIN_X * 2,
                cy=max(height - body_top - 457200, 914400),
                size=body_pt,
                bold=False,
                color="374151",
                bullet=True,
                anchor="t",
            )
        )
    elif subtitle:
        shapes.append(
            _shape_xml(
                3,
                [subtitle],
                x=_MARGIN_X,
                y=body_top,
                cx=width - _MARGIN_X * 2,
                cy=457200,
                size=body_pt,
                bold=False,
                color="6B7280",
                bullet=False,
                anchor="t",
            )
        )
    return _SLIDE.format(
        decl=_XML_DECL,
        a=_NS_A,
        r=_NS_R,
        p=_NS_P,
        tree_head=_TREE_HEAD,
        shapes="".join(shapes),
    )


def write_deck(
    path: str | Path,
    slides: Iterable[dict[str, Any]],
    *,
    size: tuple[int, int] = SLIDE_16_9,
    title: str = "",
) -> Path:
    """按 `[{title, bullets}]` 写一份 .pptx。

    `slides` 里每项一个 dict：`title` 是页标题，`bullets` 是要点列表
    （空列表 = 分节页，只显示标题）。返回写好的路径。
    """
    path = Path(path)
    width, height = size
    drafted = [
        {
            "title": str(page.get("title") or "").strip(),
            "bullets": [
                str(item).strip() for item in (page.get("bullets") or []) if str(item).strip()
            ],
            "subtitle": str(page.get("subtitle") or "").strip(),
        }
        for page in slides
    ]
    # 一页超过六条要点就拆页：投影出来十二条没人读得完。宁可多一页，
    # 也别把内容截掉——截掉的是别人的话，拆页只是换个位置。
    pages: list[dict[str, Any]] = []
    for page in drafted:
        bullets = page["bullets"]
        if len(bullets) <= MAX_BULLETS_PER_SLIDE:
            pages.append(page)
            continue
        for start in range(0, len(bullets), MAX_BULLETS_PER_SLIDE):
            title = page["title"] if start == 0 else f"{page['title']}（续）"
            pages.append(
                {
                    "title": title,
                    "bullets": bullets[start : start + MAX_BULLETS_PER_SLIDE],
                    "subtitle": page["subtitle"] if start == 0 else "",
                }
            )
    if not pages:
        raise ValueError("至少要有一页")

    path.parent.mkdir(parents=True, exist_ok=True)
    count = len(pages)
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>\n'
        for index in range(1, count + 1)
    )
    slide_ids = "".join(
        f'<p:sldId id="{255 + index}" r:id="rId{2 + index}"/>' for index in range(1, count + 1)
    )
    slide_rels = "".join(
        f'<Relationship Id="rId{2 + index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        f'Target="slides/slide{index}.xml"/>\n'
        for index in range(1, count + 1)
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        # [Content_Types].xml 必须是包里第一个条目，某些阅读器按顺序找
        archive.writestr(
            "[Content_Types].xml",
            _CONTENT_TYPES.format(decl=_XML_DECL, slide_overrides=slide_overrides),
        )
        archive.writestr("_rels/.rels", _ROOT_RELS.format(decl=_XML_DECL))
        archive.writestr(
            "ppt/presentation.xml",
            _PRESENTATION.format(
                decl=_XML_DECL, a=_NS_A, r=_NS_R, p=_NS_P, slide_ids=slide_ids, cx=width, cy=height
            ),
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            _PRESENTATION_RELS.format(decl=_XML_DECL, slide_rels=slide_rels),
        )
        archive.writestr(
            "ppt/slideMasters/slideMaster1.xml",
            _SLIDE_MASTER.format(decl=_XML_DECL, a=_NS_A, r=_NS_R, p=_NS_P, tree_head=_TREE_HEAD),
        )
        archive.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels", _MASTER_RELS.format(decl=_XML_DECL)
        )
        archive.writestr(
            "ppt/slideLayouts/slideLayout1.xml",
            _SLIDE_LAYOUT.format(decl=_XML_DECL, a=_NS_A, r=_NS_R, p=_NS_P, tree_head=_TREE_HEAD),
        )
        archive.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels", _LAYOUT_RELS.format(decl=_XML_DECL)
        )
        archive.writestr("ppt/theme/theme1.xml", _THEME.format(decl=_XML_DECL, a=_NS_A, font=_FONT))
        for index, page in enumerate(pages, start=1):
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                _slide_xml(
                    width, height, page["title"], page["bullets"], subtitle=page["subtitle"]
                ),
            )
            archive.writestr(
                f"ppt/slides/_rels/slide{index}.xml.rels", _SLIDE_RELS.format(decl=_XML_DECL)
            )
        archive.writestr(
            "docProps/core.xml",
            _CORE.format(
                decl=_XML_DECL, title=escape(title or pages[0]["title"] or "演示文稿"), stamp=_now()
            ),
        )
        archive.writestr("docProps/app.xml", _APP.format(decl=_XML_DECL, count=count))
    return path


#: `make_deck` 与 `write_deck` 同义——脚本里两种写法都常见，留个别名免得模型猜错。
make_deck = write_deck
