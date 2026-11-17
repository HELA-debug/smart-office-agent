"""RealEngine：真实模型 ReAct 工具循环（计划书第 7 章 7.1 / 7.3 / 7.5 / 7.9）。

循环：system prompt + 工具 JSON Schema（由 ToolSpec 自动生成）
  -> 模型决策（文本 + tool_calls）
  -> 内核执行工具（带 ToolContext / 审批 / 超时保护）
  -> 观察结果回填 messages
  -> 再决策，直到模型不再调用工具 / 达到步数上限 / token 预算耗尽。

事件协议与 MockEngine 完全一致（core/events.py v1.1），只追加字段：
run.started（provider）、tool.started（step）、run.completed（provider/model/engine/usage/stop_reason）。

保护机制（计划书表 7-1）：
- 最大步数 12；单次模型超时由 httpx 超时控制；token 预算 200k / 运行；
- 工具失败转结构化观察，不中断主流程；高风险工具暂停等待审批（超时 180s 转 run.failed）；
- 所有供应商不可用：运行前降级 MockEngine（run.started 标 degraded=true）；运行中失败则降级收尾。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from ..core.events import (
    APPROVAL_REQUIRED,
    ARTIFACT_READY,
    HEARTBEAT,
    MESSAGE_COMPLETED,
    MESSAGE_DELTA,
    PLAN_UPDATED,
    RUN_COMPLETED,
    RUN_FAILED,
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
from ..domain.enums import Decision, MessageRole, Risk, RunStatus
from ..tools.builtin.doc import doc_title_for
from ..tools.registry import ToolContext, ToolSpec
from .engine_protocol import (
    EngineEvent,
    RunContext,
    needs_approval,
    normalize_approval_mode,
)
from .mock_engine import MockEngine
from .model_router import ChatResult, ModelRouter, ModelUnavailableError

logger = get_logger("app.agents.real_engine")

MAX_STEPS_HARD_LIMIT = 12
OBSERVATION_LIMIT_CHARS = 1800
# file.read 的正文观察上限：足够写 600 字周报，又不至于撑爆上下文
MATERIAL_OBSERVATION_LIMIT = 7000
RESPONSE_CHUNK_CHARS = 12
THINKING_CHUNK_CHARS = 12
# 思考内容按字数分片下发，片间留一点间隔：模型真在推理时用户才看得到「在想」，
# 一次性刷完会显得比人还快、反而不可信（第十二轮反馈）。
THINKING_CHUNK_DELAY_SECONDS = 0.035
THINK_THOUGHT_MAX_TOKENS = 360
TOKEN_BUDGET_PER_RUN = 200_000

# 任务意图识别（仅用于"模型漏做时内核兜底"，不改变模型自主决策）
DOC_INTENT_KEYWORDS = ("周报", "纪要", "报告", "文档", "整理", "撰写", "生成", "摘要")

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

# 兜底步骤表：模型还没写 todo 时先顶一阵。
# 以前这里写死「读素材 / 理结构 / 出产物」三步，不管用户问什么都是这三行，
# 看着就像模板在演。现在按用户到底要干什么挑一组，措辞也跟着换——
# 排版任务不该冒出「生成报告产物」，闲聊也不该演一遍流水线。
PLAN_FORMAT: tuple[tuple[str, str], ...] = (
    ("t1", "先看清原稿现在的样子"),
    ("t2", "定下要动的格式项"),
    ("t3", "改完逐处核对"),
)
PLAN_DOC: tuple[tuple[str, str], ...] = (
    ("t1", "读素材，挑出能用的事实"),
    ("t2", "搭个提纲"),
    ("t3", "按提纲写成稿"),
    ("t4", "回头自检一遍"),
)
PLAN_EXTRACT: tuple[tuple[str, str], ...] = (
    ("t1", "找齐相关材料"),
    ("t2", "抽出关键信息"),
    ("t3", "整理成能直接用的结果"),
)
PLAN_CODE: tuple[tuple[str, str], ...] = (
    ("t1", "看清现状和报错"),
    ("t2", "定位到具体那一处"),
    ("t3", "改掉并验证"),
)
PLAN_ANSWER: tuple[tuple[str, str], ...] = (
    ("t1", "弄清你到底在问什么"),
    ("t2", "给结论，再补必要的解释"),
)

_PLAN_KEYWORDS: tuple[tuple[tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        ("排版", "格式", "行距", "字体", "字号", "居中", "页边距", "缩进", "单倍", "样式"),
        PLAN_FORMAT,
    ),
    (("脚本", "代码", "python", "报错", "bug", "异常", "调试", "函数"), PLAN_CODE),
    (
        ("周报", "纪要", "报告", "总结", "汇报", "方案", "文档", "起草", "写一份", "写一篇"),
        PLAN_DOC,
    ),
    (("汇总", "提取", "整理成", "清单", "对比", "要点", "归纳"), PLAN_EXTRACT),
)


def plan_steps_for(message: str) -> tuple[tuple[str, str], ...]:
    """按任务类型挑一组步骤。

    只做「像人一样先想清楚要几步」的最低成本实现：命中哪类关键词就走哪套，
    都不命中就当问答处理——问答不需要演三步流水线。
    """
    text = (message or "").lower()
    for keywords, steps in _PLAN_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return steps
    return PLAN_ANSWER


TOOL_RULES = """# 工具调用约定
- 工具函数名中的点已改为下划线：file_list、file_read、doc_generate_report、code_run_python、todo_write、todo_list、file_delete。
- file_read 的返回 observation 中 `material` 字段就是素材正文（超长时会截断并带 material_notice）；必须基于该正文写作，不得编造。
- 计划（todo_write）跟着任务走：2–5 条，措辞写这一步具体做什么（「把行距统一成 1.5」而不是「处理文档」），
  简单问答不必写计划。不要套用固定三步：排版任务不该出现「生成报告」，纯问答不该出现「读取素材」。
  中途发现原计划不对就重写 todo_write，不必硬凑已完成。
