"""MockEngine：确定性主链路（与 v0.1 事件顺序完全一致）。

事件顺序：
run.started -> thinking.delta* -> thinking.completed -> message.delta*
-> message.completed -> plan.updated(4 条，逐步更新)
-> tool.finished(file.list) -> tool.finished(file.read) -> tool.finished(doc.generate_report)
-> artifact.ready -> plan.updated
-> message.delta* -> message.completed -> run.completed

真实模型（B4）只替换本类的 _enrich 钩子/执行体，事件协议不变。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import AsyncIterator
from typing import Any

from ..core.events import (
    ARTIFACT_READY,
    MESSAGE_COMPLETED,
    MESSAGE_DELTA,
    PLAN_UPDATED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    THINKING_COMPLETED,
    THINKING_DELTA,
    TOOL_FINISHED,
    build_event,
)
from ..core.logging import get_logger
from ..core.security import sanitize
from ..core.utils import count_chars, new_id, now_iso
from ..domain.entities import Message
from ..domain.enums import MessageRole, Risk, RunStatus
from ..domain.formats import output_format_label
from ..tools.builtin.doc import doc_title_for
from ..tools.registry import ToolContext, ToolSpec
from .engine_protocol import EngineEvent, RunContext
from .intent import INTENT_CHAT, INTENT_READ, INTENT_WRITE
from .reading import fallback_reading

logger = get_logger("app.agents.mock_engine")

PLAN_TEMPLATE = [
    ("t1", "读取上传材料"),
    ("t2", "脚本解析素材结构"),
    ("t3", "按素材成文并生成产物"),
]

SUBAGENT_DOC = {
    "id": "doc_agent",
    "name": "文档智能体",
    "role": "读取素材、按模板成文、生成报告文件",
}

"""成文模板判定用到的关键词：用户在消息里点名要周报/报告时才优先周报。"""
WEEKLY_REQUEST_WORDS = ("周报", "日报", "月报", "报告")

"""演示模式选脚本用的提示词。

