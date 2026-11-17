"""asr_proofread.py —— 用大模型给转写稿挑同音字，但**只允许换词**。

**为什么需要第二层。** 热词进了 `initial_prompt` 之后，模型选字已经会往对的方向偏，
但 `base` 档的中文语言模型太浅，硬伤还会漏（「客户厌收」「排齐」）。这一层把整段
转写连同热词一起交给大一点的模型，让它按上下文指出「这里应该是哪个词」。

**契约（别放宽，放宽就等于让它改稿）。** 模型只被允许交回「错写法 → 正确写法」的
配对，代码侧再做四道闸：

1. **等长**：两个词字数必须相同。同音字错写本来就等长，这一条直接堵死增删内容；
2. **原件存在**：错写法必须在原文里原样出现，否则丢弃；
3. **次数上限**：同一个错写法出现超过 3 次就跳过 —— 那多半是个正常词，不是笔误；
4. **总条数上限**：一次最多接受 40 处，防止模型「顺手全改一遍」。

任何一步失败（没配 Key、超时、返回不是 JSON、网络错）都**原样返回原文**。宁可
一个字不改，也不能把用户的录音改出他没说过的话。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence

from ..core.config import Settings
from ..providers.registry import build_configured_providers

#: 一次交给模型的字数。太长（几万字）既贵又容易让模型「开始总结」；
#: 按行切块、逐块校对，块与块之间不重叠（替换只发生在块内）。
_CHUNK_CHARS = 6000

#: 单块请求的超时。转写本身要跑几分钟，这里多等十几秒不算什么；
#: 但卡住就得放弃，否则一个坏网关能把整个识别队列堵死。
_CHUNK_TIMEOUT = 15.0

#: 一次校对最多接受多少处替换
_MAX_PAIRS = 40

#: 同一个「错写法」在原文出现超过这么多次就跳过（多半是正常词）
_MAX_SAME_FORM = 3

_SYSTEM = """你是会议录音转写稿的校对员。下面这段是语音识别的结果，可能有个别同音字写错
（例如把「验收」写成「厌收」，把「排期」写成「排齐」）。

你只做一件事：把写错的词换成正确的写法。

硬性规则：
1. 只能替换**字数相同**的词。
2. 不许改写句子、不许调整语序、不许增删内容、不许动标点和时间戳。
3. 没有把握就不要改；宁可漏改，不可改错。
4. 只输出 JSON 数组，每个元素是 ["错写法","正确写法"]；没有错误就输出 []。
   除了这个数组，不要输出任何别的内容。"""


def _strip_fence(text: str) -> str:
    """模型偶尔会套 ```json 围栏，去掉再解析。"""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def parse_pairs(raw: str) -> list[tuple[str, str]]:
    """从模型回复里取出配对；格式不对就当没改。"""
    text = _strip_fence(raw)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    pairs: list[tuple[str, str]] = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            wrong, right = str(item[0]).strip(), str(item[1]).strip()
            if wrong and right and wrong != right and (wrong, right) not in pairs:
                pairs.append((wrong, right))
    return pairs


def apply_pairs(text: str, pairs: Sequence[tuple[str, str]]) -> tuple[str, list[tuple[str, str]]]:
    """把配对照到正文上，逐条过四道闸。"""
    applied: list[tuple[str, str]] = []
    for wrong, right in pairs:
        if len(applied) >= _MAX_PAIRS:
            break
        if len(wrong) != len(right):  # 等长：杜绝增删内容
            continue
        if wrong not in text:  # 原文里没有这个写法
            continue
        if text.count(wrong) > _MAX_SAME_FORM:  # 出现太多次 → 多半是正常词
            continue
        text = text.replace(wrong, right)
        applied.append((wrong, right))
    return text, applied


def _chunks(text: str) -> list[str]:
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > _CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


async def _ask(provider, chunk: str, hotwords: Sequence[str]) -> str:
    words = "、".join(hotwords) if hotwords else "（无）"
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"参考词表：{words}\n\n转写稿：\n{chunk}"},
    ]
    result = await asyncio.wait_for(
        provider.chat(messages, temperature=0.0), timeout=_CHUNK_TIMEOUT
    )
    return str(getattr(result, "text", "") or "")


def proofread(
    text: str,
    hotwords: Sequence[str] = (),
    *,
    settings: Settings,
) -> tuple[str, list[tuple[str, str]]]:
    """返回 (校对后的文本, 实际替换的配对)。没有可用的模型就原样返回。"""
    if not text.strip():
        return text, []
    try:
        providers = build_configured_providers(settings)
    except Exception:  # pragma: no cover - 配置异常不该影响识别结果
        return text, []
    if not providers:
        return text, []
    provider = next(iter(providers.values()))

    corrected: list[str] = []
    applied_all: list[tuple[str, str]] = []
    for chunk in _chunks(text):
        try:
            reply = asyncio.run(_ask(provider, chunk, hotwords))
        except Exception:
            # 超时 / 网络错 / 供应商报错：这一块保持原样，后面的块也不用再试
            corrected.append(chunk)
            continue
        fixed, applied = apply_pairs(chunk, parse_pairs(reply))
        corrected.append(fixed)
        applied_all.extend(applied)
        if len(applied_all) >= _MAX_PAIRS:
            break
    return "\n".join(corrected), applied_all[:_MAX_PAIRS]
