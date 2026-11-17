"""确定性信号层：只测「句内能确定的事」，不测「他到底想干什么」。

这组用例的写法有个规则：**每条断言都对应一种真实会出错的句子**，并在注释里
写清错法。堆一堆 `assert func("你好") is True` 没有价值——那种句子本来就不会错。

历史 bug 分三类，用例按这三类组织：

1. 剥词法伪匹配：「行」把「行业报告」咬掉，「hi」把「history」咬掉；
2. 残余不宽容：「好了」「行吧」「早上好呀」被判成"不是"；
3. 没有句法位置：「先别生成吧」「如果按这个来」「他说按这个来」全被当成拍板。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.agents.intent import (
    _STRONG_COMMIT,
    HOLD_NONE,
    HOLD_PROPOSED,
    INTENT_CHAT,
    INTENT_READ,
    INTENT_WRITE,
    MAX_ANALYZED_CHARS,
    advice_verdict,
    asks_advice,
    bare_confirmation,
    blank_verdict,
    classify,
    commit_verdict,
    confirmation_verdict,
    explain,
    explicit_commit,
    greeting_only,
    greeting_verdict,
    hold_of,
    intent_of,
    is_blank,
    normalize,
    order_verdict,
    phrase_stands,
    retraction_verdict,
    shape_of,
    standing_phrase,
)

# ---------------- 第 1 类：整词匹配，不许咬进实词 ----------------


@pytest.mark.parametrize(
    "text",
    [
        "行业报告帮我看看",  # 「行」在里面
        "行为分析",  # 「行」在里面
        "行李放哪",  # 「行」在里面
        "history",  # 「hi」在里面
        "this is history",
        "thankyouverymuch 的用法",  # 寒暄词不该整段生效
    ],
)
def test_confirmation_does_not_bite_into_content(text: str) -> None:
    """确认词出现在实词里，不能算「他在说好」。"""
    assert confirmation_verdict(text).value is False


@pytest.mark.parametrize("text", ["history", "this is history", "heyday"])
def test_greeting_needs_whole_latin_token(text: str) -> None:
    """拉丁段只做整段匹配：中文没词边界才需要最大匹配，拉丁有。"""
    assert greeting_verdict(text).value is False


def test_greeting_tolerates_trailing_particles() -> None:
    """语气词是残余，不是内容。「早上好呀」跟「早上好」是一回事。"""
    for text in ("你好呀", "您好，在吗？", "谢谢你啦", "早上好呀", "哈哈你好"):
        assert greeting_verdict(text).value is True, text


def test_confirmation_tolerates_particles_and_thanks() -> None:
    """「好了」「行吧」「好的，谢谢」都只是回应，没有新内容。"""
    for text in ("好了", "行吧", "就这样吧", "嗯嗯", "好的，谢谢", "可以的", "收到啦"):
        assert confirmation_verdict(text).value is True, text


def test_confirmation_rejects_new_content() -> None:
    """一旦带了新要求，它就不是"空泛的同意"了。"""
    for text in ("可以，但标题要居中", "好，顺便把日期改一下", "行，字号调大两号"):
        assert confirmation_verdict(text).value is False, text


# ---------------- 第 2 类：撤回不是同意 ----------------


def test_retraction_is_not_confirmation() -> None:
    """「算了」「先不弄了」里含确认词和语气词的字符，语义却相反。

    这是最危险的一类假阳性：把"不要"读成"要"，直接产出一份没人要的文件。
    """
    for text in ("算了", "不用了", "先不弄了", "别弄了", "取消", "到此为止"):
        verdict = retraction_verdict(text)
        assert verdict.value is True, text
        assert confirmation_verdict(text).value is False, text


def test_questioning_a_confirmation_is_not_consent() -> None:
    """「行吗」是在问，不是在答。"""
    assert confirmation_verdict("行吗").value is False
    assert confirmation_verdict("可以吗").value is False


# ---------------- 第 3 类：句法位置 ----------------


@pytest.mark.parametrize(
    "text",
    [
        "先别生成吧",
        "不要直接生成",
        "不用改吧",
        "没必要现在弄吧",
        "晚点再生成吧",
    ],
)
def test_negated_commit_is_not_commit(text: str) -> None:
    """否定紧挨着动作，「……吧」就不算拍板。

    旧实现只看「动作 + 吧」，这四句全会放行——而且是放行到写盘。
    """
    verdict = commit_verdict(text)
    assert verdict.value is False, text
    assert any("否定" in item for item in verdict.evidence), text


@pytest.mark.parametrize(
    "text",
    ["如果按这个来", "要是按这个来，会不会太快", "假如直接生成，会不会太长", "一旦开始吧"],
)
def test_hypothetical_commit_is_not_commit(text: str) -> None:
    """条件从句里的「拍板」是假设。"""
    assert commit_verdict(text).value is False, text


@pytest.mark.parametrize(
    "text",
    ["他说按这个来", "老板要求直接生成", "文档里写着按这个来", "你刚才说按这个来是什么意思"],
)
def test_reported_commit_is_not_commit(text: str) -> None:
    """转述别人的话不是自己拍板。"""
    assert commit_verdict(text).value is False, text


def test_authorized_phrase_is_not_mistaken_for_reporting() -> None:
    """「按你说的来」是最典型的授权，不能被引述规则误伤。"""
    assert commit_verdict("按你说的来").value is True


@pytest.mark.parametrize(
    "text",
    [
        "刚才那个不生成吧",  # 裸「不」也必须算否定
        "生成吧——不对，等等",  # 说完自己反悔
        "不用你生成了，我自己来",
        "要是不着急的话就明天再生成吧",
        "我看看再决定吧",
        "先这样吧，明天再说",
        "你要不要先给我看一下再生成",
        "上次生成的周报能不能再改改",
        "帮我看看结构合不合理，别改内容",
    ],
)
def test_adversarial_non_commit(text: str) -> None:
    """这些句子都由人写出来测试过，全部是「像拍板但没拍板」。

    每一条都对应一个具体的错法：裸否定、自我反悔、受益请求里的动作词、
    假设句、句尾「再说」、疑问嵌套。判错任何一条，代价都是一份多余的文件。
    """
    verdict = commit_verdict(text)
    assert verdict.value is False, f"{text} → {verdict.evidence}"


def test_negation_in_another_clause_does_not_block() -> None:
    """否定只在同一分句生效：「不错，直接生成吧」里的「不」隔着一个逗号。"""
    assert commit_verdict("不错，直接生成吧").value is True


@pytest.mark.parametrize(
    "text",
    [
        "直接生成吧，先不弄了",
        "就按这个来吧，回头再说",
        "改成横向吧，这个先不做了",
        "整理成一份吧，等我确认了再动手",
    ],
)
def test_soft_retraction_after_the_phrase_blocks(text: str) -> None:
    """拍板短语本身完整、位置也对，软反悔长在**后面那个分句**里。

    这是按短语判定的天然盲点：`_blocker` 只往前看（否定、条件、引述），
    往后看只看句号前的疑问和「算了」。「生成吧，先不弄了」里没有任何一个词
    是拍板短语的一部分，否定在隔壁分句——以前整句判成拍板，直接落盘。
    """
    verdict = commit_verdict(text)
    assert verdict.value is False, text
    assert any(("推后" in item) or ("否掉" in item) for item in verdict.evidence), text


def test_soft_retraction_does_not_eat_real_commits() -> None:
    """「不用问了」「别再问了」是把拦路的东西拿开，不是在否掉动作。"""
    for text in ("直接生成吧，不用问了", "就按这个来吧，别再问了", "生成吧，别忘了加页脚"):
        assert commit_verdict(text).value is True, text


@pytest.mark.parametrize(
    "text",
    [
        "改成横向吧，如果领导同意的话",
        "改吧的话，我看行",
        "排版吧，只要别太挤",
    ],
)
def test_weak_commit_inside_a_protasis_is_not_a_commit(text: str) -> None:
    """弱匹配（动作 + 「吧」）分不清主句和条件从句的前件。

    「改成横向吧，如果领导同意的话」：动作、语气词、位置全对，只有意思是
    "等同意再改"。强说法是人挑过的、配上条件读起来就是假设，前缀检查够用；
    弱说法必须再查一遍所在分句与紧邻的下一分句是不是条件从句。
    """
    verdict = commit_verdict(text)
    assert verdict.value is False, text
    assert any("条件" in item for item in verdict.evidence), text


def test_negation_inside_the_span_blocks() -> None:
    """「这样改不太好吧」——否定长在词组内部，同样要挡。"""
    assert commit_verdict("这样改不太好吧").value is False


def test_negation_guard_only_applies_to_weak_matches() -> None:
    """否定闸只管正则拼出来的弱匹配，不管人选进表里的短语。

    「不用问了」「别再问了」带否定词，意思偏偏是"别问了、直接做"。
    让否定闸去拦它们，等于表里两个词当场作废——这个 bug 是靠
    `test_every_phrase_in_the_table_can_stand_alone` 抓出来的。
    """
    assert commit_verdict("不用问了").value is True
    assert commit_verdict("别再问了，动手吧").value is True
    # 弱匹配那条路不能跟着松：「改不太好吧」里没有表内短语可依靠
    assert commit_verdict("这样改不太好吧").value is False


@pytest.mark.parametrize(
    "text",
    ["按这个来会不会太快", "就按这个是不是更好", "按你说的来，要不要再加一段"],
)
def test_question_marker_after_the_phrase_is_not_a_decision(text: str) -> None:
    """疑问标记落在短语**后面**，说明短语只是话题。

    中文常常不打问号：「按这个来会不会太快」。只看句尾问号会把它当成决定，
    然后就是一次没人要的生成。判据仍然是位置，不是词。
    """
    verdict = commit_verdict(text)
    assert verdict.value is False, text
    assert any("疑问" in item for item in verdict.evidence), text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("直接生成一份周报吧", True),
        ("就按这个，落盘", True),
        ("按你说的来", True),
        ("帮我直接生成一份周报", True),
        ("开始吧", True),
        ("生成一份吧", True),  # 弱说法，靠句尾「吧」
        ("把这份材料整理成周报", False),  # 只是描述要做的事，没说"就做"
        ("这几份整理一下", False),
        ("改改标题", False),
        ("把标题居中", False),
        ("按你说的来？", False),  # 句尾疑问 = 在确认
        ("这份周报怎么改好？", False),
    ],
)
def test_commit_verdict_table(text: str, expected: bool) -> None:
    """拍板判定的主表。两个方向都要有：漏判只是多问一句，误判会出文件。"""
    assert commit_verdict(text).value is expected, text


# ---------------- 征询 ----------------


@pytest.mark.parametrize(
    "text",
    [
        "这份周报我想改成给老板看的版本，怎么改好？",
        "把标题改成 8 号字，是不是会太挤",
        "这样行吗",
        "要不要按月份拆开",
        "你觉得哪种排法好",
        "有什么建议吗",
    ],
)
def test_advice_is_asking_not_telling(text: str) -> None:
    assert advice_verdict(text).value is True, text


def test_polite_request_is_not_advice() -> None:
    """「能帮我生成一份吗」是请你动手，不是问你怎么看。

    判成征询的后果是它同时压掉拍板信号，于是一句明确请求被拖成一轮反问。
    """
    verdict = advice_verdict("能帮我生成一份周报吗")
    assert verdict.value is False
    assert any("请求" in item for item in verdict.evidence)


def test_benefit_word_in_another_clause_does_not_cancel_advice() -> None:
    """受益标记必须**就近**：「顺便帮我改下标题」是另一件事。

    错法：在这个方案你觉得行吗？顺便帮我改下标题」。他把判断交给你，
    「帮我」在另一个分句里管的是标题。以前是全文 search，一个隔着一整个
    分句的「帮我」就能把真征询否掉，于是你开始动手改东西。
    """
    assert advice_verdict("这个方案你觉得行吗？顺便帮我改下标题").value is True
    # 同一分句里、紧贴动作的受益标记才算请求
    assert advice_verdict("帮我看看这段怎么改好").value is False
    assert advice_verdict("麻烦你判断一下这样行不行").value is False


def test_asking_for_advice_is_still_advice() -> None:
    """要求的是"意见"本身时，受益标记不改变性质：「给我个建议」仍是征询。"""
    assert advice_verdict("给我个建议，这个标题怎么改好").value is True
    assert advice_verdict("帮我拿个主意吧，选哪个").value is True


# ---------------- 形状与兜底 ----------------


def test_blank_covers_emoji_and_invisible_chars() -> None:
    """纯表情、纯零宽字符都等于没说事。"""
    assert is_blank("   ") is True
    assert is_blank("。。。") is True
    assert is_blank("👍👍") is True
    assert is_blank("\u200b\u200b") is True
    assert blank_verdict("👍").value is True


def test_fullwidth_and_mixed_width_are_normalized() -> None:
    """全角问号、全角字母、零宽连接符都要归一到同一种写法。"""
    assert bare_confirmation("好的，谢谢") is True
    assert explicit_commit("直接生成！") is True
    assert explicit_commit("按你说的来？") is False  # 全角问号也是问号
    assert greeting_only("ｈｅｌｌｏ") is True  # 全角拉丁
    assert normalize(" 你 好 ") == "你好"


def test_long_message_is_analyzed_from_the_tail() -> None:
    """长消息只看尾部：拍板在句尾，开头往往是粘进来的材料。

    注意这**不是**长度判据——长度从不参与"他是不是在商量"，
    它只决定看哪一段。
    """
    filler = "会议记录：" + "今天讨论了排期和预算。" * 60
    shaped = explain(filler + "直接生成吧")
    assert shaped["truncated"] is True
    # 纯长文不可能被当成寒暄：那不是"短句算聊天"，是看不到全貌就不下结论
    assert greeting_verdict(filler + "谢谢").value is False


def test_truncated_message_never_counts_as_a_commit() -> None:
    """分析窗口被截断时，直接不认拍板——**不是**降低置信度。

    错法：窗口里看到「直接生成吧」，于是判成拍板。可是前缀被切掉了，「如果
    ……就……」的「如果」可能正好在被切掉的那一段；引述（「他说」）、否定
    （「先别」）同理。以前的做法是扣 0.05 把握度，而 0.9-0.05=0.85 照样越过
    门控的下限 0.72——降了个寂寞。

    代价是"长材料 + 拍板"不再由确定性层放行。这一句该由理解层读全文来判断，
    它读得到整段，本来也比这里更该做这个判断。
    """
    filler = "会议记录：" + "今天讨论了排期和预算。" * 60
    verdict = commit_verdict(filler + "直接生成吧")
    assert verdict.value is False
    assert any("截断" in item for item in verdict.evidence)
    # 兜底交付那条路同理：短语位置不可信，就不替模型补动作
    assert phrase_stands(filler + "直接生成吧", ["直接生成"]).value is False
    # 截断只看分析，不影响「有没有内容」这类判断
    assert is_blank(filler) is False


def test_intent_of_never_returns_write() -> None:
    """兜底永远站在便宜的一边：模型都读不懂，就没资格替用户决定落盘。"""
    samples = [
        "你好",
        "   ",
        "帮我写一份周报",
        "就按这个，直接生成",
        "把标题居中",
        "算了",
        "👍",
    ]
    for text in samples:
        assert intent_of(text) != INTENT_WRITE, text
    assert intent_of("你好") == INTENT_CHAT
    assert intent_of("👍") == INTENT_CHAT
    assert intent_of("帮我写一份周报") == INTENT_READ


def test_classify_carries_confidence_and_evidence() -> None:
    signal = classify("你好")
    assert signal.intent == INTENT_CHAT
    assert signal.confidence >= 0.9
    assert signal.evidence

    signal = classify("这两份周报合成一份更合适")
    assert signal.intent == INTENT_READ
    assert signal.confidence < 0.9, "读不出要不要动手时，把握度必须低"


def test_explain_exposes_every_signal() -> None:
    """排障要能回答「它到底看到了什么」。"""
    report = explain("先别生成吧")
    assert report["analyzed"] == "先别生成吧"
    assert report["question_tail"] is False
    assert set(report["signals"]) == {
        "blank",
        "greeting",
        "confirmation",
        "advice",
        "commit",
        "hold",
    }
    assert report["signals"]["commit"]["value"] is False
    assert report["signals"]["commit"]["evidence"]
    assert report["intent"]["intent"] in {INTENT_CHAT, INTENT_READ}


def test_verdicts_are_hashable_and_jsonable() -> None:
    """判定要能进日志、进缓存。"""
    verdict = commit_verdict("就按这个，落盘")
    assert hash(verdict) == hash(commit_verdict("就按这个，落盘"))
    payload = verdict.as_dict()
    assert payload["value"] is True
    assert isinstance(payload["evidence"], list)


def test_empty_input_never_raises() -> None:
    for text in ("", "   ", "\n\n", "\x00", None):  # type: ignore[arg-type]
        assert intent_of(text) in {INTENT_CHAT, INTENT_READ}
    assert asks_advice("") is False


# ---------------- 方向性护栏：拿真实说法做回归 ----------------

_UTTERANCES = Path(__file__).resolve().parents[1] / "data" / "utterances.jsonl"


def _load_utterances() -> list[dict[str, str]]:
    if not _UTTERANCES.exists():  # pragma: no cover
        return []
    rows: list[dict[str, str]] = []
    for line in _UTTERANCES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            rows.append(json.loads(line))
    return rows


#: 白纸黑字把决定说出口的说法：兜底必须认出来。
#:
#: 这份清单**故意写死在测试里**，不从 `_STRONG_COMMIT` 读。从表里读只能证明
#: "表里的词还能用"，证明不了"词表没被删空"——删掉一条，它就跟着少一条，
#: 测试还是绿的。所以这里是独立的一份底账。
_MUST_CATCH = (
    "直接生成一份周报吧",
    "就按这个，落盘",
    "按这个来，导出成 pdf",
    "开始吧",
    "嗯，就这么办",
    "按你说的来",
    "不用问了",
    "别再问了，动手吧",
    "导出成 pdf",
    "存下来",
)


def test_zero_dangerous_authorizations_on_real_utterances() -> None:
    """确定性层绝不能在「他还在商量」的句子上判出拍板。

    这是全项目最贵的一条断言：它守的是「一份没人要的 docx」那个入口。
    往 `_STRONG_COMMIT` / `_WEAK_COMMIT_RE` 里加词之前先跑一遍这里——
    加词让它这次对，加样本才知道它下次错在哪。
    """
    rows = _load_utterances()
    if not rows:  # pragma: no cover
        pytest.skip("评估集缺失")

    dangerous = [
        row["text"]
        for row in rows
        if row.get("commitment") != "authorized" and commit_verdict(row["text"]).value
    ]
    assert dangerous == [], f"这些句子被判成拍板了，但标注说没有：{dangerous}"


def test_commit_lexicon_still_covers_the_obvious_cases() -> None:
    """反向护栏：白纸黑字说「直接生成」时，兜底必须放行。

    这条防的是"越改越保守"——把所有说法都判成没授权，安全但没用。

    **曾经这里卡的是「评估集漏判不超过 30 条」**。那个数不成立：它随样本
    数量一起涨，加一条祈使句就挤占一格配额，最后调的是配额不是判据。
    改成对上面这份固定清单零漏判，精确、且不随数据集缩水。
    """
    missed = [text for text in _MUST_CATCH if not commit_verdict(text).value]
    assert missed == [], f"兜底认不出这些明确的拍板：{missed}"


def test_every_phrase_in_the_table_can_stand_alone() -> None:
    """表内短语单独说出来，必须判成拍板。

    这条抓的是"表里写着一个词，闸门却永远让它过不去"——「不用问了」
    「别再问了」就这样被自己的否定闸白关了半年：词在表里，
    判定时被当成否句。逐条跑一遍才看得见。
    """
    broken = [phrase for phrase in _STRONG_COMMIT if not commit_verdict(phrase).value]
    assert broken == [], f"这些词在表里，却永远判不出拍板：{broken}"


# ---------------- 叫停 / 只问 / 推后：三种都不是授权 ----------------
#
# 一句话把这三类全踩了：「先别生成吧，我就是想问问周报该怎么写」。
# 它在词法上含有最强的拍板短语「生成吧」，语义上却是"现在别动，我只是问"。
# 靠位置（「先别」在短语前面）和自述（「我就是想问问」）才判得对。


def test_hold_sees_stop_ask_and_deferral() -> None:
    stopped = hold_of("先别生成吧，我就是想问问周报该怎么写")
    assert stopped is not None
    assert stopped.target == HOLD_NONE

    asking = hold_of("我只是打听一下周报的格式")
    assert asking is not None, "他明说自己只是在问"
    assert asking.target == HOLD_NONE

    deferred = hold_of("先给方案，我点头了再落盘")
    assert deferred is not None
    assert deferred.target == HOLD_PROPOSED, "方向对、时间没到：可以说打算，不能动手"


def test_hold_is_silent_when_he_actually_ordered_something() -> None:
    """拍板压过叫停：「先别管格式」管的是另一件事，不该把整句否掉。"""
    for text in (
        "先别管格式，直接生成吧",
        "直接生成一份周报",
        "帮我生成一份周报",
        "我确认了，直接生成吧",
    ):
        assert hold_of(text) is None, f"这句是明确下令，不该被 hold 拦下：{text}"


def test_hold_ignores_the_same_words_in_someone_elses_mouth() -> None:
    """「他说先别生成」是转述别人的话，不是他叫停。"""
    assert hold_of("老板说先别生成，等他看完再说") is None
    assert hold_of("客户的意思是先别写退款那段") is None


def test_deferred_authorization_is_not_an_authorization() -> None:
    """「我点头了再落盘」含最硬的拍板词「落盘」，整句却是"现在别落盘"。"""
    assert commit_verdict("先给方案，我点头了再落盘").value is False
    assert commit_verdict("等我确认了再生成").value is False
    # 确认过了就不再是推后
    assert commit_verdict("我确认了，直接生成吧").value is True


def test_phrase_stands_reads_the_word_in_front_of_it() -> None:
    """引擎兜底以前是 `keyword in message`：看不出「生成吧」前面站着「先别」。"""
    markers = ("生成吧", "直接生成", "开始做")
    assert phrase_stands("先别生成吧，我就是想问问周报该怎么写", markers).value is False
    assert phrase_stands("别先生成吧", markers).value is False
    assert phrase_stands("生成吧", markers).value is True
    assert phrase_stands("帮我生成吧", markers).value is True


def test_phrase_stands_does_not_take_a_question_for_an_order() -> None:
    """「你说从哪开始做比较好」里的「开始做」是话题，不是命令。"""
    markers = ("开始做", "现在就做")
    for text in ("你说从哪开始做比较好", "从哪开始做呢", "现在就做，还是等明天？"):
        assert phrase_stands(text, markers).value is False, text


def test_standing_phrase_returns_the_words_that_fired() -> None:
    """命中时要给出**短语原文**：日志靠它回答「哪句话被当成了命令」。

    从 evidence 里反抠引号是不行的——短语本身就可能带引号（「就按这个」）。
    """
    markers = ("生成吧", "直接生成", "就按这个")
    phrase, verdict = standing_phrase("行，就按这个来", markers)
    assert verdict.value is True
    assert phrase == "就按这个"
    assert phrase in verdict.evidence[0]

    phrase, verdict = standing_phrase("先别生成吧", markers)
    assert verdict.value is False
    assert phrase == "", "被否决的短语不能当成命中，否则日志会指错方向"


def test_a_narrowing_clause_is_not_a_call_off() -> None:
    """「先不用改，改标题就行」——他把范围收窄了，动作还在。

    第一版 hold 只看「先不用」，把整句判成"别动"，于是这个明确的窄指令
    被拦下来问了一句。评估里表现为"保守 +1"，是这轮唯一自己引入的误伤。

    判据还是位置：叫停后面若跟着「……就行 / ……就好」，它是在**指定**做什么，
    不是在停手。真正的叫停不会跟一句"改这个就行"。
    """
    assert hold_of("这个先不用改，改标题就行") is None
    assert hold_of("先别改格式，把标题居中就行") is None
    # 没有收窄句时照旧叫停
    assert hold_of("先别生成吧，我就是想问问周报该怎么写") is not None


# ---------------- 直接下令：句内自足的命令 ----------------
#
# 语料里 45 条 authorized，`commit_verdict` 只认出 7 条（16%）。把 38 条漏判
# 逐条铺开看，**没有一条是"词表少了一个词"**：它们主要是直接下令（「把标题居中」
# 「删掉第二段」）。这是少了一整个维度，不是密度不够。
#
# 但补法不是把 `commit_verdict` 加宽——那会让"描述要做的事"也变成拍板，
# 而「把这份材料整理成周报」被判 False 是 `test_commit_verdict_table` 里
# 有意写下的立场。所以补的是**第二个问题**：`order_verdict` 问"他有没有
# 让我动手"，用途是 `fallback_reading` 里的 goal——**记下要做什么，不给权限**
# （祈使句不说明范围，兜底没法替他确认哪份文件）。
# 下面每条都把两个函数的边界一起钉住。


def test_a_direct_order_is_an_order_but_not_a_verdict() -> None:
    """「把标题居中」够不上"他决定了"，但够得上"他让我做"。

    为什么不能靠加词：祈使句是**开放集合**——动词 × 宾语无限组合，加二十个
    词也罩不住「把表里的数据核对一遍」。句式才是有限集合。

    这五句取自语料里真实标为 authorized 的说法，改动前 `order_verdict` 一条
    都认不出，兜底时连"他要做什么"都记不下来，只能反问一句。
    """
    for text in (
        "把标题居中",
        "改成 8 号字",
        "删掉第二段",
        "把这两份合并成一个文件",
        "帮我把三个文件的内容对比一下",
    ):
        assert order_verdict(text).value is True, text
        # 边界：它仍然不是"决定"。两个问题必须分开答。
        assert commit_verdict(text).value is False, text


def test_describing_what_to_do_is_not_an_order() -> None:
    """「我想整理成摘要，你觉得先动哪份」不是在让我动手。

    这是加句式规则时**真的踩到**的误判：`整理成` 命中了，可他要的是
    "先动哪份"的答案。真照办的话，他还没选，文件已经出来了。

    判据是整句的性质：征询会笼罩整个句子，不管动作词落在哪。
    """
    text = "这几份材料我想整理成摘要，你觉得先动哪份"
    assert order_verdict(text).value is False
    assert "征询" in order_verdict(text).evidence[0]


def test_an_imperative_inside_long_material_is_not_an_order() -> None:
    """三百字材料里的「把…改成…」是内容，不是指令。

    实测来源：语料里一条会议记录含「运营建议把五百元以下的小额退款改为系统
    自动放行」，句式完全命中。用户在问"有没有漏掉的"，内核却认为他下了令。

    这是祈使规则**必须带长度上限**的原因：真下令的句子很短，长句里的祈使
    多半是材料原文或转述。注意这条要落在分析窗口内，否则测到的是截断那条
    规则，而不是这里想测的位置规则。
    """
    material = "会议记录：" + "运营建议把五百元以下的小额退款改为系统自动放行。" * 12
    assert MAX_ANALYZED_CHARS // 2 < len(material) < MAX_ANALYZED_CHARS
    assert shape_of(material).truncated is False, "这条不该被截断规则兜住"
    assert order_verdict(material).value is False


def test_handing_the_decision_over_is_authorization_not_advice() -> None:
    """「你看着办吧」是把决定权交出去，不是征询意见。

    以前 `_ADVICE_RE` 里收了「你看着办」，于是它被判成**征询**。征询会压掉
    拍板信号，一句明确的授权被拖成一轮反问——而语料里它标的是 authorized。
    """
    assert advice_verdict("你看着办吧").value is False
    assert order_verdict("你看着办吧").value is True
    assert order_verdict("随便，哪个都行").value is True


def test_bare_confirmation_is_not_self_contained() -> None:
    """「好」「可以」两个函数都不判——它授权了什么，只有上一轮知道。

    这条是护栏，防的是"为了提高召回把它加进去"。语料里它们确实标
    authorized（有上下文时成立），但两个判定都只看得到这一句：单句判
    authorized 正是误生成的入口。`deterministic_reading` 的注释写的是
    同一件事，两处必须一致。

    它们不是"漏判"，是**职责不在这一层**——这也是这轮最容易被算错的一笔账：
    6 条"看起来最便宜"的漏判，其实是唯一不该补的。
    """
    for text in ("好", "可以", "就这个", "继续"):
        assert commit_verdict(text).value is False, text
        assert order_verdict(text).value is False, text
