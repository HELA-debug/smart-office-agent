"""写权限门控：判断错了也不该出事故。

## 为什么需要这一层

以前「意图判断的结论」直接就等于「能不能写文件」：

    reading → intent(write) → 工具清单里出现 doc.generate_report → 文件生成

这条链上只要判断错一次，就必然产出一份没人要的文件。而判断不可能永远对——
不管是关键词还是模型，都会有读偏的时候。**把「猜得准」当成安全前提，本身就不成立。**

所以把两件事拆开：

- 理解层负责**猜**（尽量准，但允许错）；
- 门控层负责**兜**（猜错时不让错误落地）。

模型想调用写工具时，先过这里。没获得授权就不执行，把一句说明回给模型，
让它改成「先讲打算怎么做，再问一句」。代价从「一份多余的 docx」变成「多问半句话」。

## 为什么不是一刀切都拦

「把标题居中」「标题再大一点」这种动作明确、范围小、可逆，问一句反而烦人。
所以按**风险**分，不按意图分：

- 低风险写（写任务计划这类）→ 不拦。
- 高风险写（生成文档、跑脚本、删文件）→ 必须已经拍板。

风险标签来自工具注册时的 `risk=`，不是这里另立一套。

## 为什么不看句子里的动作词

「生成」「整理」「改」这些词商量的时候天天出现，正因如此旧逻辑才会在
「怎么改好？」上误判。这里只看理解层给出的 `commitment`：
他有没有把决定说出口。动词不参与判断。

## 三道否决，一道也没多给

除了理解层的结论，这里还看三件**句子本身就写着**的事，方向全是**否决**：

1. 他明说了这一轮先别动手（「先别生成」「我点头了再落盘」「我就是想问问」）；
2. 他说了撤回（「算了」「不用了」）；
3. 整条消息长得超出分析窗口，而授权判断只有一般把握。

为什么只让它否决、不让它授予：确定性层读得出"否"，读不出"是"。「他说了
『行』」到底授权了什么，只有结合上一轮才知道；而「他说了『先别』」是自足的。
放行一次的成本是一份没人要的文件，多问一句的成本是半句话——所以这层只做减法。
"""

from __future__ import annotations

from dataclasses import dataclass

from .intent import MAX_ANALYZED_CHARS, hold_of, retraction_verdict
from .reading import (
    COMMIT_AUTHORIZED,
    COMMIT_PROPOSED,
    STANCE_DIRECT,
    TurnReading,
)

#: 判断依据，落日志用。出事时靠它复盘是哪一环放行的。
REASON_LOW_RISK = "low_risk"
REASON_AUTHORIZED = "authorized"
REASON_DIRECT = "direct"
REASON_NOT_COMMITTED = "not_committed"
REASON_UNSURE = "unsure"
#: 他自己说出口的「先别 / 我只是问问 / 我点头了再」。
REASON_HOLD = "hold"
#: 他自己说了「算了 / 不用了」。
REASON_RETRACTED = "retracted"
#: 消息太长，授权判断的把握不够高。
REASON_LONG_MESSAGE = "long_message"
#: 这一轮已经产出过产物，这一步是在接着改它——不需要再问一遍「你让我做吗」。
REASON_CONTINUING = "continuing"
#: 档位设成了「放手」：他自己选的，出了问题也是他要的。
REASON_ALL_ALLOW = "all_allow"
#: 会动已有文件（删除 / 改名 / 覆盖），而这句话不是冲那件事说的。
REASON_DESTRUCTIVE = "destructive"

#: 档位 = 门控给多少「善意推定」。它调的是放行线，不再是「弹不弹卡」——
#: 卡片这一层已经整个拿掉了，选择权收回到内核：要么按他的话办，要么不做，
#: 不再把人拉进来点按钮。
#:
#: 三档对应的把握度下限（authorized / direct）：
MODE_BARS: dict[str, tuple[float, float]] = {
    "always_ask": (0.85, 0.85),  # 谨慎：模棱两可就别动
    "risky": (0.72, 0.75),  # 标准：说出口就算数
    "all_allow": (0.0, 0.0),  # 放手：别拿把握度挡他
}

