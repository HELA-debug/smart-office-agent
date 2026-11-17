"""门控的判定矩阵：效果分档 × 档位 × 理解层结论。

这张表决定「这一步做不做」。判错的方向很不对称：多拦一次只是没做成，
少拦一次可能删掉他的文件——所以逐格断言，而且**放行的每一格都要能说清
凭什么**。
"""

from __future__ import annotations

from app.agents.policy import (
    MODE_BARS,
    REASON_ALL_ALLOW,
    REASON_AUTHORIZED,
    REASON_CONTINUING,
    REASON_DESTRUCTIVE,
    REASON_HOLD,
    REASON_NOT_COMMITTED,
    REASON_RETRACTED,
    decide_write,
)
from app.agents.reading import (
    COMMIT_AUTHORIZED,
    COMMIT_NONE,
    COMMIT_PROPOSED,
    STANCE_DIRECT,
    TurnReading,
)

MSG = "把标题改成深蓝"


def _reading(commitment: str, *, stance: str = STANCE_DIRECT, confidence: float = 0.9):
    return TurnReading(
        stance=stance,
        commitment=commitment,
        goal="把标题改成深蓝",
        confidence=confidence,
        basis="test",
    )


def _gate(
    reading,
    *,
    effect: str = "output",
    mode: str = "risky",
    continuing: bool = False,
    message: str = MSG,
    risk: str = "high",
):
    return decide_write(
        risk, reading, message=message, effect=effect, mode=mode, continuing=continuing
    )


def test_low_risk_never_needs_authorization() -> None:
    """写任务计划这类不动用户文件，谁都不用问。"""
    decision = _gate(_reading(COMMIT_PROPOSED), risk="low")
    assert decision.allow is True


def test_clear_instruction_writes_output() -> None:
    """他说「把标题改成深蓝」，就是让改——不再弹卡、不再问一遍。"""
    decision = _gate(_reading(COMMIT_AUTHORIZED))
    assert decision.allow is True
    assert decision.reason == REASON_AUTHORIZED


def test_direct_instruction_without_commitment_still_writes() -> None:
    """理解层没判出 authorized，但句子是明确祈使句、把握够——照做。"""
    decision = _gate(
        TurnReading(stance=STANCE_DIRECT, commitment=COMMIT_NONE, goal="改标题", confidence=0.8)
    )
    assert decision.allow is True


def test_hesitation_blocks_output() -> None:
    """「我想弄成一份周报，你看行吗」——在问，不是在让做。"""
    decision = _gate(_reading(COMMIT_PROPOSED, confidence=0.5))
    assert decision.allow is False
    assert decision.reason == REASON_NOT_COMMITTED


def test_continuing_lets_him_keep_tweaking() -> None:
    """这一轮已经产出过产物，他再说「换成深墨蓝」——那是接着改，不是新商量。"""
    decision = _gate(_reading(COMMIT_PROPOSED, confidence=0.5), continuing=True)
    assert decision.allow is True
    assert decision.reason == REASON_CONTINUING


def test_destructive_needs_his_own_words() -> None:
    """删除 / 覆盖别人的文件：一句「你看着弄」不够，要把握度更高的明确授权。"""
    weak = _gate(_reading(COMMIT_AUTHORIZED, confidence=0.75), effect="destructive")
    assert weak.allow is False
    assert weak.reason == REASON_DESTRUCTIVE

    strong = _gate(_reading(COMMIT_AUTHORIZED, confidence=0.95), effect="destructive")
    assert strong.allow is True


def test_hold_and_retraction_veto_everything() -> None:
    """「先别动」「算了」是自足的否决，压过理解层，也压过「接着改」。"""
    for text in ("先别动，我还没想好", "算了不用了"):
        decision = _gate(_reading(COMMIT_AUTHORIZED), continuing=True, message=text)
        assert decision.allow is False
        assert decision.reason in (REASON_HOLD, REASON_RETRACTED)


def test_all_allow_only_keeps_the_vetoes() -> None:
    decision = _gate(_reading(COMMIT_PROPOSED, confidence=0.1), mode="all_allow")
    assert decision.allow is True
    assert decision.reason == REASON_ALL_ALLOW

    vetoed = _gate(_reading(COMMIT_AUTHORIZED), mode="all_allow", message="先别动")
    assert vetoed.allow is False


def test_cautious_mode_raises_the_bar() -> None:
    """「谨慎」档：同样一句 authorized，把握 0.75 在标准档能做，在谨慎档不做。"""
    reading = _reading(COMMIT_AUTHORIZED, confidence=0.75)
    assert _gate(reading, mode="risky").allow is True
    cautious = _gate(reading, mode="always_ask")
    assert cautious.allow is False


def test_unknown_mode_falls_back_to_standard() -> None:
    assert MODE_BARS["risky"] == (0.72, 0.75)
    reading = _reading(COMMIT_AUTHORIZED, confidence=0.8)
    assert _gate(reading, mode="放行吧").allow is True
