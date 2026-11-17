"""理解层与写权限门控。

这里只测**确定性**的部分：解析容错、兜底方向、门控判定。
「模型读得准不准」不在这里测——那是评估集的事（`scripts/eval_reading.py`
配合 `tests/data/utterances.jsonl`），因为断言一个模型对某句话的读法，
换一版模型就会红，那种测试只会让人关掉它。
"""

from __future__ import annotations

import json

import pytest
from app.agents.policy import (
    REASON_AUTHORIZED,
    REASON_DIRECT,
    REASON_HOLD,
    REASON_LONG_MESSAGE,
    REASON_LOW_RISK,
    REASON_NOT_COMMITTED,
    REASON_RETRACTED,
    TRUNCATION_ELEVATE_CHARS,
    decide_write,
    reason_label,
)
from app.agents.reading import (
    BASIS_MAX_CHARS,
    COMMIT_AUTHORIZED,
    COMMIT_NONE,
    COMMIT_PROPOSED,
    DELIVERY_CHAT,
    DELIVERY_DELIVER,
    DELIVERY_DRAFT,
    DELIVERY_READ,
    GOAL_MAX_CHARS,
    MISSING_MAX_CHARS,
    QUESTION_MAX_CHARS,
    READING_RULES,
    SCOPE_MAX_ITEMS,
    STANCE_CHAT,
    STANCE_DIRECT,
    STANCE_EXPLORE,
    TurnReading,
    apply_commit,
    apply_hold,
    deterministic_reading,
    fallback_reading,
    parse_reading,
    read_turn,
)


def test_parse_reads_plain_json() -> None:
    reading = parse_reading(
        '{"goal": "合成一份周报", "stance": "direct", "commitment": "authorized",'
        ' "scope": ["a.docx"], "missing": "", "question": "", "confidence": 0.9,'
        ' "basis": "用了「直接生成」"}'
    )
    assert reading is not None
    assert reading.stance == STANCE_DIRECT
    assert reading.commitment == COMMIT_AUTHORIZED
    assert reading.goal == "合成一份周报"
    assert reading.scope == ["a.docx"]
    assert reading.authorized is True
    assert reading.intent == "write"


def test_parse_survives_markdown_fence_and_leading_noise() -> None:
    reading = parse_reading(
        '好的，我读一下。\n```json\n{"stance": "explore", "commitment": "none",'
        ' "confidence": 0.8}\n```'
    )
    assert reading is not None
    assert reading.stance == STANCE_EXPLORE
    assert reading.commitment == COMMIT_NONE


def test_missing_commitment_leans_conservative() -> None:
    """模型没给 commitment 时：direct 当成授权，其余一律当成没授权。"""
    direct = parse_reading('{"stance": "direct", "confidence": 0.9}')
    explore = parse_reading('{"stance": "explore", "confidence": 0.9}')
    assert direct is not None and direct.commitment == COMMIT_AUTHORIZED
    assert explore is not None and explore.commitment == COMMIT_NONE


def test_chat_with_authorized_is_corrected() -> None:
    """自相矛盾时按闲聊算——宁可少动手，不能凭空生成。"""
    reading = parse_reading('{"stance": "chat", "commitment": "authorized", "confidence": 0.9}')
    assert reading is not None
    assert reading.commitment == COMMIT_NONE


def test_parse_accepts_percent_confidence_and_clips_goal() -> None:
    reading = parse_reading(
        '{"stance": "direct", "commitment": "proposed", "confidence": 85,'
        ' "goal": "把四份材料合成一份周报，按月份分组，每份分别说明来源"}'
    )
    assert reading is not None
    assert reading.confidence == pytest.approx(0.85)
    assert len(reading.goal) <= 41  # 40 字 + 省略号


def test_parse_rejects_unknown_stance_and_garbage() -> None:
    assert parse_reading('{"stance": "do_it"}') is None
    assert parse_reading("我觉得他要生成一份周报") is None
    assert parse_reading("") is None


def test_low_confidence_with_question_blocks() -> None:
    reading = TurnReading(
        stance=STANCE_DIRECT,
        commitment=COMMIT_PROPOSED,
        question="合并时保留原来的小节标题吗？",
        confidence=0.4,
    )
    assert reading.needs_confirm is True


