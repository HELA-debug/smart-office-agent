"""上下文窗口：轮次归集、预算裁切、压缩摘要。

这一层是「多轮对话不失忆」的地基，重点覆盖三件事：
1. 只把成对轮次（用户说过 + 助手答过）当历史，半截轮次不能进；
2. 超预算时保留最近的轮次，被挤掉的必须变成摘要而不是凭空消失；
3. 单条超长消息要截断，不能一条回复吃掉整个窗口。
"""

from __future__ import annotations

from app.agents.context_window import (
    TRUNCATED_SUFFIX,
    build_plan,
    collect_turns,
    plan_from_messages,
    summarize_turns,
)
from app.domain.entities import Message


def _msg(role: str, content: str, run_id: str = "r1", mid: str = "") -> Message:
    return Message(
        id=mid or f"m-{role}-{content[:6]}-{run_id}",
        thread_id="t1",
        role=role,
        content=content,
        run_id=run_id,
        created_at="2026-10-30T21:00:00+08:00",
    )


def _turn(run_id: str, user: str, assistant: str) -> list[Message]:
    return [_msg("user", user, run_id), _msg("assistant", assistant, run_id)]


# ---------------------------------------------------------------- 轮次归集
def test_collect_turns_pairs_user_and_assistant_by_run() -> None:
    turns = collect_turns(
        _turn("r1", "把这份材料整理成周报", "已生成周报 docx")
        + _turn("r2", "改成八号字", "已调整正文字号")
    )
    assert [turn.user for turn in turns] == ["把这份材料整理成周报", "改成八号字"]
    assert [turn.assistant for turn in turns] == ["已生成周报 docx", "已调整正文字号"]


def test_collect_turns_drops_half_finished_run() -> None:
    """用户发了但没答完（取消/失败）的那一轮不进历史：否则重试时同一句话会出现两遍。"""
    messages = [*_turn("r1", "第一轮", "第一轮答复"), _msg("user", "第二轮还没跑完", "r2")]
    turns = collect_turns(messages)
    assert len(turns) == 1
    assert turns[0].user == "第一轮"


def test_collect_turns_ignores_run_summary_and_empty_content() -> None:
    messages = [
        _msg("run_summary", "系统摘要行", "r0"),
        _msg("user", "   ", "r1"),
        _msg("assistant", "", "r1"),
        *_turn("r2", "正式的一轮", "正式答复"),
    ]
    turns = collect_turns(messages)
    assert len(turns) == 1
    assert turns[0].user == "正式的一轮"


def test_collect_turns_is_stable_when_assistant_recorded_first() -> None:
    """仓储按秒级时间戳排序，同一秒内顺序不可靠；按 run 归组后必须仍是用户在前。"""
    messages = [_msg("assistant", "答复", "r1"), _msg("user", "问题", "r1")]
    turns = collect_turns(messages)
    assert turns[0].user == "问题"
    assert turns[0].assistant == "答复"


def test_collect_turns_keeps_legacy_messages_without_run_id() -> None:
    legacy = Message(
        id="m-legacy",
        thread_id="t1",
        role="user",
        content="改造前的老消息",
        run_id=None,
        created_at="2026-10-01T09:00:00+08:00",
    )
    # 老消息没有助手侧答复 → 不进历史，但也不能把整批轮次带崩
    assert collect_turns([legacy]) == []
    assert len(collect_turns([legacy, *_turn("r1", "新的一轮", "新答复")])) == 1


# ---------------------------------------------------------------- 预算裁切
def test_build_plan_keeps_recent_turns_and_summarizes_the_rest() -> None:
    turns = collect_turns(
        [
            msg
            for index in range(5)
            for msg in _turn(f"r{index}", f"第{index}个请求", f"第{index}个答复")
        ]
    )
    plan = build_plan(turns, max_turns=2)
    assert plan.turns_kept == 2
    assert plan.turns_dropped == 3
    assert plan.compacted is True
    # 保留的必须是最近的
    assert plan.messages[0]["content"] == "第3个请求"
    # 被挤掉的要在摘要里留下痕迹，不能静默丢失
    assert "第0个请求" in plan.summary
    assert plan.meta()["dropped_turns"] == 3


def test_build_plan_without_history_is_not_marked_compacted() -> None:
    plan = build_plan([])
    assert plan.messages == []
    assert plan.summary == ""
    assert plan.compacted is False
    assert plan.meta()["kept_turns"] == 0


def test_build_plan_always_keeps_the_latest_turn_even_if_over_char_budget() -> None:
    """最近一轮再长也要留下：否则用户刚说完就失忆，压缩反而更伤。"""
    turns = collect_turns(_turn("r1", "很长的问题" * 400, "很长的答复" * 400))
    plan = build_plan(turns, max_chars=100)
    assert plan.turns_kept == 1
    assert plan.messages, "最近一轮被预算丢掉了"


def test_build_plan_truncates_single_long_message() -> None:
    turns = collect_turns(_turn("r1", "问题", "答" * 5000))
    plan = build_plan(turns, max_turn_chars=200)
    assert len(plan.messages[1]["content"]) < 300
    assert plan.messages[1]["content"].endswith(TRUNCATED_SUFFIX)


def test_build_plan_respects_char_budget_between_turns() -> None:
    turns = collect_turns(
        [msg for index in range(4) for msg in _turn(f"r{index}", "问" * 100, "答" * 100)]
    )
    plan = build_plan(turns, max_turns=0, max_chars=450, max_turn_chars=0)
    # 每轮约 200 字：450 的预算只装得下两轮
    assert plan.turns_kept == 2
    assert plan.turns_dropped == 2


# ---------------------------------------------------------------- 摘要
def test_summary_is_capped_and_marks_omitted_turns() -> None:
    turns = collect_turns(
        [msg for index in range(10) for msg in _turn(f"r{index}", "问" * 60, "答" * 60)]
    )
    summary = summarize_turns(turns, max_chars=200)
    assert summary.startswith("【更早的对话（已压缩）】")
    assert "未展开" in summary
    assert len(summary) < 600


def test_summary_of_empty_input_is_empty() -> None:
    assert summarize_turns([]) == ""


# ---------------------------------------------------------------- 入口封装
def test_plan_from_messages_excludes_given_message_ids() -> None:
    messages = _turn("r1", "上一轮", "上一轮答复")
    current = _msg("user", "这一轮", "r2", mid="m-current")
    plan = plan_from_messages([*messages, current], exclude_message_ids=("m-current",))
    assert plan.turns_total == 1
    assert plan.messages[0]["content"] == "上一轮"
