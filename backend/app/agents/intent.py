"""确定性信号层：只回答「看句子本身就能回答」的问题，其余交给理解层。

## 这一层的职责边界

它**不做意图分类**。它只在模型读不懂、或者不值得花一次模型调用的时候，给出
几个零成本、可复现的判断：

- 这句话有没有内容；
- 是不是整句只有寒暄；
- 是不是只说了「行 / 可以 / 就这个」；
- 是不是在问「该怎么做」；
- 是不是已经把决定说出口。

凡是需要语境才能判断的（他是在商量还是已经拍板、他指的是哪一份材料），
一律不在这里做——那是 `reading.py` 的活。

## 为什么不再加动作词

「生成」「整理」「改」这些是**动作词**，开放集合，商量的时候天天出现。
把它们当判据，就会出现「这份周报想改成给老板看的版本，怎么改好？」被判成派活。
每加一个动作词，就多一个误判入口，而覆盖率永远追不上语气、省略和指代。

这一层加的只有**功能词**：语气词、否定词、条件连词、引述动词、疑问标记。
它们的共同点是集合封闭、语法位置固定、不随话题变化——「别」永远是状语，
「如果」永远引导从句，「吧」永远在句尾。判据因此可以写成「词出现在什么位置」，
而不是「句子里有没有某个词」。

这就是"精卫填海"和"大海捞针"的区别：不是把网撒得更大去捞，而是一块一块把
边界砌实——每一条判据都能说清它在排除哪一种具体错法。

## 兜底为什么永不写盘

`intent_of()` 是模型读不懂时的降级判断，它**只回 chat 或 read，永远不回 write**。

模型都读不出这句话想干什么，内核凭什么替用户决定「生成一份文件」？
两种误判代价并不对称：把派活当商量，用户再说一句就好；把商量当派活，
他会收到一份自己没要的 docx。所以兜底一律站在便宜的那一边。

## 怎么改进这一层

三条路，按性价比排序：

1. 往 `tests/data/utterances.jsonl` 加真实说法——只有它度量得出覆盖率；
2. 改 `reading.py` 的判据说明——那里才是「他到底想干什么」的裁判；
3. 往这里加**功能词**或**句法位置规则**，并且为它补一条会失败的用例。

不要加动作词。那是把旧bug一条一条捡回来。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# ============================================================
# 〇、对外标签与规模上界
# ============================================================

INTENT_CHAT = "chat"
INTENT_READ = "read"
INTENT_WRITE = "write"

#: 单条消息参与分析的最大字符数。超出的部分不做词法分析，**但保留尾部**：
#: 拍板几乎总在句尾（「……直接生成吧」），而开头往往是粘贴进来的材料。
#: 这不是"长句算商量、短句算派活"——长度从不参与判断，它只决定看哪一段。
MAX_ANALYZED_CHARS = 400


# ============================================================
# 一、语料：只有功能词
# ============================================================
#
# 下面每张表都必须在注释里写清两件事：它回答什么问题、它在排除哪一种错法。
# 写不出来的，就不该放在这里。


def _words(block: str) -> tuple[str, ...]:
    """把横着写的词表拆成元组。

    为什么不写成 `("你好", "您好", ...)`：只要带上尾逗号，格式化器就认定
    "作者要竖排"，一个词一行——六张表加起来两百多行，改一个词要数缩进，
    翻起来也不像一张表。隐式字符串拼接是它唯一不动的写法：一行放十来个词，
    按空白切。**行数不是指标，能一眼看全才是指标。**
    """
    return tuple(block.split())


#: 寒暄词。用法是「把整句里的寒暄词整词取走，看还剩不剩东西」，
#: **不是**「句子里出现这个词就算寒暄」——那样「谢谢你，顺手把周报改一下」
#: 会被判成聊天，紧接着就是一次没人要的生成。
GREETING_KEYWORDS: tuple[str, ...] = _words(
    "你好 您好 在吗 在不在 早上好 中午好 下午好 晚上好 早安 午安 晚安 "
    "哈喽 嗨 早啊 早呀 "
    "谢谢你 谢谢您 谢谢 多谢 感谢 谢啦 谢了 辛苦了 辛苦啦 辛苦辛苦 劳驾 "
    "再见 拜拜 回聊 下次聊 先忙 收工 "
    "先这样 先这么着 先到这 就这样吧先 "
    "hi hello hey thanks thankyou thankyouverymuch thx morning"
)

#: 「同意 / 继续」。本身不携带新内容，含义完全取决于上一轮说了什么。
#: 这一层只负责把它认出来，不负责解释——解释要靠历史，那是理解层的事。
CONFIRM_WORDS: tuple[str, ...] = _words(
    "好的 好 可以 行 嗯 对 是 没问题 同意 赞成 就这样 就这个 就它 "
    "按这个来 按这个 按你说的 照这个做 开始吧 来吧 继续 接着来 往下走 "
    "收到 明白 了解 清楚 记下了 ok okay yes yep sure go "
    # 口语里「同意」的说法比书面多得多：一次只说两三个字，还爱叠字
    "好嘞 好滴 好哒 好的呢 可以的 可以可以 可以了 行吧 行嘞 行滴 嗯嗯 嗯呢 "
    "对的 对的呀 是的 是啊 没毛病 木有问题 就这么办 就这么定 就按这个做 "
    "就这个了 就按你说的来 开始 走起 干吧 弄吧 做吧 来吧来吧 继续吧 接着 "
    "明白了 知道了 记住了 收到收到 晓得了 了解了解 "
    "yep yeah yup alright"
)

#: 明确的撤回。「算了吧」不是同意，是**不要了**。
#: 它出现在确认的判定路径上只有一个后果：把整句判成"不是确认"。
#: 不这样处理，「算了」会因为含"了"被当成语气词残余，「先不弄了」会被当成确认，
#: 于是"不要"变成"要"。
RETRACTION_WORDS: tuple[str, ...] = _words(
    "算了 不用了 不必了 不需要了 不弄了 不做了 不整了 "
    "先放着 先搁着 到此为止 够了 停了 别弄了 别做了 取消 撤销 "
    # 「不要」这一侧的说法同样多得离谱，而且长得像确认（都带「了」「吧」）
    "算了算了 拉倒 打住 不要了 不必 不搞了 先不做 先不弄 先不写了 "
    "放着吧 以后再说 下次再说 暂时不用 暂时不弄 搁置 先搁置 "
    "别改了 别动了 先停一下 不要动 到此为止吧"
)

#: 语气词与填充词。它们的作用是**容忍残余**：整句被寒暄词/确认词吃完之后，
#: 剩下的若是这些，说明没有新内容（「你好呀」「可以了」「行吧」）。
#: 单字表在这里的误伤方向是安全的——把「了解」的「了」剥掉只会让结果更保守。
FILLER_WORDS: tuple[str, ...] = _words(
    "吧 了 的 啊 呀 哦 噢 喔 呢 嘛 哈 嘿 诶 欸 嗯 咯 啦 嘞 么 "
    "呗 呐 嗷 呵 咦 唉 哎 唔 额 呃 乎 滴 哒 捏 哦豁 哈哈 嘿嘿 呵呵 嘻嘻 呜 "
    "哟 嚯 啧 嗐 哇 呐呐 嗯呐 咧 啵 哒哒 呀嘿 嘿呀"
)

#: 整段就等于语气噪声的拉丁串（分词后整段匹配，不做子串匹配）。
_LATIN_NOISE: frozenset[str] = frozenset({"hhh", "hh", "lol", "pls", "please", "omg", "xd", "awa"})

#: 在问「该怎么做 / 这样行不行」，而不是在说「就这么做」。
#: 刻意不收「能不能」开头的请求句：「能不能帮我生成一份」是请求，不是征询。
#:
#: 也刻意**不收「你看着办」**：那是把决定权交出来，属于授权（见
#: `_HANDOVER_RE`）。以前它在这里，被判成征询后又压掉拍板信号，
#: 于是一句"你拿主意"被拖成一轮"你想怎么做"——正好问回了本人。
_ADVICE_RE = re.compile(
    r"(?:怎么改|怎么弄|怎么写|怎么调|怎么做|怎么处理|怎么排|怎么改好|怎么办|"
    r"如何改|如何弄|如何做|如何处理|如何排|"
    r"要不要|要不|是不是|该不该|需不需要|有没有必要|值不值得|合不合适|"
    r"你觉得|你认为|你看呢|你看怎么|你说呢|"
    r"哪个好|哪种好|哪一版|哪一版好|选哪个|用哪个|哪种更|哪个更|"
    r"合适吗|合适不|好不好|妥不妥|行不行|行吗|可以吗|对吗|对吧|是吧|"
    r"该怎么|应该怎么|最好怎么|建议|推荐|"
    r"会不会太|是不是会|会不会有点)"
)

#: 给别人办事的受益标记。它把「能不能帮我生成一份」这类**礼貌请求**
#: 从「征询意见」里摘出来：他在请你动手，不是在问你怎么看。
#:
#: 注意它只在**同一个分句、且紧挨在征询标记前面**才生效（见 `_benefit_near`）。
#: 以前是全文 `search`，于是「这个方案你觉得行吗？顺便帮我改下标题」里那个
#: 隔着一整个分句的「帮我」，会把前面的真征询否定掉——他把判断交给你，
#: 你却把它读成派活，接下来就是一次没人要的改动。
_BENEFIT_RE = re.compile(r"(?:帮我|给我|替我|为我|帮忙|麻烦你?|劳驾|顺手|顺便)")

#: 请求的是「意见」本身（「给我个建议」「帮我拿个主意」）。这类说法带受益标记，
#: 但受益物就是判断——它仍然是征询，不是请你动手。
_ADVICE_OBJECT = ("建议", "意见", "推荐", "想法", "看法", "主意")

#: 把决定说出口的强说法。这些都是祈使/完成体，几乎只用于授权。
#: 注意**没有**单个「生成 / 改 / 整理」——那是动作词，正是过去误判的源头。
_STRONG_COMMIT: tuple[str, ...] = _words(
    "直接生成 直接做 直接改 直接出 直接弄 直接来 直接写 直接排版 "
    "直接开始 直接执行 直接给我 直接出稿 直接落地 落盘 存下来 保存下来 导出成 导出为 "
    "就按这个 就按你说的 就照这个 按这个来 按这个做 按这个办 按这个改 按这个整理 "
    "照这个做 照这个来 按你说的来 按你说的做 按你说的改 按你说的办 "
    "按刚才说的来 按上面说的来 按上面的来 就这么办 就这么定 就这个吧 "
    "不用问了 别再问了 开始吧 动手吧 "
    # 「直接 + 动作」是口头上最常见的授权式，动词几乎都能搭
    "直接搞 直接整 直接干 直接开干 直接安排 直接给我做 直接做一份 "
    "落成文件 存成文件 写成文件 导出文件 就按这套 就照这个来 照这个改 "
    "按上面这个来 不用再问了 别问了 开干 开始干"
)

#: 弱说法：动作 + 可选量词 + 句尾「吧」。中文里「……吧」是典型的祈使完成标记。
#: 它比强说法弱，所以只在没有否定/假设/引述的前提下才认。
#:
#: 正则本身看不见句法：`[^，。！？；]{0,6}吧` 只保证「吧」跟动作在同一分句里，
#: 分不清这个分句是主句还是条件从句的前件。「改成横向吧，如果领导同意的话」
#: 会被整段命中——动作、语气词、位置全对，只有语义是"等同意再改"。所以
#: 弱匹配额外过一道条件从句检查（见 `_weak_in_condition`），表内短语不需要。
_WEAK_COMMIT_RE = re.compile(
    r"(?:生成|做|改|出|弄|写|排版|导出|合并|拆分|整理|归档|翻译|画|制)"
    r"[^，。！？；,.!?;\n]{0,6}吧"
)

#: 直接下令：句子本身就是指令，不需要先说一句「就按这个」。
#:
#: 为什么另起一条而不是往 `_STRONG_COMMIT` 里加词——**这是两个不同的语言行为**：
#:
#: - `_STRONG_COMMIT` 收的是**决策陈述**：说话人在宣布一个已经做出的决定
#:   （「就按这个」「直接生成」「落盘」）。它要回答"他决定了没有"。
#: - 这里收的是**动作本身**（「把标题居中」「删掉第二段」）。它压根没有
#:   "决定"这一层——说出口就是命令，要回答的是"他在让我做什么"。
#:
#: 语料 45 条 authorized 里，后者是主力（38 条漏判中有 16 条属于这两种句式），
#: 而前者只认出 7 条。这是**少了一整个维度**，不是密度不够。
#:
#: 为什么是句式而不是词表：祈使句是开放集合——动词 × 宾语是无限组合，
#: 加二十个词也罩不住「把表里的数据核对一遍」，换一批语料就废；而
#: 「把 X 怎么样」「动词 + 结果」这两个句式是有限集合，一次覆盖一大片。
#:
#: 动词表只收**会改变文件或内容**的（改/删/合并/导出/排版…），刻意不收
#: 「想想 / 看看 / 说说」这类不产生动作的。宁可漏，不可多认——认错了就是
#: 一份没人要的文件。「改」要排掉「改天 / 改期」，那是时间不是修改。
_IMPERATIVE_RE = re.compile(
    r"(?:把|将)[^，。！？；,.!?;\n]{1,15}"
    r"(?:改(?!天|期|日|名|口)|调(?!整时)|删|去掉|换|合并|拆|移|居中|放大|缩小|"
    r"排(?:版|成)|导(?:出|成)|转(?:成|为)|读|对比|核对|整理|生成|写成|念|贴|标|拎|单独)"
    r"|(?:改成|换成|删掉|删了|加个|加一个|读一下|看一下|对比一下|核对一下|"
    r"合并成|导出成|整理成|重新做|重新生成)"
)

#: 直接下令规则只在**短消息**上生效。
#:
#: 语料里有现成的反例：一条会议记录写着「运营建议把五百元以下的小额退款改为
#: 系统自动放行」——句式完全命中，可那是**材料内容**，用户问的是"有没有
#: 漏掉的"。真下令的句子很短；长句里的祈使多半是材料原文或转述。
#: 80 字约为正常指令的三倍长度，够宽松，又拦得住整段材料。
_IMPERATIVE_MAX_CHARS = 80

#: 把决定权交出来：「你看着办」「随便哪个都行」。
#:
#: 这是**授权**，不是征询——他不再参与选择，把结果托付给你。以前
#: `_ADVICE_RE` 里收了「你看着办」，于是它被判成征询；征询会压掉拍板信号，
#: 一句明确的授权被拖成一轮反问（语料里它标的是 authorized）。
#:
#: 置信度只给 0.75：它授权的是"你拿主意"，不等于"照这个写盘"，
#: 刚好够过 `MIN_AUTHORIZED_CONFIDENCE`，但比说出口的指令弱一档。
#: 「你看着调一下」「你拿主意」「你说了算」都在这里：它们交出去的是决定权，
#: 具体改成什么样由我定。漏掉它们的代价很具体——实测「你看着调一下吧」被理
#: 解层判成 authorized、把握 0.62，既没过放行线、又没被认成授权语，于是静默
#: 拦下：他明明说了"你定"，系统却一动不动，也不问他。
_HANDOVER_RE = re.compile(
    r"(?:你看着(?:办|调|改|弄|来|做|处理|安排|定)|"
    r"(?<!我)看着(?:办|调|改|弄|来)吧|"
    r"你(?:定|决定|拿主意|说了算|安排|做主)|听你的|随你|"
    r"随便[^，。！？；,.!?;\n]{0,6}(?:都行|都成|你选|都无所谓)|"
    r"哪个都行|哪版都行|都行|无所谓)"
)

#: 在说打算，不是在派活。「我想把标题居中，这样好看」——他解释了为什么，
#: 但没说"你来做"。真下指令会带请求标记（「帮我」「请你」「麻烦」），
#: 所以两者同时出现时听请求那一侧（见 `_REQUEST_RE`）。
#:
#: 为什么值得单列：中文里"我想…"和"你把…"只差一个字，但对内核是
#: 两种完全不同的东西——前者是自言自语，后者是要落到文件上的动作。
_WISH_RE = re.compile(r"(?:我想|我想着|我觉得|我希望|我打算|我准备|计划着|打算)")

#: 请求标记。它一旦出现，「我想请你把标题居中」就是派活而不是独白。
_REQUEST_RE = re.compile(r"(?:帮我|给我|请你|请帮|麻烦|辛苦|劳驾|帮忙|能不能)")


#: 祈使短语与后续分句之间会出现的语气词。
#:
#: 「把标题居中**吧**，如果领导同意的话」：短语本身不含「吧」，
#: `_clauses_after` 会把「吧」当成下一个分句，真正的条件句退到第二格，
#: 位置检查就看不见了——语气词必须一起吃掉再查。
_TAIL_PARTICLES = "吧啊呀哦嘛呗啦咯嘞呢"

#: 词组内部带否定，整个词组就不算拍板（「这样改不太好吧」）。
_NEG_IN_SPAN_RE = re.compile(r"(?:不|别|甭|勿|没|无需|不必)")

#: 紧挨在动作前面的否定。只看最近一个分句，所以「不错，直接生成吧」不会被
#: 「不」误伤——中间隔着逗号，那是另一个分句了。
#: 裸「不」放在最后兜底，但排掉「不错 / 不然 / 不但」这些不是否定的词：
#: 不排的话，「刚才那个不生成吧」会被漏掉，而它是个真实的否句。
_NEG_TAIL_RE = re.compile(
    r"(?:先别|暂时别|别先|别(?!的|人|处)|甭|勿|莫|"
    r"不(?:要|用|必|需|能|准|许|该|应|着|急|先|再|忙|打|想|如|妨)|"
    r"无需|无须|没必要|没有必要|"
    r"不(?![错然但仅光过少久妨如])|"
    r"晚点再|等等再|回头再|明天再|改天再|过会儿再|稍后再)"
    r"[^，。！？；,.!?;:\n]{0,3}$"
)

#: 把动手**推到条件满足之后**。「先给方案，我点头了再落盘」里有「落盘」这个
#: 最硬的拍板词，但整句的意思是"现在别落盘"。以前它被判成拍板——因为在词法上
#: 「落盘」确实出现了，只是位置在"我点头了再"之后。
#:
#: 这类说法在真实对话里很常见（"等我确认了再生成""你看完回我一声我再改"），
#: 而且它是**最容易被误读成授权**的一类：说得越具体（点名动作、点名文件），
#: 越像已经决定了。判据仍然是位置——条件在短语前面，短语就还没生效。
_DEFER_RE = re.compile(
    r"(?:"
    r"我(?:点头|确认|看(?:完|过)|想清楚|回复|答复)(?:了|过)?(?:再|之后|以后)"
    r"|(?:等我|待我|让我|等您?)[^，。！？；,.!?;\n]{0,8}(?:再|之后|以后)"
    r")"
)

#: 「……就行 / ……就好」是**收窄**，不是叫停。
#:
#: 「先不用改，改标题就行」被整句当成"别动"是错的：他把范围从"改这份文件"收窄到
#: "只改标题"，动作还在。真正的叫停不会跟一句"改这个就行"——那是把禁止变成了指定。
#:
#: 实测这条误伤会让一个明确的窄指令被拦（评估里表现为"保守 +1"）。
#: 只对**叫停类**放行这条规则：「先别生成，写成文字就行」这种他确实不要文件的，
#: 靠理解层与门控兜住，不必让确定性层抢答。
_NARROW_RE = re.compile(r"就行|就好|即可|就成|就够了|就可以了|行了")

#: 说完之后的自我更正。「生成吧——不对，等等」里最终的意思是"先别生成"。
#: 这条只往后看，宁可多排除一次（保守方向），也不放行一次。
_POST_RETRACT_RE = re.compile(r"(?:不对|算了|当我没说|撤回|我说错了|收回|开玩笑|等等|等一下)")

#: 说完之后的**软反悔**：他没有直接说"算了"，而是把动手推到后面，或者
#: 把动作否掉。这类句子在词法上完全是拍板（「就按这个来吧」），软反悔长在
#: 下一个分句里，所以以前只看短语本身是看不见的。
#:
#: 只往后看**一到两个分句**：再往后就是另一件事了（「生成吧。明天如果下雨
#: 就延期」里的"如果"跟这次生成无关）。方向仍然是单一的——多排除一次只是
#: 多问一句，漏掉一次就是一份没人要的文件。
_POST_DEFER_RE = re.compile(
    r"(?:先等等|再等等|等等再说|再说着?吧|回头再说|明天再|改天再|以后再说|稍后"
    r"|先放放|先搁着|搁一搁|往后放|缓一缓|压一压"
    r"|等我(?:确认|点头|看完|回复|答复))"
)

#: 说完之后把动作否掉。「直接生成吧，先不弄了」里拍板短语完整、位置正确，
#: 只有后面的「先不弄了」说了实话。
#:
#: 刻意**不收**「不用问了 / 别再问了 / 不用麻烦」——那是把拦路的东西拿开，
#: 意思恰恰是"现在做"。判据是"否的是什么"：否的是**动作**才拦，否的是
#: 提问、客气、别的动作（「别改标题」）不在这里拦。
_POST_NEG_RE = re.compile(
    r"(?:先别|暂时别|先不(?:要|用|急|动|弄|做|写|生成|出)"
    r"|不(?:用|必|需要)?(?:弄|做|写|生成|出|改)了"
    r"|别(?:弄|做|写|生成|出|改)了)"
)

#: 下一个分句如果是条件从句的**起头**，说明刚才那句是前件（protasis），
#: 还没生效。「改成横向吧，如果领导同意的话」说的是"等领导同意再改"。
#: 只在弱匹配上用：表内短语是人挑过的，配上条件读起来就是假设，前缀那条
#: `_CONDITION_RE` 已经够了。
_PROTASIS_HEAD_RE = re.compile(r"^\s*(?:如果|要是|假如|假使|假设|万一|一旦|除非|只要|否则)")

#: 「……吧的话」：句尾条件标记直接挂在拍板短语上，是最隐蔽的一种假设。
_PROTASIS_TAIL = "的话"

#: 条件从句。落在它后面的「拍板」其实是假设：「如果按这个来，会不会太快」。
#: 排除它带来的代价只是多问一句，漏掉它的代价是一份没人要的文件。
_CONDITION_RE = re.compile(r"(?:如果|要是|假如|假使|假设|假定|倘若|万一|一旦|若是|如若|除非|否则)")

#: 引述。他在转述别人的话，不是自己在拍板。
#: 注意**不含**「你说的」——「按你说的来」是最典型的授权，不能被当成引述。
_REPORT_RE = re.compile(
    r"(?:"
    r"(?:他|她|他们|她们|对方|客户|老板|领导)(?:说|讲|提到|要求|意思)"
    r"|(?:文档|材料|文件|方案|邮件|通知)(?:里)?(?:说|写着|写|要求|提到)"
    # 「你说按这个来」是转述；「按你说的来」是授权，所以要排掉「你说的」。
    r"|你(?:刚才|之前|上次)?说(?!的)"
    r"|所谓|指的是|意思是"
    r")"
)

#: 句尾疑问标记。问号本身就是疑问，哪怕句子里有「按你说的」——他在确认，不是在拍板。
#: 单字「么」要排除「这么 / 那么 / 怎么」这类指示/疑问代词的尾部。
_QUESTION_TAIL_RE = re.compile(
    r"(?:[?？]\s*$)|(?:[吗呢]\s*[。.…]*\s*$)|(?<![这那怎什多要])么\s*[。.…]*\s*$"
)

#: 出现在短语**之后**的疑问标记。中文常常不打问号：「按这个来会不会太快」
#: 「就按这个是不是更好」。只看句尾问号会漏掉这类，于是把问句当成决定。
#: 判据仍然是位置——标记在短语后面，说明短语是话题，不是结论。
_QUESTION_MARKER_RE = re.compile(
    r"(?:会不会|是不是|要不要|能不能|可不可以|行不行|对不对|好不好|够不够|来不来得及"
    r"|比较好|更好|好一点|怎么样|如何|多久|多长|合不合适)"
)

#: 只读工具：看得见内容，动不了文件。
READ_ONLY_TOOL_NAMES: tuple[str, ...] = _words("file.list file.read doc.analyze_material todo.list")


# ============================================================
# 二、文本整形
# ============================================================

#: 零宽与双向控制字符。粘贴来的文本里常混着它们，会把「你好」变成「你好」，
#: 让整词匹配莫名失败。
_INVISIBLE = dict.fromkeys(
    [ord(ch) for ch in "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u202a\u202b\u202c\u202d\u202e"]
)

#: ASCII 控制字符：换成空格，别让它们把分句切歪。
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: emoji 与符号区。只在算「有没有内容」时剥掉——一条纯表情消息等同于空消息。
_EMOJI_RE = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d]+")

#: 标点。**替换成空格**而不是删除：删掉会把「不，要」粘成「不要」，
#: 也会把「你，好」粘成「你好」，两种都是凭空造出一个词。
_PUNCT_RE = re.compile(
    r"[\s，。！？、,.!?~～…—\-·:：;；\"'“”‘’()（）\[\]【】《》〈〉「」『』<>/=+*%$#@^&|\\_]+"
)

#: 分句边界。否定、条件、引述都只在**同一个分句**或**前缀**里看，不跨句乱联想。
_CLAUSE_SPLIT_RE = re.compile(r"[，。！？；、,.!?;:\n]+")

#: 重复字符折叠：「哈哈哈」→「哈」，「好好好」→「好」。
_REPEAT_RE = re.compile(r"(.)\1+")

#: 纯拉丁字母段。这类段有天然词边界，只允许整段命中词典。
_LATIN_WORD_RE = re.compile(r"^[a-z]+$")


@dataclass(frozen=True)
class TextShape:
    """一条消息的三种视图。分开存是因为它们服务不同判断，混用就会出错。

    - `text`：清理过、标点仍在。句法判断（疑问尾、分句、span 位置）用它。
    - `stem`：标点换成空格、小写。词法匹配用它——空格是天然的拉丁词边界。
    - `compact`：再去掉空格与 emoji。只用来回答「有没有内容」和算长度。
    """

    raw: str
    text: str
    stem: str
    compact: str
    truncated: bool
    question_tail: bool
    clause_count: int


def _clean(raw: str) -> str:
    """统一宽度、去掉不可见字符、压掉多余空白。

    NFKC 会把全角「？」变成「?」、全角字母变成半角，后面所有正则只需要认一种写法。
    """
    text = unicodedata.normalize("NFKC", raw)
    text = text.translate(_INVISIBLE)
    text = _CTRL_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=512)
def shape_of(message: str) -> TextShape:
    """把一条消息拆成三种视图。同一个进程里同一条消息只算一次。"""
    raw = message or ""
    truncated = len(raw) > MAX_ANALYZED_CHARS
    source = raw[-MAX_ANALYZED_CHARS:] if truncated else raw
    text = _clean(source)
    stem = re.sub(r"\s+", " ", _PUNCT_RE.sub(" ", text)).strip().lower()
    compact = _EMOJI_RE.sub("", stem).replace(" ", "")
    return TextShape(
        raw=raw,
        text=text,
        stem=stem,
        compact=compact,
        truncated=truncated,
        question_tail=bool(_QUESTION_TAIL_RE.search(text)),
        clause_count=len(_CLAUSE_SPLIT_RE.findall(text)) + 1 if text else 0,
    )


def normalize(message: str) -> str:
    """去掉标点与空白，只留下可用于判断的字符。"""
    return shape_of(message).compact


def is_blank(message: str) -> bool:
    """这句里没有任何可读内容（空串、纯标点、纯空白、纯表情）。"""
    return not shape_of(message).compact


# ============================================================
# 三、词法器：最大匹配，不是字符串替换
# ============================================================


class _Lexicon:
    """短语表 + 正向最大匹配分词。

    ## 为什么不是 `str.replace` 逐词剥离

    「行」是确认词，「行业报告」里也有「行」。`replace` 会把后者剥成「业报告」，
    这次结论恰好还是"不是确认"，但那是运气——换个句子就翻车。更常见的
    「好了」「行吧」「可以了」反而会被判成"不是确认"，因为它不知道该把
    「了」「吧」当语气词。

    最大匹配保证每个字符只被**整词**消费一次，绝不跨词咬进实词；剩下的残余
    再交给语气词表容忍。这样一来：

    - 「好了」→ 命中「好」，残余「了」是语气词 → 确认；
    - 「行业报告」→ 命中「行」，残余「业报告」→ 不是确认；
    - 「可以，但标题要居中」→ 命中「可以」，残余「但标题要居中」→ 不是确认。
    """

    __slots__ = ("_max_len", "_table", "name")

    def __init__(self, name: str, phrases: Iterable[str]) -> None:
        cleaned = {p.strip().lower() for p in phrases if p and p.strip()}
        self.name = name
        self._table: frozenset[str] = frozenset(cleaned)
        self._max_len = max((len(p) for p in cleaned), default=0)

    def segment(self, stem: str) -> tuple[list[str], list[str]]:
        """返回 (命中的词, 没被字典覆盖的残余段)。

        按空格先切段拿天然边界；纯拉丁段**只做整段匹配**——中文没有词边界，
        只能靠最大匹配，但拉丁有，「history」绝不该命中「hi」。这两条规则
        分开写，是因为它们防的是两种不同的错。
        """
        hits: list[str] = []
        residue: list[str] = []
        for chunk in stem.split():
            if _LATIN_WORD_RE.match(chunk):
                (hits if chunk in self._table else residue).append(chunk)
                continue
            i, size = 0, len(chunk)
            while i < size:
                for width in range(min(self._max_len, size - i), 0, -1):
                    piece = chunk[i : i + width]
                    if piece in self._table:
                        hits.append(piece)
                        i += width
                        break
                else:
                    residue.append(chunk[i])
                    i += 1
        return hits, ["".join(residue)] if residue else []


_GREETING_LEX = _Lexicon("greeting", GREETING_KEYWORDS)
_CONFIRM_LEX = _Lexicon("confirm", (*CONFIRM_WORDS, *RETRACTION_WORDS))

_FILLER_SORTED: tuple[str, ...] = tuple(sorted(set(FILLER_WORDS), key=len, reverse=True))


def _residue_is_noise(chunks: Sequence[str]) -> bool:
    """残余是否只是语气噪声——剥完语气词、折叠完重复之后不剩任何东西。

    反复剥三轮是因为剥和折叠会互相露出对方：「吧吧吧」先折叠成「吧」再剥成空。
    单字语气词的误伤方向是安全的：「了解」剥掉「了」还剩「解」，结论偏向
    "不是确认"，而保守永远比冒进便宜。
    """
    for chunk in chunks:
        if chunk in _LATIN_NOISE:
            continue
        rest = chunk
        for _ in range(3):
            before = rest
            for word in _FILLER_SORTED:
                if word in rest:
                    rest = rest.replace(word, "")
            rest = _REPEAT_RE.sub(r"\1", rest)
            if rest == before:
                break
        if rest:
            return False
    return True


def _residue_is_inert(chunks: Sequence[str], *extra: _Lexicon) -> bool:
    """残余只是语气噪声，或者只是**另一张表里的废话**。

    「好的，谢谢」里「好的」是同意、「谢谢」是寒暄，两者都不携带新内容。
    只看确认表会把它判成"还说了别的"，所以允许再用寒暄表吃一遍。
    """
    if _residue_is_noise(chunks):
        return True
    for lexicon in extra:
        hits, rest = lexicon.segment(" ".join(chunks))
        if hits and _residue_is_noise(rest):
            return True
    return False


def _find_all(haystack: str, needle: str) -> Iterator[int]:
    """`str.find` 的全部命中位置。用 find 而不是正则，避免把短语里的
    「（」「.」这类字符当元字符处理，也免去一次 re.escape。"""
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return
        yield index
        start = index + len(needle)


def _clause_span(text: str, index: int) -> tuple[int, int]:
    """`index` 所在分句的 (起点, 终点)。分句边界与 `_clause_tail` 用的是同一张表。"""
    start = 0
    for match in _CLAUSE_SPLIT_RE.finditer(text):
        if match.end() > index:
            return start, match.start()
        start = match.end()
    return start, len(text)


def _clauses_after(text: str, index: int, limit: int = 2) -> list[str]:
    """`index` 之后的**最近几个分句**，去掉空白分句。

    为什么要限量：软反悔是紧跟着拍板说的（「就这样吧，先不弄了」）。再往后
    的内容属于另一件事，「生成吧。明天如果下雨就延期」里的"如果"管不到这次
    生成，扫得太远会把每一句话都读成条件。
    """
    clauses: list[str] = []
    for piece in _CLAUSE_SPLIT_RE.split(text[index:]):
        stripped = piece.strip()
        if stripped:
            clauses.append(stripped)
        if len(clauses) >= limit:
            break
    return clauses


def _near_clause(text: str, index: int, *, window: int = 12) -> str:
    """`index` 前面那一小段：**同一个分句内**、不超过 `window` 个字。

    以前这里是全文 `search`：句子里任何地方出现「帮我」，这次判断就被算成
    "他在请你办事"。于是「这个方案你觉得行吗？顺便帮我改下标题」不再算征询——
    可他问的是意见，「帮我改标题」是另一件事。

    就近匹配分两步：先砍到同一分句（跨分句不算），再看距离（同一分句里也不该
    隔着一整句话）。中文的受益短语永远紧贴在动作前面（「帮我生成」），不会
    隔十几个字再出现，所以窗口只需要一小段。
    """
    start, _ = _clause_span(text, max(0, index - 1))
    clause = text[start:index]
    return clause[-window:] if len(clause) > window else clause


def _weak_in_condition(text: str, start: int, end: int) -> str | None:
    """弱匹配是不是落在条件从句里。返回命中的标记，`None` 表示不在。

    两道：本分句里有没有条件连词（「生成吧如果能行」），下一个分句是不是
    条件从句的起头、或者以「的话」收尾（「改成横向吧，如果领导同意的话」）。
    """
    clause_start, clause_end = _clause_span(text, start)
    own = _CONDITION_RE.search(text[clause_start:clause_end])
    if own:
        return own.group(0)

    following = _clauses_after(text, end, limit=1)
    if not following:
        return None
    head = following[0]
    matched = _PROTASIS_HEAD_RE.match(head)
    if matched:
        return matched.group(0).strip()
    if head.startswith(_PROTASIS_TAIL) or head.endswith(_PROTASIS_TAIL):
        return _PROTASIS_TAIL
    return None


# ============================================================
# 四、判定：每条都返回结论 + 把握 + 依据
# ============================================================


@dataclass(frozen=True)
class Verdict:
    """一个判定的完整结果。

    为什么不是裸 `bool`：

    - 落日志要能回答「这句话为什么被判成聊天」，只有布尔值答不了；
    - `policy.py` 需要把握度来决定高风险写要不要放行，只有布尔值给不了；
    - 评估脚本 `eval_reading.py` 要靠 `evidence` 定位是哪个判据出了偏差。
    """

    value: bool
    confidence: float
    evidence: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.value

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "evidence": list(self.evidence),
        }


def _yes(confidence: float, *evidence: str) -> Verdict:
    return Verdict(True, confidence, evidence)


def _no(confidence: float, *evidence: str) -> Verdict:
    return Verdict(False, confidence, evidence)


def blank_verdict(message: str) -> Verdict:
    """没有任何可读内容。纯表情也算——不然一条「👍」会被当成待办。"""
    shape = shape_of(message)
    if not shape.compact:
        return _yes(1.0, "没有可读字符")
    return _no(0.95)


def greeting_verdict(message: str) -> Verdict:
    """整句只有寒暄，没有夹带别的事。

    做法是**整词取走**而不是**子串查找**：把寒暄词全取走，如果什么都不剩，
    才算纯寒暄。这样「谢谢你，顺手把周报也改了吧」不会被误判成聊天。
    """
    shape = shape_of(message)
    if not shape.compact:
        return _no(1.0, "空消息")
    if shape.truncated:
        # 一条几百字的材料不可能是"整句寒暄"。这里不是长度判据，
        # 而是"分析窗口被截断了，看不到全貌，就不下这个结论"。
        return _no(0.9, "消息过长，看不到全貌")
    hits, residue = _GREETING_LEX.segment(shape.stem)
    if not hits:
        return _no(0.9, "没有寒暄词")
    if not _residue_is_noise(residue):
        return _no(0.9, f"剥掉寒暄词后还剩「{''.join(residue)[:20]}」")
    return _yes(0.95, f"整句只有寒暄：{'、'.join(dict.fromkeys(hits))}")


def retraction_verdict(message: str) -> Verdict:
    """明确在撤回（「算了」「先不弄了」「取消」）。

    它是确认判定的前置闸门：「算了」不是"好的"。
    """
    shape = shape_of(message)
    if not shape.compact:
        return _no(1.0, "空消息")
    hits, _ = _CONFIRM_LEX.segment(shape.stem)
    found = [hit for hit in hits if hit in RETRACTION_WORDS]
    if not found:
        return _no(0.85)
    return _yes(0.9, f"含撤回说法：{'、'.join(dict.fromkeys(found))}")


def confirmation_verdict(message: str) -> Verdict:
    """只说了「行 / 可以 / 就这个 / 继续」，没有提出任何新内容。

    这类话本身不是指令，它是**对上一轮的回应**。所以它不能单独被当成派活：
    「可以」到底授权了什么，取决于上一轮 agent 提议的是什么。
    """
    shape = shape_of(message)
    if not shape.compact:
        return _no(1.0, "空消息")
    if shape.question_tail:
        # 「行吗」「可以吗」是在问，不是在答。
        return _no(0.9, "句尾是疑问，是征询不是同意")
    retraction = retraction_verdict(message)
    if retraction.value:
        return _no(0.9, *retraction.evidence)
    hits, residue = _CONFIRM_LEX.segment(shape.stem)
    if not hits:
        return _no(0.9, "没有同意类说法")
    if not _residue_is_inert(residue, _GREETING_LEX):
        return _no(0.9, f"除了同意还说了别的：「{''.join(residue)[:20]}」")
    return _yes(0.9, f"整句只有同意：{'、'.join(dict.fromkeys(hits))}")


def advice_verdict(message: str) -> Verdict:
    """在问「该怎么做 / 这样行不行」，而不是在说「就这么做」。

    这里有第二组对立：**征询**（问你怎么看）和**请求**（请你动手）。
    「能帮我生成一份吗」形如问句，实际是派活；判成征询会连带压掉拍板信号，
    把一句明确的请求拖成一轮反问。

    区分靠受益标记，但必须**就近**——见 `_near_clause`。隔着一个分句的
    「顺便帮我……」是另一件事，不能拿它否定前面的真征询。
    """
    shape = shape_of(message)
    if not shape.compact:
        return _no(1.0, "空消息")

    match = _ADVICE_RE.search(shape.text)
    if match:
        window = _near_clause(shape.text, match.start())
        # 「给我个建议」「帮我拿个主意」：受益物就是判断本身，仍是征询。
        # 这里把命中的词也拼进来看——「给我个建议」里，征询标记就是「建议」，
        # 它在「给我」后面，不算进去就只剩受益人，会被读成请求。
        if not any(word in window + match.group(0) for word in _ADVICE_OBJECT) and (
            _BENEFIT_RE.search(window)
        ):
            return _no(0.6, "同一分句里带着受益人，这是请求不是征询")
        return _yes(0.85, f"征询说法「{match.group(0)}」")

    if shape.question_tail:
        if _BENEFIT_RE.search(_near_clause(shape.text, len(shape.text), window=16)):
            # 「能帮我生成一份吗」是在请你动手，不是在问你怎么看。
            return _no(0.6, "带受益人的请求，按请求处理而不是征询")
        return _yes(0.7, "句尾是疑问，且不是在请人办事")
    return _no(0.8)


def _clause_tail(text: str) -> str:
    """prefix 的最后一个分句。否定只在同一分句里生效，跨逗号不算。"""
    parts = _CLAUSE_SPLIT_RE.split(text)
    return parts[-1] if parts else ""


def _blocker(
    shape: TextShape,
    start: int,
    end: int,
    *,
    veto_own_negation: bool = True,
) -> str | None:
    """这个"拍板短语"为什么不算数。返回 None 表示放行。

    四道检查：词组自身 → 同一分句的否定 → 前缀里的假设/引述 → 说完之后的反悔。

    `veto_own_negation` 只对**弱匹配**为真。弱匹配是正则拼出来的
    （动作词 + 六字以内 + 「吧」），里面出现「不」几乎必然是否句，
    （「这样改不太好吧」）。表内短语相反：它是人挑过的，「不用问了」
    「别再问了」带「不」恰恰就是"别再问、直接做"的意思，让否定闸去拦它们
    等于把表里两个词当场作废。
    """
    if veto_own_negation and _NEG_IN_SPAN_RE.search(shape.text[start:end]):
        return "词组本身带否定"

    prefix = shape.text[:start]

    negated = _NEG_TAIL_RE.search(_clause_tail(prefix))
    if negated:
        return f"紧挨着否定「{negated.group(0).strip()}」"

    deferred = _DEFER_RE.search(_clause_tail(prefix))
    if deferred:
        return f"被「{deferred.group(0).strip()}」推后了"

    condition = _CONDITION_RE.search(prefix)
    if condition:
        return f"在被「{condition.group(0)}」引出的假设里"

    reported = _REPORT_RE.search(prefix)
    if reported:
        return f"是在转述「{reported.group(0)}」的话"

    suffix = shape.text[end:]
    asking = _QUESTION_MARKER_RE.search(suffix)
    if asking:
        return f"后面跟着疑问「{asking.group(0)}」"

    retracted = _POST_RETRACT_RE.search(suffix)
    if retracted:
        return f"说完又反悔「{retracted.group(0)}」"

    # 软反悔：没有明说"算了"，但在后面分句里把动手推后、或者把动作否掉。
    # 只看紧跟的一到两个分句——那是他补的条件，再往后就是别的事了。
    for clause in _clauses_after(shape.text, end):
        deferred = _POST_DEFER_RE.search(clause)
        if deferred:
            return f"说完又推后「{deferred.group(0)}」"
        denied = _POST_NEG_RE.search(clause)
        if denied:
            return f"说完又否掉「{denied.group(0)}」"

    return None


def commit_verdict(message: str) -> Verdict:
    """是否已经把决定说出口（「直接生成」「就按这个，落盘」「开始吧」）。

    这是**加分信号，不是判据**：它只说明"这句话听起来像拍板"，最终还得由
    理解层结合上下文确认——「按这个来」也可以是在复述别人的话。所以这里
    把能想到的"像却不是"的情况逐条排除：否定、假设、引述、句尾疑问。
    """
    shape = shape_of(message)
    if not shape.compact:
        return _no(1.0, "空消息")

    # 分析窗口被截断时**直接不认拍板**，不是"降一点置信度"。
    #
    # 以前是 `confidence - 0.05`：理由听上去合理（拍板在句尾，尾巴留下来了），
    # 但漏掉了另一半——前缀里的条件、引述、否定也一起被截掉了。窗口里看到的
    # 「生成吧」可能落在一个「如果……就……」里，而「如果」在被丢掉的开头。
    # 置信度低一点照样过 `MIN_AUTHORIZED_CONFIDENCE` 的下限（0.9-0.05=0.85），
    # 于是这条降低形同虚设，代价是一份没人要的文件。
    #
    # 代价是"长材料 + 拍板"不再由确定性层放行，交给理解层读全文——它读得到
    # 整段，本来也比这里更该做这个判断。
    if shape.truncated:
        return _no(
            0.5,
            f"消息超过 {MAX_ANALYZED_CHARS} 字，分析窗口被截断，看不到前缀里的条件与引述，不认拍板",
        )

    if shape.question_tail:
        return _no(0.9, "句尾是疑问，在确认不是在拍板")

    text = shape.text
    # (起点, 终点, 短语, 权重, 是否是表内短语)
    candidates: list[tuple[int, int, str, float, bool]] = []
    for phrase in _STRONG_COMMIT:
        for index in _find_all(text, phrase):
            candidates.append((index, index + len(phrase), phrase, 0.9, True))
    for match in _WEAK_COMMIT_RE.finditer(text):
        candidates.append((match.start(), match.end(), match.group(0), 0.72, False))

    if not candidates:
        return _no(0.9, "没有把决定说出口的说法")

    # 位置靠前的优先；同一位置取更长的那个（「直接生成」优于「生成…吧」）。
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    rejected: list[str] = []
    for start, end, phrase, weight, curated in candidates:
        reason = _blocker(shape, start, end, veto_own_negation=not curated)
        if reason is None and not curated:
            # 弱匹配是正则拼出来的，分不清主句和前件；表内短语是人挑过的，
            # 配上条件读起来就是假设，前缀检查已经够用。
            protasis = _weak_in_condition(text, start, end)
            if protasis is not None:
                reason = f"落在「{protasis}」引出的条件从句里"
        if reason is not None:
            rejected.append(f"「{phrase}」不算：{reason}")
            continue
        return _yes(weight, f"说出口的决定「{phrase}」", *rejected)

    return _no(0.85, *rejected[:3])


def order_verdict(message: str) -> Verdict:
    """他有没有**明确让我动手**——比 `commit_verdict` 宽一档的第二个问题。

    为什么要分成两个函数而不是把一个加宽：

    - `commit_verdict` 问的是「**他决定了没有**」。它只认决策陈述
      （「就按这个」「直接生成」「落盘」），因为它的结论会进 `Verdict` 的
      证据链、进日志、进兜底的放行判据，认错一次就是一份没人要的文件。
      「把这份材料整理成周报」只是**描述要做的事**，没说"就做"——这条立场
      写在 `test_commit_verdict_table` 里，是有意为之。
    - 这里问的是「**他有没有明确让我做**」。直接下令（「把标题居中」
      「删掉第二段」）也算：它没有"决定"这一层，但动作写在自己句子里，
      谁来读都是同一个意思。

    谁用哪个：`commit_verdict` 决定**能不能写盘**（宁可少认），`order_verdict`
    只用来**记下"他要做什么"**——`fallback_reading` 把它的命中写进 `goal`，
    权限一格都不动。

    为什么后者不能拿去授权：祈使句缺的不是语气，是**范围**——哪份文件、
    哪一段。「把标题居中」在有三份材料时，理解层都得往前翻两轮才知道改哪个；
    兜底恰恰没人替他翻，放行就是对着猜出来的文件动手。
    `test_fallback_never_guesses` 钉着这条，改动时别绕过它。

    与「好 / 可以」的区别仍然守着：确认词授权了什么由历史决定，单句判它
    正是误生成的入口（`deterministic_reading` 里对着同一件事写了注释）。
    这里只认**把动作写在自己句子里**的说法。
    """
    commit = commit_verdict(message)
    if commit.value:
        return commit

    shape = shape_of(message)
    # 空消息 / 截断 / 句尾疑问：`commit_verdict` 已经给出理由，
    # 这几条对祈使句同样成立，不重复判断。
    if not shape.compact or shape.truncated or shape.question_tail:
        return commit

    text = shape.text
    rejected: list[str] = [f"不是决策陈述：{commit.evidence[0]}"] if commit.evidence else []

    # 整句在征询意见时不算下令。来源是一条**真实误判**：
    # 「这几份材料我想整理成摘要，你觉得先动哪份」被「整理成」命中，
    # 可他要的是"先动哪份"的答案，不是"现在就整理"——真照办的话，
    # 他还没选，文件已经出来了。
    #
    # 判据是**整句的性质**而不是短语：征询会笼罩整个句子，不管动作词落在哪。
    # 方向是保守的——一句又请求又征询的话（「帮我生成一份，你觉得用哪个模板好」），
    # 宁可等他把话说全。
    advice = advice_verdict(message)
    if advice.value:
        reason = advice.evidence[0] if advice.evidence else "整句在征询"
        return _no(0.80, f"整句在征询意见（{reason}），不是下令", *rejected)

    def _screen(start: int, end: int) -> str | None:
        """位置检查 + 条件从句检查 + 意愿检查。返回拦下的理由，None 表示放行。"""
        reason = _blocker(shape, start, end, veto_own_negation=True)
        if reason is not None:
            return reason

        # 在说打算而不是派活：「我想把标题居中，这样好看」。带请求标记时不算
        # （「我想请你把标题居中」是要你动手）。
        if _WISH_RE.search(_near_clause(text, start)) and not _REQUEST_RE.search(text):
            return "句子里是打算/希望（…想…），没有请你动手的意思"

        # 语气词要一起吃掉：否则「把标题居中吧，如果领导同意的话」里，
        # `_clauses_after` 的第一个分句是「吧」，条件句退到第二格看不见。
        while end < len(text) and text[end] in _TAIL_PARTICLES:
            end += 1
        protasis = _weak_in_condition(text, start, end)
        return f"落在「{protasis}」引出的条件从句里" if protasis else None

    # 授权转移：交的是决定权，不是具体动作，所以比指令低半档。
    for match in _HANDOVER_RE.finditer(text):
        reason = _screen(match.start(), match.end())
        if reason is None:
            return _yes(0.75, f"把决定权交出来「{match.group(0)}」", *rejected)
        rejected.append(f"「{match.group(0)}」不算：{reason}")

    # 直接下令。长度上限是这条规则的一部分，不是优化：长句里的祈使多半是
    # 材料原文（语料里一条会议记录写着「运营建议把…改为…」），
    # 用户问的是"有没有漏掉的"，不是在下令。
    if len(text) > _IMPERATIVE_MAX_CHARS:
        return _no(
            0.80,
            f"消息 {len(text)} 字，超过直接下令的长度上限 {_IMPERATIVE_MAX_CHARS}，"
            "长句里的祈使多半是材料原文",
            *rejected[:2],
        )

    for match in _IMPERATIVE_RE.finditer(text):
        reason = _screen(match.start(), match.end())
        if reason is None:
            return _yes(0.80, f"直接下令「{match.group(0)}」", *rejected)
        rejected.append(f"「{match.group(0)}」不算：{reason}")

    return _no(0.85, *rejected[:4])


#: 「这一轮先别动手」。三类依据，方向只有一个：把动手推后，或者否认让你动手。
#:
#: 为什么要单独一张表，而不是靠 `commit_verdict` 返回 False：
#: 「没拍板」和「明确叫停」在行为上要区别对待——前者是"还没定，给方案问一句"，
#: 后者是"他说的就是别动，直接回答，连方案都不用给"。而且叫停往往是**顺口**
#: 说出来的（「先别生成吧，我就是想问问」），它没有拍板短语那样的固定形态，
#: 只能靠这类标记识别。
#:
#: 方向单一所以可以写宽：命中一次最多多问一句，漏掉一次就是一份没人要的文件。
#: 唯一要防的是**别人说的**（「他说先别生成」）——那不是他的指令，用引述检查排掉。
#:
#: 第四列是**压回哪一档**，这是这张表唯一需要分档的地方：
#: 「先别生成」是"这一轮别动"，压到 none；「我点头了再落盘」是"方向对、时间没到"，
#: 压到 proposed——他要的仍是那个结果，只是还得点头。两者都压到 none 会更安全，
#: 但那样「先给方案，我点头了再落盘」只会收到一句回答，连方案都拿不到，
#: 等于把"让我先看看"听成"别说了"。
HOLD_NONE = "none"
HOLD_PROPOSED = "proposed"

_HOLD_PATTERNS: tuple[tuple[str, str, float, str], ...] = (
    (
        "明确叫停",
        r"先别|暂时别|别先|先不(?:要|用|急|忙|动|改|弄|写|做|生成|出)|先放着|先搁着",
        0.92,
        HOLD_NONE,
    ),
    (
        "推迟到确认之后",
        r"我(?:点头|确认|看(?:完|过)|想清楚)(?:了|过)?(?:再|之后|以后)",
        0.9,
        HOLD_PROPOSED,
    ),
    (
        "推迟到以后",
        r"(?:回头|明天|下周|改天|过两天|稍后|晚点|等会儿?)(?:再|说)",
        0.8,
        HOLD_PROPOSED,
    ),
    (
        "自述只是在问",
        r"(?:我|咱)?(?:也|就|只|还)?(?:只是|就是想|只是想|就想|只想|就是)"
        r"[^，。！？；,.!?;\n]{0,4}"
        r"(?:问问|问一下|问下|问个|了解一下|了解下|打听|知道|搞清楚|弄明白|确认一下)",
        0.86,
        HOLD_NONE,
    ),
    (
        "否认让你动手",
        r"没(?:有)?(?:让你|要你|叫你)|没说过要|谁说要|什么时候说要|我还没让",
        0.9,
        HOLD_NONE,
    ),
)


@dataclass(frozen=True)
class Hold:
    """这一轮为什么不动手，以及该压回哪一档。"""

    label: str
    target: str
    confidence: float
    text: str


def hold_of(message: str) -> Hold | None:
    """命中一条 hold 依据就返回它。`None` 表示没有。"""
    shape = shape_of(message)
    if not shape.compact:
        return None

    commit = commit_verdict(message)
    if commit.value:
        # 「先别管格式，直接生成吧」两个标记都在。听拍板：它更具体，
        # 而「先别管」管的是别的事。这个顺序不是偏好，是唯一不自相矛盾的顺序。
        return None

    for label, pattern, confidence, target in _HOLD_PATTERNS:
        for match in re.finditer(pattern, shape.text):
            reported = _REPORT_RE.search(shape.text[: match.start()])
            if reported:
                # 「他说先别生成」是在转述别人，不是他叫停。
                continue
            if label == "明确叫停" and _NARROW_RE.search(shape.text[match.end() :]):
                # 叫停后面跟着「改标题就行」——那是收窄，不是停手。
                continue
            return Hold(label, target, confidence, match.group(0).strip())

    return None


def hold_verdict(message: str) -> Verdict:
    """这一轮「先别动手」——他自己说出口的，不是模型猜的。

    ## 为什么拍板优先

    「先别管格式，直接生成吧」里两个标记都在。这时候听哪个？听拍板：它更具体
    （点了动作、点了结果），而「先别管」管的是别的事。所以先跑一次
    `commit_verdict`，能站住就直接返回"没有 hold"。

    反过来，「先别生成吧，我就是想问问」里的「生成吧」站不住（被「先别」挡住），
    于是轮到 hold 生效。这个顺序不是偏好，是唯一不会自相矛盾的顺序。

    ## 它否决的是什么

    只否决"这一轮动手"，不否决"他到底想不想要"。所以它不能用来授予任何权限，
    只能把已授权的结论压回去。方向单一，判错也只有一个后果：多问一句。

    要压回哪一档见 `hold_of` 的第四列：叫停压到 none，推后压到 proposed。
    """
    hit = hold_of(message)
    if hit is not None:
        return _yes(hit.confidence, f"{hit.label}「{hit.text}」")

    shape = shape_of(message)
    if not shape.compact:
        return _no(1.0, "空消息")
    commit = commit_verdict(message)
    if commit.value:
        return _no(
            0.75, f"句子里有生效的拍板说法（{commit.evidence[0] if commit.evidence else ''}）"
        )
    return _no(0.7, "没有叫停、推后或「只是在问」的说法")


def standing_phrase(message: str, phrases: Sequence[str]) -> tuple[str, Verdict]:
    """命中的短语原文 + 判定结果。没命中时短语是空串。

    为什么要把短语单独返回：兜底触发时日志里必须能写「他命中的是『直接生成』」。
    只记一个 `allowed=True` 的布尔值，线上排查「这份文件为什么冒出来」时
    还是得回头猜是哪句被当成了命令；而 evidence 里那句「「直接生成」在起作用」
    是给人读的文案，从中反抠引号很脆——短语本身就可能带引号（「就按这个」）。

    判定复用上面那套位置检查（否定 / 推后 / 假设 / 转述 / 疑问尾 / 反悔），
    只是把短语表换成调用方给的。`veto_own_negation=False`：调用方给的是精选
    短语（「不用问了」「别再问了」本身就带否定，意思恰恰是"别再问、直接做"）。
    """
    shape = shape_of(message)
    if not shape.compact:
        return "", _no(1.0, "空消息")
    if shape.truncated:
        # 与 `commit_verdict` 同一条规矩：窗口被截断时，短语可能落在看不到的
        # 条件里。兜底交付是替模型补动作，理由不足就不补。
        return "", _no(0.5, "消息过长，分析窗口被截断，短语位置不可信")
    if shape.question_tail:
        # 「生成吧？」「就按这个来吗」——带问号的短语是话题，不是指令。
        return "", _no(0.9, "整句是疑问，短语只是话题")

    rejected: list[str] = []
    for phrase in phrases:
        for index in _find_all(shape.text, phrase):
            reason = _blocker(shape, index, index + len(phrase), veto_own_negation=False)
            if reason is None:
                return phrase, _yes(0.9, f"「{phrase}」在起作用", *rejected)
            rejected.append(f"「{phrase}」不算：{reason}")

    if not rejected:
        return "", _no(0.9, "这些短语一个都没出现")
    return "", _no(0.85, *rejected[:3])


def phrase_stands(message: str, phrases: Sequence[str]) -> Verdict:
    """这些短语里有没有**一处**是真的在起作用。

    给引擎兜底用的。那里原来写的是 `keyword in message`：

        "先别生成吧，我就是想问问周报该怎么写" 里含有 "生成吧"  ← 于是判成"他要生成"

    子串匹配看不出「生成吧」前面站着一个「先别」。这跟 `intent.py` 早先那版
    `str.replace` 剥词是同一个毛病，只不过长在另一个文件里，改判据时没扫到。
    """
    return standing_phrase(message, phrases)[1]


# ============================================================
# 五、兼容层：旧接口保持原样
# ============================================================


def greeting_only(message: str) -> bool:
    """整句就是寒暄，没有夹带任何别的事。"""
    return greeting_verdict(message).value


def bare_confirmation(message: str) -> bool:
    """只说了「行 / 可以 / 就这个 / 继续」。"""
    return confirmation_verdict(message).value


def asks_advice(message: str) -> bool:
    """在问「该怎么做 / 这样行不行」。"""
    return advice_verdict(message).value


def explicit_commit(message: str) -> bool:
    """是否已经把决定说出口。**加分信号，不是判据。**"""
    return commit_verdict(message).value


# ============================================================
# 六、融合：仍然永不返回 write
# ============================================================


@dataclass(frozen=True)
class IntentSignal:
    intent: str
    confidence: float
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": round(self.confidence, 3),
            "evidence": list(self.evidence),
        }


def classify(message: str) -> IntentSignal:
    """零成本的档位判断。只区分「明显不用动手」和「可能要看点东西」。"""
    shape = shape_of(message)
    if not shape.compact:
        return IntentSignal(INTENT_CHAT, 1.0, ("空消息",))
    greeting = greeting_verdict(message)
    if greeting.value:
        return IntentSignal(INTENT_CHAT, greeting.confidence, greeting.evidence)
    return IntentSignal(
        INTENT_READ,
        0.5,
        ("有内容，但句内看不出要不要动手，按只读处理",),
    )


def intent_of(message: str) -> str:
    """模型读不懂时的降级判断。**永远不返回 write。**

    以前这里会返回 write，于是词表没命中/命中错就直接决定了能不能落盘。
    现在写权限由 `policy.py` 按「是否已授权 + 工具风险」单独把关，
    这里判错最多让对话话风不对，不会产出多余文件。
    """
    return classify(message).intent


def explain(message: str) -> dict[str, Any]:
    """把这条消息的每一项判定摊开，用于排障与评估。

    模型判错时最常问的是「它到底看到了什么」。没有这个函数，只能靠重跑加断点。
    """
    shape = shape_of(message)
    signals = {
        "blank": blank_verdict(message),
        "greeting": greeting_verdict(message),
        "confirmation": confirmation_verdict(message),
        "advice": advice_verdict(message),
        "commit": commit_verdict(message),
        "hold": hold_verdict(message),
    }
    return {
        "input": shape.raw,
        "analyzed": shape.text,
        "stem": shape.stem,
        "truncated": shape.truncated,
        "question_tail": shape.question_tail,
        "clause_count": shape.clause_count,
        "signals": {name: verdict.as_dict() for name, verdict in signals.items()},
        "intent": classify(message).as_dict(),
    }


__all__ = [
    "CONFIRM_WORDS",
    "GREETING_KEYWORDS",
    "HOLD_NONE",
    "HOLD_PROPOSED",
    "INTENT_CHAT",
    "INTENT_READ",
    "INTENT_WRITE",
    "MAX_ANALYZED_CHARS",
    "READ_ONLY_TOOL_NAMES",
    "RETRACTION_WORDS",
    "Hold",
    "IntentSignal",
    "TextShape",
    "Verdict",
    "advice_verdict",
    "asks_advice",
    "bare_confirmation",
    "blank_verdict",
    "classify",
    "commit_verdict",
    "confirmation_verdict",
    "explain",
    "explicit_commit",
    "greeting_only",
    "greeting_verdict",
    "hold_of",
    "hold_verdict",
    "intent_of",
    "is_blank",
    "normalize",
    "order_verdict",
    "phrase_stands",
    "retraction_verdict",
    "shape_of",
    "standing_phrase",
]