def test_question_without_low_confidence_does_not_block() -> None:
    """想到了一个可问的问题，不等于要停下来问——同事不会那样。"""
    reading = TurnReading(
        stance=STANCE_DIRECT,
        commitment=COMMIT_AUTHORIZED,
        question="要不要按月分组？",
        confidence=0.9,
    )
    assert reading.needs_confirm is False


def test_fallback_never_guesses() -> None:
    """理解失败时**不猜**：模糊说法一律不授权，白纸黑字的拍板才放行。

    「不猜」的意思是：它不解释语气、不推断指代，只认句子里确实写着的那几个
    拍板短语。「把标题居中」这种明确指令它也不会放行——那需要判断「范围是否
    唯一」，是理解层的活，不是兜底该做的。少做一次比做错一次好。
    """
    for vague in ("把这两份合成一份", "把标题居中", "这几份整理一下", "改改标题"):
        reading = fallback_reading(vague)
        assert reading.commitment != COMMIT_AUTHORIZED, vague
        assert reading.question == "", "兜底不许反问——没读懂就别装懂"

    # 白纸黑字说要执行：理解模型挂了也不该把明确指令一起拦掉
    for explicit in ("帮我直接生成一份周报", "就按这个，落盘"):
        reading = fallback_reading(explicit)
        assert reading.commitment == COMMIT_AUTHORIZED, explicit
        assert reading.stance == STANCE_DIRECT


def test_fallback_records_the_order_without_granting_it() -> None:
    """明确交办但范围不唯一：**记下要做什么，权限仍然封着**。

    这是「把标题居中」的第三条路——既不是当成没听见（回一句"你想做什么"），
    也不是授权写盘（对着猜出来的文件动手）。

    为什么不一刀切放行：祈使句缺的不是语气，是**范围**（哪份文件、哪一段），
    判断范围是否唯一是理解层的活，兜底没人替他确认。上面
    `test_fallback_never_guesses` 守的就是这条。所以这里只改 goal，不改门。
    """
    reading = fallback_reading("把标题居中")
    assert reading.commitment == COMMIT_NONE, "范围不唯一，不能授权写盘"
    assert reading.goal == "把标题居中", "要把'他要什么'记下来，否则模型只能反问"
    assert "交办" in reading.basis

    order = fallback_reading("把这三份材料合并成一个文件")
    assert order.commitment == COMMIT_NONE
    assert order.goal.startswith("把这三份材料合并")

    # 没有交办的说法照旧什么都不记
    vague = fallback_reading("这几份材料你怎么看")
    assert vague.commitment == COMMIT_NONE
    assert vague.goal == ""


def test_deterministic_reading_only_handles_unambiguous() -> None:
    empty = deterministic_reading("   ")
    greet = deterministic_reading("你好")
    assert empty is not None and empty.stance == STANCE_CHAT
    assert greet is not None and greet.stance == STANCE_CHAT
    # 带正事的问候不能短路：剥完还剩内容，必须交给模型读
    assert deterministic_reading("谢谢你，顺手把周报也改了吧") is None
    # 「好」要结合上一轮才知道授权了什么，不能在这里直接判 authorized
    assert deterministic_reading("好") is None


class _StubRouter:
    def __init__(self, text: str = "", raise_error: bool = False) -> None:
        self.text = text
        self.raise_error = raise_error
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("model down")
        return type("_R", (), {"text": self.text})()


class _Ctx:
    def __init__(self, message: str) -> None:
        self.message = message
        self.history: list[dict[str, str]] = []
        self.uploads: list[object] = []


@pytest.mark.anyio
async def test_read_turn_skips_model_for_greeting() -> None:
    """一句「你好」不值得花一次模型调用，短路掉。"""
    router = _StubRouter('{"stance": "direct", "commitment": "authorized"}')
    reading = await read_turn(router, _Ctx("你好"))
    assert router.calls == 0
    assert reading.stance == STANCE_CHAT


@pytest.mark.anyio
async def test_read_turn_uses_model_result() -> None:
    router = _StubRouter(
        '{"stance": "direct", "commitment": "authorized", "goal": "合并两份周报",'
        ' "confidence": 0.9}'
    )
    reading = await read_turn(router, _Ctx("就按你说的，合并吧"))
    assert router.calls == 1
    assert reading.authorized is True
    assert reading.goal == "合并两份周报"


