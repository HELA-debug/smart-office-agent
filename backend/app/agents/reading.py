"""读懂这一轮用户到底要什么，以及他授权你做到哪一步。

## 为什么不再用关键词

旧版的 `intent.py` 是一张动作词表：出现「生成 / 整理 / 改成」就判派活，否则按字数猜。
它的两处结构性错误：

- **把语法特征当意图。** 商量的时候也天天说「改成」「整理」，
  于是「这份周报想改成给老板看的版本，怎么改好？」被判成派活，文件直接生成了。
- **用长度代替理解。** 「这个表按月份拆开会清楚很多」很短，却是在让你动手；
  「按刚才说的那样」更短，却是明确授权。长度和意图没有关系。

补词救不了这件事：词表是封闭的，人的说法是开放的。

## 现在判什么

不再问「这句话里有没有动作词」，而问两个更接近人的问题：

1. **`stance`：他这一轮要的是话、是判断，还是一个结果？**（chat / explore / direct）
2. **`commitment`：他拍板了没有？**（none / proposed / authorized）

第二个才是关键。同一句「整理成周报」，在「你觉得整理成周报好不好」和
「就按这个整理成周报」里，动作词一模一样，但前者不能动手、后者必须动手。
区分它们的不是动词，是**有没有把决定说出口**。

## 三条硬规则

1. **判错往宽了兜。** 理解调用失败、输出不合格式，一律退到「能读、不能写」，
   而不是「只能聊」。少给能力的代价是用户再说一句；多给一次写权限的代价是一份
   没人要的文件。
2. **不确定就问，不硬猜。** `confidence` 低且缺关键信息时，这一轮不动手，
   只把 `question` 问出来。猜错要白干一轮加上一份多余产物，问一句只要半句话。
3. **授权不是一次性的，但会过期。** 上一轮的 `authorized` 不会自动延续到这一轮：
   用户说「再改改」是新的一轮，得重新判。上下文能给的是「他在回应什么」，
   不是「他已经同意过」。

## 结果拿去干什么

`stance` 决定提示词重心和步数预算，**不直接决定能不能写文件**——
写权限由 `policy.py` 按「是否已授权 + 工具风险」单独把关。
理解层判错，最多让话风不对；不会让一份没人要的文件出现在产物仓库里。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

from .intent import (
    HOLD_NONE,
    INTENT_CHAT,
    INTENT_READ,
    INTENT_WRITE,
    commit_verdict,
    greeting_only,
    hold_of,
    intent_of,
    is_blank,
    order_verdict,
)

logger = logging.getLogger(__name__)

# ---------------- 档位 ----------------

STANCE_CHAT = "chat"
STANCE_EXPLORE = "explore"
STANCE_DIRECT = "direct"
STANCES: tuple[str, ...] = (STANCE_CHAT, STANCE_EXPLORE, STANCE_DIRECT)

#: 授权程度。名字刻意用「承诺」而不是「意图」：它描述的是他**说到哪一步**，
#: 不是他**想什么**。想什么是猜的，说到哪一步是能看出来的。
COMMIT_NONE = "none"
COMMIT_PROPOSED = "proposed"
COMMIT_AUTHORIZED = "authorized"
COMMITMENTS: tuple[str, ...] = (COMMIT_NONE, COMMIT_PROPOSED, COMMIT_AUTHORIZED)

#: stance → 引擎里「给多少提示词 / 多少步」的老三档。
#: 注意这套映射**不再决定工具可见性**：工具永远全给，写权限由 policy 把关。
#: 它现在只剩一个用途：给旧调用方（mock 剧本）一个说得通的粗粒度标签。
#: 真正决定提示词组合与步数的是下面的 `delivery`——它把 write 拆成了 draft/deliver。
STANCE_TO_INTENT: dict[str, str] = {
    STANCE_CHAT: INTENT_CHAT,
    STANCE_EXPLORE: INTENT_READ,
    STANCE_DIRECT: INTENT_WRITE,
}

# ---------------- 交付形态 ----------------
#
# stance 说的是「他要话还是要结果」，commitment 说的是「他拍板没有」。
# 两维交叉出四种完全不同的处境，用一套提示词招呼它们是不够的：
#
#   direct + proposed（「我想弄成一份周报，你看行吗」）
#   以前落到 write 档，拿到的是「用户要文件就调 doc_generate_report，不能只在回复里
#   给文本」，同时又收到一句「他还在商量，这一轮不要生成」。两段话打架，模型只能自己
#   调和——评估里 stance 忽高忽低，一半是这个原因。
#
# 所以再多切一刀：**方向已明确但还没拍板**，给方案、给取舍、给一句问话，不落盘。
DELIVERY_CHAT = "chat"
DELIVERY_READ = "read"
DELIVERY_DRAFT = "draft"
DELIVERY_DELIVER = "deliver"
DELIVERIES: tuple[str, ...] = (
    DELIVERY_CHAT,
    DELIVERY_READ,
    DELIVERY_DRAFT,
    DELIVERY_DELIVER,
)

#: 复述、提问、缺口的字数上限。这些是**防跑飞的天花板**，不是表达上限：
#: 卡到四十字、六十字的后果是模型把「缺什么」压成半句，用户看不出到底缺哪一样，
#: 于是又来回一轮——省下的字数全变成多问的轮次。宁可宽一点。
GOAL_MAX_CHARS = 120
QUESTION_MAX_CHARS = 120
MISSING_MAX_CHARS = 160
SCOPE_MAX_ITEMS = 12
BASIS_MAX_CHARS = 160

#: 低于这个把握度，就不许靠猜动手；也是 `needs_confirm` 的分界。
#: 定在 0.75 而不是 0.65：实测里模型的 0.6–0.7 基本等于「我在两档之间犹豫」，
#: 那个分数段的判断在评估集上错误率明显更高。也不要定到 0.9——那样每个
#: 明确指令都要先问一句，同事之间不这么说话。
CONFIDENCE_FLOOR = 0.75

#: 给理解层看的历史：最近几轮、每侧截断。要够看到「上一轮我提了什么方案」，
#: 否则一句「好」无法解读——那是授权还是敷衍，全看上一句说了什么。
HISTORY_MESSAGES = 8
HISTORY_SIDE_CHARS = 240

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)
_FENCE_RE = re.compile(r"^\s*```(?:json)?|```\s*$", re.M)


READING_RULES = """# 你现在只做一件事：读懂他这一轮要什么，以及他授权到哪一步