**这不是意图判断**，只是给预录脚本挑一段：真实引擎那套判断在 `reading.py`，
有上下文、有授权字段、有门控兜底。这里判错最多是演示脚本选得不对，
不会影响任何真实链路，也不会写进真实模型的提示词。
"""
_DEMO_WORK_HINTS: tuple[str, ...] = (
    "生成",
    "做一份",
    "做一版",
    "做一个",
    "整理",
    "汇总",
    "合并",
    "导出",
    "排版",
    "改一下",
    "改成",
    "周报",
    "日报",
    "月报",
    "报告",
    "文档",
    "表格",
)
_DEMO_READ_HINTS: tuple[str, ...] = (
    "讲了什么",
    "说了什么",
    "写了什么",
    "看看",
    "看一下",
    "读一下",
    "内容",
    "有哪些",
    "分析",
    "对比",
    "比较",
    "是什么",
    "多少",
)


# 产物格式展示名只有一处定义（domain/formats.py），这里只做本地别名，
# 免得演示引擎与真实引擎在审批卡上显示成两个名字。
format_label = output_format_label


class MockEngine:
    name = "mock"

    def __init__(self, tools: Any, approval_tools: list[str], prompt: str = ""):
        self.tools = tools
        self.approval_tools = approval_tools
        self.prompt = prompt

    # ---------- 可被子类覆盖的扩展钩子 ----------
    async def _enrich(self, ctx: RunContext, tool_ctx: ToolContext, title: str) -> None:
        """真实模型生成摘要正文；mock 不做事。"""

    # ---------- 主链路 ----------
    async def run(self, ctx: RunContext) -> AsyncIterator[EngineEvent]:
        started = time.perf_counter()
        speed = float(ctx.settings.mock_model_speed) if ctx.mode == "mock" else 0.0
        tool_ctx = ToolContext(
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            trace_id=ctx.trace_id,
            settings=ctx.settings,
            artifacts=ctx.artifacts,
            storage=ctx.storage,
            mode=ctx.mode,
            degraded=ctx.degraded,
            uploads=list(ctx.uploads),
            doc_style=dict(ctx.doc_style or {}),
        )
        token_chars = 0

        def event(name: str, **data: Any) -> dict[str, Any]:
            payload = build_event(ctx.run_id, name, **data)
            if ctx.trace_id:
                payload["trace_id"] = ctx.trace_id
            return payload

        yield EngineEvent(
            RUN_STARTED,
            event(
                RUN_STARTED,
                thread_id=ctx.thread_id,
                mode=ctx.mode,
                model=ctx.model,
                engine=self.name,
                started_at=now_iso(),
                degraded=ctx.degraded,
            ),
        )

        # 演示模式没有模型可问，只能按「这段话像要东西还是像在问」挑一段脚本。
        # **这不是意图判断**——真实引擎的判断在 reading.py 里，有上下文、有授权字段。
        # 这里只是决定放哪段录像，判错了最多是演示脚本选得不对。
        reading = fallback_reading(ctx.message)
        intent = reading.intent
        text_lower = (ctx.message or "").lower()
        asks = any(hint in text_lower for hint in _DEMO_READ_HINTS)
        wants = any(hint in text_lower for hint in _DEMO_WORK_HINTS)
        if intent != INTENT_CHAT and wants and not asks:
            intent = INTENT_WRITE

        # 演示引擎没有判断力：原来它对任何输入都跑同一套脚本——「你好」也能把
        # 四份素材读一遍、再生成一份没人要的文档。现在按意图收住：
        # 聊天只回话，问内容只读，派活才走下面那套完整脚本。
        if intent == INTENT_CHAT:
            text = (
                "你好。先把话说清楚：现在是演示模式，我跑的是固定脚本，"
                "回的话都是预设的，不会真的跟你对话。"
                "把右上角切成真实模型，我就能正常应答了。"
            )
            async for item in self._reply_only(
                ctx, event, speed, text, started, token_chars=len(text)
            ):
                yield item
            return

        if intent == INTENT_READ:
            list_data, _ = await self._call_tool(ctx, event, tool_ctx, "file.list", {})
            yield EngineEvent(TOOL_FINISHED, list_data)
            await self._pause(speed, 2)
            read_data, _ = await self._call_tool(ctx, event, tool_ctx, "file.read", {})
            yield EngineEvent(TOOL_FINISHED, read_data)
            material = (tool_ctx.material_text or "").strip()
            if material:
                snippet = " ".join(material.split())[:140]
                text = f"演示模式只能把原文开头贴给你，真正的归纳要切到真实模型才有：\n\n{snippet}…"
            else:
                text = "这个会话里还没有可读的素材。"
            async for item in self._reply_only(
                ctx, event, speed, text, started, token_chars=len(text)
            ):
                yield item
            return

        # 演示模式不再先念一遍「先看什么、再抓什么」：那段固定推演是真的定式，
        # 真人不会每次开工都复述一遍方法论。开场那句交代已经走 channel=process，
        # 决策行只留给真正需要判断的地方（模板怎么选）。

        opening = (
            "我先把素材读出来、让脚本过一遍结构（段数、字数、标题层级、图片和表格），"
            "再看它适不适合套周报；"
            f"生成 {format_label(ctx.output_format)} 前会停下来，等你确认写入产物目录。"
        )
        if ctx.degraded:
            opening += "（模型不可用，已切换演示模式）"
        # 旁白走 channel=process：前端收进「执行过程」，不单独占一个气泡；
        # 也不落 messages 表——重开会话时只该看到「你的问题 + 最终回复」。
        async for delta_event in self._stream_message(
            ctx, event, opening, speed, "m_open", channel="process"
        ):
            yield delta_event
        token_chars += count_chars(opening)

        yield EngineEvent(
            PLAN_UPDATED, event(PLAN_UPDATED, todos=self._plan(tool_ctx, {"t1": "in_progress"}))
        )
        await self._pause(speed, 2)

        list_data, _ = await self._call_tool(ctx, event, tool_ctx, "file.list", {})
        yield EngineEvent(TOOL_FINISHED, list_data)
        await self._pause(speed, 2)

        yield EngineEvent(
            PLAN_UPDATED,
            event(
                PLAN_UPDATED, todos=self._plan(tool_ctx, {"t1": "completed", "t2": "in_progress"})
            ),
        )

        read_data, _ = await self._call_tool(
            ctx, event, tool_ctx, "file.read", {}, subagent_status="running"
        )
        yield EngineEvent(TOOL_FINISHED, read_data)
        await self._pause(speed, 2)

        # 脚本体检：真跑 python 子进程（python-docx / openpyxl / pypdf）读结构。
        # 只读、不写盘，所以不触发审批；成文时的段数/字数/图片/图注都来自这里。
        facts: dict[str, Any] = {}
        if ctx.uploads:
            facts_data, facts_result = await self._call_tool(
                ctx, event, tool_ctx, "doc.analyze_material", {}
            )
            yield EngineEvent(TOOL_FINISHED, facts_data)
            await self._pause(speed, 2)
            if facts_data.get("ok"):
                facts = {
                    "files": facts_result.get("files") or [],
                    "totals": facts_result.get("totals") or {},
                    "signals": facts_result.get("signals") or {},
                }

        template, title = self._decide_template(ctx, facts)

        # 读到真实结构之后再想一次：这回讲的是「为什么用这个模板」，不是套话
        async for think_event in self._stream_thinking(
            ctx,
            event,
            speed,
            message_id="m_think_facts",
            thought=self._facts_thought(facts, template),
            kind="decision",
        ):
            yield think_event

        # 「脚本解析完成：…」这段旁白删掉了：内容已经落在 doc.analyze_material 的
        # 工具卡片里（份数 / 段落 / 字数 / 图片），换个模板的理由也在上面那次思考里。
        # 一次运行只留一条正式回复，中间过程由「执行过程」折叠条承载。

        if ctx.mode == "real":
            await self._enrich(ctx, tool_ctx, title)

        yield EngineEvent(
            PLAN_UPDATED,
            event(
                PLAN_UPDATED,
                todos=self._plan(
                    tool_ctx, {"t1": "completed", "t2": "completed", "t3": "in_progress"}
                ),
            ),
        )

        doc_args = {"title": title, "template": template, "format": ctx.output_format}
        if facts:
            # 体检结果走上下文而不是入参：它只是给成文用的中间数据，
            # 灌进 tool 入参会把事件体积撑大好几倍（每个文件还带原文样例）
            tool_ctx.material_facts = facts
        # 以前这里会先挂起等审批。卡片这一层已经整个拿掉了：写产物是这一轮的
        # 正事，内核按「他让你动手了没有」逐次判，不再把人拉进来点按钮。
        approvals_record: list[dict[str, str]] = []
        doc_data, doc_result = await self._call_tool(
            ctx,
            event,
            tool_ctx,
            "doc.generate_report",
            doc_args,
            subagent_status="done",
        )
        yield EngineEvent(TOOL_FINISHED, doc_data)

        artifact = None
        if doc_result.get("artifact_id"):
            artifact = ctx.artifacts.get(str(doc_result["artifact_id"]))
        if artifact is None:
            elapsed = int((time.perf_counter() - started) * 1000)
            yield EngineEvent(
                RUN_FAILED,
                event(
                    RUN_FAILED,
                    error={
                        "code": "TOOL_ERROR",
                        "message": "文档生成失败，无法继续",
                        "retryable": True,
                    },
                    degraded=ctx.degraded,
                    elapsed_ms=elapsed,
                ),
            )
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
                sources=list((artifact.extra or {}).get("sources") or [])[:5],
            ),
        )
        conclusion = (
            f"{'摘要' if template == 'summary' else '周报'}已生成，可在产物中心下载。"
            f"产物：{artifact.filename}"
        )
        status = RunStatus.COMPLETED
        plan_statuses = {"t3": "completed"}

        if ctx.degraded:
            conclusion += "（本次运行使用演示模式）"

        yield EngineEvent(
            PLAN_UPDATED,
            event(
                PLAN_UPDATED,
                todos=self._plan(
                    tool_ctx,
                    {"t1": "completed", "t2": "completed", **plan_statuses},
                ),
            ),
        )

        # 审批之后的「二次思考」删掉了：那只是把「核对结果、整理结论」念一遍，
        # 用户真正要看的是下面那份文件到底成没成。

        async for delta_event in self._stream_message(ctx, event, conclusion, speed, "m_done"):
            yield delta_event
        token_chars += count_chars(conclusion)
        ctx.messages.add(
            Message(
                id=new_id("m"),
                thread_id=ctx.thread_id,
                role=MessageRole.ASSISTANT.value,
                content=conclusion,
                run_id=ctx.run_id,
                created_at=now_iso(),
            )
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        tokens = max(320, token_chars // 2 + 200 * (len(tool_ctx.artifact_ids) + 1))
        # mock 不调外部模型，一分钱都不花。以前这里按 7.5 元/百万 tokens 编了个金额，
        # 审计里就出现「本地跑出来的账单」，让人拿去和供应商控制台对账——必然对不上。
        cost = 0.0
        yield EngineEvent(
            RUN_COMPLETED,
            event(
                RUN_COMPLETED,
                status=status.value,
                tokens=tokens,
                cost_cny=cost,
                elapsed_ms=elapsed_ms,
                artifact_ids=list(tool_ctx.artifact_ids),
                approvals=approvals_record,
                degraded=ctx.degraded,
                engine=self.name,
                model=ctx.model,
                usage={
                    "input_tokens": max(1, token_chars // 3),
                    "output_tokens": max(1, token_chars - token_chars // 3),
                    "total_tokens": tokens,
                },
            ),
        )

    # ---------- 模板判定与「怎么想」 ----------
    def _decide_template(self, ctx: RunContext, facts: dict[str, Any]) -> tuple[str, str]:
        """素材里有周报要素才用周报骨架；没有就换摘要，别硬把散文凑成周报。

        标题一律带素材名（`24级软件工程（智慧能源）· 素材摘要`），
        否则一天出几份全是「素材摘要（日期）」，产物列表里根本分不出哪份是哪份。
        """
        sources = [{"filename": upload.filename} for upload in ctx.uploads]
        if facts and not (facts.get("signals") or {}).get("weekly"):
            return "summary", doc_title_for("summary", sources)
        return "weekly", doc_title_for("weekly", sources)

    def _facts_thought(self, facts: dict[str, Any], template: str) -> str:
        """一句「为什么这么定」。

        以前这里会摊开「几份素材、多少段、多少字、图注写了什么、按什么骨架写」，
        四五行走下来像在读体检报告；那些数字在 doc.analyze_material 的卡片上都有，
        这里只需要说清「我为什么选了这条路」。
        """
        totals = facts.get("totals") or {}
        if template == "summary":
            line = "没有进展/数据/计划这些周报要素，硬套只能编，改按文件摘要走"
        else:
            line = "素材里有进展和计划，按周报骨架写"
        if totals.get("images"):
            line += "，图按图注放回原位"
        return line

    # ---------- 内部工具 ----------
    async def _stream_thinking(
        self,
        ctx: RunContext,
        event: Any,
        speed: float,
        message_id: str = "m_think",
        thought: str | None = None,
        kind: str = "decision",
    ) -> AsyncIterator[EngineEvent]:
        """决策行（沿用 thinking.*）：和真实引擎一样，一次只给一句话。

        演示模式以前是「每次开工先念四段方法论」，正是用户说的那种定式；
        现在这里只承载「为什么这么定」的一句话，其余过程都落在工具卡片上。
        """
        if thought is None:
            thought = "素材不多，先按最省事的路子来"
        thought = " ".join((thought or "").split())[:64]
        if not thought:
            return
        started = time.perf_counter()
        step = 4
        for index, start in enumerate(range(0, len(thought), step)):
            yield EngineEvent(
                THINKING_DELTA,
                event(
                    THINKING_DELTA,
                    message_id=message_id,
                    delta=thought[start : start + step],
                    index=index,
                    kind=kind,
                ),
            )
            # 一句话不该演太久：按片给一点节奏就够了
            if speed > 0:
                await asyncio.sleep(speed * 1.2)
        yield EngineEvent(
            THINKING_COMPLETED,
            event(
                THINKING_COMPLETED,
                message_id=message_id,
                content=thought,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                kind=kind,
            ),
        )

    async def _reply_only(
        self,
        ctx: RunContext,
        event: Any,
        speed: float,
        text: str,
        started: float,
        token_chars: int,
    ) -> AsyncIterator[EngineEvent]:
        """只回一句话就收尾：不排计划、不挂工具、不出产物。

        演示模式最容易露馅的地方就是「见谁都跑一遍生成脚本」，所以聊天和
        单纯的询问走这里，和真实引擎的 chat / read 两条路对齐。
        """
        async for delta_event in self._stream_message(ctx, event, text, speed, "m_reply"):
            yield delta_event
        ctx.messages.add(
            Message(
                id=new_id("m"),
                thread_id=ctx.thread_id,
                role=MessageRole.ASSISTANT.value,
                content=text,
                run_id=ctx.run_id,
                created_at=now_iso(),
            )
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        tokens = max(120, token_chars // 2 + 60)
        yield EngineEvent(
            RUN_COMPLETED,
            event(
                RUN_COMPLETED,
                status=RunStatus.COMPLETED.value,
                tokens=tokens,
                cost_cny=0.0,
                elapsed_ms=elapsed_ms,
                artifact_ids=[],
                approvals=[],
                degraded=ctx.degraded,
                engine=self.name,
                model=ctx.model,
                usage={
                    "input_tokens": max(1, token_chars // 3),
                    "output_tokens": max(1, token_chars - token_chars // 3),
                    "total_tokens": tokens,
                },
            ),
        )

    async def _stream_message(
        self,
        ctx: RunContext,
        event: Any,
        text: str,
        speed: float,
        message_id: str,
        channel: str = "reply",
    ) -> AsyncIterator[EngineEvent]:
        """`channel`：reply = 对话里的正式回复；process = 中间旁白，前端收进「执行过程」。

        一次运行会蹦出三四段旁白，全按气泡渲染时每个都带一遍头像和名字，
        一屏下来光看「Office Agent」就翻了两屏。旁白只该在执行过程里留一行。
        """
        step = 7
        for index, start in enumerate(range(0, len(text), step)):
            yield EngineEvent(
                MESSAGE_DELTA,
                event(
                    MESSAGE_DELTA,
                    message_id=message_id,
                    delta=text[start : start + step],
                    index=index,
                    channel=channel,
                ),
            )
            if speed > 0:
                await asyncio.sleep(speed * 0.6)
        yield EngineEvent(
            MESSAGE_COMPLETED,
            event(
                MESSAGE_COMPLETED,
                message_id=message_id,
                content=text,
                channel=channel,
            ),
        )

    def _plan(self, tool_ctx: ToolContext, statuses: dict[str, str]) -> list[dict[str, str]]:
        tool_ctx.todos = [
            {"id": tid, "content": content, "status": statuses.get(tid, "pending")}
            for tid, content in PLAN_TEMPLATE
        ]
        return tool_ctx.todos

    async def _call_tool(
        self,
        ctx: RunContext,
        event: Any,
        tool_ctx: ToolContext,
        name: str,
        args: dict[str, Any],
        subagent_status: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        spec: ToolSpec | None = self.tools.get(name)
        started = time.perf_counter()
        result: dict[str, Any] = {}
        error: dict[str, str] | None = None
        ok = False
        risk = Risk.LOW.value
        summary = ""
        if spec is None:
            error = {"code": "TOOL_ERROR", "message": f"工具未注册：{name}"}
            summary = error["message"]
        else:
            risk = spec.risk.value
            try:
                # 工具可能包含阻塞 IO（python-docx / 文件读写），放线程池执行
                result = await asyncio.to_thread(spec.handler, tool_ctx, **args)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, dict):
                    result = {"value": result, "ok": True}
                ok = bool(result.get("ok", True))
                summary = str(result.get("_summary") or f"已执行 {name}")
            except Exception as exc:
                error = {"code": "TOOL_ERROR", "message": str(exc)[:500] or "工具执行异常"}
                summary = f"工具执行失败：{error['message']}"
                logger.warning(
                    "工具执行失败 tool=%s error=%s",
                    name,
                    error["message"],
                    extra={"event": "tool_error", "tool": name},
                )
        duration_ms = int((time.perf_counter() - started) * 1000)
        output = {key: sanitize(value) for key, value in result.items() if not key.startswith("_")}
        data = event(
            TOOL_FINISHED,
            tool=name,
            ok=ok,
            risk=risk,
            summary=summary,
            duration_ms=duration_ms,
            input=sanitize(args),
            output=output,
            artifact_id=output.get("artifact_id"),
        )
        if not ok and error:
            data["error"] = error
        if subagent_status:
            data["subagent"] = {**SUBAGENT_DOC, "status": subagent_status}
        return data, result

    @staticmethod
    async def _pause(speed: float, factor: float) -> None:
        if speed > 0:
            await asyncio.sleep(speed * factor)