@pytest.mark.anyio
async def test_read_turn_falls_back_on_error_and_bad_output() -> None:
    broken = await read_turn(_StubRouter(raise_error=True), _Ctx("把这两份合成一份"))
    garbage = await read_turn(_StubRouter("我看他想合并"), _Ctx("把这两份合成一份"))
    for reading in (broken, garbage):
        assert reading.source == "fallback"
        assert reading.authorized is False
        assert reading.stance == STANCE_EXPLORE


# ---------------- 写权限门控 ----------------


def test_low_risk_write_is_never_blocked() -> None:
    """写任务计划这类不动用户文件，不值得停下来问。"""
    reading = TurnReading(stance=STANCE_CHAT, commitment=COMMIT_NONE, confidence=0.2)
    decision = decide_write("low", reading)
    assert decision.allow is True
    assert decision.reason == REASON_LOW_RISK


def test_high_risk_needs_authorization() -> None:
    """核心回归：他在商量、没拍板，就不许产出文件。"""
    proposed = TurnReading(stance=STANCE_EXPLORE, commitment=COMMIT_PROPOSED, confidence=0.85)
    decision = decide_write("high", proposed)
    assert decision.allow is False
    assert decision.reason == REASON_NOT_COMMITTED
    assert "拍板" in decision.hint


def test_authorized_passes() -> None:
    reading = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.9)
    decision = decide_write("high", reading)
    assert decision.allow is True
    assert decision.reason == REASON_AUTHORIZED


def test_direct_without_commitment_passes_when_sure() -> None:
    """「把标题居中」这种：范围小、结果唯一，不需要再问一遍。"""
    reading = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_NONE, confidence=0.8)
    assert decide_write("high", reading).reason == REASON_DIRECT


def test_direct_but_unsure_is_blocked() -> None:
    """只是「好像是这个意思」不够——不确定就别动手。"""
    reading = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_NONE, confidence=0.4)
    assert decide_write("high", reading).allow is False


# ---------------- 交付形态：stance × commitment 的四种处境 ----------------


@pytest.mark.parametrize(
    "stance, commitment, expected",
    [
        # 只是说话：无论授权与否都按聊天招呼（chat+authorized 会被 parse 压成 none）
        (STANCE_CHAT, COMMIT_NONE, DELIVERY_CHAT),
        (STANCE_CHAT, COMMIT_AUTHORIZED, DELIVERY_CHAT),
        # 在问、在评价、在商量但没提要求
        (STANCE_EXPLORE, COMMIT_NONE, DELIVERY_READ),
        # 方向明确了，就差一句话点头
        (STANCE_EXPLORE, COMMIT_PROPOSED, DELIVERY_DRAFT),
        (STANCE_DIRECT, COMMIT_PROPOSED, DELIVERY_DRAFT),
        # 要结果但没说"就做"：给方案比直接动手便宜
        (STANCE_DIRECT, COMMIT_NONE, DELIVERY_DRAFT),
        # 拍板了
        (STANCE_DIRECT, COMMIT_AUTHORIZED, DELIVERY_DELIVER),
        (STANCE_EXPLORE, COMMIT_AUTHORIZED, DELIVERY_DELIVER),
    ],
)
def test_delivery_splits_write_into_draft_and_deliver(
    stance: str, commitment: str, expected: str
) -> None:
    """write 这一档要再切一刀。

    以前 `direct + proposed`（「我想弄成一份周报，你看行吗」）和
    `direct + authorized`（「直接生成」）拿到的是同一套提示词：一边写着
    「用户要文件就生成」，一边写着「他还在商量，不要生成」。两句话打架，
    模型只能自己调和——评估里行为发飘，一半是这个原因。
    """
    reading = TurnReading(stance=stance, commitment=commitment, confidence=0.9)
    assert reading.delivery == expected


def test_delivery_does_not_grant_permission() -> None:
    """交付形态只决定提示词和步数，**不决定能不能写盘**。

    这条断言的用处是防止有人图省事，将来拿 `delivery == "deliver"` 当放行条件。
    权限只有一处：`policy.decide_write`。
    """
    chatty = TurnReading(stance=STANCE_CHAT, commitment=COMMIT_NONE, confidence=0.1)
    assert decide_write("high", chatty).allow is False
    assert decide_write("low", chatty).allow is True  # 低风险本来就不拦

    proposed = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_PROPOSED, confidence=0.99)
    assert proposed.delivery == DELIVERY_DRAFT
    assert decide_write("high", proposed).allow is False, "把握再高，没拍板也不许落盘"


