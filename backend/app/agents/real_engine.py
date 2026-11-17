"""RealEngine：真实模型 ReAct 工具循环（计划书第 7 章 7.1 / 7.3 / 7.5 / 7.9）。

循环：system prompt + 工具 JSON Schema（由 ToolSpec 自动生成）
  -> 模型决策（文本 + tool_calls）
  -> 内核执行工具（带 ToolContext / 写权限门控 / 超时保护）
  -> 观察结果回填 messages
  -> 再决策，直到模型不再调用工具 / 达到步数上限 / token 预算耗尽。

事件协议与 MockEngine 完全一致（core/events.py v1.1），只追加字段：
run.started（provider）、tool.started（step）、run.completed（provider/model/engine/usage/stop_reason）。

保护机制（计划书表 7-1）：
- 步数是有界硬顶（`MAX_STEPS_HARD_LIMIT`），只防死循环，不进用户视野；
- 工具失败转结构化观察，不中断主流程；写盘动作先过门控，没放行就跳过（不发审批卡）；
- 所有供应商不可用：运行前降级 MockEngine（run.started 标 degraded=true）；运行中失败则降级收尾。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from ..core.events import (
    ARTIFACT_READY,
    MESSAGE_COMPLETED,
    MESSAGE_DELTA,
    PLAN_UPDATED,
    RUN_COMPLETED,
    RUN_STARTED,
    THINKING_COMPLETED,
    THINKING_DELTA,
    TOOL_FINISHED,
    TOOL_STARTED,
    build_event,
)
from ..core.logging import get_logger
from ..core.security import sanitize
from ..core.utils import now_iso
from ..domain.entities import Message
from ..domain.enums import MessageRole, Risk, RunStatus
from ..domain.formats import output_format_label, util_bullets
from ..domain.rag import unsupported_facts
from ..tools.builtin.doc import doc_title_for
from ..tools.registry import ToolContext, ToolSpec
from .engine_protocol import (
    EngineEvent,
    RunContext,
    normalize_approval_mode,
)
from .intent import (
    INTENT_CHAT,
    INTENT_READ,
    INTENT_WRITE,
    hold_verdict,
    standing_phrase,
)
from .mock_engine import MockEngine
from .model_router import ChatResult, ModelRouter, ModelUnavailableError
from .policy import (
    MAX_BLOCKS_PER_RUN,
    REASON_DESTRUCTIVE,
    REASON_HOLD,
    REASON_LONG_MESSAGE,
    REASON_RETRACTED,
    REASON_UNSURE,
    decide_write,
    stop_hint,
)
from .reading import (
    COMMIT_AUTHORIZED,
    COMMIT_PROPOSED,
    DELIVERY_CHAT,
    DELIVERY_DELIVER,
    DELIVERY_DRAFT,
    DELIVERY_READ,
    STANCE_CHAT,
    TurnReading,
    read_turn,
)

logger = get_logger("app.agents.real_engine")

# 一次运行的绝对硬顶：只防死循环，不是「做到第几步就交差」。
# 以前 12 步，复杂任务常在「还差最后一步」时被掐断，然后收到一句「到步数上限了」。
MAX_STEPS_HARD_LIMIT = 200
# 连续 N 步「同样的工具调用 + 同样的旁白」视为空转。这是唯一会主动提前停的判据：
# 步数放开之后，模型卡在重复调用里会白烧 token，得有个不依赖预算数的护栏。
NO_PROGRESS_LIMIT = 4
# 工具观察结果回给模型时截到多少字。
# 以前 1800：一个 doc.analyze_material 的结构摘要就能占满，模型看不到第三份材料的细节，
# 于是「没读到」被误当成「没有」。这是判错，不是省钱的必要代价。
OBSERVATION_LIMIT_CHARS = 4000
# file.read 的正文观察上限。
# 以前 7000：一份两万字的报告只能看到开头三分之一，后面全靠猜或反复重读。
# 放宽到 24000 仍然有界（够 30 页），但足够让模型读到结尾再动手。
MATERIAL_OBSERVATION_LIMIT = 24_000
# 检索片段的注入上限。单独一档是因为它和正文观察的取舍不同：片段是**已经选过**的
# 高相关内容，按 4000 字截掉后面几段，等于让模型只看第一条依据就下结论。
PASSAGE_OBSERVATION_LIMIT = 8_000
RESPONSE_CHUNK_CHARS = 12
# 分片之间的间隔。以前是 `sleep(0)`：所有片子在同一帧里发完，浏览器把它们合成
# 一整块——用户看到的就是"凭空蹦出一大段字"。24ms/12 字 ≈ 500 字/秒，
# 比打字快、比整块出现自然。
TEXT_CHUNK_DELAY_SECONDS = 0.024
# 一整段话的呈现预算。长文不能按片数线性变慢（1500 字要 3 秒，反而像卡住），
# 超出预算就自动加快，总时长封顶在这儿。
TEXT_REVEAL_BUDGET_SECONDS = 1.8
# 只读档的步数配方：首尾各一步，每份材料两步。见 `_max_steps_for()`。
READ_STEPS_BASE = 2
READ_STEPS_PER_FILE = 2
# 商量档：一步读、一步成文，加上每份材料一步。
DRAFT_STEPS_BASE = 3
THINKING_CHUNK_CHARS = 12
# 思考内容按字数分片下发，片间留一点间隔：模型真在推理时用户才看得到「在想」，
# 一次性刷完会显得比人还快、反而不可信（第十二轮反馈）。
THINKING_CHUNK_DELAY_SECONDS = 0.035
# 整轮预算：只防失控，不参与「思考得够不够」。
TOKEN_BUDGET_PER_RUN = 1_000_000

# 「思考」在这个产品里的定位：不是每轮开工的仪式，而是**决策那一刻的一句话**。
# 所以先要判断这句话里到底有没有决策：问句、给方向、说没把握、要用户点头才算。
# 「我先读一下素材」不算——那是过程播报，进执行过程里的一行字就够了。
DECISION_MARKERS = (
    "？",
    "?",
    "要不要",
    "是不是",
    "是否有",
    "你看",
    "你觉得",
    "你希望",
    "选一个",
    "先确认",
    "确认一下",
    "不确定",
    "没把握",
    "我建议",
    "需要你",
    "两个方案",
    "两个方向",
    "三种",
    # 同义说法：同一次「把选择权交回去」，用户能听出来的版本有很多种
    "要不要我",
    "需要你定",
    "你来定",
    "由你定",
    "你定",
    "你挑",
    "挑一个",
    "选哪个",
    "用哪个",
    "哪个更",
    "哪种更",
    "拿不准",
    "不好说",
    "两种做法",
    "三个做法",
    "两个选择",
    "先问你",
    "你说了算",
)

#: 「为什么这么定」的痕迹。思考区里一句带理由的话，胜过三句「我先做什么」——
#: 后者只说明它在干活，前者才说明它在想。
REASON_MARKERS = (
    "因为",
    "所以",
    "不过",
    "但是",
    "其实",
    "与其",
    "不如",
    "宁可",
    "权衡",
    "取舍",
    "否则",
    "既然",
    "考虑到",
    "反过来",
)

# 一句决策话的上限：超了就是又在念流程，不是在做判断。
DECISION_LINE_MAX_CHARS = 64
# 动手前的过程播报（「我先读素材」这类）压成一行，塞进执行过程
PROCESS_NOTE_MAX_CHARS = 48

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])|\n+")

# 工具名 → 人话动词：出错时那句「XX 没成」得说人话，不能把 file.read 抛给用户
TOOL_VERB = {
    "file.list": "列出素材",
    "file.read": "读素材",
    "file.search": "翻素材",
    "file.delete": "删文件",
    "doc.analyze_material": "过一遍素材结构",
    "doc.generate_report": "生成文件",
    "code.run_python": "跑脚本",
    "todo.list": "看计划",
    "todo.write": "更新计划",
}


def clamp_line(text: str, limit: int) -> str:
    """压成一行的短句：换行、连续空白都收掉，超长在句读处截断。"""
    line = " ".join((text or "").split())
    if len(line) <= limit:
        return line
    head = line[:limit]
    # 尽量在标点处收口，别把半句话切在词中间
    cut = max(head.rfind(mark) for mark in "。，、；：！？,;:!?")
    if cut >= limit // 2:
        head = head[: cut + 1]
    return head.rstrip("，、；：,;:") + "…"


def decision_line(text: str) -> str:
    """从模型动手前说的话里挑出「它在拿主意」的那一句；没有就返回空。

    这一段以前是整段拿去做「思考」，于是每次开工都先念一遍「先看什么、再抓什么」
    ——不管这句话里有没有真的需要判断的东西。现在反过来：先看有没有决策信号，
    有就只留那一句（一句就够，多了又变流水账），没有就当过程播报。

    挑句子时优先带**理由**的那句：「素材里没有数字，所以数据那节留空」比
    「我先做数据那节」更像在想。理由词是判断的唯一痕迹——只复述动作的话，
    用户看到的就是一句"它在干活"，不是"它在想"。
    """
    body = (text or "").strip()
    if not body:
        return ""
    if not any(marker in body for marker in DECISION_MARKERS):
        return ""
    best = ""
    best_score = 0
    for raw in _SENTENCE_SPLIT_RE.split(body):
        sentence = (raw or "").strip()
        if not sentence:
            continue
        score = 0
        if any(marker in sentence for marker in DECISION_MARKERS):
            score += 2
        if any(marker in sentence for marker in REASON_MARKERS):
            score += 3
        if score > best_score:
            best, best_score = sentence, score
    if best:
        return clamp_line(best, DECISION_LINE_MAX_CHARS)
    return clamp_line(body, DECISION_LINE_MAX_CHARS)


def material_thought(facts: dict[str, Any]) -> str:
    """读完素材之后那句判断：素材长什么样，所以我按哪种写法走。

    这里只说**从数据里看出来的事**——几份、多少字、有没有表和图、素材自己带不带
    小标题——以及由此定下的写法。模型拿到的是片段，看不见这个全貌；这些事实说清了，
    用户才信得过后面那篇稿子是按材料写的，不是按模板套的。
    """
    totals = facts.get("totals") or {}
    files = int(totals.get("files") or 0)
    if files <= 0:
        return ""
    chars = int(totals.get("chars") or 0)
    size = f"{chars / 10000:.1f} 万字" if chars >= 10000 else f"{chars} 字"
    tables = int(totals.get("tables") or 0)
    images = int(totals.get("images") or 0)
    headings = int(totals.get("headings") or 0)
    weekly = bool((facts.get("signals") or {}).get("weekly"))

    if headings >= 3:
        how = f"素材自己有 {headings} 个小标题，照它的顺序走，不另起一套"
    elif tables:
        how = f"{tables} 张表，数字照搬，不自己算"
    elif images:
        how = f"{images} 张图，图注照抄"
    else:
        how = "只有正文，没表没图，按段落归纳"
    lead = (
        "里面写着进展和计划，按周报的节来"
        if weekly
        else "没有进展和计划，硬套周报只能编，按它自己的顺序归纳"
    )
    return f"{files} 份、{size}；{lead}；{how}"


def tool_failure_line(tool: str, error: str) -> str:
    """某一步没成时的那句话：说出来、并说清接下来怎么变。"""
    verb = TOOL_VERB.get(tool, tool)
    reason = clamp_line(error, 40) or "没有返回原因"
    return f"{verb}没成（{reason}），换个法子接着来"


def decision_kind(line: str) -> str:
    """这句话是在等你回话，还是它自己已经拿定主意。"""
    asking = ("？", "?", "要不要", "是不是", "你希望", "你看")
    return "ask" if any(marker in line for marker in asking) else "decision"


# 模型明确表示"做不了"的说法：命中就不补生成，避免结论与产物互相打脸
MODEL_REFUSAL_MARKERS = (
    "无法",
    "做不了",
    "做不成",
    "做不出",
    "没法",
    "不具备",
    "缺少",
    "缺要素",
    "不匹配",
    "不是会议",
    "没有会议",
    "未产出",
    "没有产出",
)


def model_refused(text: str) -> bool:
    """模型是否已明确说「这件事做不了」。

    只在兜底前用：模型说做不了、内核却补生成文件，两条消息自相矛盾，
    用户会以为前面那段解释是编的（第五十轮）。
    """
    body = text or ""
    return any(marker in body for marker in MODEL_REFUSAL_MARKERS)


#: 兜底跳过的原因 → 日志事件名。分开命名的用处是能在日志里直接按事件筛：
#: 「这周有多少轮是他说了先别、有多少轮是理解层判成商量」是两个完全不同的问题。
_FALLBACK_SKIP_EVENTS = {
    "no_marker": "kernel_fallback_skipped_consult",
    "hold": "kernel_fallback_skipped_hold",
    "proposed": "kernel_fallback_skipped_proposed",
    "no_commit": "kernel_fallback_skipped_no_commit",
    "model_refused": "kernel_fallback_skipped_refused",
}

# 只有这几种说法算「现在就动手」，模型漏做时才替它补。
# 注意不含「整理 / 报告 / 摘要」这类词：那是任务类型，不是授权。
# 以前按任务类型兜底，于是「这几份材料我想整理成摘要，你觉得先动哪份」也会被补一份 docx。
#
# 另一条经验：**别放虚词**。原来表里有「现在就」和「开始做」，
# 「现在就差退款那节了」「你说从哪开始做比较好」都会命中——两句话都不是在下令。
# 这里的每条都要能单独当命令念出来。
EXPLICIT_BUILD_MARKERS = (
    "直接生成",
    "现在就做",
    "现在就生成",
    "现在就出",
    "现在生成",
    "马上生成",
    "立刻生成",
    "开始生成",
    "开始动手",
    "动手吧",
    "生成吧",
    "出文件吧",
    "照这个做",
    "就按这个",
    "就按第一个",
    "就按第二个",
    "不用问",
    "别再问",
    # 同义口令：都是「现在就动手」，只是口气不同
    "直接出稿",
    "直接落地",
    "马上做",
    "马上就做",
    "现在就开始",
    "照这个来",
    "就按这套",
    "不用确认",
    "别问了",
    "开工",
    "开干",
)

# 模型说了「我这就给你做」却没动手：这是真故障，替它补上不算越界。
#
# 这里**必须点到文档类动词**。原来写的是「这就」「马上」「现在给你」，
# 三个都是高频虚词：「这就要看你想要什么了」「现在就差退款那节」都会命中，
# 于是模型正常答完，内核以为它承诺过、补出一份 docx。
# 承诺是可核对的："他说要出文档"才补，不是说"这就"就补。
PROMISE_MARKERS = (
    "我给你生成",
    "我给你出",
    "我来生成",
    "我做一份",
    "我直接生成",
    "我这就生成",
    "我这就出",
    "这就给你生成",
    "这就给你出",
    "马上给你生成",
    "现在就生成",
    "现在就给你生成",
    "这就开始生成",
    "这就开始写",
    # 承诺要**点到文档**才补：只说「这就」不作数（上面那段注释是踩过的坑）
    "我给你做一份",
    "我来出一份",
    "我这就做一份",
    "我马上生成",
    "我马上给你生成",
    "我这就动手",
    "这就动手做",
    "马上动手做",
)


_UTIL_BULLETS = "\n".join(util_bullets())

TOOL_RULES = f"""# 工具约定
- 工具函数名中的点已改为下划线：file_list、file_read、file_search、doc_generate_report、code_run_python、todo_write、todo_list、file_delete。
- file_read 返回的 observation 里 `material` 字段就是素材正文；超长时它给的是「分节目录 + 前若干块」，
  会明说还有几块没注入——那不是读完了，别把没读到的部分当「素材里没有」，也别凭印象补。