不要执行任务、不要写文件、不要客套。只输出一个 JSON 对象，别的什么都不要。

你要回答的是两个问题，不是三个标签：

1. 他这一轮要的是**话**、是**判断**，还是一个**结果**？（stance）
2. 他**拍板了没有**？（commitment）

## stance

- `chat`：只是在说话。寒暄、道谢、情绪、跟手上材料无关的闲聊。
- `explore`：想知道点什么、想听你的判断、在跟你商量怎么办。
  包括：问材料里有什么、让你评估、问你怎么改、给了一堆要求但还在讨论。
- `direct`：他要一个具体结果，或者明确让你动手。

判 `direct` 的依据**不是句子里有没有「生成 / 整理 / 改」这类词**，而是他是不是
已经在要那个东西了。「这份周报想改成给老板看的版本」有「改成」，但他在说想法。

## commitment（这一栏最重要）

它说的是**「他有没有让你动手」**，不是「他要不要文件」。
让你读一份材料、让你把原文贴过来、让你核对一遍数据，都是动手。

- `none`：没提要动手，或者只是在问、在聊。
- `proposed`：提了要求、给了方向，但还没定下来——还带着「想 / 打算 / 要不 /
  是不是 / 你看行吗 / 我觉得」这类没落地的语气。**这时候动手就是错。**
- `authorized`：已经把决定说出口了，或者这件事本身明确到不需要再确认。

判 `authorized` 的四个依据，满足其一即可：