# ---------------- 把握度门槛 ----------------


def test_confidence_floor_rejects_the_hesitant_band() -> None:
    """0.6–0.7 是「我在两档之间犹豫」的分数段，不能拿它当动手依据。

    门槛定在 0.75 而不是 0.65：实测里这个分数段的判断错误率明显更高。
    也不能定到 0.9——那样每个明确指令都要先问一句，同事之间不这么说话。
    """
    hesitant = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_NONE, confidence=0.7)
    assert decide_write("high", hesitant).allow is False

    sure = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_NONE, confidence=0.78)
    assert decide_write("high", sure).reason == REASON_DIRECT


def test_authorized_needs_backing_not_just_volume() -> None:
    """说「已授权」但只有五成把握，一样拦。凭据比口气重要。"""
    shaky = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.55)
    assert decide_write("high", shaky).allow is False

    solid = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.72)
    assert decide_write("high", solid).reason == REASON_AUTHORIZED


# ---------------- 门控的第二道：句子自己写着的否决 ----------------


def test_explicit_hold_vetoes_even_a_confident_authorization() -> None:
    """他自己说了「先别 / 我点头了再 / 我就是问问」，把握再高也不放行。

    这是门控与理解层打擂台时的判据：模型可能读串（尤其长句、多件事混在
    一起），但「先别生成」是白纸黑字。以前门控只看 `commitment`，于是
    「先别管格式，直接生成吧」这种句子判对了，「先别生成吧，我就是想问问」
    一旦模型读成 authorized 就照写不误。
    """
    authorized = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.99)
    for text in (
        "先别生成吧，我就是想问问周报该怎么写",
        "我点头了再落盘",
        "先放着，晚点再说",
    ):
        decision = decide_write("high", authorized, message=text)
        assert decision.allow is False, text
        assert decision.reason == REASON_HOLD, text
        # 给模型的话要具体：他要答案，不是文件
        assert "不要换" in decision.hint or "别再" in decision.hint


def test_retraction_vetoes_even_a_confident_authorization() -> None:
    """「算了 / 不用了」和 hold 分开记：一个是"等"，一个是"不要"。"""
    authorized = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.99)
    decision = decide_write("high", authorized, message="算了，不用了")
    assert decision.allow is False
    assert decision.reason == REASON_RETRACTED


def test_hold_veto_does_not_fire_when_the_commit_is_real() -> None:
    """「先别管格式，直接生成吧」里两个标记都在，听拍板。

    hold 的判定自己已经处理了这件事（`hold_of` 先跑一次拍板），这里守的是
    门控别把它再翻一次——一句话里既有"别"又有"就做"，最终该做。
    """
    authorized = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.9)
    decision = decide_write("high", authorized, message="先别管格式，直接生成吧")
    assert decision.allow is True
    assert decision.reason == REASON_AUTHORIZED


def test_low_risk_is_still_never_blocked_by_a_hold() -> None:
    """写任务计划不动用户文件，不该被"先别生成"连坐。"""
    reading = TurnReading(stance=STANCE_EXPLORE, commitment=COMMIT_NONE, confidence=0.2)
    decision = decide_write("low", reading, message="先别生成吧，我就是问问")
    assert decision.allow is True
    assert decision.reason == REASON_LOW_RISK


def test_very_long_message_raises_the_authorization_bar() -> None:
    """整篇材料 + 一句话，授权的门槛要抬一档。

    400 字只是开头被切掉一点，理解层读的是全文，不必加码。到了三倍窗口
    就是另一种句子了——「这份材料想整理成周报」很容易被读成「他要我整理」。
    这一段长度上加码，代价是长材料场景多问一句，收益是不拿文件去赌。
    """
    material = "会议记录：" + "今天讨论了排期和预算。" * (TRUNCATION_ELEVATE_CHARS // 10)
    assert len(material) > TRUNCATION_ELEVATE_CHARS
    authorized = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.8)
    decision = decide_write("high", authorized, message=material + "整理成周报吧")
    assert decision.allow is False
    assert decision.reason == REASON_LONG_MESSAGE

    # 把握足够时照旧放行：抬门槛不是一刀切
    solid = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.9)
    assert decide_write("high", solid, message=material + "整理成周报吧").allow is True


