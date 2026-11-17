"""文件解析实现：docx / xlsx / pptx / pdf / csv / txt / md -> 纯文本。

支持哪些格式不在这里决定：白名单来自 `domain/formats.py`，这里只负责
「表里有的都能解析」。失败统一抛 ParseFailure（服务层转 AppError(FILE_PARSE_ERROR)），
不抛裸异常。
"""

from __future__ import annotations

import codecs
import csv
import html
import io
import re
import zipfile
from typing import Any

from ..core.security import BLOCKED_UPLOAD_EXTS, UploadLimits, check_zip_bomb
from ..domain.enums import ErrorCode
from ..domain.formats import UPLOAD_EXTS
from ..domain.media import KIND_TRANSCRIPT, media_spec


class ParseFailure(Exception):
    def __init__(self, message: str, code: ErrorCode = ErrorCode.FILE_PARSE_ERROR):
        super().__init__(message)
        self.message = message
        self.code = code


def _sniff_utf16(data: bytes) -> str:
    """没有 BOM 的 UTF-16 猜测：ASCII 部分会留下成片的零字节。

    这是最可靠的指纹 —— 中文内容里同样有零字节，但只会出现在一半的字节位上，
    而且比例远低于「全英文的时间轴 + 序号」那一半。
    """
    head = data[:4096]
    pairs = len(head) // 2
    if pairs < 4:
        return ""
    zeros_even = head[0::2].count(b"\x00") / pairs
    zeros_odd = head[1::2].count(b"\x00") / pairs
    if zeros_odd >= 0.3 and zeros_even <= 0.05:
        return "utf-16-le"
    if zeros_even >= 0.3 and zeros_odd <= 0.05:
        return "utf-16-be"
    return ""


def _decode_text(data: bytes) -> str:
    # BOM 必须先认：UTF-32 的 BOM 以 UTF-16 LE 的 BOM 开头，顺序反了会解错
    for bom, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                break

    # UTF-16 不认出来就会落到 gb18030 —— 那个编码几乎能「成功」解任何字节，
    # 于是 Windows 导出的字幕静默变成满屏怪字，用户还以为识别坏了。
    guessed = _sniff_utf16(data)
    if guessed:
        try:
            return data.decode(guessed)
        except UnicodeDecodeError:
            pass

    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseFailure("文本编码无法识别，请另存为 UTF-8 后重试")


def _guard_zip(data: bytes, limits: UploadLimits | None = None) -> None:
    """OOXML 解析前先查解压规模，挡住压缩炸弹。"""
    try:
        check_zip_bomb(data, limits=limits)
    except ValueError as exc:
        raise ParseFailure(f"文件结构异常：{exc}") from exc