1. **说了拍板的话**：「就按这个」「直接生成」「就这么办」「开始吧」「按你说的来」
   「可以，弄吧」，以及**带语气词的短命令**：「你生成吧」「生成吧」「出吧」
   「做吧」「改吧」。后者只有一个动作加一个语气词，是命令，不是提议——
   不要把「吧」读成"也许"。
2. **上轮你提了具体方案，这轮他短促确认**：「好」「行」「嗯」「可以」「就这个」。
   没看到上轮方案时不要猜成 authorized。
3. **祈使句，且对象、范围、结果都唯一**：「把标题居中」「把这两份合并成一个文件」
   「改成 8 号字」「帮我把三个文件对比一下」。明确、范围小、不需要再定任何事。
4. **祈使式的纠正**：「标题再大一点」「表格别用横线」「第二段删掉」——
   这是对已授权工作的延续，直接改，不要再问一遍。

反过来，这些都**不是** authorized：

- 「你觉得整理成周报好不好」——在问意见。
- 「这两份合成一份会清楚很多」——一句判断，没说要不要做。
- 「我想把这几份材料弄成一份周报，你看行吗」——带确认。
- 「要不先出个草稿？」——在提议。
- 「先别动，我再想想」——明确叫停，commitment 记 none。

### 评价不是指令（最容易判错的一处）

「这版太长了」「结构有点乱」「这一版不对」「看得很累」——这些是在**描述问题**，
不是在告诉你该怎么改。他不知道要改成什么样，你也不知道，这时候直接重做一版
只是赌一把。这种给 `proposed`，先说你的判断和打算，再问一句。

判据很简单：**句子里有具体的改法（改哪个、改成什么）才是指令**；
只有形容词和感受的，是评价。

## 对照表（照这个判，不要照动词判）

| 他说的话 | stance | commitment |
|---|---|---|
| 你好 / 谢谢 / 在吗 | chat | none |
| 你能做什么 / 你是什么模型 | chat | none |
| 这份周报讲了什么 | explore | none |
| 这份周报想改成给老板看的版本，怎么改好？ | explore | none |
| 这个表按月份拆开会清楚很多 | explore | none |
| 这两份合成一份更合适 | explore | proposed |
| 我想弄成一份周报，你看行吗 | direct | proposed |
| 就按你说的，合成一份吧 | direct | authorized |
| 你生成吧 / 生成吧（上轮你在等他确认） | direct | authorized |
| 帮我生成一份周报 | direct | authorized |
| 把标题居中 | direct | authorized |
| 标题再大一点 | direct | authorized |
| 好 / 行 / 就这个（上轮你给了方案） | direct | authorized |
| 先别动，我看看 | chat | none |
| 先别生成吧，我就是想问问周报该怎么写 | explore | none |
| 我就是想问问周报一般怎么写 | explore | none |
| 先给方案，我点头了再落盘 | explore | proposed |
| 我没让你生成啊 | explore | none |

## 不要向用户要口令

他已经把决定说出口时，**「你说『就这样』我再动手」是错的**——他刚说的那句就是。
只有缺一样「不做就会做错」的信息（哪份文件、改哪一段、给谁看）才值得问，
而且问的是那个信息，不是一句确认。

判错的代价不对称：多问一句，用户要再打一遍字；直接做，最多是多改一次。

## 叫停、只问、推后：这三种都不是授权

它们经常和动作词同时出现（「先别**生成**吧」「我点头了再**落盘**」），
按词判必错。判断只看**他站在动作的哪一边**：

- **叫停**：「先别 / 暂时别 / 不用 / 别急 / 这版我不要了」。他说的是"现在不要"，
  commitment 记 `none`。别因为他顺带提了一句"该怎么写"就改判。
  **也不要反过来问"要不要我做"**——他已经说了先别，再问一遍等于没听见。
- **只是问**：「我就是想问问」「我只是想了解一下」「我想知道怎么写」。
  这是**他自己说的意图**，比任何推断都可信。他要的是方法和判断，
  给一段能直接用的说明就是交付，不是半成品。
- **推后**：「等我确认了再…」「我点头了再…」「回头再说」。方向定了但**时间没到**，
  记 `proposed`：可以说打算，不能动手。