#: 不可逆动作另有一套线：删除 / 覆盖别人的文件，一句「你看着弄」不够。
MIN_DESTRUCTIVE_CONFIDENCE = 0.85

#: 同一轮被拦几次之后，就别再让模型试了——它明显在反复冲同一个门。
MAX_BLOCKS_PER_RUN = 2

#: 说「已授权」但自己都没把握时，宁可问一句。
#: `authorized` 是放行的最强依据，所以更不能让它带着 0.5 的把握直接放行——
#: 实测里误判的那些「危险」条目，置信度集中在 0.5 上下，而这个分数段的模型
#: 基本是在两档之间犹豫。定在 0.72 而不是 `CONFIDENCE_FLOOR` 的 0.75：
#: authorized 有"说出口的那句话"作凭据，可以比纯靠语气的判断松一点。
#: 也不拉到 0.85——那样大批真授权的说法（「就按这个吧」常给 0.8）会被拦下，
#: 每件事都要再问一遍，比误放行一次还烦人。
MIN_AUTHORIZED_CONFIDENCE = 0.72

#: 消息超过这个长度，授权的门槛再抬一档。
#:
#: 为什么不是"一超过分析窗口就抬"：400 字只是开头被切掉一点，理解层读的是
#: **全文**，判断依据没少。可到了三倍窗口（1200 字）就是另一种句子了——
#: 「整篇材料 + 结尾一句话」。这种句子里模型的注意力容易漂在材料上，把
#: 「这份材料想整理成周报」读成「他要我整理」。这个长度上加码，代价只是
#: 长材料场景多问一句，收益是不拿一份文件去赌它有没有读串。
TRUNCATION_ELEVATE_CHARS = MAX_ANALYZED_CHARS * 3
MIN_AUTHORIZED_CONFIDENCE_LONG = 0.85

#: 认不出的风险等级按高风险处理。
#:
#: `spec_risk` 是字符串。以前写的是 `if spec_risk != "high": 放行`——于是
#: `"High"`、`"hight"`、空串都会走进"低风险"那一支被直接放行，一个拼写错误
#: 就把门拆了。门控认不出这个工具有多危险，就没资格替它担保。
_KNOWN_RISK = frozenset({"low", "high"})


@dataclass(frozen=True)
class GateDecision:
    allow: bool
    reason: str
    hint: str = ""


def _hint(reading: TurnReading) -> str:
    """给模型的一句话说明。要具体到「接下来该做什么」，不是「操作被拒绝」。"""
    if reading.commitment == COMMIT_PROPOSED:
        return (
            "他还在商量，没有拍板，所以这次写盘没有执行。"
            "别换个工具再试：先用两三句话说清你打算怎么做、会改哪些地方，"
            "最后用一句话问他要不要就这么做。"
        )
    return (
        "这一轮他没让你产出文件，所以写盘没有执行。"
        "如果确实需要动手，先用一句话说明你打算做什么，再问他一句要不要做；"
        "如果他只是想了解情况，就直接回答，不要提生成文件的事。"
    )


def _veto(message: str) -> tuple[str, str] | None:
    """句子里有没有写着"别动手"的凭据。返回 (reason, 说明) 或 None。

    只在消息确实传进来时才看——没有原文就没有凭据，这时候不装懂。
    """
    if not message.strip():
        return None
    hold = hold_of(message)
    if hold is not None:
        # 「先别生成」「我点头了再落盘」「我就是想问问」——他自己说的，
        # 比模型的猜测硬。理解层的 `apply_hold` 本该已经压过一档，这里是
        # 第二道：`decide_write` 的入参可能来自别的调用方（子智能体、
        # 直接构造的 TurnReading），不能指望它们都记得过那道。
        return REASON_HOLD, hold.label
    retraction = retraction_verdict(message)
    if retraction.value:
        return REASON_RETRACTED, "他说了撤回"
    return None


