"""媒体识别：图片 OCR 与会议音视频转写。

两个引擎都是「懒加载 + 进程内单例」，因为它们各自要几百毫秒到几秒的初始化，
而且会把模型常驻内存：

- **图片**：PaddleOCR 优先（PP-OCRv5/v6 中文模型），RapidOCR 兜底。选谁由
  `OCR_ENGINE` 决定（`auto` = 装了 Paddle 就用它），两家的输出结构差异全在
  `ocr_engine` 里归一化成「带坐标的文字块」，本文件只认那一种。识别一张
  1440×900 的界面截图约 3~5 秒（Paddle 的 server 模型更准也更慢些）。
- **录音 / 视频**：faster-whisper（CTranslate2，int8 量化，CPU）。模型首次使用时
  下载到 `data/models/asr`，默认 `base`（约 145MB，中文识别够用，速度约 4 倍实时）；
  可在设置里换成 `small`（更准，约 1.7 倍实时）或 `medium`。视频不抽画面，直接读
  音轨 —— 会议视频要的是说话内容，画面 OCR 只会把 PPT 上的字混进会议纪要。

识别本身放在后台线程里跑（见 `ArtifactService`）：30 分钟的录音要转几分钟，
同步等会把上传请求挂死、界面一直转圈，也让人分不清「在上传」还是「在读」。
"""

from __future__ import annotations

import io
import itertools
import os
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from . import asr_lexicon
from .ocr_engine import OcrEngineError, OcrLine, build_engine, normalize_result
from .ocr_engine import available as ocr_engines_available
from .ocr_engine import configured as ocr_engine_configured


class MediaError(Exception):
    """识别失败：消息直接给用户看（缺组件、模型下载失败、文件损坏）。"""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass
class RecognitionResult:
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except Exception:
        return False
    return True


def _timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _short_error(exc: BaseException, limit: int = 160) -> str:
    """异常摘要：类型 + 一行消息。

    原始消息里常带几十行堆栈或多行 ffmpeg 日志，塞进界面的红色小字里既读不完
    也看不出重点；截断后至少能让人判断「是文件坏了还是模型没装」。
    """
    message = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ").strip()
    return message[:limit] + ("…" if len(message) > limit else "")