- **否认**：「我没让你生成啊」「谁说要做了」。记 `none`，并且不要辩解，
  直接回答他真正问的那件事。

唯一例外：叫停和明确指令**同时**出现时（「先别管格式，直接生成吧」），
按明确指令判——它更具体，而「先别管」管的是另一件事。

## 输出字段

```json
{
  "goal": "用第二人称说清他要的结果，一句到两句，把条件、范围、口径写进去",
  "stance": "chat | explore | direct",
  "commitment": "none | proposed | authorized",
  "scope": ["涉及的文件名或范围；没点名就空数组"],
  "missing": "要动手但还缺的关键信息；不缺就空串",
  "question": "真缺信息时你要问他的那一句；否则空串",
  "confidence": 0.9,
  "basis": "你为什么这么判，一到两句话，写清抓住的依据"
}
```

字段要求：

- `goal` 说的是**他要的结果**，不是他的原话。他说「这四份材料我想弄成一份」，
  goal 应该是「把这四份材料合成一份」。不要写「他想让我帮他整理材料」这种空话。
  **不要为了短而丢掉限定条件**：篇幅、受众、口径、格式、要动的范围，凡是这一轮
  说清楚了的都写进去。压成十个字的 goal 会让你自己下一轮忘掉这些条件。
- `scope` 只放材料清单里真实存在的文件名。他没点名就留空数组，不要编。
- `missing` 只在「不确认就一定会做错」时才写。格式、篇幅、口径这类能靠常识
  或惯例决定的，不要写。真缺就写清楚缺哪一样、为什么缺了会做错。
- `question` 必须是一句能直接发出去的话，一次只问一件，不要列 1/2/3 菜单。
- `confidence` 是 0 到 1 的数。这句话有多种读法、或你在两档之间犹豫时，给低分。
  **宁可给 0.5 让他被问一句，也不要给 0.9 赌一把。**
- `basis` 写你抓住的那个关键依据（「用了『就按这个』」「上轮你问了要不要合并」），
  便于事后核对是哪里判错了。一句不够就写两句，别为了凑字数丢掉关键那一半。