def decide_write(
    spec_risk: str,
    reading: TurnReading,
    *,
    message: str = "",
    effect: str = "output",
    mode: str = "risky",
    continuing: bool = False,
) -> GateDecision:
    """这一步要不要放行。

    `spec_risk` 取工具注册时的 risk（"low" / "high"）；只有 high 才需要授权。
    `effect` 是这一次调用的效果分档（读 / 写产物 / 动已有文件），由工具自己给。
    `mode` 是档位（谨慎 / 标准 / 放手），只调放行线，不改变「谁做决定」。
    `continuing` 表示这一轮已经产出过产物，这一步是在它的基础上接着改。

    `message` 是这一轮他原话；给了就多两道确定性否决（见模块说明），不给就
    只看理解层——以前一直是这样，保持兼容。
    """
    risk = (spec_risk or "").strip().lower()
    if risk not in _KNOWN_RISK:
        # 认不出就按高风险办：门控不知道它有多危险，就没资格担保。
        risk = "high"

    if risk == "low":
        # 写任务计划这类不改变用户文件，不值得为它停下来问一句。
        return GateDecision(allow=True, reason=REASON_LOW_RISK)

    veto = _veto(message)
    if veto is not None:
        reason, detail = veto
        if reason == REASON_HOLD:
            hint = (
                f"他这一轮明确说了「{detail}」，所以写盘没有执行。"
                "不要换个工具再试，也不要再问「要不要做」——他要的是答案，"
                "不是文件。直接把话说清楚就收尾。"
            )
        else:
            hint = (
                "他这一轮说了撤回，所以写盘没有执行。"
                "别再提生成文件的事；如果还有没说完的判断，用两三句话说清就收尾。"
            )
        return GateDecision(allow=False, reason=reason, hint=hint)

    bar_authorized, bar_direct = MODE_BARS.get(_norm_mode(mode), MODE_BARS["risky"])
    if _norm_mode(mode) == "all_allow":
        # 他自己把门开到最大：只保留上面那两道「先别 / 算了」。
        return GateDecision(allow=True, reason=REASON_ALL_ALLOW)

    # 第三档：会动已有文件。这一档不看「他让你动手了没有」，看「他是不是
    # 冲这件事说的」。一句「你看着弄」能担保「再生成一版」，担保不了
    # 「把旧稿删了」——后者做完了收不回来。
    if effect == "destructive":
        if reading.commitment == COMMIT_AUTHORIZED and (
            reading.confidence >= max(bar_authorized, MIN_DESTRUCTIVE_CONFIDENCE)
        ):
            return GateDecision(allow=True, reason=REASON_AUTHORIZED)
        return GateDecision(
            allow=False,
            reason=REASON_DESTRUCTIVE,
            hint=(
                "这一步会动到已有的文件（删除 / 改名 / 覆盖），而这一轮他没有明确"
                "说要动它们。别换个写法绕过去：先用一句话说清你要动哪一份、为什么，"
                "让他自己说「删吧 / 就这么改」。"
            ),
        )

    if reading.commitment == COMMIT_AUTHORIZED:
        bar = bar_authorized
        if len(message or "") > TRUNCATION_ELEVATE_CHARS:
            bar = max(bar, MIN_AUTHORIZED_CONFIDENCE_LONG)
        if reading.confidence >= bar:
            return GateDecision(allow=True, reason=REASON_AUTHORIZED)
        if bar > MIN_AUTHORIZED_CONFIDENCE:
            return GateDecision(
                allow=False,
                reason=REASON_LONG_MESSAGE,
                hint=(
                    f"这条消息有 {len(message)} 字，超过分析窗口三倍。"
                    "你判断他同意了，但这么长的句子里，授权那句话可能只是材料的一部分。"
                    "先说清你打算怎么做、会动哪些地方，再问一句「就这样做？」"
                ),
            )
        return GateDecision(
            allow=False,
            reason=REASON_UNSURE,
            hint=(
                "你判断他可能已经同意动手，但自己也拿不准。这一轮先别写盘："
                "用一句话说清你打算做什么，再问他这样对不对——一句话就能确认的事，"
                "不值得赌一份文件。"
            ),
        )

    # 他自己说过「还没定」，就不能再拿 stance 把它盖过去。
    # 这是一处真实漏洞：「我想弄成一份周报，你看行吗」是 direct/proposed，
    # 以前只要模型给的把握度过线，就直接走下面那条「明确指令」放行——
    # 一句话里既承认"在问"又照样落盘，等于门控没装。
    if reading.commitment == COMMIT_PROPOSED:
        # 「接着改」是这条规则唯一的例外：上文已经有一份他认可方向的产物，
        # 这一轮他说的「标题换成更深的墨蓝」本身就是改动指令，不是新商量。
        # 没有这个例外，改个颜色要重新授权一次，体感就是「又在拦我」。
        if continuing and reading.stance == STANCE_DIRECT:
            return GateDecision(allow=True, reason=REASON_CONTINUING)
        return GateDecision(allow=False, reason=REASON_NOT_COMMITTED, hint=_hint(reading))

    # 明确指令本身就含授权：他说「把标题居中」，不需要再问「你是要我把标题居中吗」。
    # 但要把握度够——把握不足时，direct 也可能只是「他好像要这个」。
    if reading.stance == STANCE_DIRECT and reading.confidence >= bar_direct:
        return GateDecision(allow=True, reason=REASON_DIRECT)

    return GateDecision(allow=False, reason=REASON_NOT_COMMITTED, hint=_hint(reading))