- file_search 在素材里按关键词检索，返回带 [S3] 编号的原文片段；回答具体事实、核对数字、确认
  「素材到底提没提」时用它。它一次比一次准，可以换词多查几轮，比反复整篇读省得多。
- 工具库里的函数都接受「对象或文件路径」：直接 `read_report(src)`、`apply_body(src)` 传路径也行，不要先自己 Document(src) 再传错对象；不确定参数时先打印 `inspect.signature(函数名)` 确认，不要猜关键字参数名。
- 脚本开头按扩展名 `from <格式>_utils import *`。工作目录已预置这些库（清单来自格式表，随支持的格式自动增减）：
{_UTIL_BULLETS}
- 每次先看上一次工具返回结果再决定下一步，不要假设工具成功；工具失败时按错误信息调整，不要编造。
- 回复使用中文；引用素材时标注文件名。"""


# 「有素材」这一轮才注入。没有素材时讲引用规则是空话，反而挤占注意力。
# 这段的重点不是让回答看起来严谨，是把「哪句有依据、哪句是推断」摊开给用户看——
# 用户没法核对一篇长报告里的每个数字，但他能看见哪里没有编号。
RAG_RULES = """# 依据与引用（这一轮手上有素材，具体事实都要能指回原文）
- 片段开头的 [S3] 就是引用编号。写具体事实时在句末标上，如「退款率降到 1.2%[S3]」；
  一句话里有多个来源就依次标 [S2][S5]。
- 只写片段里出现过的内容。数字、比例、日期、金额、人名、部门名没出现过，就先 file_search 查；
  查不到就直说素材没提，不要用「大约」「据了解」把缺口糊过去——用户分不清哪句是猜的。
- 检索返回 match=none 时，明确告诉用户素材里没有这项内容，并说明素材实际包含哪些小节；
  不要凭常识补一段像模像样的答案。用户问的如果本来就超出材料范围，说清边界就是正确回答。
- 常识可以用在措辞、结构和判断上，但不能替代素材事实。要提外部知识就明说是「一般情况」，
  并且不能和素材冲突。
- 片段之间互相矛盾时，把矛盾指出来，不要自己挑一个当结论。
- 追问很短（「那华南呢」「这个呢」）时，先把指代补成能检索的说法（「华南区网络中断」），
  拿三个字直接搜命中不了，你会以为素材没写。"""

DELIVERY_RULES = """# 交付约定（这一轮用户确实要你产出或改动东西）
- 步骤超过三步时才用 todo_write 排计划：2–5 条，措辞写这一步具体做什么（「把行距统一成 1.5」而不是「处理文档」）。
  一句话就能说清的活儿不要排计划，界面上那张表对用户没有信息量。中途发现原计划不对就重写，不必硬凑已完成。
- 用户要的是文件（「生成/写一份/整理成/周报/纪要/报告/文档/导出」）时，调用 doc_generate_report 产出文件，不能只在回复里给文本。
  「给一段文字」和「交一个文件」是两回事；用户没说要文件，就别生成文件。
- 动手前先定手段，别先出一版再返工：模板渲染能直接满足的，用 doc_generate_report 一次成稿；
  需要按特定顺序重排、或模板塞不进去的结构，直接用 code_run_python 写。
  先用模板生成、发现不对又用脚本重做一遍，产物仓库里会躺两份，用户不知道该用哪个。
- doc_generate_report 的 `format` 必须使用【产物格式】中指定的格式（用户已在界面选择，默认与素材同格式），用户明确要求其他格式时才改用用户格式。
- **一轮只交一份**：按【产物格式】出那一个文件就收手。不要同一份内容顺手再转成别的格式
  （出了 docx 又转一份 PDF、再存一份 TXT）——他要别格式会自己说；产物仓库里多出来的那几份
  只会让他分不清哪个是成品（用户 2026-11-16 反馈：「只让它生成一个目标文档，却多出很多」）。
- **中间稿别写进 $OA_OUTPUT_DIR**：那里每个文件都会登记成产物。中转正文、试排版、核对页数的
  副本写到 `$OA_TMP_DIR`（不进产物仓库）。以 `_` / `.` 开头、或名字里带 tmp / temp / probe /
  scratch 的文件系统也会跳过——但别指望兜底，养成写 tmp 的习惯。
- doc_generate_report 的正文用 `body` 传整篇 Markdown：`## 一节`（自动编号一、二、三）、`### 一小节`、`- 列表`、
  `1. 有编号列表`、`| 表头 |` 加一行 `|---|---|` 做表格、`> 引用`、`**加粗**`。给了 body 就按它排版，
  标题层级/表格/列表都如实还原；不给就按**素材自己的小节**成文（素材写「一、退款率复盘」就是「一、退款率复盘」，
  素材没写的节不出现）。最常见的周报分节（摘要/进展/数据/风险/下周计划）只在素材连小节标题都没有时兜底。
  **不要写任何「来源 / 出处 / 索引」内容**：不写「来源引用」「关键文件索引」「文件索引」
  这类小节，不在正文里列一串源码路径，也不在文末或标题下补「来源：xx.docx」
  「依据《xx.md》整理」「代码位置沿用…」这类落款。读者不会去核对出处，
  那份清单只占篇幅（产物里仍记着素材来源，右栏能看到）。
  真给人看的稿子必须自己写 body：结构由这一次的素材决定，不是每篇都总分总。
  `title` 从素材内容起（写清「哪件事 + 什么动作」），别套「数据分析报告」这种通用词。
  `subtitle` 给标题下一行小字（如「登录模块联调 · 结论先行」），`layout` 选 report / gongwen / compact，
  `line_spacing` 只在整篇要换行距时给（单倍 / 1.15 / 1.5 默认 / 双倍 / 固定值28磅）。
- 正文排版交给版式引擎：大标题、副标题、文首信息行居中（大标题全文最大，副标题次之）；小节标题左对齐、从左边距起行、逐级小一档；正文宋体小四、1.5 倍行距、两端对齐、首行缩进 2 字符。
  你要做的只是别和它对着干——**一整句话就写成段落**，不要用 `- ` 把句子一条条列出来（引擎虽然会把
  一整组长句退回段落，但混着短条目时就会当成清单）；`- ` 留给「完成 / 未完成」「影响：…」这种短条目。
- 写正文前先想清楚这一段素材该怎么组织（周报/报告/方案/纪要常见的分节见 doc-layout 技能；
  钉 PPT、表格、纯文本分别看 ppt-layout / sheet-layout / text-layout）：
  读者只读第一节就应该知道结论是什么、要他做什么。**结构由素材定，不由模板定**——
  素材按什么顺序讲就按什么顺序排，素材没有的节别硬凑。
- 需要改写既有文档、按表格汇总或做模板做不到的格式加工时，调用 code_run_python：脚本从 $OA_INPUT_DIR 读素材（这是目录，你点名的文件已按原文件名复制进去，`glob.glob(os.path.join(os.environ["OA_INPUT_DIR"], "*.docx"))` 即可），$OA_INPUTS 是 JSON 清单（含 filename/path/ext），**不是目录、不能拿它拼路径**；产物写入 $OA_OUTPUT_DIR，执行后自动登记。
- 表格分两种写法：一行一条记录的用 `write_table`；**行和列都是标签的用 `write_grid`**（课表、排班、值班表——
  上边是星期/日期、左边是节次/人名）。后者必须先把二维矩阵摆满（空格子写 None 但位置占住）再写，
  不能按识别文字的先后往右填：空格子一省，后面整行左移，出来的就是「内容填错位置」。样式全交给
  `sheet_lexicon` 的三档版式（default / grid / compact），不要自己拼 openpyxl 的 Font / Border。
- 表格产物里**不要放「识别原文」**这类对照附录（那一串流水文字行列本来就是错位的，读者只会怀疑数据）；
  要交代还原口径就单开一张「核对说明」。
- 改既有文档遵守四条：先 read_report 看现状、backup 出备份、只动用户点名的范围（未点名的段落/样式/页眉页脚不动）、保存后打印改动摘要（改了哪些段落/样式/表格与替换次数）。
- 收尾答复按文末【收尾答复】的结论卡写。"""

READ_REPLY_RULES = """# 回答方式
用户在问手上这些材料里的东西，不是在派活：
- 直接回答，先给结论，再给必要的依据。
- 问得深就答得深：他让你分析、评估、比较，就给判断 + 支撑它的两三条具体事实；
  不要用「整体不错」「基本符合」这种一句打发。