def _close_quietly(iterator: Any) -> None:
    """尽早释放解码器。

    转写到一半因为超时/截断 break 出来时，whisper 的生成器还握着音频解码上下文；
    不 close 就等 GC，30 分钟的录音会白占着内存和文件句柄。
    """
    closer = getattr(iterator, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:  # pragma: no cover - 关闭失败不影响结果
            return


#: 单张图最长边上限（像素）。手机原图 4000×3000 直接送检测，耗时从 3 秒涨到
#: 十几秒、内存也翻几倍；缩到 2200 后小字号仍认得出（检测网络输入只有 960 高）。
DEFAULT_OCR_MAX_SIDE = 2200

#: 允许解码的像素上限（6000 万，覆盖手机 4800 万像素原图）。
#: 再大就不是「翻拍会议白板」而是扫描仪图纸了，先缩了再传更划算。
_MAX_IMAGE_PIXELS = 60_000_000

#: 低于这个置信度的结果不进正文：反光、过曝、手指挡住的位置模型会吐乱码，
#: 而乱码混进会议纪要比少一行更糟（模型会当真去引用）。
DEFAULT_OCR_MIN_SCORE = 0.5


#: 一格文字 = 文案 + 置信度 + 外接框。定义在 `ocr_engine`（那是所有引擎的统一出口），
#: 这里留个别名，下游几十处「按块分行、按块分列」的代码不用跟着改名。
_OcrBlock = OcrLine


#: 行内水平间隙超过「这么多倍字高」才可能是列缝（表格单元格之间 / 双栏之间）。
#: 单行偶尔出现的大间隙多半只是排版空格，「华东区完成 82%」不该被掰成两行。
_GAP_RATIO = 1.0

#: 两条列缝的中心相距在这个范围内，算同一条列线。
_COLUMN_TOLERANCE = 40.0

#: 低置信度块的字数下限：达到这个长度就再看内容，而不是直接按分数扔掉。
_TRUSTED_MIN_CHARS = 4

#: 表格判定：至少三列、三行，且格子里的字是短的。
#: 双栏正文（两列）和长句不进来——把文章硬折成表格，读起来比流水账更糟。
_TABLE_MIN_COLUMNS = 3
_TABLE_MIN_ROWS = 3
_TABLE_MAX_CELL_CHARS = 24

#: 两块文字的横向范围重叠到「其中较窄那个的这么多」就算同一列。
#: 同一格里的几行字、上下两行同列的字，重叠通常接近 100%；不同列基本不重叠。
_OVERLAP_RATIO = 0.5

#: 比「块宽中位数」宽出这么多倍的，多半是跨列的表头或合并单元格，单独处理。
_SPAN_RATIO = 2.2

#: 一格里的某一行占到格子宽度的这个比例，就认定它是**被格子边界折断的**，
#: 下一行接着往下拼；没占到这么宽，下一行就是另一条信息（课程名 → 教师 → 教室）。
_WRAP_FILL_RATIO = 0.7

#: 空格子的占位符。用「—」而不是留空：留空在 markdown 表里会被当成少一格，
#: 后面的列整体左移——这正是识别结果被填错位置的根源。
_EMPTY_CELL = "—"


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _join_cell_line(parts: list[str]) -> str:
    """同一行里被切成几块的文字拼回去，中文之间不留缝、与数字之间留一个空格。

    跟 `_join_inline` 的差别：这里中英文混排要留空格（「卢欣欣 5101」而不是
    「卢欣欣5101」），因为表格里的空格就是字段分隔，丢了就读不出「哪部分是教室」。
    """

    out = ""
    for raw in parts:
        text = raw.strip()
        if not text:
            continue
        if out and not (_is_cjk(out[-1]) and _is_cjk(text[0])):
            out += " "
        out += text
    return out


def _resample() -> Any:
    """Pillow 9 起 `Image.Resampling` 才是新名字，旧版只有常量。"""
    from PIL import Image

    return getattr(Image, "Resampling", Image).LANCZOS


def _prepare_image(data: bytes, *, max_side: int) -> tuple[bytes, dict[str, Any]]:
    """把上传的原图整理成「模型好认」的样子，返回 PNG 字节与处理记录。

    四件事，缺一件都会让识别率莫名下降：

    - **EXIF 方向**：手机竖拍的照片 Orientation=6，按原始像素读出来是躺倒的，
      横躺的中文几乎认不出来；
    - **透明底**：透明 PNG 直接转 RGB 会变成黑底，深色文字连同背景一起糊掉，
      先合成到白底上才是人眼看到的样子；
    - **超大图缩放**：4000px 宽的截图没必要，缩到 2200 反而更快更准；
    - **过小图放大**：微信转发两遍的截图可能只剩 300px 宽，字挤在一起，
      放大一档检测框才落得上去。
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - Pillow 是基础依赖
        raise MediaError(
            "图片处理组件（Pillow）未安装：pip install pillow", retryable=True
        ) from exc

    try:
        source = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise MediaError(f"图片打不开，可能已损坏：{_short_error(exc, 80)}") from exc

    with source:
        width, height = source.size
        if width < 8 or height < 8:
            raise MediaError("这张图只有几个像素，里面不会有可读的字")
        if width * height > _MAX_IMAGE_PIXELS:
            raise MediaError(
                f"这张图太大（{width}×{height}），请先压缩到 "
                f"{_MAX_IMAGE_PIXELS // 1_000_000} 百万像素以内再传"
            )
        try:
            source.load()
        except Exception as exc:
            raise MediaError(f"图片解码失败，可能已损坏：{_short_error(exc, 80)}") from exc

        frames = int(getattr(source, "n_frames", 1) or 1)
        image = ImageOps.exif_transpose(source) or source
        if image.mode in ("RGBA", "LA", "PA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, (255, 255, 255))
            canvas.paste(rgba, mask=rgba.split()[-1])
            image = canvas
        elif image.mode != "RGB":
            image = image.convert("RGB")

        longest = max(image.size)
        scaled = False
        if max_side > 0 and longest > max_side:
            ratio = max_side / float(longest)
            image = image.resize(
                (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
                _resample(),
            )
            scaled = True
        elif longest < 480:
            image = image.resize((image.width * 2, image.height * 2), _resample())
            scaled = True

        # 曝光不足 / 翻拍发灰的图先拉一档对比度。放在缩放之后：
        # 处理的是缩过的图，直方图统计更便宜，结果也一样。
        image, enhanced = _enhance_if_washed_out(image)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        processed_size = [image.width, image.height]

    return (
        buffer.getvalue(),
        {
            "size": [width, height],
            "processed_size": processed_size,
            "scaled": scaled,
            "frames": frames,
            **({"enhanced": True} if enhanced else {}),
        },
    )


#: 灰度极差小于这个值，就当成「灰蒙蒙」拉一档对比度。
#: 正常截图是白底黑字，极差接近 255；翻拍的白板、曝光不足的会议照常只有 40~90，
#: 这种图检测框能落上去、识别却连成一片乱码。
_WASHED_OUT_SPAN = 96


def _enhance_if_washed_out(image: Any) -> tuple[Any, bool]:
    """对比度太低的图先拉一档再识别。

    只做**线性拉伸**（`autocontrast`），不做锐化、不做二值化：
    后者会把细笔画（「未」「末」）黏在一起，反而更难认。

    判据看灰度**极差**而不是直方图分位数：一页 PPT 截图里黑字可能只占 0.5%，
    1% 分位直接落在白底上，算出来「极差为 0」，把一张好图当成灰图。
    极差只看有没有黑、有没有白，最小的一块字也算数。

    `cutoff=0` 也是同一个理由：按分位截断（默认 1%）会把那一小块黑字当噪声切掉，
    拉伸后字反而淡成了背景色。
    """
    from PIL import ImageOps

    low, high = image.convert("L").getextrema()
    if high - low >= _WASHED_OUT_SPAN:
        return image, False
    if high - low <= 0:
        # 纯色图（纯白 / 纯黑）：没有可比的东西，拉了也是原样
        return image, False
    return ImageOps.autocontrast(image, cutoff=0), True


#: 顺时针转多少度 → Pillow 的 transpose 名字（`rotate` 会重采样，字会糊）
_ROTATIONS = {90: "ROTATE_270", 270: "ROTATE_90"}

#: 平均置信度低于这个值、且块数不多时，怀疑整页方向不对。
#: 判据不敢设高：正常截图里水印、页脚小字会把平均分压到 0.7 左右，
#: 拿它当阈值会让每张图都白跑两次旋转。
_ROTATE_RETRY_SCORE = 0.5

#: 同上，块数上限。整页躺倒时是「所有块都错」，不会是零星几块错。
_ROTATE_RETRY_BLOCKS = 8


def _rotate_image(data: bytes, angle: int) -> bytes:
    from PIL import Image

    transpose = getattr(getattr(Image, "Transpose", Image), _ROTATIONS[angle])
    with Image.open(io.BytesIO(data)) as image:
        rotated = image.transpose(transpose)
        buffer = io.BytesIO()
        rotated.save(buffer, format="PNG")
        return buffer.getvalue()


def _quality(blocks: list[_OcrBlock]) -> tuple[float, int]:
    """哪个方向认得更好：先比平均置信度，再比块数。

    不能先比块数——图转错方向时噪声框反而更多（一堆「一段」被切成十几块），
    数量会赢在错的一边。平均分则很诚实：认错的方向清一色低分。
    """
    if not blocks:
        return (0.0, 0)
    mean = sum(block.score for block in blocks) / len(blocks)
    return (round(mean, 2), len(blocks))


def _looks_upside_down(blocks: list[_OcrBlock]) -> bool:
    """要不要试着转个方向再认一遍。

    一块都没认到就**不试**：多半图里真没有字，转两次只会白等三倍时间。
    躺倒的图恰恰不是这种情况——正着认会认出一堆低分乱码，所以才有下面这条。
    """
    if not blocks:
        return False
    return _quality(blocks)[0] < _ROTATE_RETRY_SCORE and len(blocks) <= _ROTATE_RETRY_BLOCKS


def _join_inline(parts: list[str]) -> str:
    """同一行里被切成几块的文字拼回去。

    中文之间不补空格（「华东区完成」+「82%」= 「华东区完成82%」才是原文），
    只有两个 ASCII 字母数字相接时才补 —— 那是英文单词被切开了。
    """

    def ascii_word(char: str) -> bool:
        return char.isascii() and char.isalnum()

    out = ""
    for raw in parts:
        text = raw.strip()
        if not text:
            continue
        if out and ascii_word(out[-1]) and ascii_word(text[0]):
            out += " "
        out += text
    return out


def _keep_low_score(text: str, *, score: float, min_score: float) -> bool:
    """低置信度的块要不要留。

    按分数一刀切会误伤长句：一句话里有个别字没认准，平均分被拉到线下，整块就
    没了 —— 文字其实是对的，用户只会看到少了一行，比认错字更难受。所以长块
    把门槛放宽一档（字数多，平均分本就容易被摊薄）；短块维持原标准，反光、
    水印、手指边缘那种一两个符号照旧丢掉。
    """
    if score >= min_score:
        return True
    floor = min_score * 0.8 if len(text) >= _TRUSTED_MIN_CHARS else min_score
    return score >= floor


def _group_rows(blocks: list[_OcrBlock]) -> list[list[_OcrBlock]]:
    """按纵向位置聚成行。

    参照点取**行首块**而不是上一块：翻拍的白板常有几度倾斜，逐块比较会把偏差
    一路累积，第 10 块就被判到下一行去，整行顺序全乱；以行首为锚，倾斜最多让
    一行拆成两行，读起来仍然是通的。
    """
    rows: list[list[_OcrBlock]] = []
    for block in sorted(blocks, key=lambda b: (b.center_y, b.left)):
        best: list[_OcrBlock] | None = None
        best_delta = 0.0
        for row in rows:
            anchor = row[0]
            tolerance = max(anchor.height, block.height) * 0.6
            delta = abs(block.center_y - anchor.center_y)
            if delta <= tolerance and (best is None or delta < best_delta):
                best, best_delta = row, delta
        if best is None:
            rows.append([block])
        else:
            best.append(block)
    return rows


def _column_lines(rows: list[list[_OcrBlock]]) -> list[float]:
    """找出真正的列缝（表格单元格之间 / 双栏之间），返回列线 x。

    不能只看「某一行里有个大间隙」就断行 —— 一句话中间的空格也能超过一个字高。
    列缝的特征是**纵向贯穿**：至少两行在同一个 x 位置都有缝。找不到这样的列线
    就整页当单栏，一个字都不切。
    """
    seams: list[tuple[float, float, int]] = []  # (中心 x, 行高, 行号)
    for index, row in enumerate(rows):
        ordered = sorted(row, key=lambda b: b.left)
        for prev, cur in itertools.pairwise(ordered):
            height = max(prev.height, cur.height)
            if cur.left - prev.right <= height * _GAP_RATIO:
                continue
            seams.append(((prev.right + cur.left) / 2.0, height, index))

    confirmed: list[float] = []
    for index, (center, height, row_index) in enumerate(seams):
        tolerance = max(_COLUMN_TOLERANCE, height * 2)
        for other_index, (other_center, _other_height, other_row) in enumerate(seams):
            if other_index == index or other_row == row_index:
                continue
            if abs(center - other_center) <= tolerance:
                confirmed.append(center)
                break

    # 同一条列线会被好几行各记一次，合并成一条
    merged: list[float] = []
    for center in sorted(confirmed):
        if merged and center - merged[-1] <= _COLUMN_TOLERANCE:
            merged[-1] = (merged[-1] + center) / 2.0
        else:
            merged.append(center)
    return merged


def _split_row(row: list[_OcrBlock], columns: list[float]) -> list[list[_OcrBlock]]:
    """按列线把一行切成若干格；不在列线上的间隙仍当同一句里的空格。"""
    ordered = sorted(row, key=lambda b: b.left)
    segments: list[list[_OcrBlock]] = [[ordered[0]]]
    for prev, cur in itertools.pairwise(ordered):
        height = max(prev.height, cur.height)
        center = (prev.right + cur.left) / 2.0
        tolerance = max(_COLUMN_TOLERANCE, height * 2)
        on_column = any(abs(center - column) <= tolerance for column in columns)
        if cur.left - prev.right > height * _GAP_RATIO and on_column:
            segments.append([cur])
        else:
            segments[-1].append(cur)
    return segments


# --------------------------------------------------------------------------- #
# 表格还原：把「按行读下来的流水文字」还原成有行有列的格子
# --------------------------------------------------------------------------- #
# 为什么非做不可。OCR 引擎不给表格结构，只给一堆带坐标的文本块。以前把它们按
# y 排序、再按列缝拼成 `A | B | C` 一行行的文字——**空格子直接消失**。于是
# 「周三没课」这件事在文字里看不出来，下游按顺序往表格里填，后面的课程就整体
# 左移一格：周五的课被填到了周一（2026-11-10 线上就是这个现象）。
#
# 这里改成先还原成矩阵：行 × 列都摆好，空格写「—」。格子位置本身就是信息，
# 不再靠下游去数「第几个」。


# 行方向**不合并**。试过按间距把相邻行并成「视觉行」，两遍都不成：并得松，
# 一行紧挨一行的课表整张并成一行，全表糊进一格；并得紧，一格里的换行（课程名折
# 三行）被拆到三行，节次反而对不上。「哪几行属于同一格」靠文字坐标判不出来，
# 那需要表格线。所以一行文字就是一行，同一格折行会连着出现几行，由模型按列位置
# 自己合起来（输出的第一行写明了这件事）。宁可多几行，也不要整表糊成一块。


def _column_groups(blocks: list[_OcrBlock]) -> list[list[_OcrBlock]]:
    """把文字块按「横向范围重叠」聚成列。

    为什么不用列缝（`_column_lines`）来分列：一格的字长一点短一点，两列之间的
    空隙中点就会左右漂几十像素，同一根列线在不同行算出七八个位置——6 列的课表
    被判成 9 列，格子全散开。

    重叠聚类只依赖一个稳定的事实：**同一列里的字，横向范围总是互相重叠的**
    （它们被同一对单元格边界夹着），而不同列的字不重叠。跨列的表头/合并单元格
    例外（它比别的块宽得多），先挑出来，最后按重叠最多的一列归位。
    """
    if not blocks:
        return []
    widths = sorted(block.right - block.left for block in blocks)
    median = widths[len(widths) // 2] or 1.0
    core = [b for b in blocks if (b.right - b.left) <= median * _SPAN_RATIO]
    spanning = [b for b in blocks if (b.right - b.left) > median * _SPAN_RATIO]
    if not core:
        return [list(blocks)]

    parent = list(range(len(core)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(core)):
        left_a, right_a = core[i].left, core[i].right
        for j in range(i + 1, len(core)):
            left_b, right_b = core[j].left, core[j].right
            overlap = min(right_a, right_b) - max(left_a, left_b)
            if overlap <= 0:
                continue
            narrower = min(right_a - left_a, right_b - left_b)
            if overlap >= narrower * _OVERLAP_RATIO:
                parent[find(i)] = find(j)

    grouped: dict[int, list[_OcrBlock]] = {}
    for index, block in enumerate(core):
        grouped.setdefault(find(index), []).append(block)
    columns = sorted(grouped.values(), key=lambda group: min(b.left for b in group))

    for block in spanning:
        best, best_overlap = 0, -1.0
        for index, group in enumerate(columns):
            left = min(item.left for item in group)
            right = max(item.right for item in group)
            overlap = min(block.right, right) - max(block.left, left)
            if overlap > best_overlap:
                best, best_overlap = index, overlap
        columns[best].append(block)
    return columns


def _cell_text(blocks: list[_OcrBlock], left: float, right: float) -> str:
    """一个格子里的文字：先按行拼，再看要不要接着上一行。

    同一格里「移动应用服务器/编/程」是被格子边界折断的一行字，中间不该加分隔符；
    「课程名 / 教师 教室」是三条信息，该分开。判据是**上一行有没有写满这一格**：
    写满了就是被折断的，没写满就是另起一条。
    """
    if not blocks:
        return ""
    lines: list[tuple[str, float]] = []
    for line in _group_rows(blocks):
        ordered = sorted(line, key=lambda block: block.left)
        text = _join_cell_line([block.text for block in ordered])
        if text:
            lines.append((text, max(block.right for block in ordered)))
    if not lines:
        return ""
    width = max(1.0, right - left)
    out = lines[0][0]
    for (_prev, prev_right), (text, _right) in itertools.pairwise(lines):
        filled = prev_right - left >= width * _WRAP_FILL_RATIO
        out += text if filled else " / " + text
    return out.replace("|", "｜")


def _table_grid(blocks: list[_OcrBlock], rows: list[list[_OcrBlock]]) -> list[str] | None:
    """看着像表格就还原成 markdown 表格；不像就返回 None（照旧按行输出）。"""
    if len(rows) < _TABLE_MIN_ROWS:
        return None
    lengths = sorted(len(block.text) for block in blocks)
    if lengths[len(lengths) // 2] > _TABLE_MAX_CELL_CHARS:
        return None  # 一格里的字比一句话还长，那是正文的栏，不是表格的格

    columns = _column_groups(blocks)
    if len(columns) < _TABLE_MIN_COLUMNS:
        return None

    order: dict[int, int] = {}
    for index, group in enumerate(columns):
        for block in group:
            order[id(block)] = index
    cells: dict[tuple[int, int], list[_OcrBlock]] = {}
    for row_index, row in enumerate(rows):
        for block in row:
            column = order.get(id(block))
            if column is not None:
                cells.setdefault((row_index, column), []).append(block)

    width = len(columns)
    extents = [
        (min(block.left for block in group), max(block.right for block in group))
        for group in columns
    ]
    matrix = [
        [
            _cell_text(cells.get((row, col), []), *extents[col]) or _EMPTY_CELL
            for col in range(width)
        ]
        for row in range(len(rows))
    ]
    header, body = matrix[0], matrix[1:]
    lines = [
        f"（以下是表格：{width} 列 × {len(rows)} 行，按原图行列还原；{_EMPTY_CELL} 表示该格为空，"
        "同一格的字折成几行时会连着出现几行）",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return lines


def _collect_ocr_lines(
    blocks: list[_OcrBlock], *, min_score: float
) -> tuple[list[str], int, list[float]]:
    """引擎给的文字块 → 按阅读顺序排好的行。

    引擎按检测框顺序返回结果，多栏界面（左边正文、右边侧栏）会左右穿插着出来；
    按中心点先分「行」、行内再按 x 排序，才读得通。同一行被切成几块的还要拼回去，
    否则「华 东 区」会被当成三个词。

    排版判断只有一条规则：**列缝是纵向贯穿的**。多行在同一个 x 位置都有大间隙，
    才认定这一页是表格／双栏，用 ` | ` 连成一行；否则当单栏，间隙只当空格。

    返回 (行列表, 因低置信度丢弃的块数, 保留块的置信度)。
    """
    kept: list[_OcrBlock] = []
    dropped = 0
    for block in blocks:
        if not block.text:
            continue
        if not _keep_low_score(block.text, score=block.score, min_score=min_score):
            dropped += 1
            continue
        kept.append(block)

    if not kept:
        return [], dropped, []

    rows = _group_rows(kept)
    # 表格先还原成矩阵再输出：流水式的 `A | B | C` 会把空格子整个丢掉，
    # 下游照着顺序填，后面的列就整体左移（详见 _table_grid 上面那段注释）。
    grid = _table_grid(kept, rows)
    if grid is not None:
        return grid, dropped, [block.score for block in kept]
    columns = _column_lines(rows)

    lines: list[str] = []

    def push(line: str) -> None:
        line = line.strip()
        # 相邻两行一模一样：检测框重叠导致的重复，只留一条
        if line and (not lines or lines[-1] != line):
            lines.append(line)

    for row in rows:
        if columns:
            segments = _split_row(row, columns)
            cells = [
                cell
                for cell in (_join_inline([block.text for block in seg]) for seg in segments)
                if cell
            ]
            if cells:
                push(" | ".join(cells))
        else:
            push(_join_inline([block.text for block in sorted(row, key=lambda b: b.left)]))
    return lines, dropped, [block.score for block in kept]


def _probe_audio(data: bytes) -> dict[str, Any]:
    """读容器头，看有没有音轨、是什么编码。

    视频「没声音」在会议场景里很常见（录屏只录了画面）。直接丢给 whisper，
    它只会报一句 `Invalid data found`，用户看不出是文件没音轨还是模型坏了。
    """
    try:
        import av
    except ImportError:  # pragma: no cover - 没装识别组件时不做探测
        return {}
    try:
        with av.open(io.BytesIO(data), metadata_errors="ignore") as container:
            audio = next((s for s in container.streams if s.type == "audio"), None)
            video = next((s for s in container.streams if s.type == "video"), None)
            if audio is None:
                return {"has_audio": False, "has_video": video is not None}
            context = audio.codec_context
            duration = float(container.duration / 1_000_000) if container.duration else 0.0
            return {
                "has_audio": True,
                "has_video": video is not None,
                "codec": str(getattr(context, "name", "") or ""),
                "sample_rate": int(getattr(context, "sample_rate", 0) or 0),
                "duration": duration,
            }
    except Exception:
        # 探测失败不阻断：让 whisper 自己去试，它的报错更具体
        return {}


#: 中文转写的前置提示。只留最短一句：whisper 的 prompt 是当「前文」续写的，
#: 提示语越长，第一段把它整句复读出来的概率越高（真发生过：正文第一行变成
#: 「以下是简体中文的会议记录，请使用简体中文转写」）。简体化交给 OpenCC 兜底，
#: 不让 prompt 兼任翻译指令。
_ZH_PROMPT = "以下是普通话会议录音。"

#: 提示语去掉标点后的样子，用来识别「模型把提示语当正文吐出来」
_PROMPT_COMPACT = re.sub(r"[^\w]", "", _ZH_PROMPT)

#: 少于这么多字的段先攒着跟下一段合并。whisper 常把「嗯」「对」「这个」单独切成
#: 一段，一段一行带时间戳，30 分钟的会议会变成几百行碎片，纪要根本没法读。
_MERGE_MAX_CHARS = 2

#: 攒着的短段最多等这么多秒，超过就不等了 —— 相隔很远的两句不该拼在一起。
_MERGE_MAX_GAP = 2.0


def _looks_like_prompt_echo(text: str) -> bool:
    """模型复读 initial_prompt 的判定。

    只对**首段**用，且要求去掉标点后仍是提示语的子串 —— 宁可漏判（多一行提示语），
    也不能误删真实台词。
    """
    compact = re.sub(r"[^\w]", "", text)
    return len(compact) >= 4 and compact in _PROMPT_COMPACT


#: 繁转简。whisper 的 simplified 偏好只是「倾向」，仍会混出繁体字，
#: 所以出字后再统一过一遍。opencc 是**可选**依赖：没装就原样返回，
#: 不能因为少一个包让整个转写报错。
_SIMPLIFIER: Any = None
_SIMPLIFIER_LOCK = threading.Lock()


def _to_simplified(text: str) -> str:
    global _SIMPLIFIER
    with _SIMPLIFIER_LOCK:
        if _SIMPLIFIER is None:
            try:
                from opencc import OpenCC
            except Exception:
                _SIMPLIFIER = False
            else:
                try:
                    _SIMPLIFIER = OpenCC("t2s")
                except Exception:  # pragma: no cover - 词典缺失
                    _SIMPLIFIER = False
    if not _SIMPLIFIER:
        return text
    try:
        return str(_SIMPLIFIER.convert(text))
    except Exception:  # pragma: no cover - 转换失败不该毁掉整段结果
        return text


class MediaRecognizer:
    """图片 / 音频 / 视频 → 文字。线程安全（引擎初始化加锁，推理串行）。"""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._ocr: Any = None
        self._ocr_lock = threading.Lock()
        self._asr: Any = None
        self._asr_lock = threading.Lock()

    # ---------- 能力探测 ----------
    def capabilities(self) -> dict[str, Any]:
        """给健康检查和设置页看的实话：组件装没装、用的哪个模型。"""
        engines = ocr_engines_available()
        # 只看「选了谁 + 装没装」，不加载模型：健康检查每次都会调这里
        chosen = build_engine(self.settings)
        return {
            "ocr": engines.get(chosen.name, False),
            "ocr_engine": chosen.name if engines.get(chosen.name, False) else "",
            "ocr_engine_configured": ocr_engine_configured(self.settings),
            "ocr_engines": engines,
            "asr": _module_available("faster_whisper"),
            "asr_model": str(getattr(self.settings, "asr_model", "base")),
            "asr_language": str(getattr(self.settings, "asr_language", "zh")),
            "asr_endpoint": str(getattr(self.settings, "asr_endpoint", "")),
            "max_minutes": int(getattr(self.settings, "asr_max_minutes", 60)),
            # OCR 的几个旋钮：识别率不满意时可以调，不用改代码
            "ocr_max_side": int(getattr(self.settings, "ocr_max_side", DEFAULT_OCR_MAX_SIDE)),
            "ocr_min_score": float(getattr(self.settings, "ocr_min_score", DEFAULT_OCR_MIN_SCORE)),
            "ocr_lang": str(getattr(self.settings, "ocr_lang", "ch")),
            # oneDNN 加速开没开：Paddle 3.3 在部分 Windows CPU 上开着它直接崩，
            # 排查「图片识别失败」时第一个要看的就是这个值
            "ocr_mkldnn": bool(getattr(self.settings, "ocr_mkldnn", False)),
            "ocr_textline_orientation": bool(
                getattr(self.settings, "ocr_textline_orientation", True)
            ),
            # 转写的旋钮：热词带几个（其中人名 / 专名各占多少）、要不要再挑一遍字
            "hotword_limit": int(getattr(self.settings, "asr_hotword_limit", 12)),
            "people": int(getattr(self.settings, "asr_people", 4)),
            "proper_nouns": int(getattr(self.settings, "asr_proper_nouns", 6)),
            "proofread": bool(getattr(self.settings, "asr_proofread", True)),
            # 繁转简是可选依赖：没装也能转写，只是可能混出繁体字
            "simplify": _module_available("opencc"),
        }

    # ---------- 图片 ----------
    def _ocr_engine(self) -> Any:
        with self._ocr_lock:
            if self._ocr is not None:
                return self._ocr
            # 这里只造对象、不加载模型：模型加载在第一次识别时发生，
            # 免得「装没装 Paddle」这件事卡在上传请求里
            self._ocr = build_engine(self.settings)
            return self._ocr

    def _run_ocr(self, engine: Any, image: bytes) -> list[_OcrBlock]:
        """调引擎拿文字块。引擎对象走 `recognize`，自定义可调用对象走归一化。"""
        try:
            if hasattr(engine, "recognize"):
                return list(engine.recognize(image))
            # 测试与自定义注入：一个接收图片字节的可调用对象，返回引擎原始结构
            return normalize_result(engine(image))
        except OcrEngineError as exc:
            raise MediaError(exc.message, retryable=exc.retryable) from exc
        except MediaError:
            raise
        except Exception as exc:
            raise MediaError(f"图片识别失败：{_short_error(exc, 90)}", retryable=True) from exc

    def ocr(self, data: bytes) -> RecognitionResult:
        max_side = int(getattr(self.settings, "ocr_max_side", DEFAULT_OCR_MAX_SIDE) or 0)
        min_score = float(getattr(self.settings, "ocr_min_score", DEFAULT_OCR_MIN_SCORE) or 0.0)
        prepared, prepared_meta = _prepare_image(data, max_side=max_side)
        engine = self._ocr_engine()
        engine_name = str(getattr(engine, "name", "") or "custom")
        started = time.monotonic()

        blocks = self._run_ocr(engine, prepared)
        rotated = 0
        if _looks_upside_down(blocks):
            # 躺倒的翻拍（手机横着拍纸、扫描件放反）整版字都是「认得出来但不像话」。
            # Paddle 的整页方向分类要多下一个模型，这里用最土但也最稳的办法：
            # 顺时针转 90°/270° 各认一遍，谁的平均分高就用谁。
            best = _quality(blocks)
            for angle in (90, 270):
                try:
                    candidate = self._run_ocr(engine, _rotate_image(prepared, angle))
                except MediaError:
                    # 旋转后的这次失败不该盖掉已经拿到的东西：继续试下一个角度
                    continue
                if not candidate:
                    continue
                current = _quality(candidate)
                if current > best:
                    blocks, best, rotated = candidate, current, angle
                if not _looks_upside_down(blocks):
                    break

        lines, dropped, scores = _collect_ocr_lines(blocks, min_score=min_score)
        if not lines:
            if dropped:
                raise MediaError("图里有文字但太模糊／太小，认不出来；把截图放大一点再试")
            raise MediaError("这张图里没有识别到文字（可能是纯照片或分辨率过低）")
        text = "\n".join(lines)
        frames = int(prepared_meta.get("frames") or 1)
        if frames > 1:
            # 多页 TIFF 只认第一页：不说清楚，用户会以为后面几页没内容
            text += f"\n\n（这是 {frames} 页 TIFF 的第 1 页，只识别了这一页）"
        meta: dict[str, Any] = {
            "engine": engine_name,
            "lines": len(lines),
            "size": prepared_meta["size"],
            "processed_size": prepared_meta["processed_size"],
            "scaled": prepared_meta["scaled"],
            "elapsed": round(time.monotonic() - started, 1),
        }
        if lines and lines[0].startswith("（以下是表格"):
            # 记一笔「按表格读的」。识别结果不对时第一件事就是看它当时认成了什么
            # 结构——是格子还原错了，还是压根没认成表格，两种情况改法完全不同。
            meta["shape"] = "table"
        if prepared_meta.get("enhanced"):
            meta["enhanced"] = True
        if rotated:
            meta["rotated"] = rotated
        if frames > 1:
            meta["frames"] = frames
        if dropped:
            meta["dropped"] = dropped
        if scores:
            meta["score"] = round(sum(scores) / len(scores), 3)
        return RecognitionResult(text=text, meta=meta)

    # ---------- 音视频 ----------
    def _asr_model(self) -> Any:
        with self._asr_lock:
            if self._asr is not None:
                return self._asr
            endpoint = str(getattr(self.settings, "asr_endpoint", "") or "").strip()
            if endpoint:
                # huggingface_hub 在导入时读环境变量，这里先钉住镜像地址：
                # 直连 huggingface.co 在国内经常是 502，模型下不下来就会让整个功能
                # 看起来「坏的」。已经有用户设置的 HF_ENDPOINT 时不覆盖。
                os.environ.setdefault("HF_ENDPOINT", endpoint)
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover
                raise MediaError(
                    "语音识别组件未安装：执行 pip install faster-whisper 后重启后端",
                    retryable=True,
                ) from exc
            name = str(getattr(self.settings, "asr_model", "base") or "base")
            root = str(getattr(self.settings, "asr_model_dir", "") or "") or None
            threads = max(1, min(8, (os.cpu_count() or 4) - 1))
            try:
                self._asr = WhisperModel(
                    name,
                    device="cpu",
                    compute_type="int8",
                    download_root=root,
                    cpu_threads=threads,
                )
            except Exception as exc:  # pragma: no cover - 首次下载失败
                raise MediaError(
                    f"语音识别模型（{name}）加载失败：{exc}。"
                    "首次使用需要联网下载模型，可重试；长期失败就换一个更小的模型名",
                    retryable=True,
                ) from exc
            return self._asr

    def transcribe(
        self, data: bytes, *, hotwords: Sequence[str] | None = None
    ) -> RecognitionResult:
        probe = _probe_audio(data)
        if probe.get("has_audio") is False:
            if probe.get("has_video"):
                raise MediaError("这个视频里没有音轨（录屏时可能没开麦），听不到说话内容")
            raise MediaError("这个文件里没有音频流，可能已损坏")
        model = self._asr_model()
        raw_language = str(getattr(self.settings, "asr_language", "zh") or "").strip()
        # "auto" / 留空 = 让模型自己判语种；固定 zh 时遇到英文会议会整段硬翻成中文
        language = None if raw_language.lower() in ("", "auto") else raw_language
        zh = bool(language) and language.lower().startswith("zh")
        max_minutes = max(1, int(getattr(self.settings, "asr_max_minutes", 60)))
        # 热词只对中文有用：英文会议的术语偏置靠的是模型自己的词表，塞中文词只会带偏
        used_hotwords = [word for word in (hotwords or ()) if word] if zh else []
        prompt = asr_lexicon.build_prompt(_ZH_PROMPT, used_hotwords)
        started = time.monotonic()
        try:
            segments, info = model.transcribe(
                io.BytesIO(data),
                language=language,
                beam_size=5,
                # 会议录音里大量「嗯、啊、停顿」：VAD 先掐掉静音，既快又不让模型
                # 在静音处幻想出句子。静音阈值不能太短 —— 中文句间三四百毫秒的
                # 停顿很常见，500ms 会把一句话切成好几段，跨句上下文断了，人名和
                # 术语就开始飘（「客户验收」认成「客户厌收」多半是这么来的）。
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 800},
                condition_on_previous_text=False,
                # 只给中文加提示：英文会议用不上，还会把英文带偏
                **({"initial_prompt": prompt} if zh else {}),
            )
        except Exception as exc:
            raise MediaError(f"音视频转写失败：{_short_error(exc, 120)}", retryable=True) from exc

        limit = max_minutes * 60
        pieces: list[tuple[float, float, str]] = []
        truncated = False
        try:
            for segment in segments:
                start = float(getattr(segment, "start", 0) or 0)
                end = float(getattr(segment, "end", 0) or 0)
                if end and end > limit:
                    truncated = True
                    break
                text = str(getattr(segment, "text", "") or "").strip()
                if not text:
                    continue
                # 首段偶尔是模型把 initial_prompt 当正文续写出来的，不是真说话
                if not pieces and zh and _looks_like_prompt_echo(text):
                    continue
                pieces.append((start, end, text))
        except Exception as exc:
            raise MediaError(f"音视频转写中断：{_short_error(exc, 120)}") from exc
        finally:
            _close_quietly(segments)

        repeats = 0
        deduped: list[tuple[float, float, str]] = []
        for start, end, text in pieces:
            # 静音、掌声、空调声处模型会「补」一句话，而且同一句连着吐好几遍；
            # 连续两次完全相同且时间挨着，只留第一条
            if deduped and text == deduped[-1][2] and start - deduped[-1][0] < 3.0:
                repeats += 1
                continue
            deduped.append((start, end, text))

        # 碎片合并放在去重之后：先把「嗯」「对」攒到下一句身上，再决定输出
        merged: list[tuple[float, float, str]] = []
        for start, end, text in deduped:
            if merged:
                prev_start, _prev_end, prev_text = merged[-1]
                if len(prev_text) <= _MERGE_MAX_CHARS and start - _prev_end <= _MERGE_MAX_GAP:
                    merged[-1] = (prev_start, end, prev_text + text)
                    continue
            merged.append((start, end, text))

        lines = [f"[{_timestamp(start)}] {text}" for start, _end, text in merged]
        count = len(merged)
        if not lines:
            raise MediaError("没有识别到说话内容（静音、纯音乐或音量过低）")
        text = "\n".join(lines)
        if zh:
            # 繁转简放在最后统一做：逐段转会把「乾／干」这类多音字拆散，整段更准
            text = _to_simplified(text)
        if truncated:
            text += f"\n\n（录音超过 {max_minutes} 分钟，只转写了前 {max_minutes} 分钟）"
        duration = float(probe.get("duration") or getattr(info, "duration", 0) or 0)
        meta: dict[str, Any] = {
            "engine": "faster-whisper",
            "model": str(getattr(self.settings, "asr_model", "base")),
            "duration": round(duration, 1),
            "segments": count,
            "language": str(getattr(info, "language", "") or language or ""),
            "truncated": truncated,
            "source": "video" if probe.get("has_video") else "audio",
            "elapsed": round(time.monotonic() - started, 1),
        }
        if probe.get("codec"):
            meta["audio_codec"] = probe["codec"]
        if repeats:
            meta["repeats"] = repeats
        if used_hotwords:
            # 记下来是为了可诊断：识别不准时第一件事就是看「当时给了哪些词」
            meta["hotwords"] = used_hotwords
        return RecognitionResult(text=text, meta=meta)