def test_short_message_keeps_the_old_bar() -> None:
    """没超过三倍窗口的，门槛不动——不然大批正常句子都要多问一句。"""
    authorized = TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_AUTHORIZED, confidence=0.8)
    assert decide_write("high", authorized, message="直接生成吧").allow is True


def test_unknown_risk_level_is_treated_as_high() -> None:
    """认不出的风险等级按高风险办。

    一个拼写错误（`High`、`hight`、空串）就会走进"不是 high 就是低风险"
    那一支，然后被直接放行——门在自己身上开了个洞。
    """
    idle = TurnReading(stance=STANCE_CHAT, commitment=COMMIT_NONE, confidence=0.2)
    for risk in ("High", "HIGH", "hight", "", "medium"):
        decision = decide_write(risk, idle)
        assert decision.allow is False, risk
        assert decision.reason == REASON_NOT_COMMITTED, risk


def test_reason_label_speaks_to_the_user_not_the_model() -> None:
    """卡上那句话是给用户看的：不能是对着模型说的指令。"""
    assert "拍板" in reason_label(REASON_NOT_COMMITTED)
    assert "先别" in reason_label(REASON_HOLD)
    assert reason_label("某个还没起名字的理由")


def test_question_only_blocks_when_unsure() -> None:
    """有疑问句不等于要停下——把握够时，那句只是顺口的可选问题。"""
    unsure = TurnReading(
        stance=STANCE_EXPLORE,
        commitment=COMMIT_NONE,
        question="要按周还是按月？",
        confidence=0.6,
    )
    assert unsure.needs_confirm is True

    sure = TurnReading(
        stance=STANCE_EXPLORE,
        commitment=COMMIT_NONE,
        question="要按周还是按月？",
        confidence=0.85,
    )
    assert sure.needs_confirm is False


# ---------------- 字段上限：天花板，不是表达上限 ----------------


def test_long_goal_is_kept_mostly_intact() -> None:
    """复述要能装下限定条件，否则下一轮它就忘了自己要交什么。

    旧上限 40 字会把「把 W44 和 W45 两份周报合成一份，退款部分单独成节，
    输出 docx 给老板看，口径按订单数」截成半句——条件全丢。
    """
    goal = (
        "把 W44 和 W45 两份周报合成一份，退款部分单独成节，"
        "输出 docx 给老板看，口径按订单数而不是金额，标题沿用上周格式"
    )
    raw = json.dumps(
        {"stance": "direct", "commitment": "authorized", "goal": goal, "confidence": 0.9},
        ensure_ascii=False,
    )
    reading = parse_reading(raw)
    assert reading is not None
    assert reading.goal == goal, "这么长的复述不该被截"
    assert "退款" in reading.goal and "口径" in reading.goal


def test_field_caps_are_generous_but_finite() -> None:
    """上限仍然存在——它是防跑飞的天花板，不是越宽越好。"""
    assert GOAL_MAX_CHARS >= 100
    assert QUESTION_MAX_CHARS >= 100
    assert MISSING_MAX_CHARS >= QUESTION_MAX_CHARS
    assert BASIS_MAX_CHARS >= 100
    assert SCOPE_MAX_ITEMS >= 8

    long_question = "缺" * 500
    raw = json.dumps(
        {
            "stance": "explore",
            "commitment": "proposed",
            "question": long_question,
            "basis": "依" * 500,
            "confidence": 0.6,
        },
        ensure_ascii=False,
    )
    reading = parse_reading(raw)
    assert reading is not None
    assert len(reading.question) <= QUESTION_MAX_CHARS + 1
    assert len(reading.basis) <= BASIS_MAX_CHARS + 1


def test_prompt_no_longer_asks_for_30_char_brief() -> None:
    """提示词和代码要一起改。

    只放宽代码里 `_clip` 的上限没用——模型照着 prompt 里的「不超过 30 字」
    自己就压扁了，截断根本不会触发。这条断言防的就是只改一半。
    """
    assert "不超过 30 字" not in READING_RULES
    assert "不超过 40 字" not in READING_RULES
    assert "不要为了短而丢掉限定条件" in READING_RULES