def _parse_docx(data: bytes, limits: UploadLimits | None = None) -> str:
    _guard_zip(data, limits)
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise ParseFailure("docx 解析依赖 python-docx 未安装") from exc
    try:
        document = Document(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ParseFailure(f"DOCX 文件损坏或格式不正确：{exc}") from exc
    except Exception as exc:
        raise ParseFailure(f"DOCX 解析失败：{type(exc).__name__}") from exc
    parts: list[str] = []
    for para in document.paragraphs:
        text = (para.text or "").strip()
        if text:
            parts.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            line = " | ".join(cell for cell in cells if cell)
            if line:
                parts.append(line)
    if not parts:
        raise ParseFailure("DOCX 中没有可提取的文字（可能是纯图片文档）")
    return "\n".join(parts)


def _parse_pdf(data: bytes, limits: UploadLimits | None = None) -> str:
    limits = limits or UploadLimits()
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ParseFailure("PDF 解析依赖 pypdf 未安装，请先安装 pypdf") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ParseFailure(f"PDF 解析失败：{exc}") from exc
    # 页数上限：超大 PDF 逐页抽取文本会长时间占用 CPU
    if len(reader.pages) > limits.max_pdf_pages:
        raise ParseFailure(
            f"PDF 共 {len(reader.pages)} 页，超过 {limits.max_pdf_pages} 页上限，请拆分后再上传"
        )
    try:
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise ParseFailure(f"PDF 文本抽取失败：{type(exc).__name__}") from exc
    text = "\n".join(page for page in pages if page)
    if not text.strip():
        raise ParseFailure("PDF 中没有可提取的文字（可能是扫描件，需 OCR）")
    return text


def _parse_xlsx(data: bytes, limits: UploadLimits | None = None) -> str:
    """xlsx 解析为「表头 + 行摘要」文本（最多 200 行，避免超大文件拖垮提示词）。"""
    _guard_zip(data, limits)
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise ParseFailure("xlsx 解析依赖 openpyxl 未安装") from exc
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ParseFailure(f"XLSX 解析失败：{exc}") from exc
    try:
        sheet = workbook.worksheets[0]
        rows: list[list[str]] = []
        for index, row in enumerate(sheet.iter_rows(values_only=True)):
            if index >= 201:
                break
            cells = ["" if value is None else str(value).strip() for value in row]
            if any(cells):
                rows.append(cells)
    finally:
        workbook.close()
    if not rows:
        raise ParseFailure("XLSX 中没有可用数据")
    header = rows[0]
    lines = ["【工作表】" + sheet.title, "【表头】" + " | ".join(header)]
    for index, row in enumerate(rows[1:], start=1):
        pairs = [
            f"{header[column] if column < len(header) and header[column] else f'列{column + 1}'}={value}"
            for column, value in enumerate(row)
            if value
        ]
        if pairs:
            lines.append(f"第{index}行：" + "；".join(pairs))
    if sheet.max_row and sheet.max_row > 201:
        lines.append(f"（已截断，原表共 {sheet.max_row} 行）")
    return "\n".join(lines)


def _parse_csv(data: bytes) -> str:
    text = _decode_text(data)
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise ParseFailure(f"CSV 解析失败：{exc}") from exc
    lines = [" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows]
    lines = [line for line in lines if line]
    if not lines:
        raise ParseFailure("CSV 内容为空")
    return "\n".join(lines)


def _parse_pptx(data: bytes, limits: UploadLimits | None = None) -> str:
    """pptx 解析：一页一段，标题 + 要点。

    读取端只取文字（`<a:t>`），图片、表格、SmartArt 读不到——所以「这一页
    有图没字」必须说出来，而不是当成空页糊过去。
    """
    _guard_zip(data, limits)
    from ..services import pptx_utils

    try:
        report = pptx_utils.read_report(data)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ParseFailure(f"PPTX 文件损坏或格式不正确：{exc}") from exc
    except Exception as exc:  # pragma: no cover - XML 结构异常
        raise ParseFailure(f"PPTX 解析失败：{type(exc).__name__}") from exc
    if not report["pages"]:
        raise ParseFailure("PPTX 中没有找到幻灯片，可能不是演示文稿")
    lines = [f"【共 {report['pages']} 页】"]
    for page in report["slides"]:
        head = f"【第 {page['index']} 页】{page['title']}".rstrip()
        lines.append(head)
        lines.extend(page["bullets"])
    if report["notes"]:
        lines.append("（" + "；".join(report["notes"]) + "）")
    if report["chars"] == 0:
        raise ParseFailure("PPTX 中没有可提取的文字（可能是纯图片幻灯片）")
    return "\n".join(lines)


#: VTT 的说话人标记：`<v 张伟>` / `<v.loud 李娜>`（点号后面是样式类，不属于名字）
_VOICE_TAG = re.compile(r"<v(?:\.[\w-]+)*\s+([^>]+)>")

#: 时间轴前缀，有的导出会写成「00:00:01.000 张伟：…」
_TIMELINE_PREFIX = re.compile(r"^\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?\s*")


def _join_subtitle_lines(parts: list[str]) -> str:
    """同一条字幕被折成的几行拼回去。

    中文之间**不补空格**：折行是屏幕宽度造成的，不是词间停顿，「我们下周一再对一次
    时间定在下午三点」才是他当时说的那一句；只有英文单词被切开时才补空格。
    """

    def ascii_word(char: str) -> bool:
        return char.isascii() and char.isalnum()

    out = ""
    for part in parts:
        if not out:
            out = part
        elif ascii_word(out[-1]) and ascii_word(part[0]):
            out += " " + part
        else:
            out += part
    return out


def _parse_transcript(data: bytes) -> str:
    """会议转写稿（.srt / .vtt）→ 纯文本。

    只去「播放器用得上、模型用不上」的东西：序号、时间轴、WEBVTT 头、NOTE 段、
    行内标签。句子按出现顺序保留，一句一行 —— 会议里「谁在什么时候说了什么」
    靠的是先后顺序，合并成一大段反而难引用。

    **按字幕块合并，而不是逐行输出**：一条字幕因为屏幕宽度常被拆成两行
    （「我们下周一再对一次」/「时间定在下午三点」），逐行输出会被模型当成两句
    独立的话，还可能把半句当结论引用；合成一段才是说话人当时说的那一句。

    说话人的 `&lt;v 张伟&gt;` 标记要**保留成「张伟：」**：谁说的对纪要是关键信息，
    当成标签剥掉就再也找不回来。
    """
    text = _decode_text(data)
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    # 当前字幕块里攒下的台词行
    block: list[str] = []
    # VTT 的元数据（Kind: / Language: / X-TIMESTAMP-MAP）只在第一个时间轴之前出现，
    # 之后同样格式的行就是台词了，所以按「见过第一条时间轴没有」来区分
    in_header = True
    # NOTE / STYLE / REGION 是**块**，可以跨好几行：只跳过开头那行，第二行就会
    # 被当成谁说的话混进纪要
    in_metadata_block = False
    # 上一条 SRT 段序号：文件被截断在「2」这种残片上时，靠它判断这是序号不是台词
    last_index = 0

    def flush(*, index_follows: bool = False, eof: bool = False) -> None:
        """收尾一条字幕。

        index_follows：下一行就是时间轴 —— 那这一块末尾的纯数字是 SRT 段序号。
        紧凑导出的 srt 连空行都没有，序号会直接粘在上一条台词后面；只有「紧跟
        时间轴」的数字才删，单独一条「2026」这样的台词不会被吞掉。
        """
        nonlocal last_index
        if not block:
            return
        if index_follows and block[-1].isdigit():
            last_index = int(block.pop())
        elif (
            eof
            and len(block) == 1
            and block[0].isdigit()
            # 文件在序号处被截断（有「2」却没有时间轴和台词）。只有接得上序号
            # 才当残片丢掉 —— 真有一条台词就写「2026」，不会被吞
            and last_index
            and int(block[0]) == last_index + 1
        ):
            block.clear()
            return
        if not block:
            return
        sentence = _join_subtitle_lines(block).strip()
        block.clear()
        # 相邻两条字幕完全一样（有的工具会把上一句重复导出一次）只留一条
        if sentence and (not lines or lines[-1] != sentence):
            lines.append(sentence)

    # 末尾的空行要先去掉：否则它会先触发一次普通收尾，最后那块「序号残片」
    # 就等不到 eof 那一轮判断，直接当台词输出了
    chunks = normalised.split("\n")
    while chunks and not chunks[-1].strip():
        chunks.pop()

    for raw in chunks:
        line = raw.strip()
        if not line:
            flush()
            in_metadata_block = False
            continue
        if "-->" in line:
            flush(index_follows=True)
            in_header = False
            in_metadata_block = False
            continue
        if in_metadata_block:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if re.match(r"^(NOTE|STYLE|REGION)\b", line, re.IGNORECASE):
            flush()
            in_metadata_block = True
            continue
        if in_header and re.match(r"^(Kind|Language|X-TIMESTAMP-MAP)\s*:", line, re.IGNORECASE):
            continue
        line = _TIMELINE_PREFIX.sub("", line)
        # 先还原实体再剥标签：部分工具会把 <i> 转义成 &lt;i&gt;，顺序反了标签
        # 就会原样留在正文里，被当成「会议内容」引用出去
        line = html.unescape(line)
        # VTT 的 <v 张伟> 是说话人，不是样式：转成「张伟：」留在正文里
        voice = _VOICE_TAG.search(line)
        line = re.sub(r"<[^>]+>", "", line).strip()
        if voice and line:
            speaker = voice.group(1).strip()
            # 台词里已经带了「张伟：」就别再叠一层
            if speaker and not line.startswith(f"{speaker}："):
                line = f"{speaker}：{line}"
        if line:
            block.append(line)
    flush(eof=True)
    if not lines:
        raise ParseFailure("转写稿里没有台词（只有时间轴或序号）")
    return "\n".join(lines)


#: 旧版 Office / WPS 的复合文档（OLE2）：内容是二进制，纯 Python 读不出正文。
#: 不拒收（用户手里八成就是这种文件），但要把话说明白——告诉用户另存一份就行，
#: 而不是丢一句「不支持」让人自己猜。
_LEGACY_OFFICE_EXTS = {
    ".doc": ("旧版 Word", ".docx"),
    ".xls": ("旧版 Excel", ".xlsx"),
    ".ppt": ("旧版 PPT", ".pptx"),
    ".wps": ("WPS 文字", ".docx"),
    ".et": ("WPS 表格", ".xlsx"),
    ".dps": ("WPS 演示", ".pptx"),
    ".rtf": ("RTF", ".docx"),
}

_ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".ofd", ".epub"}


def _looks_binary(data: bytes) -> bool:
    """粗判二进制：含零字节，或控制字符成片出现。

    文本里本来就有 \\t \\n \\r，所以只数其余控制字符；阈值 5% 足够把
    「GB18030 能解任何字节」这类假成功挡在门外（`_decode_text` 最后会落到
    latin-1，什么字节都能「解」成字符串）。
    """
    head = data[:8192]
    if not head:
        return False
    if b"\x00" in head:
        return True
    control = sum(1 for byte in head if byte < 0x09 or 0x0E <= byte < 0x20)
    return control / len(head) > 0.05


def _unreadable_hint(ext: str) -> str:
    """读不出文字时给一句能照做的话（不是「不支持」这种死胡同）。"""
    legacy = _LEGACY_OFFICE_EXTS.get(ext)
    if legacy:
        label, target = legacy
        # 目标格式必须跟着类型走：让拖 .xls 的人「另存为 .docx」等于把表格存成文档，
        # 照着做只会更糟。同一个操作（另存为），不同文件给不同的对。
        return (
            f"这是{label}格式（{ext}），里面的文字读不出来；"
            f"用 Office/WPS 打开后另存为 {target} 再传就能读"
        )
    if ext in _ARCHIVE_EXTS:
        return f"{ext} 是压缩包，先解压，把里面的文件单独拖进来"
    return f"这个 {ext or '文件'} 是二进制内容，读不出文字；换个能导出文字的格式（docx / txt / csv）再传"


def _parse_generic(data: bytes, ext: str, limits: UploadLimits | None = None) -> str:
    """白名单之外的文件：能当文本读就读，读不了说清楚为什么。

    这条路径存在的理由只有一个——用户拖什么进来都得有个交代。收下文件、
    尽量取出文字，取不出来就把「换成什么格式」写在错误里。
    """
    if not data:
        raise ParseFailure("文件内容为空")
    if data[:4] == b"PK\x03\x04":
        # zip 容器（含 .ofd / .epub / 被改名的 docx）：里面可能是可读的 XML，
        # 但拆包取字的收益远小于搞错结构的风险，直接告诉用户下一步怎么做。
        raise ParseFailure(_unreadable_hint(ext))
    if _looks_binary(data):
        raise ParseFailure(_unreadable_hint(ext))
    text = _decode_text(data).replace("\r\n", "\n").strip()
    if not text:
        raise ParseFailure(f"{ext or '文件'} 里没有可用文字")
    limit = (limits or UploadLimits()).max_parsed_chars
    if len(text) > limit:
        text = text[:limit] + f"\n\n（已截断：原文 {len(text):,} 字，仅保留前 {limit:,} 字）"
    return text


def parse_bytes(data: bytes, ext: str, limits: UploadLimits | None = None) -> str:
    ext = ext.lower()
    if not ext or ext in BLOCKED_UPLOAD_EXTS:
        # 可执行文件 / 脚本 / 没有扩展名：上传那一层已经拒了，这里再挡一次，
        # 别让直接调用解析层的代码把它们当文本读进来
        raise ParseFailure(f"不支持的文件类型 {ext or '（无扩展名）'}")
    spec = media_spec(ext)
    if spec is not None and spec.kind != KIND_TRANSCRIPT:
        # 图片 / 录音 / 视频不是「读文件」，是「识别内容」：走 media_service，
        # 这里明确拒绝，免得调用方以为拿到的是空文本。
        raise ParseFailure("图片、录音、视频需要先做文字识别，不能按文档直接解析")
    if spec is None and ext not in UPLOAD_EXTS:
        return _parse_generic(data, ext, limits)
    if not data:
        raise ParseFailure("文件内容为空")
    limits = limits or UploadLimits()
    if ext == ".docx":
        text = _parse_docx(data, limits)
    elif ext == ".pdf":
        text = _parse_pdf(data, limits)
    elif ext == ".csv":
        text = _parse_csv(data)
    elif ext == ".xlsx":
        text = _parse_xlsx(data, limits)
    elif ext == ".pptx":
        text = _parse_pptx(data, limits)
    elif ext in (".srt", ".vtt"):
        text = _parse_transcript(data)
    else:
        text = _decode_text(data)
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise ParseFailure("文件中没有可用文字")
    # 文本长度上限：防止把超长内容整段塞进提示词（成本与超时双重风险）
    if len(text) > limits.max_parsed_chars:
        text = (
            text[: limits.max_parsed_chars]
            + f"\n\n（已截断：原文 {len(text):,} 字，仅保留前 {limits.max_parsed_chars:,} 字）"
        )
    return text


class LocalFileParser:
    """FileParser 端口实现。"""

    def __init__(self, settings: Any = None) -> None:
        self.limits = (
            UploadLimits.from_settings(settings) if settings is not None else UploadLimits()
        )

    @property
    def supported_exts(self) -> set[str]:
        return set(UPLOAD_EXTS)

    def parse(self, data: bytes, ext: str) -> str:
        return parse_bytes(data, ext, self.limits)