- 任务要求"生成/整理/撰写/周报/纪要/报告/文档"时，**必须调用 doc_generate_report 产出文件**（template=weekly/meeting/summary），不能只在回复里给文本。
- doc_generate_report 的 `format` 必须使用【产物格式】中指定的格式（用户已在界面选择，默认与素材同格式），用户明确要求其他格式时才改用用户格式。
- doc_generate_report 属高风险动作：内核会先暂停等待用户审批，批准后才真正写盘，被拒绝时本轮不产生文件。
- 需要改写既有文档、按表格汇总或做模板做不到的格式加工时，调用 code_run_python：脚本从 $OA_INPUT_DIR 读素材（这是目录，你点名的文件已按原文件名复制进去，`glob.glob(os.path.join(os.environ["OA_INPUT_DIR"], "*.docx"))` 即可），$OA_INPUTS 是 JSON 清单（含 filename/path/ext），**不是目录、不能拿它拼路径**；产物写入 $OA_OUTPUT_DIR，执行后自动登记。该工具同样先审批。
- 四个工具库的函数都接受「对象或文件路径」：直接 `read_report(src)`、`apply_body(src)` 传路径也行，不要先自己 Document(src) 再传错对象；不确定参数时先打印 `inspect.signature(函数名)` 确认，不要猜关键字参数名。
- 处理 .docx 时工作目录已预置 docx_utils.py：脚本开头写 `from docx_utils import *`，用 set_page / apply_body / apply_headings / set_para / add_table_simple / replace_text / backup / read_report，不要自己拼 w:eastAsia、表框线这类 XML。
- 处理表格用 xlsx_utils（read_report 先体检、sheet_records 读成记录、write_table/append_records 写、group_sum 分组汇总、add_total_row 加合计），不要现场拼 openpyxl 样式对象。
- 处理 PDF 用 pdf_utils（read_report 先看页数/加密/是否扫描件、extract_pages 取文本、make_pdf 生成中文 PDF、merge_pdfs/split_pdf/watermark 做拼接），扫描件不要假装读到了文本。
- 处理纯文本（.txt / 粘贴进来的内容）用 text_utils（read_text 自动识别 UTF-8/GBK/UTF-16、heading_tree 看结构、md_table 生成表格、md_to_docx 重排成 Word）。
- 改既有文档遵守四条：先 read_report 看现状、backup 出备份、只动用户点名的范围（未点名的段落/样式/页眉页脚不动）、保存后打印改动摘要（改了哪些段落/样式/表格与替换次数）。
- 每次先看上一次工具返回结果再决定下一步，不要假设工具成功；工具失败时按错误信息调整，不要编造。
- 回复使用中文；收尾答复按文末【收尾答复】的结论卡写，引用素材时标注文件名。"""

REPLY_RULES = """# 收尾答复：像同事说话，别交表格
用户要的是「做成了什么」或者「卡在哪」，不是一份三段式报告。用平常说话的口气写：

