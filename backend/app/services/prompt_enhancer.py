"""提示词增强：把输入框里随手写的一句话，补成「模型能照着做」的指令。

两种来源，对调用方是同一个形状（`{text, source, model, note}`）：

- ``model``：当前配了真实模型，让模型改写；
- ``rules``：演示模式 / 没配 Key / 模型这次没调通，用本地规则补出结构骨架。

为什么要有 rules 兜底：这个按钮就摆在输入框上，点了却报「没配置模型」比没这个按钮更糟。
规则版只补「怎么干」（结构、篇幅、别编造），绝不替用户编内容——补错了比不补更误导。

两件事刻意不做：
1. 不写库、不改运行期状态。用户点一下只是换掉输入框里的字，不满意可以再点、也可以直接改；
2. 不追加历史。每次都只以「当前输入框内容」为起点，连点两次不会越滚越长。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..core.logging import get_logger
from ..domain.formats import FORMAT_LABELS

logger = get_logger("app.services.prompt_enhancer")

MAX_INPUT_CHARS = 4000
MAX_OUTPUT_CHARS = 1500
TIMEOUT_SECONDS = 20.0
# 太短的改写等于没改（模型常回一句「请描述你的需求」），直接判无效
MIN_OUTPUT_CHARS = 12

# 明显是「在解释自己 / 在向我提问」而不是给改写结果
_REJECT_HINTS = ("无法", "抱歉", "作为", "助手", "请提供", "请描述", "需要你")

_PREFIX_PATTERN = re.compile(
    r"^\s*(?:以下是|下面是)?\s*(?:改写|增强|优化|润色)(?:后|过)?的?\s*(?:提示词|prompt|指令)[:：]?\s*",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "你是提示词改写助手。用户会给你一句办公需求，请把它改写成更清晰、可直接执行的提示词：\n"
    "1. 保留原意与关键对象（要处理什么材料、最终要什么东西），不新增事实、不编造素材内容；\n"
    "2. 补上可执行的要求：输出结构、篇幅、语气、必要的约束（例如「只用素材里的信息」）；\n"
    "3. 用 3-6 行短句分点写，不要长段落；\n"
    "4. 全文不超过 300 字；\n"
    "5. 只输出改写后的提示词本身：不要解释、不要加引号、不要写「以下是」。\n"
    "如果用户的需求本身已经足够清楚，就只做小幅补充，不要换掉他的说法。"
)


def _strip_fence(text: str) -> str:
    """模型爱把结果包进 ``` 代码块；围栏不是提示词的一部分。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def clean_enhanced(raw: str) -> str:
    """把模型输出收拾成可以直接放进输入框的文本；不合格返回空串。

    判不合格的三种情况：空的、去掉「以下是改写后的提示词：」这类前缀后仍为空、
    或者干脆是在向我提问（「请提供更多信息」）。
    """
    text = _strip_fence(raw or "")
    if not text:
        return ""
    text = _PREFIX_PATTERN.sub("", text, count=1).strip()
    # 整段被引号/书名号包住时去掉外层（模型喜欢「」包住整段）
    if len(text) >= 2 and text[0] in "「“\"'《" and text[-1] in "」”\"'》":
        text = text[1:-1].strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return ""
    if len(text) < MIN_OUTPUT_CHARS:
        return ""
    head = text.splitlines()[0]
    if any(hint in head for hint in _REJECT_HINTS):
        return ""
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS].rstrip() + "…"
    return text


def _target_length(text: str) -> str:
    """从原话里捡「600 字」「约 800 字」这类篇幅要求，捡不到就不写，别硬塞一个数。"""
    match = re.search(r"(\d{2,5})\s*(?:字|词|words?)", text, re.IGNORECASE)
    return f"约 {match.group(1)} 字" if match else "按内容长短自适应"


def rule_based_prompt(text: str, output_format: str | None = None) -> str:
    """本地规则增强：只补「怎么干」，不替用户编内容。

    刻意保持通用——不知道用户要周报还是合同台账，就不要猜小标题；
    猜错了用户还得逐条删，比空白更烦。
    """
    source = (text or "").strip()
    lines = [f"任务：{source}"]
    label = FORMAT_LABELS.get((output_format or "").strip().lower())
    if label:
        lines.append(f"输出格式：{label}")
    lines.append(f"目标篇幅：{_target_length(source)}")
    lines.append("要求：")
    lines.append("1. 先说结论，再给依据（依据最多 3 条，每条一句话）")
    lines.append("2. 分点分段、小标题加粗，便于扫读")
    lines.append("3. 只使用我提供的素材；素材里没有的就说「素材未提及」，不要编造")
    return "\n".join(lines)


def _same_as_source(result: str, source: str) -> bool:
    def squash(value: str) -> str:
        return re.sub(r"\s+", "", value)

    return squash(result) == squash(source)


async def enhance_prompt(
    router: Any,
    settings: Any,
    text: str,
    *,
    output_format: str | None = None,
) -> dict[str, Any]:
    """改写一句需求；任何失败都退回规则版，并把原因写进 note。"""
    source = (text or "").strip()[:MAX_INPUT_CHARS]
    if not source:
        return {"text": "", "source": "rules", "model": "", "note": "先写一句需求，再点增强"}

    rules_text = rule_based_prompt(source, output_format)
    unavailable_note = "现在没有可用的模型（演示模式或还没配 Key），已按通用结构补全"

    if router is None or not getattr(settings, "real_model_configured", False):
        return {"text": rules_text, "source": "rules", "model": "", "note": unavailable_note}

    material = f"原需求：{source}"
    label = FORMAT_LABELS.get((output_format or "").strip().lower())
    if label:
        material += f"\n期望产物格式：{label}"
    try:
        result = await asyncio.wait_for(
            router.chat_with_tools(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": material},
                ],
                tools=None,
                temperature=0.4,
                max_tokens=800,
                purpose="enhance",
            ),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:  # 网络 / 超时 / 未配置都不该让按钮变成错误
        logger.info("提示词增强失败，退回本地规则：%s", exc)
        return {
            "text": rules_text,
            "source": "rules",
            "model": "",
            "note": "模型这次没调通，已按通用结构补全",
        }

    enhanced = clean_enhanced(getattr(result, "text", "") or "")
    if not enhanced or _same_as_source(enhanced, source):
        logger.info(
            "提示词增强结果不可用，退回本地规则：%r", (getattr(result, "text", "") or "")[:80]
        )
        return {
            "text": rules_text,
            "source": "rules",
            "model": "",
            "note": "模型的改写结果不理想，已按通用结构补全",
        }

    return {
        "text": enhanced,
        "source": "model",
        "model": getattr(result, "model", "") or "",
        "note": "",
    }


__all__ = [
    "MAX_INPUT_CHARS",
    "MAX_OUTPUT_CHARS",
    "clean_enhanced",
    "enhance_prompt",
    "rule_based_prompt",
]
