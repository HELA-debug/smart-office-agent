"""对话上下文窗口：把会话历史整理成模型能读的消息，并超预算时做压缩。

## 为什么需要这一层

改造前 `RealEngine._initial_messages()` 只拼 `system + 本轮用户消息`，**历史一条都不带**：
会话在界面上是连续的，模型却是每轮失忆。用户说「把刚才那份改成 8 号字」，
模型并不知道「刚才那份」是什么，只能重问或重做一遍。

## 这里的职责边界

- 只做「挑哪些历史 / 压到多短 / 拼成什么形状」，不碰模型、不碰数据库、不抛业务异常；
- 输入是已经落库的 `Message` 实体，输出是纯数据（`ContextPlan`），因此可以离线单测；
- 压缩是**抽取式**（不额外调一次模型）：多轮对话里真正有用的是「用户要什么 / 助手给了什么」，
  原文摘句已经够模型对齐指代，比再花一次模型调用更可预测、也更省钱。
  需要更强的摘要能力时，把 `summarize_turns()` 换成一个走模型的实现即可，调用方不用改。

## 压缩规则（可配，见 Settings.context_*）

1. 只保留「用户有话说 + 助手已答复」的成对轮次；失败的半截轮次（用户发了但没答完）不进历史，
   否则重试时模型会看到同一句话出现两遍。
2. 从最近一轮往前装，超过 `max_turns` 轮或 `max_chars` 字符就停，剩下的进摘要。
3. 单条消息过长会被截断（`max_turn_chars`），避免一条万字回复把整个窗口吃满。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..domain.entities import Message

DEFAULT_MAX_TURNS = 8
DEFAULT_MAX_CHARS = 6000
DEFAULT_MAX_TURN_CHARS = 1200
DEFAULT_SUMMARY_CHARS = 800
#: 摘要里每条轮次单侧最多保留多少字（用户那句 / 助手那句各算）
SUMMARY_SIDE_CHARS = 60

TRUNCATED_SUFFIX = "…（已截断）"


@dataclass(frozen=True)
class ContextTurn:
    """一轮「用户说 → 助手答」。`run_id` 为空表示改造前没有 run 关联的老消息。"""

    user: str
    assistant: str
    run_id: str | None = None
    created_at: str = ""

    @property
    def chars(self) -> int:
        return len(self.user) + len(self.assistant)


@dataclass(frozen=True)
class ContextPlan:
    """一次运行要带上的历史（不含本轮用户消息）。"""

    messages: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    turns_total: int = 0
    turns_kept: int = 0
    turns_dropped: int = 0
    chars: int = 0

    @property
    def compacted(self) -> bool:
        return self.turns_dropped > 0 or bool(self.summary)

    def meta(self) -> dict[str, Any]:
        """`context.compacted` 事件的 data（前端可忽略，运维/排障要看）。"""
        return {
            "turns_total": self.turns_total,
            "kept_turns": self.turns_kept,
            "dropped_turns": self.turns_dropped,
            "summary_chars": len(self.summary),
            "chars": self.chars,
        }


def collect_turns(messages: Iterable[Message]) -> list[ContextTurn]:
    """把扁平的 message 列表聚成交替轮次。

    规则：
    - `run_summary`（模板/兜底写入的系统摘要行）不进上下文；
    - 按 run 分组，同组内用户在前、助手在后 —— 仓储按 `created_at` 排序，而时间戳只到秒，
      同一秒内的两条消息顺序并不可靠；按 run 分组能消掉这个不确定性；
    - 没有 run_id 的老消息按出现顺序各自成轮（只有用户侧时助手侧留空，随后被丢弃）。
    """
    order: list[str | None] = []
    buckets: dict[str | None, dict[str, list[str]]] = {}
    for message in messages:
        role = (message.role or "").strip()
        if role not in ("user", "assistant"):
            continue
        content = (message.content or "").strip()
        if not content:
            continue
        key = message.run_id or f"legacy:{message.id}"
        if key not in buckets:
            buckets[key] = {"user": [], "assistant": []}
            order.append(key)
        buckets[key][role].append(content)

    turns: list[ContextTurn] = []
    for key in order:
        bucket = buckets[key]
        user = "\n".join(bucket["user"]).strip()
        assistant = "\n".join(bucket["assistant"]).strip()
        if not assistant:
            # 只发未答（用户取消 / 运行失败 / 正在重试的那一轮）：不进历史，
            # 否则重试同一句话时模型会看到自己「回答过」同一个问题。
            continue
        run_id = key if not key.startswith("legacy:") else None
        turns.append(ContextTurn(user=user, assistant=assistant, run_id=run_id))
    return turns


def _clip(text: str, limit: int) -> str:
    if limit > 0 and len(text) > limit:
        return text[:limit].rstrip() + TRUNCATED_SUFFIX
    return text


def summarize_turns(turns: Sequence[ContextTurn], max_chars: int = DEFAULT_SUMMARY_CHARS) -> str:
    """把被挤出窗口的轮次压成一段要点（抽取式，不调模型）。

    倒着写（越近的越靠前）再翻回来，保证预算不够时优先保住离现在最近的信息。
    """
    if not turns or max_chars <= 0:
        return ""
    lines: list[str] = []
    used = 0
    omitted = 0
    for turn in reversed(turns):
        head = _clip(turn.user.replace("\n", " "), SUMMARY_SIDE_CHARS) or "（无正文）"
        tail = _clip(turn.assistant.replace("\n", " "), SUMMARY_SIDE_CHARS)
        line = f"- {head} → {tail}" if tail else f"- {head}"
        if used + len(line) > max_chars:
            omitted += 1
            continue
        lines.append(line)
        used += len(line)
    lines.reverse()
    if omitted:
        lines.insert(0, f"- （另有 {omitted} 轮更早的对话未展开）")
    return "【更早的对话（已压缩）】\n" + "\n".join(lines)


def build_plan(
    turns: Sequence[ContextTurn],
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_turn_chars: int = DEFAULT_MAX_TURN_CHARS,
    summary_chars: int = DEFAULT_SUMMARY_CHARS,
) -> ContextPlan:
    """按预算从最近往前装轮次，装不下的进摘要。"""
    budget_turns = max(0, max_turns)
    budget_chars = max(0, max_chars)
    kept: list[ContextTurn] = []
    used = 0
    for turn in reversed(turns):
        if budget_turns and len(kept) >= budget_turns:
            break
        cost = len(_clip(turn.user, max_turn_chars)) + len(_clip(turn.assistant, max_turn_chars))
        # 最近一轮无论多长都要留下（kept 为空时继续）：否则「刚说完就失忆」，压缩反而更伤
        if budget_chars and used + cost > budget_chars and kept:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    dropped = list(turns)[: len(turns) - len(kept)]

    messages: list[dict[str, Any]] = []
    for turn in kept:
        messages.append({"role": "user", "content": _clip(turn.user, max_turn_chars)})
        messages.append({"role": "assistant", "content": _clip(turn.assistant, max_turn_chars)})
    return ContextPlan(
        messages=messages,
        summary=summarize_turns(dropped, summary_chars) if dropped else "",
        turns_total=len(turns),
        turns_kept=len(kept),
        turns_dropped=len(dropped),
        chars=sum(len(item["content"]) for item in messages),
    )


def plan_from_messages(
    messages: Sequence[Message],
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_turn_chars: int = DEFAULT_MAX_TURN_CHARS,
    summary_chars: int = DEFAULT_SUMMARY_CHARS,
    exclude_message_ids: Iterable[str] = (),
) -> ContextPlan:
    """落库消息 → 上下文计划（`exclude_message_ids` 用于剔除本轮刚开始写入的那条）。"""
    excluded = {item for item in exclude_message_ids if item}
    filtered = [message for message in messages if message.id not in excluded]
    return build_plan(
        collect_turns(filtered),
        max_turns=max_turns,
        max_chars=max_chars,
        max_turn_chars=max_turn_chars,
        summary_chars=summary_chars,
    )