- 第一句直接说结果：交付了什么（带文件名），或者为什么做不了。
- 需要交代事实，就跟在后面一两句；只有三条以上并列的改动才用列表，一两条用一句话说完。
- 结尾用一句自然的邀约收住，随场景变（「要只把标题居中，说一声」「行距也能一起调」）。
- 不要写「结论：」「依据：」「下一步：」这类小标题——那读起来像填表，不像对话。

硬约束：
- 全文 120 字左右；超了先删解释，最后才动第一句的结果。
- 不复述素材内容、不摘抄原文、不逐条介绍素材写了什么、不列读过哪些文件。
- 不报字数、耗时、步骤数、token；不解释自己怎么想的（思考过程已单独展示）。
- 不重复用户的要求，不写「我不能编造」这类自我说明，直接说缺什么。
- 有产物时只提一次文件名（《某某.docx》），细节留给文件本身。
- 只有用户必须二选一时才提问，问一句就够，不要列 1/2/3 菜单。

示例（素材与需求不匹配时）：
这份表格算不了同比——只有 3 个月的本期数据，缺去年同月那一列，所以这轮没出文件。
补一份去年同期的表我就重算；或者你回一句「按月环比」，我改做环比。"""


def output_format_label(fmt: str) -> str:
    """产物格式展示名（docx -> DOCX）。"""
    from ..tools.builtin.doc import OUTPUT_FORMATS

    return OUTPUT_FORMATS.get(fmt, {}).get("label", fmt.upper())


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
        self._kernel_status: dict[str, str] = {}
        self._plan_steps: tuple[tuple[str, str], ...] = PLAN_ANSWER
        self._use_model_plan = False
        self._had_rejection = False
        self._stop_reason = "completed"
        self._abort = False
        self._approvals: list[dict[str, Any]] = []
        self._steps = 0
        self._last_provider = ""
        self._last_error: dict[str, Any] | None = None
        self._emitted_text = False
        self._approval_rejected = False
        self._called_tools: set[str] = set()
        self._fallback_actions: list[str] = []
        self._approval_mode = "risky"
        # 本次运行的用量计：run() 开头由 router.begin_run() 换来新的。
        # 单独存一份引用是为了「运行被取消」时也能取到已消耗的量——取消发生在
        # 另一个协程里，靠 contextvar 取可能拿不到本次运行的这一只。
        self._meter: Any = None

    # ================= 主入口 =================
    async def run(self, ctx: RunContext) -> AsyncIterator[EngineEvent]:
        started = time.perf_counter()
        self._reset(ctx.message)
        self._approval_mode = normalize_approval_mode(ctx.approval_mode)
        tool_ctx = self._tool_context(ctx)
        router = self.router
        self._meter = router.begin_run()

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

        initial_plan = self._kernel_plan({self._plan_steps[0][0]: "in_progress"})
        yield EngineEvent(PLAN_UPDATED, event(PLAN_UPDATED, todos=initial_plan))

        # v1.2：先输出思考过程（执行规划），再进入工具循环，与对话产品「先想后答」一致。
        # 思考内容由模型现场写（不是写死的模板），拿不到模型时才退回一句兜底。
        plan_thought = await self._compose_thought(ctx)
        async for think_event in self._stream_thinking(ctx, event, plan_thought):
            yield think_event

        messages = self._initial_messages(ctx)
        tools_schema = self.tools.openai_tools()
        budget_exceeded = False
        finished_normally = False
        last_text = ""

        max_steps = self._max_steps()
        for step in range(1, max_steps + 1):
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
                # 后面还有工具调用 → 这段只是旁白，收进执行过程；没有工具了 → 这才是正式回复
                async for engine_event in self._stream_text(
                    ctx,
                    event,
                    result.text,
                    self._message_id(ctx, f"step{step}"),
                    channel="process" if result.tool_calls else "reply",
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
            if int(usage["total_tokens"]) > budget:
                budget_exceeded = True
                self._stop_reason = "token_budget"
                note = (
                    f"本次运行已消耗 {usage['total_tokens']} tokens，"
                    f"超过预算 {budget}，已停止继续调用模型。"
                )
                async for engine_event in self._stream_text(
                    ctx, event, note, self._message_id(ctx, "budget")
                ):
                    yield engine_event
                break

        if self._abort:
            return

        # 模型可能"说完就停"（漏产出/漏发送）：内核按任务意图补做，保证主链路交付
        async for engine_event in self._reliability_fallback(
            ctx, tool_ctx, messages, event, last_text
        ):
            yield engine_event
        if self._abort:
            return

        if not finished_normally and not budget_exceeded and self._stop_reason == "completed":
            self._stop_reason = "max_steps"
            note = f"已达到最大步数 {max_steps}，返回已完成部分；你可以继续追问以便接着处理。"
            async for engine_event in self._stream_text(
                ctx, event, note, self._message_id(ctx, "maxsteps")
            ):
                yield engine_event

        if not self._emitted_text and not last_text:
            async for engine_event in self._stream_text(
                ctx, event, "任务处理完成。", self._message_id(ctx, "final")
            ):
                yield engine_event

        self._mark_plan_done(tool_ctx)
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
                artifact_ids=list(tool_ctx.artifact_ids),
                approvals=list(self._approvals),
                degraded=ctx.degraded,
                engine=self.name,
                model=ctx.model,
                provider=self._last_provider,
                stop_reason=self._stop_reason,
                fallback_actions=list(self._fallback_actions),
                usage=usage,
            ),
        )

    def usage_snapshot(self) -> dict[str, Any]:
        """本次运行到目前为止的用量（供取消/中断路径落库）。

        正常结束时用量跟着 RUN_COMPLETED 事件走；运行被取消时没有那个事件，
        若这里不给出快照，这次调用花掉的钱就会在本地账本里凭空消失，
        而供应商那边照扣——正是「用量对不上」最难解释的一种。
        """
        if self._meter is not None:
            return self._meter.as_dict()
        return self.router.usage_snapshot()

    # ================= 消息 / 计划 =================
    def _initial_messages(self, ctx: RunContext) -> list[dict[str, Any]]:
        # 提示词顺序按「缓存友好」排：稳定内容全放前面，易变的（需求路由规范、历史摘要）
        # 放最后。DeepSeek 的上下文缓存认的是**前缀**，前缀一变整段就按未命中收费
        # （¥1–2/百万），而命中只要 ¥0.02–0.04——差 50 倍。把每轮都会变的内容插在中间，
        # 等于把后面几段稳定内容一起拖成未命中，账单自然「贵得不像话」。
        system = self.prompt.strip() or "你是办公助理，目标是把任务做完并交付文件。"
        system = f"{system}\n\n{TOOL_RULES}"
        system += (
            f"\n\n【产物格式】{output_format_label(ctx.output_format)}"
            f"（format={ctx.output_format}）"
        )
        # 收尾答复的约束放在稳定段的末尾：越贴近生成位置越管用，前面堆多少规范都压不住
        # 模型「顺手把过程也写一遍」的惯性（第四十九轮：结论动不动三四百字）。
        system = f"{system}\n\n{REPLY_RULES}"
        if ctx.prompt_extra.strip():
            # 需求路由的专业规范（文档排版 / 表格清洗 / 比对 …）只在本轮注入
            system = f"{system}\n\n{ctx.prompt_extra.strip()}"
        if ctx.context_summary.strip():
            # 更早的对话已被压缩成要点：放在历史消息之前，模型才知道「指代的是什么」
            system = (
                f"{system}\n\n{ctx.context_summary.strip()}\n"
                "（以上是更早的对话要点，如需细节请向用户确认，不要凭摘要臆造文件内容。）"
            )
        upload_lines: list[str] = []
        for upload in ctx.uploads:
            state = "已解析" if upload.parsed else "未解析"
            upload_lines.append(f"- {upload.filename}（{upload.chars} 字，{state}）")
        if upload_lines:
            material_block = "【会话素材】\n" + "\n".join(upload_lines)
        else:
            material_block = "【会话素材】当前会话没有上传素材；可按模板生成，但需在结论中说明。"
        user = f"{ctx.message.strip()}\n\n{material_block}"
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

    def _kernel_plan(self, statuses: dict[str, str] | None = None) -> list[dict[str, str]]:
        statuses = statuses or {}
        steps = self._plan_steps or PLAN_ANSWER
        self._kernel_status = {
            tid: statuses.get(tid, self._kernel_status.get(tid, "pending")) for tid, _ in steps
        }
        return [
            {"id": tid, "content": content, "status": self._kernel_status.get(tid, "pending")}
            for tid, content in steps
        ]

    def _current_plan(self, tool_ctx: ToolContext) -> list[dict[str, Any]]:
        if self._use_model_plan and tool_ctx.todos:
            return list(tool_ctx.todos)
        return self._kernel_plan()

    def _mark_plan_done(self, tool_ctx: ToolContext) -> None:
        if self._use_model_plan and tool_ctx.todos:
            terminal = "cancelled" if self._had_rejection else "completed"
            for todo in tool_ctx.todos:
                if todo.get("status") in ("pending", "in_progress"):
                    todo["status"] = terminal
            return
        for tid, _ in self._plan_steps:
            if self._kernel_status.get(tid) in ("pending", "in_progress"):
                self._kernel_status[tid] = "completed"

    def _advance_plan(self, tool: str, ok: bool) -> None:
        """按「做到哪一步了」推进，而不是按工具名硬编码。

        步骤数现在跟着任务走（3 步的排版、4 步的文档、2 步的问答），
        再按 t1/t2/t3 对应某个工具就会错位。
        """
        if tool == "todo.write":
            self._use_model_plan = True
            return
        if not ok or self._use_model_plan:
            return
        ids = [tid for tid, _ in self._plan_steps]
        if not ids:
            return
        # 交付物已经落地：后面的步骤不必再逐条演，直接收口
        if tool in ("doc.generate_report", "code.run_python"):
            for tid in ids:
                if self._kernel_status.get(tid) != "cancelled":
                    self._kernel_status[tid] = "completed"
            return
        done = False
        for tid in ids:
            if self._kernel_status.get(tid) == "in_progress":
                self._kernel_status[tid] = "completed"
                done = True
                break
        if not done:
            for tid in ids:
                if self._kernel_status.get(tid, "pending") == "pending":
                    self._kernel_status[tid] = "completed"
                    break
        for tid in ids:
            if self._kernel_status.get(tid, "pending") == "pending":
                self._kernel_status[tid] = "in_progress"
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

        if self._needs_approval(spec):
            async for engine_event in self._approval_flow(ctx, spec, args, step, event):
                yield engine_event
            if self._abort:
                return
            if self._approval_rejected:
                self._approval_rejected = False
                self._called_tools.add(spec.name)
                messages.append(
                    self._tool_message(
                        call_id,
                        {
                            "ok": False,
                            "skipped": True,
                            "reason": "approval_rejected",
                            "message": "用户拒绝了该工具执行，请调整计划或跳过该动作。",
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

        self._advance_plan(spec.name, ok)
        self._called_tools.add(spec.name)
        observation = self._observation(output, summary, ok)
        if spec.name == "file.read" and ok and raw_result is not None:
            observation = self._material_observation(
                observation, str(raw_result.get("_material") or "")
            )
        messages.append(self._tool_message(call_id, observation))
        if self._use_model_plan or spec.name in (
            "file.read",
            "file.list",
            "doc.generate_report",
            "code.run_python",
            "file.delete",
            "todo.write",
        ):
            yield EngineEvent(PLAN_UPDATED, event(PLAN_UPDATED, todos=self._current_plan(tool_ctx)))

    async def _reliability_fallback(
        self,
        ctx: RunContext,
        tool_ctx: ToolContext,
        messages: list[dict[str, Any]],
        event: Any,
        last_text: str = "",
    ) -> AsyncIterator[EngineEvent]:
        """可靠性兜底：模型"说完就停"时，内核按任务意图补做交付动作。

        - 任务含文档意图 + 无 artifact + 已读到素材 -> 补 doc.generate_report（走审批）。
        - 模型已经明说「做不了/缺要素」时不补：结论说没产出、下面又冒出一份文件，
          用户只会觉得前面那段是白说的。
        兜底事件与普通工具调用完全一致（tool.started/tool.finished/artifact.ready/approval.required），
        run.completed 追加 fallback_actions 且 stop_reason=fallback。
        """
        actions: list[str] = []
        template = self._infer_template(ctx.message)
        has_material = bool(tool_ctx.material_text.strip()) or bool(ctx.uploads)
        if self._model_refused(last_text):
            logger.info(
                "模型已明确说明做不了，跳过兜底 run_id=%s",
                ctx.run_id,
                extra={"event": "kernel_fallback_skipped_refused"},
            )
        elif self._has_intent(ctx.message, DOC_INTENT_KEYWORDS) and not tool_ctx.artifact_ids:
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
                    "任务含文档意图但无素材/无产物，跳过兜底 run_id=%s",
                    ctx.run_id,
                    extra={"event": "kernel_fallback_skipped"},
                )

        if actions:
            self._fallback_actions = actions
            self._stop_reason = "fallback"
            logger.info(
                "内核可靠性兜底完成 run_id=%s actions=%s",
                ctx.run_id,
                actions,
                extra={"event": "kernel_fallback"},
            )

    def _needs_approval(self, spec: Any) -> bool:
        return needs_approval(
            mode=self._approval_mode,
            tool_name=spec.name,
            risk=spec.risk.value,
            approval_tools=self.approval_tools,
        )

    async def _approval_flow(
        self,
        ctx: RunContext,
        spec: ToolSpec,
        args: dict[str, Any],
        step: int,
        event: Any,
    ) -> AsyncIterator[EngineEvent]:
        """高风险工具：approval.required -> 暂停等待决议（心跳保活）。"""
        preview: dict[str, Any] = {
            "tool": spec.name,
            "args": sanitize(args),
            "impact": "高风险动作，执行前需要用户确认",
        }
        if spec.name == "doc.generate_report":
            preview = {
                "title": str(args.get("title", "")),
                "template": str(args.get("template", "weekly")),
                "format": str(args.get("format", "")),
                "impact": "将生成文件并写入产物目录（可在产物中心下载）",
            }
        approval = await ctx.approval_gate.create(
            ctx.thread_id, ctx.run_id, spec.name, preview, {"args": sanitize(args)}
        )
        self._approval_rejected = False
        yield EngineEvent(
            APPROVAL_REQUIRED,
            event(
                APPROVAL_REQUIRED,
                approval_id=approval.id,
                tool=spec.name,
                risk=spec.risk.value,
                message=f"即将执行 {spec.name}，请确认后继续",
                preview=preview,
                step=step,
            ),
        )
        decision: Decision | None = None
        async for waited, is_heartbeat in self._wait_for_approval(ctx, approval.id):
            if is_heartbeat:
                yield EngineEvent(HEARTBEAT, event(HEARTBEAT, heartbeat=True))
            else:
                decision = waited
        elapsed_ms = 0
        if decision is None:
            self._abort = True
            self._stop_reason = "approval_timeout"
            yield EngineEvent(
                RUN_FAILED,
                event(
                    RUN_FAILED,
                    error={
                        "code": "APPROVAL_TIMEOUT",
                        "message": (
                            f"审批超过 {int(ctx.settings.approval_timeout_seconds)} 秒未处理，"
                            "运行已终止"
                        ),
                        "retryable": True,
                    },
                    degraded=ctx.degraded,
                    elapsed_ms=elapsed_ms,
                ),
            )
            return
        self._approvals.append(
            {"approval_id": approval.id, "tool": spec.name, "decision": decision.value}
        )
        if decision is Decision.REJECTED:
            self._approval_rejected = True
            self._had_rejection = True
            yield EngineEvent(
                TOOL_FINISHED,
                event(
                    TOOL_FINISHED,
                    tool=spec.name,
                    ok=False,
                    risk=spec.risk.value,
                    summary="用户拒绝了本次工具执行，已跳过",
                    duration_ms=0,
                    input=sanitize(args),
                    output={"skipped": True, "reason": "approval_rejected"},
                    artifact_id=None,
                    error={"code": "TOOL_ERROR", "message": "用户拒绝执行，已跳过"},
                    step=step,
                ),
            )
            self._advance_plan(spec.name, False)

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
                artifact_ids=list(tool_ctx.artifact_ids),
                approvals=list(self._approvals),
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
    ) -> AsyncIterator[EngineEvent]:
        """思考过程流（v1.2）：流式下发推理/规划内容。"""
        text = (text or "").strip()
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
            ),
        )

    async def _compose_thought(self, ctx: RunContext) -> str:
        """让模型先写一段真正的「想」：看什么、抓什么、怎么组织、注意什么。

        这一段会以 thinking.* 事件流式展示，内容是真的推理，而不是固定模板；
        模型不可用时退回一句可读的兜底，保证界面不空着。
        """
        materials = "、".join(upload.filename for upload in ctx.uploads[:6]) or "（无素材）"
        prompt = (
            "先在心里过一遍再动手，想到什么写什么——事情简单就两三行，别为了凑结构硬写。\n"
            "可以想的：这活儿真正的交付物是什么、你凭什么这么判断；手上材料够不够、缺的那块怎么办；"
            "打算怎么下手、哪里可能卡住；有没有更省事的路子。\n"
            "直接写思考过程，不要寒暄、不要输出成品、不要重复用户原话，也不要列「第一步第二步」的模板。\n\n"
            f"用户需求：{ctx.message[:600]}\n"
            f"可用素材：{materials}\n"
            f"目标产物格式：{ctx.output_format}"
        )
        fallback = (
            f"先把需求拆开看：{ctx.message[:80]}。"
            f"手上有 {len(ctx.uploads)} 份素材、目标产物是 {ctx.output_format}；"
            f"大致按「{' → '.join(content for _, content in self._plan_steps)}」走。"
        )
        try:
            result = await self.router.chat_with_tools(
                [
                    {
                        "role": "system",
                        "content": "你是文档 Agent 的思考阶段，只输出简短的推理与计划。",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                temperature=0.4,
                max_tokens=THINK_THOUGHT_MAX_TOKENS,
            )
        except ModelUnavailableError:
            return fallback
        except Exception as exc:  # 思考阶段失败不该挡住主流程
            logger.warning("思考阶段调用失败，改用兜底文案：%s", exc)
            return fallback
        text = (result.text or "").strip()
        self._last_provider = result.provider
        return text or fallback

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
        for index, start in enumerate(range(0, len(text), RESPONSE_CHUNK_CHARS)):
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
            await asyncio.sleep(0)
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
        self._emitted_text = True

    # ================= 内部工具 =================
    def _reset(self, message: str = "") -> None:
        self._plan_steps = plan_steps_for(message)
        self._kernel_status = {tid: "pending" for tid, _ in self._plan_steps}
        self._use_model_plan = False
        self._had_rejection = False
        self._stop_reason = "completed"
        self._abort = False
        self._approvals = []
        self._steps = 0
        self._last_provider = ""
        self._last_error = None
        self._emitted_text = False
        self._approval_rejected = False
        self._called_tools = set()
        self._fallback_actions = []
        self._approval_mode = "risky"

    @staticmethod
    def _tool_context(ctx: RunContext) -> ToolContext:
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
        )

    def _max_steps(self) -> int:
        configured = int(self.router.settings.model_max_steps or MAX_STEPS_HARD_LIMIT)
        return max(1, min(configured, MAX_STEPS_HARD_LIMIT))

    def _max_output_tokens(self) -> int:
        return max(256, min(int(self.router.settings.model_max_tokens or 2000), 4000))

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
    def _has_intent(message: str, keywords: tuple[str, ...]) -> bool:
        text = message or ""
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _model_refused(text: str) -> bool:
        """模型是否已明确说「这件事做不了」。

        只在兜底前用：模型说做不了、内核却补生成文件，两条消息自相矛盾，
        用户会以为前面那段解释是编的（第五十轮）。
        """
        body = text or ""
        return any(marker in body for marker in MODEL_REFUSAL_MARKERS)

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
            observation["material_notice"] = (
                f"素材正文共 {len(text)} 字，已注入前 {len(shown)} 字（已截断）；"
                "如需完整内容可再次调用 file_read 并指定 files 分文件读取。"
            )
        else:
            observation["material_notice"] = "以上为素材正文，请基于正文写作，不得编造。"
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

    async def _wait_for_approval(
        self, ctx: RunContext, approval_id: str
    ) -> AsyncIterator[tuple[Decision | None, bool]]:
        """等待审批决议；每 15s 产出一个心跳标记，最终产出 (decision, False)。"""
        timeout = float(ctx.settings.approval_timeout_seconds)
        deadline = time.monotonic() + max(1.0, timeout)
        pending: asyncio.Task[Decision | None] = asyncio.create_task(
            ctx.approval_gate.wait(approval_id, timeout)
        )
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield None, False
                    return
                done, _ = await asyncio.wait({pending}, timeout=min(15.0, remaining))
                if pending in done:
                    yield pending.result(), False
                    return
                yield None, True
        finally:
            if not pending.done():
                pending.cancel()