"""


@dataclass(frozen=True)
class TurnReading:
    """这一轮的理解结果。`source=fallback` 表示模型没有参与，走的是确定性兜底。"""

    stance: str = STANCE_EXPLORE
    commitment: str = COMMIT_NONE
    goal: str = ""
    scope: list[str] = field(default_factory=list)
    missing: str = ""
    question: str = ""
    confidence: float = 0.0
    basis: str = ""
    source: str = "model"

    # ---- 兼容旧调用方 ----

    @property
    def mode(self) -> str:
        """旧字段名。`mode` 就是 `stance`。"""
        return self.stance

    @property
    def restate(self) -> str:
        """旧字段名。`restate` 就是 `goal`。"""
        return self.goal

    @property
    def confident(self) -> bool:
        return self.confidence >= CONFIDENCE_FLOOR

    @property
    def intent(self) -> str:
        """旧的三分档，给 mock 剧本用。"""
        return STANCE_TO_INTENT.get(self.stance, INTENT_READ)

    @property
    def delivery(self) -> str:
        """这一轮该按什么形态交付。决定提示词组合与步数，**不决定权限**。

        两维交叉，四条路：

        - 只是在说话 → `chat`：不背交付架子，读工具只给三行说明。
        - 在问、在评价、在商量但没提要求 → `read`：能读能给判断，不落盘。
        - 方向已经明确、但还没拍板 → `draft`：把方案做实在（具体结构、取舍、
          代价），最后问一句。**不落盘**——问的就是"要不要这么做"。
        - 拍板了 → `deliver`：完整交付，落到文件。

        `direct + none` 这种矛盾组合归到 draft：他要结果，但没说"就做"，
        给方案比直接动手便宜。
        """
        if self.stance == STANCE_CHAT:
            # parse_reading 里已把「chat + authorized」压成 none，这里不用再防
            return DELIVERY_CHAT
        if self.commitment == COMMIT_AUTHORIZED:
            return DELIVERY_DELIVER
        if self.commitment == COMMIT_PROPOSED or self.stance == STANCE_DIRECT:
            return DELIVERY_DRAFT
        return DELIVERY_READ

    # ---- 供策略层使用 ----

    @property
    def authorized(self) -> bool:
        """他是否已经授权动手。"""
        return self.commitment == COMMIT_AUTHORIZED

    @property
    def needs_confirm(self) -> bool:
        """真缺信息、又没把握时，先问一句再动手。

        有 question 但把握够的，说明模型只是顺口给了一句可问的话，不当成阻塞——
        同事之间不会因为想到一个可问的问题就停下来。
        """
        return bool(self.question) and self.confidence < CONFIDENCE_FLOOR


def _clip(text: str, limit: int) -> str:
    value = (text or "").strip().replace("\n", " ")
    if limit > 0 and len(value) > limit:
        return value[:limit].rstrip() + "…"
    return value


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value or "").strip().lower()
        if text in ("true", "yes", "是", "有把握", "high"):
            return 0.9
        if text in ("false", "no", "否", "没把握", "low"):
            return 0.3
        return default
    if number > 1.0:  # 允许模型写 0-100
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _as_scope(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw in value:
        name = _clip(str(raw or ""), 60)
        if name and name not in items:
            items.append(name)
    return items[:SCOPE_MAX_ITEMS]


def parse_reading(text: str) -> TurnReading | None:
    """把模型回的那段东西解析成 TurnReading；认不出档位就返回 None。

    容错三件事：剥掉 ``` 围栏、从杂字里抠出第一个 JSON 对象、字段缺失时用默认值。
    解析不出来不让整轮失败——调用方会退到兜底。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    cleaned = _FENCE_RE.sub("", raw).strip()
    candidate = cleaned if cleaned.startswith("{") else None
    if candidate is None:
        match = _JSON_BLOCK_RE.search(cleaned)
        candidate = match.group(0) if match else None
    if not candidate:
        return None
    try:
        data = json.loads(candidate)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    stance = str(data.get("stance") or data.get("mode") or "").strip().lower()
    if stance not in STANCES:
        return None
    commitment = str(data.get("commitment") or "").strip().lower()
    if commitment not in COMMITMENTS:
        # 授权读不出来时按最保守的算：不动手。
        commitment = COMMIT_AUTHORIZED if stance == STANCE_DIRECT else COMMIT_NONE
    if commitment == COMMIT_AUTHORIZED and stance == STANCE_CHAT:
        # 自相矛盾：一边说只是闲聊，一边说已授权动手。按闲聊算。
        commitment = COMMIT_NONE

    return TurnReading(
        stance=stance,
        commitment=commitment,
        goal=_clip(str(data.get("goal") or data.get("restate") or ""), GOAL_MAX_CHARS),
        scope=_as_scope(data.get("scope")),
        missing=_clip(str(data.get("missing") or ""), MISSING_MAX_CHARS),
        question=_clip(str(data.get("question") or ""), QUESTION_MAX_CHARS),
        confidence=_as_float(data.get("confidence"), default=0.5),
        basis=_clip(str(data.get("basis") or ""), BASIS_MAX_CHARS),
        source="model",
    )


def apply_hold(reading: TurnReading, message: str) -> TurnReading:
    """句子里明确「先别动手」时，把理解层的结论压回去。

    ## 为什么模型判过之后还要再判一次

    理解层是概率判断，同一句话两次能给两个答案（实测「这几份材料你帮我看看，
    我还没想好怎么弄」在 authorized 与 none 之间来回，两次都只有六成把握）。
    而「先别生成吧」「我就是想问问」「我点头了再落盘」是**他自己说出口的**，
    比模型对他的猜测硬。两边打架时，听他自己说的。

    ## 只往一个方向压

    authorized / proposed → none，direct → explore。hold 不授予任何东西，
    所以它判错也只会让这一轮多问一句，不可能凭空多出一份文件。

    顺手把 `question` 清掉：他明说只是问问，再反问他"要不要动手"等于把刚
    说清的边界又搅回去。`missing` 留着——那说的是"答得准还缺什么"，
    跟"要不要动手"是两件事。
    """
    hold = hold_of(message)
    if hold is None:
        return reading

    stance = STANCE_EXPLORE if reading.stance == STANCE_DIRECT else reading.stance
    commitment = COMMIT_NONE if hold.target == HOLD_NONE else COMMIT_PROPOSED
    if reading.commitment == commitment and stance == reading.stance:
        return reading  # 已经在这个方向上了，别改它的依据

    basis = (
        f"{reading.basis}；但他{hold.label}「{hold.text}」，按不动手处理"
        if reading.basis
        else f"他{hold.label}「{hold.text}」"
    )
    return replace(
        reading,
        stance=stance,
        commitment=commitment,
        question="",
        basis=_clip(basis, BASIS_MAX_CHARS),
    )


def apply_commit(reading: TurnReading, message: str, *, has_history: bool) -> TurnReading:
    """句子里有明确的拍板说法时，把理解层的结论**抬**到 authorized。

    ## 为什么模型判过还要再判一次

    `apply_hold` 管的是压档（他说了先别动手），这里是反方向。两件事都得有，
    因为理解层是概率判断：同一句「你生成吧」，带上文判 authorized，光看这四个字
    却很容易读成「他在商量」。线上就这样丢过一次：

        「你生成吧」→ 模型判 proposed → 提示词要求"先说方案再问一句"
        → 它回「你说『就这样』我就出」→ 用户以为要口令才能干活

    而 `commit_verdict("你生成吧")` 本来就是 True——它是一张逐条排除了否定、
    假设、引述、句尾疑问的白名单，「生成吧 / 出吧 / 就按这个」这类短语几乎
    只用于授权。确定性判据说"他拍板了"，就不该被模型的犹豫盖过去。

    ## 两个前提，缺一不可

    - **必须有上文**：短句里的「这个 / 这样」要有指代对象。第一轮就一句
      「按这个来」，谁也不知道"这个"是什么，这时候照旧交给模型。
    - **不覆盖已有的 authorized**：已经是授权就别动它的依据。

    它只往上抬、不往下压，抬错的最大代价是多做一件事（而 `apply_hold` 判错
    只会多问一句）——所以这里的前提比 `hold` 严：短句 + 有上文 + 白名单命中。
    """
    if reading.commitment == COMMIT_AUTHORIZED:
        return reading
    if not has_history:
        return reading
    verdict = commit_verdict(message)
    if not verdict.value:
        return reading

    evidence = verdict.evidence[0] if verdict.evidence else "明确的拍板说法"
    basis = (
        f"{reading.basis}；但他把决定说出口了（{evidence}），按已授权处理"
        if reading.basis
        else f"他把决定说出口了（{evidence}）"
    )
    return replace(
        reading,
        stance=STANCE_DIRECT,
        commitment=COMMIT_AUTHORIZED,
        # 下限 0.85：短句 + 有上文这两条前提已经把引述、假设、指代不明排掉了，
        # 剩下的不确定性只来自"这句话像不像拍板"。不设下限的话，弱正则命中的
        # 0.72 正好压在门控门槛上（`>=` 才过），换条消息长度就可能掉到线下。
        confidence=max(reading.confidence, verdict.confidence, 0.85),
        question="",
        basis=_clip(basis, BASIS_MAX_CHARS),
    )


def fallback_reading(message: str) -> TurnReading:
    """模型读不了时的兜底：能读、基本不能写、不反问。

    这里的原则是**不猜，只认白纸黑字**：

    - 默认给 explore：能读材料、能给判断，但落不了盘。
    - 唯一的例外是句子里有明确的**拍板**说法（「直接生成」「就按这个」
      「落盘」「开始吧」）。这类短语几乎只用于授权，配上「不是问句、不带征询」
      的前置条件，误判面很小。

    为什么要留这个例外：理解调用失败不等于主模型失败（超时、输出格式错都会
    走这里）。如果一刀切全拦，用户明明说了「直接生成」，却收到一句
    「要我做吗」——安全网反过来咬了自己的正常流程。宁可让明确的指令通过，
    也不让模糊的说法通过。

    **为什么「把标题居中」这类明确指令仍然不放行**（`test_fallback_never_guesses`
    钉着这条）：它缺的不是语气，是**范围**——哪份文件、哪一段。判断"范围是否
    唯一"是理解层的活；兜底没人替他确认，放行就是对着猜出来的文件动手。
    少做一次只是多问一句，做错一次要收拾一份文件。

    但这不等于把它当成没听见：句子里有明确交办时，用 `order_verdict` 把
    「要做什么」写进 `goal`，只是**不给权限**。改的是目标，不是门。
    """
    text = (message or "").strip()
    commit = commit_verdict(text)
    if commit.value:
        return TurnReading(
            stance=STANCE_DIRECT,
            commitment=COMMIT_AUTHORIZED,
            goal=_clip(text, GOAL_MAX_CHARS),
            # 把握度不写死：说得越像拍板（「直接生成」vs「……吧」），兜底放行时
            # 越有底气。policy.py 会拿这个数去卡高风险写的门槛。
            confidence=commit.confidence,
            basis="理解模型不可用，但句子里有明确的拍板说法",
            source="fallback",
        )

    intent = intent_of(text)
    stance = STANCE_CHAT if intent == INTENT_CHAT else STANCE_EXPLORE
    order = order_verdict(text)
    if not order.value:
        return TurnReading(
            stance=stance,
            commitment=COMMIT_NONE,
            confidence=1.0 if stance == STANCE_CHAT else 0.4,
            basis="理解模型不可用，按保守档处理",
            source="fallback",
        )
    # 有明确交办但没有拍板：记下要做什么，权限仍然封着。
    # 这一档的真实收益是"别反问"——用户说「把这几份合并成一个文件」，
    # 理解模型挂了，至少 model 该知道任务是什么，而不是回一句"你想做什么"。
    return TurnReading(
        stance=stance,
        commitment=COMMIT_NONE,
        goal=_clip(text, GOAL_MAX_CHARS),
        confidence=0.6,
        basis=f"理解模型不可用；句子里有明确交办（{order.evidence[0]}），已记下目标但不落盘",
        source="fallback",
    )


def deterministic_reading(message: str) -> TurnReading | None:
    """零成本就能确定的两种情况，省掉一次模型调用。

    只处理「判断依据在句子内部就齐了」的：纯寒暄、空句。

    `bare_confirmation` 刻意不在这里短路——「好」只有结合上一轮才知道授权了
    什么，直接判成 authorized 正是误生成的入口，交给模型带着历史读。
    """
    text = (message or "").strip()
    if is_blank(text):
        return TurnReading(
            stance=STANCE_CHAT, commitment=COMMIT_NONE, confidence=1.0, basis="空消息"
        )
    if greeting_only(text):
        return TurnReading(
            stance=STANCE_CHAT, commitment=COMMIT_NONE, confidence=1.0, basis="整句寒暄"
        )
    return None


def _history_hint(history: Any) -> str:
    """最近几轮的对白。作用只有一个：让「好 / 就这个 / 再改改」有得可依。"""
    if not history:
        return ""
    items = list(history)[-HISTORY_MESSAGES:]
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = _clip(str(item.get("content") or ""), HISTORY_SIDE_CHARS)
        if not content or role not in ("user", "assistant"):
            continue
        lines.append(f"{'他' if role == 'user' else '你'}：{content}")
    if not lines:
        return ""
    return "【刚才的对话】\n" + "\n".join(lines) + "\n\n"


def _material_hint(uploads: Any) -> str:
    names: list[str] = []
    for upload in uploads or []:
        name = getattr(upload, "filename", "")
        if name:
            names.append(str(name))
    if not names:
        return "【他手上的材料】这一轮没有任何素材。\n\n"
    return "【他手上的材料】\n" + "\n".join(f"- {name}" for name in names) + "\n\n"


def build_messages(ctx: Any) -> list[dict[str, str]]:
    message = str(getattr(ctx, "message", "") or "").strip()
    user = (
        f"{_history_hint(getattr(ctx, 'history', None))}"
        f"{_material_hint(getattr(ctx, 'uploads', None))}"
        f"【他这一轮说的话】\n{message}"
    )
    return [
        {"role": "system", "content": READING_RULES},
        {"role": "user", "content": user},
    ]


async def read_turn(router: Any, ctx: Any) -> TurnReading:
    """请模型读一遍。任何异常都不外抛，一律退到兜底。

    刻意不复用 `chat_with_tools`：那条路径会记账、会写 usage、还会在测试里
    消费掉脚本化的响应队列。理解层要能独立失败，不能污染主循环。

    三条出口（短路 / 兜底 / 模型）都必须过同一道落地校正（`_settle`）：
    他自己说出口的「先别」「我就是想问问」比模型的猜测硬，两边打架时听他的；
    反过来说了「你生成吧」也一样——那是拍板，不该被模型的犹豫盖住。
    """
    message = str(getattr(ctx, "message", "") or "")
    # 短句里的「这个 / 这样」要有指代对象，抬档才成立
    has_history = bool(getattr(ctx, "history", None))

    # 零成本短路：不用理解也能确定的，就别花一次调用。
    quick = deterministic_reading(message)
    if quick is not None:
        return _settle(quick, message, has_history)

    chat = getattr(router, "chat", None)
    if chat is None or not message.strip():
        return _settle(fallback_reading(message), message, has_history)
    try:
        # 800 而不是 400：这个 JSON 有七个字段、中文写作，400 会在 `missing` 或
        # `basis` 中途截断，输出变成半截 JSON、解析失败、退到保守兜底——
        # 表现就是「用户明明说得很清楚，它却一直在问」。实测 400 时约 6% 的
        # 请求被截断，且失败是静默的，只有从 basis 里的兜底文案才看得出来。
        result = await chat(
            build_messages(ctx),
            max_tokens=800,
            temperature=0.0,
            # 账本按用途分组：理解层的调用每次都发生，是「运行数 ≈ 请求数 × 2」
            # 的那一半，混进 engine 会让主循环看起来比实际贵一倍。
            purpose="reading",
        )
    except Exception as exc:  # 理解失败不该影响主链路
        logger.info(
            "意图理解调用失败，退到兜底：%s",
            str(exc)[:160],
            extra={"event": "reading_fallback"},
        )
        return _settle(fallback_reading(message), message, has_history)
    reading = parse_reading(getattr(result, "text", "") or "")
    if reading is None:
        logger.info(
            "意图理解输出不合格式，退到兜底：%s",
            (getattr(result, "text", "") or "")[:120],
            extra={"event": "reading_fallback"},
        )
        return _settle(fallback_reading(message), message, has_history)
    return _settle(reading, message, has_history)


def _settle(reading: TurnReading, message: str, has_history: bool) -> TurnReading:
    """落地前的两道确定性校正。顺序不能换：

    1. `apply_hold` 先压——「先别管格式，直接生成吧」这类句子 hold 会误命中，
       但白名单里的「直接生成」随后会把它抬回来，正好是想要的结果；
    2. `apply_commit` 后抬——「先别生成吧」的 `commit_verdict` 不成立，压完就停在那儿。
    """
    return apply_commit(apply_hold(reading, message), message, has_history=has_history)


__all__ = [
    "COMMITMENTS",
    "COMMIT_AUTHORIZED",
    "COMMIT_NONE",
    "COMMIT_PROPOSED",
    "CONFIDENCE_FLOOR",
    "READING_RULES",
    "STANCES",
    "STANCE_CHAT",
    "STANCE_DIRECT",
    "STANCE_EXPLORE",
    "TurnReading",
    "apply_commit",
    "apply_hold",
    "build_messages",
    "deterministic_reading",
    "fallback_reading",
    "parse_reading",
    "read_turn",
]
