"""会话标题助手：让模型把用户第一句需求压成一个「看得懂在做什么」的短名字。

为什么不用「截断第一句」：一句「把这份材料整理成 600 字周报」会连着出现好几次，
列表里三行一模一样，用户根本分不清哪个是哪个。改成模型概括后，
标题会带上对象（哪份材料、做什么东西），一眼能挑。

失败/超时一律返回空串，由调用方保留规则式标题——命名是锦上添花，不能拖住运行。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from typing import Any

from ..core.logging import get_logger

logger = get_logger("app.services.title_suggester")

MAX_TITLE_CHARS = 24
TIMEOUT_SECONDS = 3.0
# 明显是「在解释自己」而不是给标题的回复，直接弃用
_REJECT_HINTS = ("标题", "抱歉", "无法", "作为", "助手", "以下是")

_SYSTEM_PROMPT = (
    "你是会话命名助手。用户刚提出一个办公任务，请给出一个能概括任务的短标题："
    "6-14 个汉字，突出「动作 + 对象」（例如「证书材料整理成周报」「合同条款比对」），"
    "不要引号、不要标点结尾、不要解释，也不要出现「标题」二字。只输出标题本身。"
)


def clean_title(text: str) -> str:
    """把模型输出收拾成可入库的短标题；不合格就返回空串。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    first = raw.splitlines()[0].strip()
    first = first.strip("「」《》【】\"'`“”‘’。，,、：:！!？?")
    first = re.sub(r"^[0-9一二三四五六七八九十]+[.、)）]\s*", "", first)
    first = re.sub(r"\s+", " ", first).strip()
    if len(first) < 2 or len(first) > MAX_TITLE_CHARS:
        return ""
    if any(hint in first for hint in _REJECT_HINTS):
        return ""
    return first


async def suggest_title(
    router: Any,
    message: str,
    attachments: Iterable[str] = (),
) -> str:
    """让模型给这次会话起个名字；任何异常都吞掉并返回空串。"""
    material = f"用户需求：{(message or '').strip()[:400]}"
    names = [name for name in attachments if name][:5]
    if names:
        material += f"\n素材：{'、'.join(names)}"
    try:
        result = await asyncio.wait_for(
            router.chat_with_tools(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": material},
                ],
                tools=None,
                temperature=0.3,
                max_tokens=40,
                purpose="title",
            ),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:  # 网络/未配置/超时都不该影响运行
        logger.info("会话标题生成失败，沿用规则标题：%s", exc)
        return ""
    title = clean_title(getattr(result, "text", ""))
    if not title:
        logger.info("会话标题不可用，沿用规则标题：%r", getattr(result, "text", "")[:60])
    return title
