"""rag.py —— 素材分块与检索：让模型「按需取片段」，而不是一次塞全文。

**放在 domain 层**：`tools/builtin/file.py` 要用它，而 `services/__init__.py`
会 import `agents` → `tools` → 又回到 `services`，落在 services 包里就是循环导入
（formats.py 已经踩过一次，这次一上手就照同一条路走）。这一层只做纯计算：
切块、打分、比对数字，不碰 IO、不碰仓储，本来也不该依赖 services。

**为什么需要这一层**：以前素材是一整块被塞进上下文的，超长就从头上截掉。
一份三万字的报告只让模型看到前三分之一，它的反应不是「我没读完」，而是
把没读到的部分用通顺的话补上——这就是最典型的一类幻觉，而且从输出上完全
看不出来（语气一样笃定）。把「看不到」变成「查得到」，是这一类问题的正解。

**为什么不用向量库**：这个项目要能离线跑完整个测试集，装不了 faiss / numpy /
sentence-transformers（pptx 那次已经踩过离线装不了包的坑）。而检索质量在这里
并不取决于向量：素材是文档，用户的问题是关键词密集的业务问句（「退款率降到
多少」「华东区新客占比」），BM25 这类词频检索在这种场景下比通用 embedding 更
稳——它不会因为「退款率」和「退货比例」语义近就召回一段实际无关的内容，而
「召回得准」正是降幻觉最要紧的一步。真需要语义召回时，换 `Index.search` 的实现
即可，上层接口不变。

**中文怎么切**：不分词。中文按相邻二字滑窗取 bigram（「退款率」→ 退款 / 款率），
ASCII 按词。分词器要词典、要维护、要处理新词，而 bigram 对检索反而更宽容——
「退款手续费」和「退款」共享「退款」，只是 idf 低一点。代价是会产生跨词噪声
（「报写」），所以覆盖度判定只统计「索引里真实存在过的词」，噪声自然被排除。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Block",
    "Hit",
    "Index",
    "format_passages",
    "match_level",
    "outline",
    "pack_blocks",
    "split_blocks",
    "unsupported_facts",
]

# 单块的理想长度：一段话的规模。太短检索不准（缺上下文），太长一次注入就吃满预算。
MAX_BLOCK_CHARS = 700
# 短于此的块尽量并进下一块，否则「一、背景」这种单行标题会单独成块、白占一个引用编号。
MIN_BLOCK_CHARS = 80
# 一块的硬上限：超长段落按句切开后仍超，就只能按字数切了。
HARD_BLOCK_CHARS = 1200


@dataclass(frozen=True)
class Block:
    """素材的一个可检索片段。`id` 就是模型引用时写的那个编号。"""

    id: str
    file: str
    seq: int
    heading: str
    text: str
    start: int

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def label(self) -> str:
        """引用行：`[S3] 《周报.docx》§关键结论（第 3 块）`。"""
        section = f"§{self.heading}" if self.heading else f"第 {self.seq} 块"
        return f"[{self.id}] 《{self.file}》{section}"


@dataclass(frozen=True)
class Hit:
    block: Block
    score: float
    coverage: float
    """这一块覆盖了查询里多少**素材认识**的词。"""
    support: float = 1.0
    """查询里有多少词是素材认识的（0~1）。

    只有 coverage 会被「命中一个词就满分」骗过去：问「营收和员工餐补」，
    营收那一块 coverage 是 1.0，可「员工餐补」四个字素材里根本没有。support
    低就说明有一大块问题没被素材接住，这时候该说「没提到」而不是给一段沾边的。
    """


# ---------------------------------------------------------------- 分词

# 口语里的虚词整词删掉：用户问「帮我看看周报怎么写」，真正该去检索的是「周报」。
# 不删的话，这些词在素材里一次都没出现，会把覆盖度拉到「没找到」，最后变成
# 每句提问都被告知「素材里没有相关内容」——比幻觉更让人烦。
_STOPWORD_TEXT = (
    "帮我 帮忙 看看 看一下 查一下 告诉我 请问 一下 这个 那个 这些 那些 什么 怎么 "
    "怎样 为什么 是不是 有没有 能否 可以 需要 现在 目前 我们 他们 你们 以及 还有 "
    "就是 但是 因为 所以 如果 的话 里面 关于 相关 一些 一点 几个 哪里 哪些 如何 "
    "多少 时候 之后 之前 内容 情况 东西 进行 出现 认为 觉得 希望 麻烦 麻烦您"
)
_STOPWORD_CHARS_TEXT = (
    "的 了 着 和 与 及 或 在 是 有 我 你 他 她 它 这 那 就 都 也 要 会 能 把 被 "
    "从 到 对 为 个 之 而 且 但 则 其 以 于 吗 呢 吧 啊 呀 哦 嗯 么"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())
_STOP_CHARS = frozenset(_STOPWORD_CHARS_TEXT.split())

# 首字分桶：逐位置做 startswith 时只看同首字的几个词，避免 O(字数 × 停用词数)。
_STOP_BUCKETS: dict[str, list[str]] = {}
for _word in sorted(_STOPWORDS, key=len, reverse=True):
    _STOP_BUCKETS.setdefault(_word[0], []).append(_word)

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD_RE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


def _strip_stopwords(chunk: str) -> list[str]:
    """删掉 CJK 串里的停用词，返回剩下的片段（保留原顺序）。"""
    pieces: list[str] = []
    buf: list[str] = []
    index = 0
    while index < len(chunk):
        bucket = _STOP_BUCKETS.get(chunk[index], ())
        matched = ""
        for word in bucket:
            if chunk.startswith(word, index):
                matched = word
                break
        if matched:
            if buf:
                pieces.append("".join(buf))
                buf = []
            index += len(matched)
        else:
            buf.append(chunk[index])
            index += 1
    if buf:
        pieces.append("".join(buf))
    return pieces


def _terms(text: str) -> list[str]:
    """文本 -> 检索词。中文 bigram + ASCII 词；只留单字的片段按单字处理。"""
    if not text:
        return []
    lowered = text.lower()
    terms = [match.group(0) for match in _ASCII_WORD_RE.finditer(lowered)]
    for chunk in _CJK_RUN_RE.findall(lowered):
        for piece in _strip_stopwords(chunk):
            if len(piece) == 1:
                if piece not in _STOP_CHARS:
                    terms.append(piece)
                continue
            for offset in range(len(piece) - 1):
                gram = piece[offset : offset + 2]
                # 两个都是虚字的组合（「的在」「了就」）没有检索价值
                if gram[0] in _STOP_CHARS and gram[1] in _STOP_CHARS:
                    continue
                terms.append(gram)
    return terms


# ---------------------------------------------------------------- 切块

# 只认三种标题：Markdown `#`、中文序号「一、」、阿拉伯序号「1.」/「2.3」。
# 「2026 年营收」这种不能认成标题——它没有 `.` 或 `、` 紧跟数字，所以不会误判。
_HEADING_LINE_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s+\S|[一二三四五六七八九十]+[、.]\s*\S|\d+(?:\.\d+)*[.、]\s*\S)"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;])\s*|\n")


def _heading_of(line: str) -> str:
    """把标题行剥成纯文字（去掉 `#`、序号、外层符号）。

    多级编号要整段剥：「2.1 库存」剥成「库存」，不能只吃掉 `2.` 留下「1 库存」——
    那个残留的 1 会被当成章节号，模型引用时写出来就是错的。
    """
    text = line.strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^[一二三四五六七八九十]+[、.]\s*", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*(?:[.、]\s*|\s+)", "", text)
    return text.strip(" 　:：.、")[:60]


def _split_long(text: str, limit: int) -> list[str]:
    """超长段落按句切开再装箱；单句仍超长就硬切，反正不能留一块超上限的。"""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    buffer = ""
    for part in _SENTENCE_SPLIT_RE.split(text):
        if not part:
            continue
        if len(buffer) + len(part) <= limit:
            buffer += part
            continue
        if buffer:
            pieces.append(buffer)
            buffer = ""
        while len(part) > limit:
            pieces.append(part[:limit])
            part = part[limit:]
        buffer = part
    if buffer:
        pieces.append(buffer)
    return pieces


def _segments(text: str) -> list[tuple[str, str, int]]:
    """原文 -> [(heading, 段落, 起始偏移)]。空行分段，标题附着到其后的段落上。"""
    segments: list[tuple[str, str, int]] = []
    heading = ""
    buffer: list[str] = []
    buffer_start = 0
    offset = 0

    def flush() -> None:
        nonlocal buffer, buffer_start
        body = "\n".join(line for line in buffer).strip()
        if body:
            segments.append((heading, body, buffer_start))
        buffer = []

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        position = offset
        offset += len(line)
        if not stripped.strip():
            flush()
            continue
        if _HEADING_LINE_RE.match(stripped) and len(stripped.strip()) <= 60:
            flush()
            heading = _heading_of(stripped)
            continue
        if not buffer:
            buffer_start = position
        buffer.append(stripped)
    flush()
    return segments


def _file_blocks(filename: str, text: str, max_chars: int, min_chars: int) -> list[Block]:
    """一份材料切成块。块号先占位，最后统一重排（合并短块会让编号断开）。"""
    blocks: list[Block] = []
    heading = ""
    buffer: list[str] = []
    buffer_start = 0

    def flush() -> None:
        nonlocal buffer
        body = "\n\n".join(buffer).strip()
        buffer = []
        if not body:
            return
        blocks.append(
            Block(
                id=f"S{len(blocks) + 1}",
                file=filename,
                seq=len(blocks) + 1,
                heading=heading,
                text=body,
                start=buffer_start,
            )
        )

    for segment_heading, body, start in _segments(text):
        # 换标题就换块：一块里横跨两个小节，检索命中后注入的上下文会自相矛盾
        if buffer and segment_heading != heading:
            flush()
        if not buffer:
            heading = segment_heading
            buffer_start = start
        for piece in _split_long(body, max_chars):
            if buffer and sum(len(item) for item in buffer) + len(piece) > max_chars:
                flush()
                heading = segment_heading
                buffer_start = start
            buffer.append(piece)
    flush()

    # 太短的尾巴并回上一块，避免末块只有一行字还占一个编号。
    # 但只在同一小节内合并：跨小节并块会让「库存」这一块里混进「下一步」的内容，
    # 检索命中后注入的上下文跟用户问的对不上，比不合并更糟。
    if len(blocks) >= 2 and blocks[-1].chars < min_chars:
        last = blocks[-1]
        previous = blocks[-2]
        same_section = previous.heading == last.heading or not last.heading
        if same_section and previous.chars + last.chars <= HARD_BLOCK_CHARS:
            blocks[-2] = Block(
                id=previous.id,
                file=previous.file,
                seq=previous.seq,
                heading=previous.heading or last.heading,
                text=f"{previous.text}\n\n{last.text}",
                start=previous.start,
            )
            blocks.pop()
    return blocks


def split_blocks(
    sources: Sequence[dict[str, Any]],
    max_chars: int = MAX_BLOCK_CHARS,
    min_chars: int = MIN_BLOCK_CHARS,
) -> list[Block]:
    """把素材切成可检索的块，编号 S1…Sn 全局连续。

    编号要连续：它同时是引用（`[S3]`）和补读的坐标（`block_ids=["S3"]`）。
    合并短块会让中途空号，模型照着写 `[S7]` 却翻不到那一条时，它只会换个编号瞎标。
    """
    raw: list[Block] = []
    for source in sources:
        filename = str(source.get("filename") or "素材")
        text = str(source.get("text") or "")
        if text.strip():
            raw.extend(_file_blocks(filename, text, max_chars, min_chars))
    return [
        Block(
            id=f"S{index}",
            file=block.file,
            seq=block.seq,
            heading=block.heading,
            text=block.text,
            start=block.start,
        )
        for index, block in enumerate(raw, 1)
    ]


def outline(blocks: Sequence[Block]) -> str:
    """分节目录：告诉模型「这份材料一共有哪些块」，它才知道自己没读全。"""
    if not blocks:
        return "（没有可检索的内容）"
    totals = Counter(block.file for block in blocks)
    lines: list[str] = []
    current_file = ""
    for block in blocks:
        if block.file != current_file:
            current_file = block.file
            lines.append(f"《{current_file}》共 {totals[current_file]} 块")
        head = block.heading or f"第 {block.seq} 块"
        lines.append(f"  {block.id} {head}（{block.chars} 字）")
    return "\n".join(lines)


def pack_blocks(blocks: Sequence[Block], budget: int) -> tuple[str, int]:
    """按顺序装块直到预算用完，返回（正文, 装入块数）。用于 file.read 的超长降级。"""
    used: list[str] = []
    total = 0
    for block in blocks:
        if total + block.chars > budget and used:
            break
        used.append(f"{block.label}\n{block.text}")
        total += block.chars
    return "\n\n".join(used), len(used)


# ---------------------------------------------------------------- 检索

_K1 = 1.2
_B = 0.75


class Index:
    """BM25 倒排索引。块数在几十到几百的量级，纯 Python 足够快。"""

    def __init__(self, blocks: Sequence[Block]) -> None:
        self.blocks = list(blocks)
        self._tf: list[Counter[str]] = []
        self._length: list[int] = []
        df: Counter[str] = Counter()
        for block in self.blocks:
            terms = _terms(f"{block.heading} {block.text}")
            counts = Counter(terms)
            self._tf.append(counts)
            self._length.append(len(terms))
            df.update(counts.keys())
        self._df = df
        self._total = len(self.blocks)
        self._avg = (sum(self._length) / self._total) if self._total else 0.0
        self._idf = {
            term: math.log(1 + (self._total - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def __len__(self) -> int:
        return len(self.blocks)

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        terms = _terms(query)
        if not terms or not self.blocks:
            return []
        queries = set(terms)
        support = len([term for term in queries if term in self._idf]) / len(queries)
        ranked: list[Hit] = []
        for position, counts in enumerate(self._tf):
            score = 0.0
            for term in queries:
                freq = counts.get(term)
                if not freq:
                    continue
                idf = self._idf.get(term, 0.0)
                length = self._length[position] or 1
                score += (
                    idf
                    * freq
                    * (_K1 + 1)
                    / (freq + _K1 * (1 - _B + _B * length / (self._avg or 1)))
                )
            if score <= 0:
                continue
            ranked.append(
                Hit(
                    block=self.blocks[position],
                    score=score,
                    coverage=self._coverage(queries, counts),
                    support=support,
                )
            )
        ranked.sort(key=lambda hit: (hit.score, hit.coverage), reverse=True)
        return ranked[: max(1, top_k)]

    def _coverage(self, queries: set[str], counts: Counter[str]) -> float:
        """查询里「素材确实有这个词」的部分，有多少落在这一块上。

        分母只算索引里存在的词，这是刻意的：中文 bigram 会产生「报写」这种
        跨词噪声，它当然不在索引里；把它算进分母，任何一句正常提问的覆盖度
        都会被拉到「没找到」。而「退货政策」这种整句词都不在索引的情况，
        分母为空 → 覆盖度 0 → 判「没找到」，正是我们要的结果。
        """
        known = [term for term in queries if term in self._idf]
        if not known:
            return 0.0
        total = sum(self._idf[term] for term in known)
        if total <= 0:
            return 0.0
        hit = sum(self._idf[term] for term in known if term in counts)
        return hit / total


def match_level(hits: Sequence[Hit]) -> str:
    """strong / weak / none —— 给模型的一句实话，不是给它一个分数。

    两个维度都要看：
    - coverage：命中的块是否真的把查询讲全了；
    - support：查询里的词有多少是素材认识的。问的事情素材压根没写，support 就低，
      这时候 coverage 再高也只是「恰好命中了其中半句」。
    只看 coverage 会把「营收和员工餐补」判成 strong——素材里没有餐补，模型却
    拿到了一个「很相关」的结论标签，接下来它就会顺着餐补往下编。
    """
    if not hits:
        return "none"
    best = max(hit.coverage for hit in hits)
    support = max(hit.support for hit in hits)
    if best < 0.34:
        return "none"
    # support 只把 strong 降成 weak，不降到 none。它量的是「查询词有多少是素材认识的」，
    # 而概述类提问（「帮我看看这个项目整体怎么样」）天生词少又泛，support 必然低——
    # 判成 none 就成了「素材里没有」，可素材明明全在那儿。低 support 的正确含义是
    # 「可能只答上的一部分」，交给模型按片段核对，而不是替它宣布没有。
    if best < 0.6 or support < 0.45:
        return "weak"
    return "strong"


def format_passages(hits: Sequence[Hit], total_blocks: int = 0, level: str = "") -> str:
    """把命中块排成注入文本。每块前面带编号，模型才能写出 `[S3]` 这样的引用。"""
    if not hits:
        return "（没有检索到相关片段）"
    parts: list[str] = []
    for hit in hits:
        parts.append(f"{hit.block.label}\n{hit.block.text}")
    body = "\n\n".join(parts)
    head = f"检索到 {len(hits)} 段"
    if total_blocks:
        head += f"（素材共 {total_blocks} 块）"
    if level == "weak":
        head += "，相关度偏低，使用前请核对是否真的对得上问题"
    return f"{head}：\n\n{body}"


# ---------------------------------------------------------------- 落地校验

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 数字后面紧跟这些，说明它是在编号（「1. 结论」），不是在陈述一个事实
_ORDINAL_TAIL = (".", "、", "．", ")")


def _numbers(text: str) -> set[str]:
    """抽出所有数字的归一化写法：`1,200` / `1200.0` / `1200` 都算同一个数。"""
    values: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0).replace(",", "").strip()
        if not raw:
            continue
        values.add(raw)
        try:
            number = float(raw)
        except ValueError:
            continue
        values.add(f"{number:.10g}")
        if number == int(number):
            values.add(str(int(number)))
    return values


def unsupported_facts(
    text: str, sources: Sequence[dict[str, Any]], limit: int = 12
) -> list[dict[str, str]]:
    """回查：正文里的数字，素材里到底有没有。

    只管数字，因为数字是幻觉里最容易露馅、也最容易机器判定的一类——「提升 12%」
    的 12 是从哪来的，查得到或查不到是确定的事实。措辞层面的编造（把「略有下降」
    写成「显著下降」）机器判不了，靠提示词约束与引用编号让人去看原文。

    只报告，不阻断：拦截会把「素材里写的是 1.2 万，稿子里写成 12000」这种
    等价表述误判成幻觉，最后变成正常交付也被打回。
    """
    corpus = "\n".join(str(source.get("text") or "") for source in sources)
    known = _numbers(corpus)
    if not corpus.strip():
        return []
    seen: set[str] = set()
    missing: list[dict[str, str]] = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0).replace(",", "").strip()
        if not raw or raw in seen:
            continue
        # 行首编号：「1. 关键结论」里的 1 不是事实
        rest = text[match.end() : match.end() + 1]
        line_head = text[text.rfind("\n", 0, match.start()) + 1 : match.start()]
        if rest in _ORDINAL_TAIL and not line_head.strip():
            continue
        values = {raw}
        try:
            number = float(raw)
            values.add(f"{number:.10g}")
            if number == int(number):
                values.add(str(int(number)))
        except ValueError:
            pass
        if values & known:
            continue
        seen.add(raw)
        context = text[max(0, match.start() - 12) : match.end() + 12].replace("\n", " ")
        missing.append({"value": raw, "context": context.strip()})
        if len(missing) >= limit:
            break
    return missing