- 引用哪份材料、哪一段，说清楚（文件名 + 位置），不要含糊成「资料里提到」。
- 读到的内容和问题对不上，就直说对不上，不要硬凑一个答案。
- 这一轮不要落盘：用户没让你改文件，也没让你产出新文件。
- 需要时可以给一段能直接用的文字（节选、摘要），但那是回复内容，不是文件。"""

# 商量档：方向已经明确、就差一句话点头。这一档最容易两头不讨好——
# 说太少等于没帮上忙，说太多等于抢先替他把事做了。
DRAFT_REPLY_RULES = """# 这一轮给方案，不落盘

他给了方向，但还没说「就这么做」。你要交的是**一份他能点头或摇头的方案**，
不是文件，也不是一句「好的我明白了」。

- 方案要落到实处，别只报名词。说清三件事：做成什么样（结构/章节/字段）、
  为什么这样而不是另一种、代价是什么（要动哪些地方、丢了什么）。
  三种以上做法时挑两三个说，每种一句取舍就够，不要摊开成菜单。
- 方案要贴着这一轮的实际条件说。手上有材料就先读，读到的具体事实（口径、
  字段名、段落数）写进去；不要凭想象设计一个放之四海皆准的模板。
- 拿不准的地方直接说拿不准，并给一个默认选择（「按 W45 的周数算，不对你改我」）。
- 最后用一句话问他，只问一件事：要不要就这么做。不要列 1/2/3 让他选，
  也不要在结尾追加第二个问题。
- 不调用任何写盘工具。这一轮真的不需要文件——他要的是先看看你的想法。"""


# 商量档对 `TOOL_RULES` 的局部覆盖。必须紧跟在 TOOL_RULES 之后：
# 那一大段里写着「用户要文件就调 doc_generate_report，不能只在回复里给文本」，
# 而这一档要它反着做。两句话隔得远，模型就会挑更具体的那条执行——
# 具体的那条恰好是"要落盘"。与其指望它自己权衡，不如明着作废。
DRAFT_TOOL_OVERRIDE = """# 本回合的工具限制（覆盖「工具约定」里与落盘有关的条目）
- 本回合禁止调用任何写文件工具，即使需求提到产出文件，仅输出方案文本。
- 具体说：不调 doc_generate_report，不调 code_run_python 写盘；需要给结果就写进回复正文，
  结构、字段、取舍写在正文里一样看得清。"""


# 复述进提示词时的字数上限。
# `reading.GOAL_MAX_CHARS` 是第一道闸（解析理解结果时裁），这是第二道：
# `TurnReading` 也能由测试、旧调用方、确定性兜底直接构造，绕过解析层。
# 为什么要卡：复述是「一句话说清他要什么」，写到两百字说明理解层把材料抄回来了；
# 而它贴在用户消息最末尾——最长的那段会盖住目标本身，还会让每轮输入多付一截钱。
RESTATE_PROMPT_LIMIT = 120


def _clip_restate(text: str) -> str:
    """把复述裁到一句能读的长度。超长时保留开头，并用「…」明说没写完。"""
    body = (text or "").strip()
    if len(body) <= RESTATE_PROMPT_LIMIT:
        return body
    return body[:RESTATE_PROMPT_LIMIT].rstrip("，、,;； ") + "…"


REPLY_RULES = """# 收尾答复：像同事说话，别交表格
用户要的是「做成了什么」或者「卡在哪」，不是一份填好的表。用平常说话的口气写：

- 第一句直接说结果：交付了什么（带文件名），或者为什么做不了。
- 需要交代事实，就跟在后面一两句；只有三条以上并列的改动才用列表，一两条用一句话说完。
- 讲结构就把节名念出来（「摘要、进展、数据这几节」），不要用「骨架 / preset / body」这类内部叫法。
- 结尾用一句自然的邀约收住，随场景变（「要只把标题居中，说一声」「行距也能一起调」）。
- 不要写「结论：」「依据：」「下一步：」这类小标题——那读起来像填表，不像对话。

硬约束：
- 不设字数上限，但每句都要有信息。判断标准：删掉这句，他要做的事会不会变？不会就删。
  通常交付一件事三五句能说完；要交代口径、缺失、改动范围时，可以写到十来句，别硬压。
- 结论依据的关键事实必须写在回复里：用了哪几份材料、关键数字、口径差异、改了哪些范围。
  这是「依据」，不是「复述」——不要整段摘抄原文，也不要逐条介绍素材写了什么。
- 不列读过哪些文件（点到的文件名除外）、不报字数、耗时、步骤数、token；
  不解释自己怎么想的（思考过程已单独展示）。
- 不重复用户的要求，不写「我不能编造」这类自我说明，直接说缺什么。
- 有产物时只提一次文件名（《某某.docx》），细节留给文件本身。
- 只有用户必须二选一时才提问，问一句就够，不要列 1/2/3 菜单。

示例（素材与需求不匹配时）：
这份表格算不了同比——只有 3 个月的本期数据，缺去年同月那一列，所以这轮没出文件。
补一份去年同期的表我就重算；或者你回一句「按月环比」，我改做环比。"""


# 所有意图共用的一段：把「接单-交付」纠正成「先对齐、再动手」。
# 紧跟 system.md 注入——那一份通篇是「必须交付文件」的口吻，不紧跟一句纠正，
# 模型听完就开工，商量根本发不起来。
CONSULT_RULES = """# 先对齐，再动手
对面是合作方，不是下单的人。多数时候他想先听你怎么想，而不是马上收到一个文件。

- 遇到这几种情况，先说判断、再给方向，等他挑，这一轮不要产出文件：
  需求有歧义、有几种都说得通的做法、他在问意见（「怎么改」「你觉得」「要不要」）。
  判断写两三句就够，要指出问题在哪（「这两份的统计口径不一致，直接汇总会把 6 月和 7 月混在一起」），
  每个方向各说一句代价，不要只报名字。
- 他已经给了明确做法（「把标题居中」「改成 8 号字」「按第二个来」）时：直接做，别再问一遍。
- 只有缺关键信息、做下去必错时才提问。一次问一件，不要发问卷。
- 动手前用一句话说清你打算干什么、为什么（40 字以内）。这句话会显示成他眼前的「思考」，
  所以要具体（「先看两份的表头对不对得上，对不上就先统一下口径」），
  不要写「我将为您处理」这种空话，也不要复述他的话。
- 中途不必汇报进度；卡住了、或者要换方案，才说一句。
"""


# 一句话到底是在「聊两句」「问点东西」，还是「派活」。
# 这个判定决定三件事：给不给工具、能不能落到文件、要不要按交付的口吻收尾。
# 判错的代价不对称：把派活当成商量，用户再说一遍就行；把商量当成派活，
# 他会收到一份自己没要的 docx——这是最伤的一种错。
# 说话档也能读，但它不需要背整个工具约定。给三行说清读的语义就够：
# 不给这段，它读回来的 `observation.material` 不知道是什么，容易当成报错。
READ_TOOLS_BRIEF = """# 手上能用的读工具
- file_list：看这个会话里有哪些素材。
- file_read：读某个素材的正文，返回的 observation.material 就是正文（超长时只给目录 + 前几块）。
- file_search：在素材里按关键词检索，拿回带 [S3] 编号的原文片段；要引用具体内容就用它。
- 只是聊两句不用读；需要引用具体内容时再读，不要为了显得勤快先读一遍。"""


CHAT_REPLY_RULES = """# 说话方式
这是随口聊几句，不是交作业：
- 怎么想就怎么说。能一句说完就一句，需要多说几句就自然往下说，不用压到某个字数。
- 该给的实在内容别省：一个具体判断、一个他没想到的点、一句提醒，都比空泛的回应有用。
  但不要为了显得周到而重复、客套，或者把一句话拆成三句。