def _norm_mode(mode: str) -> str:
    value = (mode or "").strip().lower()
    return value if value in MODE_BARS else "risky"


def stop_hint(reading: TurnReading) -> str:
    """被拦到上限之后塞给模型的话：别再试工具了，把方案说出来收尾。"""
    return (
        f"{_hint(reading)} 这一轮不要再调用任何写盘工具，"
        "直接把你的打算和那个问题说出来，本轮就到这里。"
    )


#: 拦下的原因说给**用户**听的那一句。模型拿到的是 `hint`（教它下一步怎么做），
#: 用户拿到的是这张卡上的一句话（为什么没动）。两者受众不同，不能互相顶替：
#: 把 `hint` 直接摆在界面上，用户会看到一段对着模型说的指令。
_REASON_LABELS: dict[str, str] = {
    REASON_NOT_COMMITTED: "他还在商量，没有拍板",
    REASON_UNSURE: "判断还没把握",
    REASON_HOLD: "他说了这一轮先别动手",
    REASON_RETRACTED: "他说了撤回",
    REASON_LONG_MESSAGE: "消息太长，授权判断没把握",
    REASON_CONTINUING: "正在这版上接着改",
    REASON_DESTRUCTIVE: "这一步会动到已有文件",
    REASON_ALL_ALLOW: "档位设成了放手",
}


def reason_label(reason: str) -> str:
    """把门控的 reason 翻成一句人话，给界面上的工具卡用。"""
    return _REASON_LABELS.get(reason, "这一轮还没到动手的时候")


__all__ = [
    "MAX_BLOCKS_PER_RUN",
    "MIN_AUTHORIZED_CONFIDENCE",
    "MIN_AUTHORIZED_CONFIDENCE_LONG",
    "MIN_DESTRUCTIVE_CONFIDENCE",
    "MODE_BARS",
    "REASON_ALL_ALLOW",
    "REASON_AUTHORIZED",
    "REASON_CONTINUING",
    "REASON_DESTRUCTIVE",
    "REASON_DIRECT",
    "REASON_HOLD",
    "REASON_LONG_MESSAGE",
    "REASON_LOW_RISK",
    "REASON_NOT_COMMITTED",
    "REASON_RETRACTED",
    "REASON_UNSURE",
    "TRUNCATION_ELEVATE_CHARS",
    "GateDecision",
    "decide_write",
    "reason_label",
    "stop_hint",
]