# ---------------- 叫停 / 只问 / 推后：他自己说的话压过模型的推断 ----------------
#
# 这一组守的是同一条真实路径：他说「先别生成吧，我就是想问问周报该怎么写」，
# 模型答对了（只讲方法、不落盘），但引擎的可靠性兜底看到句子里有「生成吧」，
# 又替它补了一份 docx。判据在两个地方错，修法也只能在两个地方：
# 词法上认出「先别」挡在前面，语义上让 hold 压过模型给的 authorized。


@pytest.mark.anyio
async def test_read_turn_holds_even_when_model_granted_authorization() -> None:
    """模型说是 authorized，但这句明确叫停——听他的，不听模型的。"""
    router = _StubRouter(
        '{"stance": "direct", "commitment": "authorized", "goal": "生成周报",'
        ' "question": "要按周还是按月？", "confidence": 0.93, "basis": "提到周报"}'
    )
    reading = await read_turn(router, _Ctx("先别生成吧，我就是想问问周报该怎么写"))

    assert reading.commitment == COMMIT_NONE
    assert reading.stance == STANCE_EXPLORE
    assert reading.delivery == DELIVERY_READ
    assert reading.question == "", "他已经说了先别，再反问「要不要做」等于没听见"
    assert reading.authorized is False


@pytest.mark.anyio
async def test_read_turn_hold_also_covers_deferred_authorization() -> None:
    """「我点头了再落盘」里有「落盘」这个最硬的拍板词，但整句是"现在别"。"""
    router = _StubRouter(
        '{"stance": "direct", "commitment": "authorized", "goal": "落盘",'
        ' "confidence": 0.9, "basis": "出现了落盘"}'
    )
    reading = await read_turn(router, _Ctx("先给方案，我点头了再落盘"))
    assert reading.authorized is False
    assert reading.delivery == DELIVERY_DRAFT


def test_apply_hold_does_not_touch_a_reading_already_in_the_safe_direction() -> None:
    """已经在安全方向上就别动它——尤其是别把模型的依据覆盖掉。"""
    reading = TurnReading(
        stance=STANCE_EXPLORE, commitment=COMMIT_NONE, confidence=0.8, basis="他在问方法"
    )
    assert apply_hold(reading, "我就是想问问周报怎么写") is reading


def test_apply_hold_never_grants_anything() -> None:
    """hold 只往下压。它判错的代价只能是多问一句，不能凭空多一份文件。"""
    for stance in (STANCE_CHAT, STANCE_EXPLORE, STANCE_DIRECT):
        for commitment in (COMMIT_NONE, COMMIT_PROPOSED, COMMIT_AUTHORIZED):
            reading = TurnReading(stance=stance, commitment=commitment, confidence=0.99)
            capped = apply_hold(reading, "先别生成吧，我就是想问问")
            assert capped.commitment == COMMIT_NONE
            assert capped.stance != STANCE_DIRECT


def test_apply_commit_lifts_a_short_confirmation_with_history() -> None:
    """「你生成吧」是拍板，不该被模型读成"还在商量"。

    线上就是这句：理解层判 proposed，提示词于是要求"最后问一句"，模型回
    「你说『就这样』我就出」——用户以为要口令才能干活。
    """
    reading = TurnReading(
        stance=STANCE_DIRECT,
        commitment=COMMIT_PROPOSED,
        confidence=0.6,
        goal="把标题改红、字号缩一半，然后出 PDF",
        question="这样改可以吗？",
    )
    lifted = apply_commit(reading, "你生成吧", has_history=True)

    assert lifted.commitment == COMMIT_AUTHORIZED
    assert lifted.delivery == DELIVERY_DELIVER
    assert lifted.question == "", "已经拍板就别再问一句"
    assert "拍板" in lifted.basis or "决定" in lifted.basis


def test_apply_commit_needs_history_and_never_fights_a_hold() -> None:
    """两个前提：短句要有指代对象；他说过先别动手时不许抬回来。"""
    reading = TurnReading(stance=STANCE_EXPLORE, commitment=COMMIT_PROPOSED, confidence=0.6)

    assert apply_commit(reading, "你生成吧", has_history=False) is reading
    assert apply_commit(reading, "先别生成吧，我就是想问问", has_history=True) is reading, (
        "叫停的句子 commit_verdict 不成立，不能被抬成授权"
    )