- 不要复述用户的问题，不要写「结论：」「建议：」「步骤如下：」这类小标题。
- 不确定就直说不确定，别绕；做不到就说做不到，别硬凑。
- 上一轮交付过的东西不用再报一遍，也别张口说「我去生成一份」——这一轮你手上没有写文件的工具，说了就是空话。
- 不主动推销功能，不列 1/2/3 菜单，除非用户真的在问该怎么选。"""


class RealEngine:
    name = "real"

    def __init__(
        self,
        tools: Any,
        approval_tools: list[str],
        router: ModelRouter,
        prompt: str = "",
    ) -> None:
        self.tools = tools
        self.approval_tools = approval_tools
        self.router = router
        self.prompt = prompt
        # 单次运行状态（run() 开头重置）
        # 计划只认模型自己写的那份：没有兜底步骤表，也就没有「内核拟好的草稿」
        self._use_model_plan = False
        self._had_rejection = False
        self._stop_reason = "completed"
        self._abort = False
        self._steps = 0
        self._last_provider = ""
        self._last_error: dict[str, Any] | None = None
        self._emitted_text = False
        self._called_tools: set[str] = set()
        self._fallback_actions: list[str] = []
        self._approval_mode = "risky"
        # 这一轮的理解结果。写权限门控要拿它判断「授权到哪一步」，
        # 所以它必须活到工具执行那一刻，不能只在 run() 开头用完就丢。
        self._reading: TurnReading | None = None
        # 本轮被门控拦下的次数。拦到上限就收手，别让模型反复冲同一个门。
        self._write_blocks = 0
        # 拦到上限之后，这一轮的写工具整体关掉：模型换个工具再来一次也是白搭，
        # 而每一次都值得一条日志、一步预算和一次用户等待。
        self._write_disabled = False
        # 最后一次被门控拦下的原因。收尾时要把"为什么没落盘"说清，
        # 而 `_write_blocks` 只记次数不记原因。
        self._last_gate_reason = ""
        # 这一轮是否已经给过一句思考。思考区只留一条——多了就成了流水账，
        # 用户会跳着读，等于没有。
        self._thinking_shown = False

    # ================= 主入口 =================
    async def run(self, ctx: RunContext) -> AsyncIterator[EngineEvent]:
        started = time.perf_counter()
        self._reset(ctx.message)
        self._approval_mode = normalize_approval_mode(ctx.approval_mode)
        tool_ctx = self._tool_context(ctx)
        router = self.router
        router.begin_run()

        def event(name: str, **data: Any) -> dict[str, Any]:
            payload = build_event(ctx.run_id, name, **data)
            if ctx.trace_id:
                payload["trace_id"] = ctx.trace_id
            return payload

        # 没有任何可用供应商：整条运行降级到 MockEngine（事件协议不变）
        if not router.ensure_available():
            async for engine_event in self._run_as_mock(ctx, event):
                yield engine_event
            return

        provider = router.available_provider or ctx.settings.configured_provider
        model = router.model_for(provider)
        ctx.model = model
        self._last_provider = provider
        yield EngineEvent(
            RUN_STARTED,
            event(
                RUN_STARTED,
                thread_id=ctx.thread_id,
                mode=ctx.mode,
                model=model,
                engine=self.name,
                provider=provider,
                started_at=now_iso(),
                degraded=ctx.degraded,
            ),
        )

        # 读懂这一轮要什么。以前这里是关键词判定：人的说法一变形就判错，
        # 而且判错会**同时**关掉工具和档位——「再把 old_weekly.docx 也读出来」
        # 里没有词表里的动作词，就被当成聊天，连读文件的能力都没了。
        # 现在让模型读一遍（`reading.py`），用它的结论决定给多少能力。
        reading = await read_turn(router, ctx)
        intent = reading.intent
        # 门控要用它，且它得活到工具执行的那一刻
        self._reading = reading
        logger.info(
            "本轮理解 stance=%s commitment=%s conf=%.2f source=%s basis=%s",
            reading.stance,
            reading.commitment,
            reading.confidence,
            reading.source,
            reading.basis,
            extra={"event": "turn_reading"},
        )

        # 真缺信息、又没把握：先问一句，这一轮不动手。
        # 猜错要白干一轮、还附赠一份没人要的文件；问一句只要半句话。
        #
        # **那句话必须真的说出去。** 以前这里只发 run.completed：理解层已经想好了
        # 「缺什么、该问什么」，用户却一个字都看不到——他连续发三条「你咋不做修改」
        # 也等不到回应，只会以为程序卡住了。钱花了（理解层那次调用是真金白银）、
        # 判断也做了，唯独最后那半句话掉在地上。这不是「沉默地问」，是没问。
        if reading.needs_confirm:
            # 问句不该为空（`needs_confirm` 的判据就是 question 非空），但这里宁可
            # 说一句通用的，也不允许「什么都不说就结束」——那是最坏的一种失败：
            # 用户既不知道发生了什么，也不知道该补什么。
            question = (reading.question or "").strip() or (
                "这句我还拿不准：具体要动哪份材料、改哪一部分？你说一句我就接着做。"
            )
            async for engine_event in self._stream_text(
                ctx,
                event,
                question,
                self._message_id(ctx, "ask"),
                channel="reply",
            ):
                yield engine_event
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            usage = router.usage_snapshot()
            yield EngineEvent(
                RUN_COMPLETED,
                event(
                    RUN_COMPLETED,
                    status=RunStatus.COMPLETED.value,
                    tokens=int(usage["total_tokens"]),
                    cost_cny=float(usage["cost_cny"]),
                    elapsed_ms=elapsed_ms,
                    artifact_ids=[],
                    approvals=[],
                    degraded=ctx.degraded,
                    engine=self.name,
                    model=ctx.model,
                    provider=self._last_provider,
                    stop_reason="awaiting_user",
                    fallback_actions=[],
                    usage=usage,
                ),
            )
            return

        # 不再由内核先排一份计划、也不再单独跑一次「思考」模型调用：
        # 计划只在模型自己用 todo_write 列出来时才发，思考则是它动手前说的那句话。
        # 内核一旦替它排好 4 步、替它想好一遍，界面上的东西就不再是它真打算干的事。

        messages = self._initial_messages(ctx, intent, reading)
        tools_schema = self._tools_for()
        budget_exceeded = False
        finished_normally = False
        last_text = ""
        no_progress = 0
        last_progress: tuple[Any, ...] | None = None

        # 步数不是给用户的东西，更不该成为「把任务掐断再让用户来推」的理由。
        # 分档步数现在只用来记一条内部跨段日志；主循环跑的是全局 cap，能继续就
        # 继续，直到模型自己给出不带工具的最终答复。保留一个有界上限是防死循环
        # 的工程保险（真实模式下空转会烧钱），它只进日志和 stop_reason，
        # 界面上不出现任何「步数 / 上限 / 预算」字样。
        delivery = reading.delivery
        first_segment = self._max_steps_for(delivery, max(len(ctx.uploads), len(reading.scope)))
        cap = self._max_steps()
        for step in range(1, cap + 1):
            if step == first_segment + 1:
                logger.info(
                    "跨过起步步数，自动续跑不打断 run_id=%s step=%s cap=%s",
                    ctx.run_id,
                    step,
                    cap,
                    extra={"event": "run_auto_continue"},
                )
            self._steps = step
            try:
                result = await router.chat_with_tools(
                    messages,
                    tools=tools_schema,
                    temperature=self.router.settings.model_temperature,
                    max_tokens=self._max_output_tokens(),
                )
            except ModelUnavailableError as exc:
                self._last_error = exc.public()
                logger.warning(
                    "运行中模型不可用，降级收尾 run_id=%s attempts=%s",
                    ctx.run_id,
                    exc.public()["attempts"],
                    extra={"event": "run_model_degraded"},
                )
                async for engine_event in self._degrade_midrun(
                    ctx, event, started, tool_ctx, "model_unavailable"
                ):
                    yield engine_event
                return

            self._last_provider = result.provider
            ctx.model = result.model
            if result.text:
                last_text = result.text
                if result.tool_calls:
                    # 动手前这句话分两种：真的在拿主意（问一句、给两个方向、说没把握），
                    # 还是纯播报（「我先读一下素材」）。
                    # 前者记一条决策行，后者压成一行过程文字——以前一律当「思考」，
                    # 于是每次开工都先冒出一段格式一样的推演，看着像模板在演。
                    line = decision_line(result.text)
                    if line:
                        self._thinking_shown = True
                        async for think_event in self._stream_thinking(
                            ctx,
                            event,
                            line,
                            self._message_id(ctx, f"think{step}"),
                            kind=decision_kind(line),
                        ):
                            yield think_event
                    else:
                        async for note_event in self._stream_text(
                            ctx,
                            event,
                            clamp_line(result.text, PROCESS_NOTE_MAX_CHARS),
                            self._message_id(ctx, f"note{step}"),
                            channel="process",
                        ):
                            yield note_event
                else:
                    # 后面还有工具调用 → 这段只是旁白，收进执行过程；没有工具了 → 这才是正式回复
                    async for engine_event in self._stream_text(
                        ctx,
                        event,
                        result.text,
                        self._message_id(ctx, f"step{step}"),
                        channel="reply",
                    ):
                        yield engine_event

            if not result.tool_calls:
                # 模型给出最终答复，循环结束（兜底交付在循环后统一执行）
                finished_normally = True
                break

            messages.append(self._assistant_message(result))
            async for engine_event in self._execute_tool_calls(
                ctx, tool_ctx, result, messages, step, event
            ):
                yield engine_event
            if self._abort:
                return

            usage = router.usage_snapshot()
            budget = int(usage.get("budget") or TOKEN_BUDGET_PER_RUN)

            # 预算是内部保险丝，不是给用户看的台词。以前这里往聊天流里注入
            # 「已消耗 N tokens，超过预算」，等于把自家成本摊到用户面前还让他
            # 收拾残局。现在只记日志，收尾交给下面「没有正式回复」的兜底。
            #
            # 同一处补空转检测：步数放开后，模型卡在「重复调同一个工具」时
            # 不再有步数替我们刹车。连续几步同样的调用 + 同样的旁白就是卡住了，
            # 继续只会白烧 token。判据看的是**有没有新信息**，不是步数。
            progress = (
                tuple((call.name, repr(call.arguments)) for call in result.tool_calls),
                (result.text or "").strip()[:120],
            )
            if progress == last_progress:
                no_progress += 1
            else:
                no_progress = 0
            last_progress = progress
            if no_progress >= NO_PROGRESS_LIMIT:
                self._stop_reason = "no_progress"
                logger.info(
                    "连续 %s 步没有新进展，提前收尾 run_id=%s step=%s",
                    no_progress,
                    ctx.run_id,
                    step,
                    extra={"event": "run_no_progress"},
                )
                break
            if int(usage["total_tokens"]) > budget:
                budget_exceeded = True
                self._stop_reason = "token_budget"
                logger.info(
                    "运行触及 token 预算，停止继续调用 run_id=%s tokens=%s budget=%s",
                    ctx.run_id,
                    usage["total_tokens"],
                    budget,
                    extra={"event": "run_token_budget", "skip": "no_user_note"},
                )
                break

        if self._abort:
            return

        # 答复落地自检放在兜底之前：检的是模型自己写的那段话，不是内核补的交付说明。
        self._check_grounding(ctx, tool_ctx, last_text)

        # 模型可能"说完就停"（漏产出/漏发送）：内核按任务意图补做，保证主链路交付。
        # 只有真的派了活才需要补：聊天没有产物，单纯读素材也不该被补出一份文件。
        # `reading` 必须带进去——兜底现在要它那一票（见 `_fallback_verdict`）。
        if intent == INTENT_WRITE:
            async for engine_event in self._reliability_fallback(
                ctx, tool_ctx, messages, event, last_text, reading
            ):
                yield engine_event
            if self._abort:
                return

        if not finished_normally and not budget_exceeded and self._stop_reason == "completed":
            self._stop_reason = "max_steps"
            # 到上限只是内部状态，不注入聊天流。用户不该看到「步数用完了」，
            # 更不该被要求「你说下重点改哪儿」——把自家预算变成他的活。
            # 真没正式回复的情况由下面的 `_closing_text` 按「有产物 / 说过话 /
            # 为什么停」处理，那几句话只讲结果和下一步，不讲预算。
            logger.info(
                "运行到全局步数上限 run_id=%s cap=%s artifacts=%s",
                ctx.run_id,
                cap,
                len(tool_ctx.artifact_ids),
                extra={"event": "run_step_cap", "skip": "no_user_note"},
            )

        if not self._emitted_text:
            # 整轮一条正式回复都没有。这时候回哪句话，取决于"为什么没话说"——
            # 而不是只看"有没有说过话"：
            # 有产物 → 报文件名；说过话但只是规划 → 那句话本身是回答，
            # 后面再跟一句为什么停（见 `_closing_note`）；
            # 一声不吭且没有具体原因 → 真故障，直说。
            final_text = self._closing_text(tool_ctx, last_text, delivery)
            async for engine_event in self._stream_text(
                ctx, event, final_text, self._message_id(ctx, "final")
            ):
                yield engine_event

        if intent != INTENT_CHAT:
            self._mark_plan_done(tool_ctx)
            # 只收尾「模型自己排过」的那条计划：没排过就别在结束时凭空补一条，
            # 那样刚聊完的问答末尾会突然多出一块「全部步骤已完成」。
            if self._use_model_plan:
                final_plan = self._current_plan(tool_ctx)
                yield EngineEvent(PLAN_UPDATED, event(PLAN_UPDATED, todos=final_plan))

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        usage = router.usage_snapshot()
        status = RunStatus.REJECTED if self._had_rejection else RunStatus.COMPLETED
        if budget_exceeded:
            self._stop_reason = "token_budget"
        yield EngineEvent(
            RUN_COMPLETED,
            event(
                RUN_COMPLETED,
                status=status.value,
                tokens=int(usage["total_tokens"]),
                cost_cny=float(usage["cost_cny"]),
                elapsed_ms=elapsed_ms,
                artifact_ids=self._live_artifact_ids(ctx, tool_ctx),
                # 字段留着是为了不改事件契约；引擎已经不再发起审批，永远是空的。
                approvals=[],
                degraded=ctx.degraded,
                engine=self.name,
                model=ctx.model,
                provider=self._last_provider,
                stop_reason=self._stop_reason,
                fallback_actions=list(self._fallback_actions),
                usage=usage,
            ),
        )

    # ================= 消息 / 计划 =================
    def _tools_for(self) -> list[dict[str, Any]]:
        """这一轮给模型看哪些工具：**全部**。

        这里曾经按意图裁：聊天一个都不给，商量只给只读的，派活才给写盘工具。
        出发点是对的（工具不在清单里，模型就没有「顺手生成一份」的选项），
        但它把「判断是否准确」变成了安全前提——判断错一次，用户说「读一下」
        连文件都打不开；判断错另一个方向，就多出一份没人要的 docx。

        现在改成「能力全给、权限单管」：工具一直在，能不能落盘由
        `policy.decide_write()` 在真正执行前判断。这样：

        - 判错不会让能力消失（读永远读得到）；
        - 判错也不会让文件落地（写被拦下，改成先给方案 + 问一句）。

        换句话说，把「猜得准」从安全前提降级成体验优化。
        """
        return self.tools.openai_tools()

    def _authorization_note(self, reading: TurnReading | None) -> str:
        """把授权状态写成一句话，贴在 system 末尾。

        这不是权限——权限在门控里。这是让模型**不用试探**就知道边界，
        省掉「它先试着调用一次写工具、被拦、再改口」的那一轮。
        """
        if reading is None:
            return ""
        if reading.commitment == COMMIT_AUTHORIZED:
            return "【这一轮的授权】他已经同意动手，直接做到位，不用再问要不要做。"
        if reading.commitment == COMMIT_PROPOSED:
            return (
                "【这一轮的授权】他还在商量，没有拍板。这一轮不要生成或改动文件："
                "把方案说实在——具体动哪里、动成什么样——让他一眼能判断。"
                "只有缺一样不做就会做错的信息才问他；不要向他要一句确认口令"
                "（「你说就这样我就出」这种话不要出现）。"
            )
        if reading.stance == STANCE_CHAT:
            return "【这一轮的授权】他只是在说话，别主动提生成文件的事。"
        return (
            "【这一轮的授权】他在了解情况或问意见。可以读材料、可以给判断，"
            "但不要生成或改动文件；他要是明显想让你做，先把怎么做说清楚，"
            "真缺信息再问那一件。"
        )

    def _max_steps_for(self, delivery: str, breadth: int) -> int:
        """这一档的**起步步数**（跨过它只记一条内部日志，不再打断任务）。

        主循环现在跑 `_max_steps()` 这个全局上限：以前走到这个数就 exit，还要给
        用户发一句「到步数上限了」，等于把自家预算变成他的活。现在它只用来标记
        「原本的起步预算」，循环会自然续跑，直到模型给出不带工具的最终答复。
        保留分档是为了跨段日志和封顶计算；`breadth` 是本轮要碰的材料份数。

        为什么只读档的起步预算不比交付档紧：只读档不落盘、不动用户文件，多读几步
        的全部代价是几毛钱 token；而它读不完的代价是模型拿前两份的内容把第三份
        「补」出来，也就是把「没读到」写成「没有」。这种错不可回滚，用户没法从
        成稿里看出哪句是补的。所以「便宜的那个档位」不该比「贵的那个」更紧。

        为什么按份数放宽：三份材料只给三步，它读完两份就得开始编第三份。
        为什么 chat 有素材给三步：判成"只是在说话"也可能是判错（「这两份写了啥」
        被判成聊天），两步只够读一份。三步让它至少能读一份再答。

        交付档起步就给满全局预算：写盘那几步不该由素材份数决定——写一份文件和
        改十份文件都只要一步，真正会把步数吃光的是「读」，而读已经能自动续跑。
        """
        cap = self._max_steps()
        if delivery == DELIVERY_CHAT:
            return min(3 if breadth else 2, cap)
        files = max(breadth, 1)
        if delivery == DELIVERY_READ:
            # 每份材料两步（读一次 + 必要时检索/核对），首尾各留一步收尾。
            return min(READ_STEPS_BASE + READ_STEPS_PER_FILE * files, cap)
        if delivery == DELIVERY_DRAFT:
            # 商量档要先把材料读成能写方案的依据，再多一步成文，所以比只读少一档。
            return min(DRAFT_STEPS_BASE + files, cap)
        return cap

    @staticmethod
    def _live_artifact_ids(ctx: RunContext, tool_ctx: Any) -> list[str]:
        """这一轮还剩哪些产物活着。

        模型可能中途把刚写的文件删掉（`file.delete`），同名重写也可能让旧记录退场。
        这些 id 再报给前端，界面上就会多出一张点不开的卡——预览接口查不到记录，
        只能回「产物不存在」。宁可少报一张，也不要在对话里挂一张死链。
        """
        alive: list[str] = []
        seen: set[str] = set()
        for artifact_id in getattr(tool_ctx, "artifact_ids", []):
            if not artifact_id or artifact_id in seen:
                continue
            seen.add(artifact_id)
            try:
                exists = ctx.artifacts.get(artifact_id) is not None
            except Exception:
                exists = True
            if exists:
                alive.append(artifact_id)
        return alive

    @staticmethod
    def _delivery_of(intent: str, reading: TurnReading | None) -> str:
        """这一轮按哪一档交付。**只影响提示词与步数，不影响权限。**

        权限只有一处：`policy.decide_write`。这里多切一刀是为了让提示词不再自相
        矛盾——同一份 system 里既要它「必须交文件」又要它「这一轮别动手」，
        模型只能赌，赌错就是那份没人要的 docx。

        没有 reading 时退回到老三档（测试和旧调用方会这么用）。
        """
        if reading is not None:
            return reading.delivery
        if intent == INTENT_CHAT:
            return DELIVERY_CHAT
        if intent == INTENT_READ:
            return DELIVERY_READ
        return DELIVERY_DELIVER

    def _stable_system(self, ctx: RunContext, delivery: str) -> str:
        """system 的**稳定前缀**：人设 + 本档规则。一轮之内、同类请求之间都不变。

        这半段唯一的作用是给上下文缓存命中——DeepSeek 认的是**前缀**，命中与
        未命中差 50 倍（¥0.02–0.04 vs ¥1–2/百万）。所以这里只许放「按档位固定」
        的内容：加一句依赖本轮消息、素材、理解结果的话，后面全部作废。
        每轮会变的东西一律去 `_turn_tail()`，两处不要混。
        """
        system = self.prompt.strip() or "你是办公助理，先弄清用户要什么，再决定要不要动手。"
        system = f"{system}\n\n{CONSULT_RULES}"
        if delivery == DELIVERY_CHAT:
            # 说话档不背交付架子（产物格式、结论卡）：那些规矩会让回答变成填表。
            # 但读工具在手上，得给三行说清 material 是什么，否则它读回来也不知道怎么用。
            system = f"{system}\n\n{READ_TOOLS_BRIEF}"
            system = f"{system}\n\n{CHAT_REPLY_RULES}"
        elif delivery == DELIVERY_READ:
            # 只是在问、在评价：给读的能力，不给交付的架子。
            system = f"{system}\n\n{TOOL_RULES}"
            system = f"{system}\n\n{READ_REPLY_RULES}"
        elif delivery == DELIVERY_DRAFT:
            # 方向明确但没拍板。这一档以前和交付档共用 DELIVERY_RULES，
            # 于是同一段 system 里一边写着「用户要文件就生成，不能只给文本」，
            # 一边写着「他还在商量，不要生成」——模型只能自己调和，行为就飘了。
            #
            # 光切档还不够：TOOL_RULES 里「用户要文件就调 doc_generate_report」
            # 仍然生效，模型读到「周报」两个字就会照那条办（它读到的是一张检查表，
            # 不是一段需要权衡的建议）。所以紧贴 TOOL_RULES 追加一段局部覆盖，
            # 把这条规矩在本档明确作废。
            system = f"{system}\n\n{TOOL_RULES}"
            system = f"{system}\n\n{DRAFT_TOOL_OVERRIDE}"
            system = f"{system}\n\n{DRAFT_REPLY_RULES}"
        else:
            system = f"{system}\n\n{TOOL_RULES}"
            system = f"{system}\n\n{DELIVERY_RULES}"
            system += (
                f"\n\n【产物格式】{output_format_label(ctx.output_format)}"
                f"（format={ctx.output_format}）"
            )
            # 收尾答复的约束放在稳定段的末尾：越贴近生成位置越管用，前面堆多少规范都压不住
            # 模型「顺手把过程也写一遍」的惯性（第四十九轮：结论动不动三四百字）。
            system = f"{system}\n\n{REPLY_RULES}"
        return system

    def _turn_tail(self, ctx: RunContext, delivery: str, reading: TurnReading | None) -> str:
        """system 的**尾段**：只放每轮都会变的内容，顺序 = 越靠后越贴身。

        ⚠️ 强约束：这是 system 的最后一节，只允许**往这个函数里追加**，
        禁止把这里的内容挪回 `_stable_system()`，也禁止在它之后再拼任何东西。
        理由有两条，踩过才知道疼：

        1. 缓存：这几段每轮都变。它们一旦散落在前面，后面的稳定段全部跟着未命中，
           账单会「贵得不像话」，而排查时几乎看不出来——提示词读起来完全正常。
        2. 冲突：它们都是**本轮**的口径（这一轮有没有素材、这一轮授权到哪一步、
           这一轮的路由规范）。散在中间时，后面又接上「必须交文件」这类固定规矩，
           模型看到的就是两句互相打架的话，只能挑一句执行——这就是「提示词冲突」
           在线上表现为行为忽左忽右的原因。

        尾段内部的顺序也是排过的：先「依据」（有素材才给），再「本门类怎么做」，
        最后是「这一轮授权到哪一步」——离生成最近的那一句，管得最实。
        """
        parts: list[str] = []
        if delivery != DELIVERY_CHAT and ctx.uploads:
            # 只在手上有素材时讲引用。没素材还要求「逐句给依据」，模型会去编依据。
            parts.append(RAG_RULES)
        if delivery == DELIVERY_DELIVER and ctx.prompt_extra.strip():
            # 需求路由的专业规范（文档排版 / 表格清洗 / 比对 …）只在本轮注入。
            parts.append(ctx.prompt_extra.strip())
        if ctx.context_summary.strip():
            # 更早的对话已被压缩成要点：放在历史消息之前，模型才知道「指代的是什么」。
            parts.append(
                f"{ctx.context_summary.strip()}\n"
                "（以上是更早的对话要点，如需细节请向用户确认，不要凭摘要臆造文件内容。）"
            )
        auth_note = self._authorization_note(reading)
        if ctx.delivered and delivery in (DELIVERY_DELIVER, DELIVERY_DRAFT):
            # 用户说「你自己斟酌」时，他要的是这一版继续改，不是再来一份。
            # 模型看不到手上已经有什么，就会从零重做一遍，产物里多出 X(2)、X(3)。
            names = "\n".join(
                f"- {str(item.get('filename', '')).strip()}"
                for item in ctx.delivered[-6:]
                if str(item.get("filename", "")).strip()
            )
            if names:
                parts.append(
                    "【本会话已交付的文件】\n"
                    f"{names}\n"
                    "他说「你自己斟酌 / 你看着办 / 都行」这类话时，指的是在**这些文件的最新一版**"
                    "上继续改：先读它、再改它，落盘沿用同一个文件名；不要从零再生成一份新的，"
                    "也不要另存成 `(2)` 副本。只有他明确要「再来一份新的」时才另存。"
                )
        if auth_note:
            # 放最后一个：它每轮都变，也最需要压住「顺手做一版」的惯性。
            parts.append(auth_note)
        return "\n\n".join(parts)

    def _initial_messages(
        self,
        ctx: RunContext,
        intent: str = INTENT_WRITE,
        reading: TurnReading | None = None,
    ) -> list[dict[str, Any]]:
        delivery = self._delivery_of(intent, reading)
        system = self._stable_system(ctx, delivery)
        tail = self._turn_tail(ctx, delivery, reading)
        if tail:
            system = f"{system}\n\n{tail}"
        # 把「这一轮要的结果」贴在用户消息末尾。system 里那两三千字规则很容易把目标冲淡，
        # 贴在离生成最近的地方最管用；用模型自己的复述，而不是重复用户原话——
        # 原话里往往混着背景和情绪，复述才是它该交付的那个东西。
        goal = ""
        if reading is not None:
            restate = _clip_restate(reading.restate)
            if restate:
                goal = f"\n\n【这一轮要的结果】{restate}"
        if delivery == DELIVERY_CHAT:
            # 说话档连素材清单都不列：列了就等于在提醒它「手上有活要干」。
            # 它手上有 file_list，真需要时自己查。
            user = f"{ctx.message.strip()}{goal}"
        else:
            upload_lines: list[str] = []
            for upload in ctx.uploads:
                state = "已解析" if upload.parsed else "未解析"
                upload_lines.append(f"- {upload.filename}（{upload.chars} 字，{state}）")
            if upload_lines:
                material_block = "【会话素材】\n" + "\n".join(upload_lines)
                if delivery in (DELIVERY_READ, DELIVERY_DRAFT):
                    # 有材料 ≠ 要处理材料。这句话得说出来，否则模型会把清单当任务清单。
                    # 商量档特别需要：它正打算给方案，很容易顺手开始动手。
                    material_block += (
                        "\n（这些是会话里现有的材料，用户可能是在问它们的内容、"
                        "也可能已经在说方向了。这一轮他没让你改、也没让你产出新文件。）"
                    )
            else:
                material_block = (
                    "【会话素材】当前会话没有上传素材；可按模板生成，但需在结论中说明。"
                )
            user = f"{ctx.message.strip()}\n\n{material_block}{goal}"
        return [
            {"role": "system", "content": system},
            # 历史对话：只带「用户说了什么 / 上一轮交付了什么」，中间的工具调用过程不重放
            # （过程对模型没用，重放还容易让它以为工具已经调过、直接跳过执行）。
            *[dict(item) for item in ctx.history],
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _assistant_message(result: ChatResult) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": result.text or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw_arguments
                        or json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in result.tool_calls
            ],
        }

    def _current_plan(self, tool_ctx: ToolContext) -> list[dict[str, Any]]:
        """当前计划：只认模型自己写的那份。

        内核不再有兜底步骤表。以前不管问什么，面板里都是那三四行，
        用户看到的是模板在演，而不是这个人打算怎么干。
        """
        return list(tool_ctx.todos)

    def _mark_plan_done(self, tool_ctx: ToolContext) -> None:
        """收尾：只安顿「正在做的那一步」，不替模型把没做的步骤打勾。

        以前这里把 pending 一律标 completed——界面上永远 4/4 全绿，
        哪怕「回头自检一遍」根本没做。那不是进度，是化妆。
        """
        if not tool_ctx.todos:
            return
        if self._had_rejection:
            for todo in tool_ctx.todos:
                if todo.get("status") in ("pending", "in_progress"):
                    todo["status"] = "cancelled"
            return
        # 正常结束：最后一项正在做的算做完；后面还没开始的一律留在 pending，
        # 让用户看得见「这轮停在哪」。
        for todo in reversed(tool_ctx.todos):
            if todo.get("status") == "in_progress":
                todo["status"] = "completed"
                break

    # ================= 工具调用 =================
    async def _execute_tool_calls(
        self,
        ctx: RunContext,
        tool_ctx: ToolContext,
        result: ChatResult,
        messages: list[dict[str, Any]],
        step: int,
        event: Any,
    ) -> AsyncIterator[EngineEvent]:
        for call in result.tool_calls:
            async for engine_event in self._run_single_tool(
                ctx, tool_ctx, call.name, call.arguments, messages, call.id, step, event
            ):
                yield engine_event
            if self._abort:
                return

    async def _run_single_tool(
        self,
        ctx: RunContext,
        tool_ctx: ToolContext,
        name: str,
        arguments: dict[str, Any],
        messages: list[dict[str, Any]],
        call_id: str,
        step: int,
        event: Any,
    ) -> AsyncIterator[EngineEvent]:
        """执行单个工具（模型 tool_call 与内核兜底共用同一条路径）。"""
        spec = self.tools.resolve(name)
        args = self._clean_args(spec, arguments)
        if spec is None:
            observation = {
                "ok": False,
                "error": {"code": "TOOL_ERROR", "message": f"未注册的工具：{name}"},
            }
            yield EngineEvent(
                TOOL_FINISHED,
                event(
                    TOOL_FINISHED,
                    tool=name,
                    ok=False,
                    risk=Risk.LOW.value,
                    summary=f"未注册的工具：{name}",
                    duration_ms=0,
                    input=sanitize(args),
                    output=observation,
                    artifact_id=None,
                    step=step,
                ),
            )
            messages.append(self._tool_message(call_id, observation))
            return

        # 写权限门控：唯一的关口。它问的是「他到底让你做了没有」——不成立时
        # 这一步直接不做，回一句说明给模型，让它改成先讲打算，而不是把选择权
        # 再抛回给用户（那是两次打扰：先拦一次，再让他点一次「授权」）。
        #
        # 只看**这一次调用会不会动文件**，不看工具名。同一个 `code.run_python`
        # 既能打印 PDF 页数也能生成 PDF：按工具名一刀切，只读也被拦在这道门外，
        # 模型连量个字号都要先证明「他让我动手了」。
        #
        # 原文一起传下去：门控除了看理解层的结论，还要查句子里写着的
        # 「先别 / 我点头了再 / 算了」。那类凭据比模型的判断硬。
        writes = spec.mutates_files(args)

        if writes and self._write_disabled:
            # 本轮已经被拦到上限了，不再放它去撞门：模型会一次次换工具重试，
            # 每次都要走一遍门控、写一条日志、多占一步预算。直接告诉它结束。
            messages.append(
                self._tool_message(
                    call_id,
                    {
                        "ok": False,
                        "skipped": True,
                        "reason": "write_disabled",
                        "message": stop_hint(self._reading or TurnReading()),
                    },
                )
            )
            return

        if writes:
            gate = decide_write(
                spec.risk.value,
                self._reading or TurnReading(),
                message=ctx.message,
                # 效果分档：读 / 写产物 / 动已有文件。三档门槛不同，是这一轮
                # 「门禁和脚本结合」的落点——判的是这一段脚本要干什么，不是
                # 「run_python 这个工具危不危险」。
                effect=spec.effect_kind(args),
                mode=self._approval_mode,
                # 这一轮已经产出过产物 = 他在接着改那一版。改个颜色不该重新授权。
                continuing=bool(tool_ctx.artifact_ids),
            )
            if not gate.allow:
                self._write_blocks += 1
                self._last_gate_reason = gate.reason
                hint = gate.hint
                if self._write_blocks >= MAX_BLOCKS_PER_RUN:
                    # 它明显在反复冲同一个门：把话说明白，别再试工具了。
                    self._write_disabled = True
                    hint = stop_hint(self._reading or TurnReading())
                logger.info(
                    "写操作被门控拦下 tool=%s reason=%s blocks=%s",
                    spec.name,
                    gate.reason,
                    self._write_blocks,
                    extra={"event": "write_blocked", "tool": spec.name},
                )
                # 拦下也要留一张卡。以前这里只回模型一句话、不发事件，
                # 界面上什么都没发生：用户看着"它说要生成"然后凭空开始讲方案，
                # 既不知道是被拦了，也不知道为什么。卡上写清"没执行"和原因。
                yield EngineEvent(
                    TOOL_FINISHED,
                    event(
                        TOOL_FINISHED,
                        tool=spec.name,
                        ok=False,
                        risk=spec.risk.value,
                        summary=f"这一步先没动：{self._gate_card_note(gate.reason)}",
                        duration_ms=0,
                        input=sanitize(args),
                        output={
                            "skipped": True,
                            "reason": "not_authorized",
                            "gate": gate.reason,
                        },
                        artifact_id=None,
                        step=step,
                    ),
                )
                messages.append(
                    self._tool_message(
                        call_id,
                        {
                            "ok": False,
                            "skipped": True,
                            "reason": "not_authorized",
                            "message": hint,
                        },
                    )
                )
                return

        yield EngineEvent(
            TOOL_STARTED,
            event(
                TOOL_STARTED,
                tool=spec.name,
                risk=spec.risk.value,
                input=sanitize(args),
                step=step,
            ),
        )
        tool_started = time.perf_counter()
        # 工具可能一次产出多份文件（code.run_python 的 outputs 是列表），
        # 所以按「本次新登记了哪些产物」发事件，不能只看单个 output["artifact_id"]——
        # 只看它的话，脚本写出的文件用户得刷新页面才能看见。
        artifacts_before = set(tool_ctx.artifact_ids)
        output: dict[str, Any] = {}
        raw_result: dict[str, Any] | None = None
        error: dict[str, str] | None = None
        ok = False
        summary = ""
        try:
            handler_result = await asyncio.to_thread(spec.handler, tool_ctx, **args)
            if inspect.isawaitable(handler_result):
                handler_result = await handler_result
            if not isinstance(handler_result, dict):
                handler_result = {"value": handler_result, "ok": True}
            raw_result = handler_result
            output = {
                key: sanitize(value) for key, value in raw_result.items() if not key.startswith("_")
            }
            ok = bool(raw_result.get("ok", True))
            summary = str(raw_result.get("_summary") or f"已执行 {spec.name}")
        except Exception as exc:  # 工具失败不中断运行
            error = {"code": "TOOL_ERROR", "message": str(exc)[:500] or "工具执行异常"}
            summary = f"工具执行失败：{error['message']}"
            ok = False
            logger.warning(
                "工具执行失败 tool=%s error=%s",
                spec.name,
                error["message"],
                extra={"event": "tool_error", "tool": spec.name},
            )
        duration_ms = int((time.perf_counter() - tool_started) * 1000)
        artifact_id = output.get("artifact_id")
        finished = event(
            TOOL_FINISHED,
            tool=spec.name,
            ok=ok,
            risk=spec.risk.value,
            summary=summary,
            duration_ms=duration_ms,
            input=sanitize(args),
            output=output,
            artifact_id=artifact_id,
            step=step,
        )
        if not ok and error:
            finished["error"] = error
        yield EngineEvent(TOOL_FINISHED, finished)

        # 读完素材后补一句「材料长什么样，所以我按这套写」。这是模型看不见的全貌：
        # 它拿到的是片段，份数/字数/表数/小标题数是脚本数出来的。一轮只补一次，
        # 模型自己已经给过判断就不重复——思考区一多就成了流水账。
        if ok and spec.name == "doc.analyze_material" and not self._thinking_shown:
            fact_line = material_thought(output)
            if fact_line:
                self._thinking_shown = True
                async for think_event in self._stream_thinking(
                    ctx, event, fact_line, self._message_id(ctx, f"thinkfact{step}")
                ):
                    yield think_event

        if not ok and error:
            # 出错是真正的决策点：这一步行不通，接下来得换个做法。
            # 工具卡上只写「失败」，这一句说的是「那我怎么办」——一句话，不摊开。
            async for think_event in self._stream_thinking(
                ctx,
                event,
                tool_failure_line(spec.name, error["message"]),
                self._message_id(ctx, f"thinkerr{call_id}"),
                kind="error",
            ):
                yield think_event

        if ok:
            # 先把标量 artifact_id 发掉（doc.generate_report 这类），再补发本次
            # 新登记、但没出现在 output.artifact_id 里的产物（脚本批量写文件）
            emitted: set[str] = set()
            if artifact_id:
                emitted.add(str(artifact_id))
                async for engine_event in self._artifact_event(ctx, str(artifact_id), event):
                    yield engine_event
            for extra_id in tool_ctx.artifact_ids:
                if extra_id in artifacts_before or extra_id in emitted:
                    continue
                emitted.add(extra_id)
                async for engine_event in self._artifact_event(ctx, extra_id, event):
                    yield engine_event

        self._called_tools.add(spec.name)
        observation = self._observation(output, summary, ok)
        if spec.name == "file.read" and ok and raw_result is not None:
            observation = self._material_observation(
                observation, str(raw_result.get("_material") or "")
            )
        elif spec.name == "file.search" and ok and raw_result is not None:
            observation = self._passage_observation(observation, raw_result)
        messages.append(self._tool_message(call_id, observation))
        # 计划面板只在模型自己写过步骤时存在，且只有它自己更新状态时才重发——
        # 不再由内核按「调了哪个工具」猜进度（读一次文件就勾掉一步，那不是真进度）。
        if spec.name == "todo.write" and tool_ctx.todos:
            self._use_model_plan = True
            yield EngineEvent(PLAN_UPDATED, event(PLAN_UPDATED, todos=self._current_plan(tool_ctx)))

    async def _reliability_fallback(
        self,
        ctx: RunContext,
        tool_ctx: ToolContext,
        messages: list[dict[str, Any]],
        event: Any,
        last_text: str = "",
        reading: TurnReading | None = None,
    ) -> AsyncIterator[EngineEvent]:
        """可靠性兜底：模型「说完就停」且**确实该交付**时，内核补做一次交付动作。

        **两把钥匙同时转到底才补**：话里有一句站得住的动手指令（marker），
        且理解层读出来他确实拍板了（`commitment == authorized`）。

        为什么非得两把：单看任意一把都会误触发，而且都是线上真出过的错——

        - 只有 marker：「就按这个格式改标题」含「就按这个」，「生成吧」也可能出现在
          「先别生成吧」里（位置检查挡掉了一部分，挡不干净）。补一份没人要的 docx。
        - 只有 authorized：「跑个脚本统计字数」同样判成 authorized，于是被补出一份
          周报；「这类材料你打算怎么整理」也可能被读成已经授权。
          这条经验写在旧代码里，现在把它反过来用在门控上。

        `commitment == proposed` 直接跳过：他还在商量，兜底补动作等于替他拍板。
        `none` 同理——连方向都没定，谈不上漏交付。

        补生成的事件与普通工具调用完全一致（tool.started/finished/artifact.ready/approval.required），
        run.completed 追加 fallback_actions 且 stop_reason=fallback。
        """
        allowed, marker, skip = self._fallback_verdict(ctx, last_text, reading)
        if not allowed:
            # marker 一定要写进日志：线上出现「文件乱生成」时，第一个要回答的问题
            # 就是「哪句话被当成了命令」。只留一个 allowed=False 等于什么都没留。
            logger.info(
                "跳过内核兜底 run_id=%s skip=%s marker=%s commitment=%s conf=%.2f",
                ctx.run_id,
                skip,
                marker or "-",
                reading.commitment if reading is not None else "unknown",
                reading.confidence if reading is not None else 0.0,
                extra={
                    "event": _FALLBACK_SKIP_EVENTS.get(skip, "kernel_fallback_skipped"),
                    "skip": skip,
                    "marker": marker,
                },
            )
            return

        template = self._infer_template(ctx.message)
        has_material = bool(tool_ctx.material_text.strip()) or bool(ctx.uploads)
        actions: list[str] = []
        if not tool_ctx.artifact_ids:
            if has_material:
                async for engine_event in self._run_single_tool(
                    ctx,
                    tool_ctx,
                    "doc.generate_report",
                    {
                        "title": self._fallback_title(
                            template,
                            [{"filename": upload.filename} for upload in ctx.uploads],
                        ),
                        "template": template,
                        "format": ctx.output_format,
                    },
                    messages,
                    f"{ctx.run_id}_fb_doc",
                    self._steps + 1,
                    event,
                ):
                    yield engine_event
                if self._abort:
                    return
                if tool_ctx.artifact_ids:
                    actions.append("doc.generate_report")
                    # 先补生成、再说话：这样这一句能带上文件名。
                    # 且只说用户关心的结果——「模型未产出文档、内核补生成」是运行日志，
                    # 混在结论区里只会让人以为文件是凑出来的（第五十轮）。
                    note = self._fallback_note(tool_ctx)
                    async for engine_event in self._stream_text(
                        ctx, event, note, self._message_id(ctx, "fallback_doc")
                    ):
                        yield engine_event
            else:
                logger.info(
                    "任务含文档意图但无素材/无产物，跳过兜底 run_id=%s marker=%s",
                    ctx.run_id,
                    marker,
                    extra={"event": "kernel_fallback_skipped", "marker": marker},
                )

        if actions:
            self._fallback_actions = actions
            self._stop_reason = "fallback"
            logger.info(
                "内核可靠性兜底完成 run_id=%s actions=%s marker=%s",
                ctx.run_id,
                actions,
                marker,
                extra={"event": "kernel_fallback", "marker": marker},
            )

    @staticmethod
    def _fallback_verdict(
        ctx: RunContext, last_text: str, reading: TurnReading | None
    ) -> tuple[bool, str, str]:
        """兜底该不该触发。返回 `(能不能补, 命中的短语, 跳过原因)`。

        三个值都要：`allowed` 决定行为，`marker` 给日志定位是哪句话，`skip` 说明
        是哪一道闸挡下来的——三种跳过（没指令 / 他在商量 / 他说先别）看起来
        完全一样，混在一个布尔值里就没法复盘。
        """
        build_marker, _ = standing_phrase(ctx.message, EXPLICIT_BUILD_MARKERS)
        promise_marker, _ = standing_phrase(last_text, PROMISE_MARKERS)
        marker = build_marker or promise_marker
        if not marker:
            return False, "", "no_marker"
        # 他说过「先别 / 我只是问问 / 我点头了再」时，兜底整条不成立：兜底是替模型
        # 补动作，而这一轮他明确不要动作。放在授权之前看，是因为两者可能同时成立
        # （「先别管格式，直接生成」判成 hold 是误判，但保守方向可以接受；反过来
        # 「先别生成吧，我问问怎么写」被判成 authorized 才是真事故）。
        hold = hold_verdict(ctx.message)
        if hold.value:
            return False, marker, "hold"
        # 模型已经说了「这份素材做不了」时也不补：结论和产物互相打脸，
        # 用户会以为前面那段解释是编的（第五十轮）。
        if model_refused(last_text):
            return False, marker, "model_refused"
        if reading is None:
            # 老调用方 / 测试桩没有理解结果：退回只看 marker。这是唯一一处不叠校验的
            # 路径，运行主链路上 reading 一定有值。
            return True, marker, ""
        if reading.commitment == COMMIT_AUTHORIZED:
            return True, marker, ""
        if reading.commitment == COMMIT_PROPOSED:
            return False, marker, "proposed"
        return False, marker, "no_commit"

    async def _artifact_event(
        self, ctx: RunContext, artifact_id: str, event: Any
    ) -> AsyncIterator[EngineEvent]:
        artifact = ctx.artifacts.get(artifact_id)
        if artifact is None:
            return
        yield EngineEvent(
            ARTIFACT_READY,
            event(
                ARTIFACT_READY,
                artifact_id=artifact.id,
                type=artifact.type,
                filename=artifact.filename,
                size=artifact.size,
                download_url=f"/api/v1/artifacts/{artifact.id}/download",
                preview_url=f"/api/v1/artifacts/{artifact.id}/preview",
                # 与 mock 引擎保持一致：带上素材来源，右栏才能说明这份产物从哪来
                sources=list((artifact.extra or {}).get("sources") or [])[:5],
            ),
        )

    # ================= 降级 / 收尾 =================
    async def _run_as_mock(self, ctx: RunContext, event: Any) -> AsyncIterator[EngineEvent]:
        """模型完全不可用：整条运行交给 MockEngine（跳过其重复的 run.started）。"""
        logger.warning(
            "无可用模型供应商，运行降级 MockEngine run_id=%s",
            ctx.run_id,
            extra={"event": "engine_degraded_mock"},
        )
        ctx.degraded = True
        ctx.mode = "mock"
        ctx.model = "mock-scripted"
        yield EngineEvent(
            RUN_STARTED,
            event(
                RUN_STARTED,
                thread_id=ctx.thread_id,
                mode="mock",
                model="mock-scripted",
                engine="mock",
                started_at=now_iso(),
                degraded=True,
            ),
        )
        mock = MockEngine(self.tools, self.approval_tools, self.prompt)
        async for engine_event in mock.run(ctx):
            if engine_event.event == RUN_STARTED:
                continue
            yield engine_event

    async def _degrade_midrun(
        self,
        ctx: RunContext,
        event: Any,
        started: float,
        tool_ctx: ToolContext,
        reason: str,
    ) -> AsyncIterator[EngineEvent]:
        ctx.degraded = True
        self._stop_reason = reason
        note = "模型服务暂时不可用，本次运行已降级收尾；已完成的工具结果与产物保留。"
        async for engine_event in self._stream_text(
            ctx, event, note, self._message_id(ctx, "degrade")
        ):
            yield engine_event
        self._mark_plan_done(tool_ctx)
        if self._use_model_plan:
            yield EngineEvent(PLAN_UPDATED, event(PLAN_UPDATED, todos=self._current_plan(tool_ctx)))
        usage = self.router.usage_snapshot()
        yield EngineEvent(
            RUN_COMPLETED,
            event(
                RUN_COMPLETED,
                status=RunStatus.COMPLETED.value,
                tokens=int(usage["total_tokens"]),
                cost_cny=float(usage["cost_cny"]),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                artifact_ids=self._live_artifact_ids(ctx, tool_ctx),
                # 字段留着是为了不改事件契约；引擎已经不再发起审批，永远是空的。
                approvals=[],
                degraded=True,
                engine=self.name,
                model=ctx.model,
                provider=self._last_provider,
                stop_reason=reason,
                usage=usage,
                error=self._last_error,
            ),
        )

    # ================= 流式文本 =================
    async def _stream_thinking(
        self,
        ctx: RunContext,
        event: Any,
        text: str,
        message_id: str = "m_think",
        kind: str = "decision",
    ) -> AsyncIterator[EngineEvent]:
        """决策行（沿用 thinking.* 事件，语义已经变了）。

        以前这里是「每轮必跑一次的思考环节」，内容由一次独立调用生成，四平八稳；
        现在只在三种场合出现，且永远只有一句话：
        - decision：它在两个方向之间挑了一个，或者停下等你点头；
        - error：某一步没成，得换个法子；
        - ask：需要你补一个信息才能往下走。
        一句话之外的东西不进思考区——那属于执行过程。
        """
        text = clamp_line(text, DECISION_LINE_MAX_CHARS)
        if not text:
            return
        started = time.perf_counter()
        for index, start in enumerate(range(0, len(text), THINKING_CHUNK_CHARS)):
            yield EngineEvent(
                THINKING_DELTA,
                event(
                    THINKING_DELTA,
                    message_id=message_id,
                    delta=text[start : start + THINKING_CHUNK_CHARS],
                    index=index,
                    kind=kind,
                ),
            )
            await asyncio.sleep(THINKING_CHUNK_DELAY_SECONDS)
        yield EngineEvent(
            THINKING_COMPLETED,
            event(
                THINKING_COMPLETED,
                message_id=message_id,
                content=text,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                kind=kind,
            ),
        )

    async def _stream_text(
        self,
        ctx: RunContext,
        event: Any,
        text: str,
        message_id: str,
        channel: str = "reply",
    ) -> AsyncIterator[EngineEvent]:
        """`channel`：reply = 对话里的正式回复；process = 中间旁白，前端收进「执行过程」。

        一次运行会有多轮「说话 → 调工具」，全按气泡渲染时每段都带一遍头像和名字，
        一屏下来光看「Office Agent」就翻了两屏。中间旁白只该在执行过程里留一行。
        """
        text = (text or "").strip()
        if not text:
            return
        starts = list(range(0, len(text), RESPONSE_CHUNK_CHARS))
        # 片子越多间隔越短，总时长不超过预算；一句话就一片时直接给足 24ms。
        delay = min(TEXT_CHUNK_DELAY_SECONDS, TEXT_REVEAL_BUDGET_SECONDS / max(1, len(starts)))
        for index, start in enumerate(starts):
            yield EngineEvent(
                MESSAGE_DELTA,
                event(
                    MESSAGE_DELTA,
                    message_id=message_id,
                    delta=text[start : start + RESPONSE_CHUNK_CHARS],
                    index=index,
                    channel=channel,
                ),
            )
            await asyncio.sleep(delay)
        yield EngineEvent(
            MESSAGE_COMPLETED,
            event(
                MESSAGE_COMPLETED,
                message_id=message_id,
                content=text,
                channel=channel,
            ),
        )
        # 旁白（后面还要调工具的中间发言）不落库：重开会话只该看到问题和最终回复
        if channel == "reply":
            ctx.messages.add(
                Message(
                    id=message_id,
                    thread_id=ctx.thread_id,
                    role=MessageRole.ASSISTANT.value,
                    content=text,
                    run_id=ctx.run_id,
                    created_at=now_iso(),
                )
            )
        # 只有「正式回复」才算说过话：旁白只是执行过程里的一行，用户并没有收到回答。
        # （以前这里不看 channel，于是「只说了句旁白就收尾」的运行会连一个气泡都没有。）
        if channel == "reply":
            self._emitted_text = True

    # ================= 内部工具 =================
    def _reset(self, message: str = "") -> None:
        # 这一轮不预设任何步骤：计划要么由模型写，要么就没有。
        # （原来这里是 plan_steps_for(message)——按关键词挑一套模板，
        #   在模型开口之前就把「这活分几步」定死了。）
        _ = message
        self._use_model_plan = False
        self._had_rejection = False
        self._stop_reason = "completed"
        self._abort = False
        self._steps = 0
        self._last_provider = ""
        self._last_error = None
        self._emitted_text = False
        self._called_tools = set()
        self._fallback_actions = []
        self._approval_mode = "risky"
        self._reading = None
        self._write_blocks = 0
        self._write_disabled = False
        self._last_gate_reason = ""
        self._thinking_shown = False

    def _tool_context(self, ctx: RunContext) -> ToolContext:
        """本轮的工具上下文。

        `reading` 必须跟着走：子智能体（doc_agent）在内部直接调 handler，
        不经过 `_run_single_tool` 那道门。把这一轮的读法放进上下文，
        子智能体就能用同一个 `policy.decide_write` 自己过一遍门，
        而不是靠「反正外面拦过了」这种假设——假设在重构一次之后就没了。
        """
        return ToolContext(
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            trace_id=ctx.trace_id,
            settings=ctx.settings,
            artifacts=ctx.artifacts,
            storage=ctx.storage,
            mode=ctx.mode,
            degraded=ctx.degraded,
            uploads=list(ctx.uploads),
            reading=self._reading,
            message=ctx.message,
            doc_style=dict(ctx.doc_style or {}),
        )

    def _max_steps(self) -> int:
        configured = int(self.router.settings.model_max_steps or MAX_STEPS_HARD_LIMIT)
        return max(1, min(configured, MAX_STEPS_HARD_LIMIT))

    def _max_output_tokens(self) -> int | None:
        """单次调用的输出上限；`None` = 不限制。

        默认**不设上限**（`MODEL_MAX_TOKENS=0`）：请求里不带这个字段，由模型按自身
        输出上限决定，思考用多少是多少。理由有两条，都是实测出来的：

        1. 它是**上限不是花费**。按实际输出计费，卡紧几乎不省钱，却会实实在在毁掉
           答案：`deepseek-flash` 默认开着 thinking，2000 时一次带推理的调用会先把
           额度花在 reasoning 上、正文变成空串（provider 日志 `正文为空但
           finish_reason=length`），再放大到 6000 重试——白等 30 秒还多付一次调用。
        2. 「你能想多久」这个信息内核没有。内核说 120 字、说 8000 token，都只是替
           模型做它更有条件做的判断。

        留一个正数还能当硬顶用（多租户限流、成本兜底等场景），这时按原样下发。
        """
        configured = int(self.router.settings.model_max_tokens or 0)
        if configured <= 0:
            return None
        return max(1024, configured)

    def _clean_args(self, spec: ToolSpec | None, arguments: dict[str, Any]) -> dict[str, Any]:
        """只保留 schema 声明的参数，容忍模型多传字段。"""
        if spec is None:
            return dict(arguments or {})
        properties = spec.schema.get("properties") or {}
        return {
            key: value
            for key, value in (arguments or {}).items()
            if key in properties or not properties
        }

    @staticmethod
    def _message_id(ctx: RunContext, suffix: str) -> str:
        """消息主键全局唯一：run_id 唯一，避免跨 run/会话 UNIQUE 冲突。"""
        return f"{ctx.run_id}_m{suffix}"

    @staticmethod
    def _tool_message(call_id: str, observation: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(observation, ensure_ascii=False, default=str),
        }

    @staticmethod
    def _infer_template(message: str) -> str:
        text = message or ""
        if "纪要" in text:
            return "meeting"
        if "摘要" in text or "总结" in text:
            return "summary"
        return "weekly"

    @staticmethod
    def _fallback_title(template: str, sources: list[dict[str, Any]] | None = None) -> str:
        """兜底交付用的标题：优先「素材名 · 类型」，一天出多份也分得清。"""
        return doc_title_for(template, sources)

    @staticmethod
    def _fallback_note(tool_ctx: ToolContext) -> str:
        """兜底补生成后的交付说明：只说结果（文件名 + 去哪拿），不解释内核动作。"""
        filename = ""
        if tool_ctx.artifact_ids:
            artifact = tool_ctx.artifacts.get(tool_ctx.artifact_ids[-1])
            if artifact:
                filename = f"《{artifact.filename}》"
        return f"已补生成{filename}，可在产物中心下载。"

    def _closing_text(self, tool_ctx: ToolContext, last_text: str, delivery: str) -> str:
        """整轮没有正式回复时，回一句真正说到点上的话。

        以前这里只分「有产物 / 说过话 / 真故障」三档，问题出在第二档：模型中途那句
        「我先读一下这两份材料」被原样当成结论交出去，用户会以为事情做完了，而实际上
        运行是被上限或空转截断的。所以现在改成：**说过的话照给，再补一句为什么停**。

        补的这句来自 `_closing_note()`，只讲结果和下一步，不出现步数 / 预算 / token
        之类的自家计量——那些只进日志（见 `run_step_cap` / `run_token_budget`）。
        """
        if tool_ctx.artifact_ids:
            artifact = tool_ctx.artifacts.get(tool_ctx.artifact_ids[-1])
            name = f"《{artifact.filename}》" if artifact else "文件"
            return f"做好了，{name}已经放进产物仓库。"

        said = (last_text or "").strip()
        note = self._closing_note()
        if said and note:
            return f"{said}\n\n{note}"
        if said:
            return said
        if note:
            return note
        if delivery == DELIVERY_CHAT:
            return "这次没接上话，你再说一遍？"
        return "这轮没能给出答复，麻烦重试一次。"

    def _closing_note(self) -> str:
        """为什么这一轮停在这儿——按"最具体的原因"挑一句，用户看了能接着往下走。

        优先级不是随意的：门控没放行 → 停的原因，因为越靠前的越"不是他的问题"，
        也越需要他知道下一步该做什么。
        """
        if self._write_blocks:
            return self._gate_note(self._last_gate_reason)
        if self._stop_reason == "no_progress":
            # 空转是唯一值得明说的原因：它指向"你的要求还不够具体"，是可操作的。
            return (
                "我在同一个动作上绕了几圈没往前走，先停在这儿。"
                "你说一句具体要改哪里——哪份文件、哪一段——我接着做。"
            )
        if self._stop_reason in ("token_budget", "max_steps"):
            return "这一轮还没收尾就停下了，剩下的没做完。你说一声「继续」，我从这儿接着往下做。"
        return ""

    @staticmethod
    def _gate_note(reason: str) -> str:
        """门控拦下时给用户的那一句。

        和 `policy.reason_label()` 不能混用：那个是第三人称（"他说了这一轮先别动手"），
        贴在工具卡上合适，放进对话正文就变成了背后议论用户。
        """
        if reason == REASON_HOLD:
            return "你说了这一轮先别动，所以我没有落盘。等你说了再动。"
        if reason == REASON_RETRACTED:
            return "你已经把这件事收回去了，所以我没有落盘。"
        if reason == REASON_LONG_MESSAGE:
            return "消息太长，我没敢直接动手落盘。你挑一句最要紧的，我按那句做。"
        if reason == REASON_UNSURE:
            return "我还没把握你要动的是哪一部分，所以没有落盘。你指一下文件或段落，我立刻做。"
        if reason == REASON_DESTRUCTIVE:
            return (
                "这一步会动到已有的文件（删、改名、覆盖），你没说要动它们，所以我没动。"
                "要删哪份、改哪份，说一声我就做。"
            )
        return "这一轮我先把打算说清楚，没有落盘——你点头，我就动手。"

    @staticmethod
    def _gate_card_note(reason: str) -> str:
        """工具卡上那一行：为什么这一步没动。

        不用 `reason_label()`：那是第三人称（"他还在商量"），可看卡的人就是"他"。
        也不用 `_gate_note()`：那是正文里的一整段话，卡上只有一行的位置。
        措辞一律不用「失败」——这一步根本没跑，谈不上成败。
        """
        if reason == REASON_HOLD:
            return "你说了先别动"
        if reason == REASON_RETRACTED:
            return "你已经撤回了"
        if reason == REASON_LONG_MESSAGE:
            return "消息太长，先确认再动"
        if reason == REASON_UNSURE:
            return "没把握你要动哪一部分"
        if reason == REASON_DESTRUCTIVE:
            return "这一步会动到已有文件，你没说要动"
        return "还没听到你说动手"

    def _check_grounding(self, ctx: RunContext, tool_ctx: ToolContext, text: str) -> None:
        """答复里出现的数字，能不能在素材里找到出处。只记日志，不改答复。

        数字是唯一能机器判定的那类幻觉：措辞上的夸大（「略有下降」写成「显著下降」）
        判不了，但「提升 12%」里的 12 有没有出处，是确定的事实。这条日志是给回归
        看的——引入检索之后模型还在不在编数字，一眼就能翻出来。
        """
        body = (text or "").strip()
        if not body or not tool_ctx.material_sources:
            return
        unverified = unsupported_facts(body, tool_ctx.material_sources)
        if not unverified:
            return
        logger.warning(
            "答复里有 %d 处数字在素材中找不到出处 run_id=%s values=%s",
            len(unverified),
            ctx.run_id,
            [item["value"] for item in unverified[:6]],
            extra={"event": "grounding_unverified", "run_id": ctx.run_id},
        )

    def _material_observation(self, base: dict[str, Any], material: str) -> dict[str, Any]:
        """把 file.read 的正文（`_material`）注入模型观察；超长截断并标注。"""
        text = (material or "").strip()
        if not text:
            return base
        truncated = len(text) > MATERIAL_OBSERVATION_LIMIT
        shown = text
        if truncated:
            cut = text.rfind("\n\n", 0, MATERIAL_OBSERVATION_LIMIT)
            if cut < MATERIAL_OBSERVATION_LIMIT // 2:
                cut = MATERIAL_OBSERVATION_LIMIT
            shown = text[:cut]
        observation: dict[str, Any] = dict(base)
        observation["material"] = shown
        observation["material_chars"] = len(text)
        observation["material_truncated"] = truncated
        if truncated:
            # 以前这里写「可再次调用 file_read 并指定 files 分文件读取」——单份文件
            # 本身就超限时，再读一次还是同一个开头，这句话等于没给出口。
            observation["material_notice"] = (
                f"素材正文共 {len(text)} 字，本次只注入了前 {len(shown)} 字；"
                "其余内容用 file_search 按问题检索（或 file_read 指定 block_ids），"
                "不要因为没看到就当成素材里没有。"
            )
        else:
            observation["material_notice"] = "以上为素材正文，请基于正文写作，不得编造。"
        return observation

    def _passage_observation(
        self, base: dict[str, Any], raw_result: dict[str, Any]
    ) -> dict[str, Any]:
        """把检索片段整段注入观察，不走 4000 字的通用截断。"""
        passages = str(raw_result.get("_passages") or "").strip()
        if not passages:
            return base
        if len(passages) > PASSAGE_OBSERVATION_LIMIT:
            passages = (
                passages[:PASSAGE_OBSERVATION_LIMIT]
                + "\n…（片段过长已截断：减小 top_k，或把问题问得更具体再查一次）"
            )
        observation = dict(base)
        observation["match"] = str(raw_result.get("match") or "")
        observation["passages"] = passages
        observation["passages_notice"] = (
            "每段开头的 [S3] 是引用编号。写结论时在句末标上；"
            "只能用这里出现过的内容，这里没有的不要补。"
        )
        return observation

    @staticmethod
    def _observation(output: dict[str, Any], summary: str, ok: bool) -> dict[str, Any]:
        observed: dict[str, Any] = {"ok": ok, "summary": summary, **output}
        raw = json.dumps(observed, ensure_ascii=False, default=str)
        if len(raw) <= OBSERVATION_LIMIT_CHARS:
            return observed
        return {
            "ok": ok,
            "summary": summary,
            "truncated": True,
            "preview": raw[:OBSERVATION_LIMIT_CHARS],
        }
