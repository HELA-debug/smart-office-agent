"""RealEngine 单测：用 fake model 驱动 ReAct 循环（不访问网络）。

覆盖：工具自主调用链、审批批准/拒绝、工具失败不中断、最大步数、运行中降级、
模型完全不可用时整条运行降级 MockEngine，以及 run.completed 的 usage 字段。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from app.agents.engine_protocol import EngineEvent, RunContext
from app.agents.model_router import ChatResult, ModelUnavailableError
from app.agents.real_engine import MATERIAL_OBSERVATION_LIMIT, RealEngine
from app.core.config import Settings
from app.core.utils import now_iso
from app.domain.entities import Artifact, Message, UploadInfo
from app.domain.enums import Decision
from app.providers import ToolCall
from app.tools.registry import ToolRegistry


# ---------------- fakes ----------------
class FakeMessages:
    def __init__(self) -> None:
        self.items: list[Message] = []

    def add(self, message: Message) -> Message:
        self.items.append(message)
        return message

    def list_by_thread(self, thread_id: str, include_run_summary: bool = True) -> list[Message]:
        return [item for item in self.items if item.thread_id == thread_id]


class FakeArtifacts:
    def __init__(self) -> None:
        self.items: dict[str, Artifact] = {}

    def add(self, artifact: Artifact) -> Artifact:
        self.items[artifact.id] = artifact
        return artifact

    def get(self, artifact_id: str, include_deleted: bool = False) -> Artifact | None:
        return self.items.get(artifact_id)


class FakeApprovals:
    def add(self, approval: Any) -> Any:
        return approval

    def list_by_thread(self, thread_id: str, run_id: str | None = None) -> list[Any]:
        return []


class FakeStorage:
    def exists(self, path: str) -> bool:
        return True

    def read_text(self, path: str) -> str:
        return "本周完成登录联调，接口覆盖 12 个。"


class FakeGate:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self._events: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, Decision] = {}

    async def create(
        self,
        thread_id: str,
        run_id: str,
        tool: str,
        payload: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> Any:
        approval = SimpleNamespace(
            id=f"a_{len(self.created) + 1}",
            thread_id=thread_id,
            run_id=run_id,
            tool=tool,
            payload=payload,
            extra=extra,
        )
        self.created.append(approval)
        self._events[approval.id] = asyncio.Event()
        return approval

    async def wait(self, approval_id: str, timeout_seconds: float) -> Decision | None:
        await asyncio.wait_for(self._events[approval_id].wait(), max(1.0, timeout_seconds))
        return self._decisions.pop(approval_id, None)

    def decide(self, approval_id: str, decision: Decision) -> None:
        self._decisions[approval_id] = decision
        self._events[approval_id].set()


class FakeRouter:
    def __init__(self, script: list[Any], *, available: bool = True) -> None:
        self.settings = make_settings()
        self.script = list(script)
        self.available = available
        self.requests: list[list[dict[str, Any]]] = []
        self._usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_cny": 0.0,
            "calls": 0,
            "by_provider": [],
            "budget": 200_000,
            "currency": "CNY",
        }

    def begin_run(self, preferred: str | None = None) -> None:
        self.requests = []
        self._usage = {
            **self._usage,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_cny": 0.0,
            "calls": 0,
        }

    def ensure_available(self) -> bool:
        return self.available

    @property
    def available_provider(self) -> str:
        return "deepseek"

    def model_for(self, provider: str) -> str:
        return "deepseek-chat"

    async def chat_with_tools(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        # 不开工具的调用是「思考阶段」：直接给一段固定推理，既不消耗脚本也不计用量，
        # 这样各用例仍然只关心 ReAct 循环里的那几次工具型调用。
        if kwargs.get("tools") is None:
            return ChatResult(
                text="先确认交付物：一份周报；再读素材、抓要点、按结构成文，最后自检一遍。",
                provider="deepseek",
                model="deepseek-chat",
                prompt_tokens=0,
                completion_tokens=0,
            )
        self.requests.append([dict(item) for item in messages])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        self._usage["input_tokens"] += item.prompt_tokens
        self._usage["output_tokens"] += item.completion_tokens
        self._usage["total_tokens"] += item.total_tokens
        self._usage["cost_cny"] = round(self._usage["cost_cny"] + item.cost_cny, 6)
        self._usage["calls"] += 1
        return item

    def usage_snapshot(self) -> dict[str, Any]:
        return dict(self._usage)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mock_mode": False,
        "model_provider": "deepseek",
        "model_name": "deepseek-chat",
        "model_fallback_chain": "deepseek,mock",
        "deepseek_api_key": "sk-fake",
        "model_max_steps": 8,
        "model_max_tokens": 1000,
        "approval_timeout_seconds": 2,
        "approval_rules": "file.delete",
        "mock_model_speed": 0,
    }
    base.update(overrides)
    return Settings(**base)


def make_tools(
    artifacts: FakeArtifacts, material: str = "本周完成登录联调，接口覆盖 12 个。"
) -> ToolRegistry:
    registry = ToolRegistry()

    @registry.register("file.list", "列出会话素材", risk="low")
    def list_files(ctx: Any, files: list[str] | None = None) -> dict[str, Any]:
        return {
            "files": [{"filename": "周报素材.txt", "chars": 20}],
            "count": 1,
            "_summary": "共 1 个素材文件",
        }

    @registry.register("file.read", "读取会话素材", risk="low")
    def read_files(ctx: Any, files: list[str] | None = None) -> dict[str, Any]:
        ctx.material_text = material
        ctx.material_sources = [{"filename": "周报素材.txt", "text": material}]
        return {
            "files": [{"filename": "周报素材.txt", "chars": len(material)}],
            "chars": len(material),
            "_material": material,
            "_sources": [{"filename": "周报素材.txt", "text": material}],
            "_summary": f"已读取 1 个文件，共 {len(material)} 字",
        }

    @registry.register("todo.write", "更新任务计划", risk="low")
    def write_todos(ctx: Any, todos: list[dict[str, Any]]) -> dict[str, Any]:
        ctx.todos = [
            {
                "id": item.get("id", f"t{index + 1}"),
                "content": str(item.get("content")),
                "status": str(item.get("status", "pending")),
            }
            for index, item in enumerate(todos)
        ]
        return {"todos": ctx.todos, "_summary": f"计划已更新（{len(ctx.todos)} 条）"}

    @registry.register("doc.generate_report", "生成报告文件", risk="low")
    def generate_report(
        ctx: Any,
        title: str = "",
        template: str = "weekly",
        files: list[str] | None = None,
        format: str = "",
    ) -> dict[str, Any]:
        artifact = Artifact(
            id="art_1",
            thread_id=ctx.thread_id,
            type="docx",
            filename="周报_2026-W43.docx",
            path="artifacts/周报_2026-W43.docx",
            size=2048,
            sha256="deadbeef",
            created_at=now_iso(),
            run_id=ctx.run_id,
        )
        artifacts.add(artifact)
        ctx.register_artifact(artifact)
        return {
            "artifact_id": artifact.id,
            "filename": artifact.filename,
            "path": artifact.path,
            "template": template,
            "format": format or "docx",
            "_summary": "已生成《周报_2026-W43.docx》",
        }

    @registry.register("file.delete", "删除产物", risk="high", effect=lambda _a: "destructive")
    def delete_files(ctx: Any, files: list[str] | None = None) -> dict[str, Any]:
        targets = list(files or [])
        return {"deleted": targets, "count": len(targets), "_summary": "已删除指定产物"}

    return registry


def make_ctx(
    router: FakeRouter,
    gate: FakeGate | None = None,
    *,
    settings: Settings | None = None,
    message: str = "把这份材料整理成周报",
    material: str = "本周完成登录联调，接口覆盖 12 个。",
    history: list[dict[str, Any]] | None = None,
    context_summary: str = "",
    context_meta: dict[str, Any] | None = None,
) -> RunContext:
    active_settings = settings or router.settings
    artifacts = FakeArtifacts()
    return RunContext(
        thread_id="th_test",
        run_id="r_test",
        trace_id="tr_test",
        message=message,
        mode="real",
        model="deepseek-chat",
        degraded=False,
        settings=active_settings,
        messages=FakeMessages(),
        artifacts=artifacts,
        approvals=FakeApprovals(),
        storage=FakeStorage(),
        approval_gate=gate or FakeGate(),
        tools=make_tools(artifacts, material),
        approval_tools=["file.delete"],
        uploads=[
            UploadInfo(
                artifact_id="art_upload",
                filename="周报素材.txt",
                path="artifacts/周报素材.txt",
                ext=".txt",
                chars=len(material),
                parsed=True,
            )
        ],
        history=list(history or []),
        context_summary=context_summary,
        context_meta=dict(context_meta or {}),
    )


def collect_events(engine: RealEngine, ctx: RunContext, gate: FakeGate) -> list[EngineEvent]:
    async def runner() -> list[EngineEvent]:
        events: list[EngineEvent] = []
        async for engine_event in engine.run(ctx):
            events.append(engine_event)
            if engine_event.event == "approval.required":
                gate.decide(engine_event.data["approval_id"], Decision.APPROVED)
        return events

    return asyncio.run(runner())


def chat_result(text: str = "", calls: list[ToolCall] | None = None) -> ChatResult:
    return ChatResult(
        text=text,
        provider="deepseek",
        model="deepseek-chat",
        prompt_tokens=100,
        completion_tokens=20,
        tool_calls=tuple(calls or []),
        finish_reason="tool_calls" if calls else "stop",
        cost_cny=0.0005,
    )


# ---------------- tests ----------------
def build_engine_and_ctx(
    script: list[Any],
    *,
    settings: Settings | None = None,
    available: bool = True,
    message: str = "把这份材料整理成周报",
    material: str = "本周完成登录联调，接口覆盖 12 个。",
) -> tuple[RealEngine, FakeRouter, FakeGate, RunContext]:
    router = FakeRouter(script, available=available)
    if settings is not None:
        router.settings = settings
    gate = FakeGate()
    ctx = make_ctx(router, gate, settings=settings, message=message, material=material)
    engine = RealEngine(ctx.tools, ["file.delete"], router)  # type: ignore[arg-type]
    return engine, router, gate, ctx


def test_tool_failure_does_not_abort_run() -> None:
    script = [
        chat_result("", [ToolCall(id="c1", name="not_exists", arguments={})]),
        chat_result("工具不可用，我改为按默认模板处理。"),
    ]
    engine, _router, gate, ctx = build_engine_and_ctx(script, message="处理一下这份材料")
    events = collect_events(engine, ctx, gate)

    failed = [
        event for event in events if event.event == "tool.finished" and event.data["ok"] is False
    ]
    assert failed and failed[0].data["tool"] == "not_exists"
    assert events[-1].event == "run.completed"
    assert events[-1].data["status"] == "completed"


def test_max_steps_stop_reason() -> None:
    script = [
        chat_result("继续。", [ToolCall(id=f"c{i}", name="file_read", arguments={})])
        for i in range(3)
    ]
    settings = make_settings(model_max_steps=2)
    engine, _router, gate, ctx = build_engine_and_ctx(
        script, settings=settings, message="继续处理素材"
    )
    events = collect_events(engine, ctx, gate)

    completed = events[-1]
    assert completed.event == "run.completed"
    assert completed.data["stop_reason"] == "max_steps"
    assert completed.data["status"] == "completed"


def test_midrun_model_unavailable_degrades_gracefully() -> None:
    script = [
        chat_result("", [ToolCall(id="c1", name="file_read", arguments={})]),
        ModelUnavailableError(
            "全部模型供应商不可用",
            attempts=[
                {"provider": "deepseek", "result": "failed", "message": "timeout"},
            ],
        ),
    ]
    engine, _router, gate, ctx = build_engine_and_ctx(script)
    events = collect_events(engine, ctx, gate)

    completed = events[-1]
    assert completed.event == "run.completed"
    assert completed.data["degraded"] is True
    assert completed.data["stop_reason"] == "model_unavailable"
    assert completed.data["status"] == "completed"


def test_no_available_provider_falls_back_to_mock_engine() -> None:
    engine, _router, gate, ctx = build_engine_and_ctx([], available=False)
    events = collect_events(engine, ctx, gate)

    started = events[0]
    assert started.event == "run.started"
    assert started.data["mode"] == "mock"
    assert started.data["engine"] == "mock"
    assert started.data["degraded"] is True
    assert events[-1].event == "run.completed"
    assert events[-1].data["degraded"] is True
    assert events[-1].data["status"] == "completed"


# ---------------- B4R：正文回填 / 兜底 ----------------
def _last_tool_observation(router: FakeRouter, request_index: int = -1) -> dict[str, Any]:
    messages = router.requests[request_index]
    tool_messages = [item for item in messages if item.get("role") == "tool"]
    assert tool_messages, "模型观察中没有 tool 消息"
    return json.loads(tool_messages[-1]["content"])


def test_file_read_observation_injects_material_body() -> None:
    script = [
        chat_result("", [ToolCall(id="c1", name="file_read", arguments={})]),
        chat_result("已读取素材，开始写作。"),
    ]
    engine, router, gate, ctx = build_engine_and_ctx(script)
    collect_events(engine, ctx, gate)

    observation = _last_tool_observation(router, 1)
    assert "本周完成登录联调" in observation["material"]
    assert observation["material_chars"] == len("本周完成登录联调，接口覆盖 12 个。")
    assert observation["material_truncated"] is False
    assert "不得编造" in observation["material_notice"]
    # _sources 等冗余/内部字段不得注入模型观察
    assert "_sources" not in json.dumps(observation, ensure_ascii=False)


def test_file_read_observation_truncates_long_material() -> None:
    material = "\n\n".join(f"第 {index} 段：本周完成联调与上线。" for index in range(1500))
    assert len(material) > MATERIAL_OBSERVATION_LIMIT
    script = [
        chat_result("", [ToolCall(id="c1", name="file_read", arguments={})]),
        chat_result("已完成。"),
    ]
    engine, router, gate, ctx = build_engine_and_ctx(script, material=material)
    collect_events(engine, ctx, gate)

    observation = _last_tool_observation(router, 1)
    assert observation["material_truncated"] is True
    assert len(observation["material"]) <= MATERIAL_OBSERVATION_LIMIT
    assert observation["material_chars"] == len(material)
    # 提示语后来改成人话：说清注入了多少、剩下怎么取，不再只是一个「已截断」标签
    assert "只注入了前" in observation["material_notice"]


def test_no_fallback_for_non_document_task() -> None:
    script = [chat_result("今天是晴天。")]
    engine, _router, gate, ctx = build_engine_and_ctx(script, message="今天天气怎么样")
    events = collect_events(engine, ctx, gate)
    completed = events[-1]
    assert completed.data["fallback_actions"] == []
    assert completed.data["stop_reason"] == "completed"


# ---------------- 收尾答复契约 ----------------
def test_no_fallback_when_model_says_it_cannot() -> None:
    """模型已说「这份素材做不了」时不再补生成：结论与产物不能互相打脸。"""
    script = [
        chat_result("", [ToolCall(id="c1", name="file_read", arguments={})]),
        chat_result("**结论**：这份素材无法整理成周报，缺本周进展与数据。"),
    ]
    engine, _router, gate, ctx = build_engine_and_ctx(script, message="把这份材料整理成 600 字周报")
    events = collect_events(engine, ctx, gate)
    completed = events[-1]
    assert completed.data["artifact_ids"] == []
    assert completed.data["fallback_actions"] == []
    assert completed.data["stop_reason"] == "completed"
    assert not [event for event in events if event.event == "artifact.ready"]


# ---------------- 上下文（多轮历史） ----------------
def test_initial_messages_place_history_between_system_and_current_turn() -> None:
    """多轮对话的地基：历史必须真的进 messages，而不是只在界面上连续。"""
    router = FakeRouter([])
    ctx = make_ctx(
        router,
        history=[
            {"role": "user", "content": "把这份材料整理成周报"},
            {"role": "assistant", "content": "已生成《周报.docx》，可在产物中心下载。"},
        ],
    )
    engine = RealEngine(ctx.tools, ["file.delete"], router)  # type: ignore[arg-type]
    messages = engine._initial_messages(ctx)

    assert messages[0]["role"] == "system"
    assert [item["role"] for item in messages[1:3]] == ["user", "assistant"]
    assert messages[1]["content"] == "把这份材料整理成周报"
    assert messages[-1]["role"] == "user"
    assert "把它改成八号字" in messages[-1]["content"] or "周报" in messages[-1]["content"]
    # 历史 + 本轮：system / 用户 / 助手 / 用户
    assert len(messages) == 4


def test_initial_messages_without_history_stay_single_turn() -> None:
    """首轮对话的形状不能变：老会话、老测试都依赖 system + user 两条。"""
    router = FakeRouter([])
    ctx = make_ctx(router)
    engine = RealEngine(ctx.tools, ["file.delete"], router)  # type: ignore[arg-type]
    messages = engine._initial_messages(ctx)
    assert [item["role"] for item in messages] == ["system", "user"]


def test_compressed_summary_goes_into_system_prompt() -> None:
    """被挤出窗口的更早轮次以摘要形式留给模型，避免「完全没提过」的失忆。"""
    router = FakeRouter([])
    ctx = make_ctx(
        router,
        history=[
            {"role": "user", "content": "上一轮"},
            {"role": "assistant", "content": "上一轮答复"},
        ],
        context_summary="【更早的对话（已压缩）】\n- 第一轮：出周报 → 已生成周报.docx",
        context_meta={"turns_total": 5, "kept_turns": 1, "dropped_turns": 4, "summary_chars": 40},
    )
    engine = RealEngine(ctx.tools, ["file.delete"], router)  # type: ignore[arg-type]
    messages = engine._initial_messages(ctx)
    system = messages[0]["content"]
    assert "更早的对话（已压缩）" in system
    assert "已生成周报.docx" in system
    # 摘要要明确「别照摘要编内容」，否则模型会拿摘要当素材
    assert "不要凭摘要臆造" in system


def test_delete_without_his_words_is_skipped_not_failed() -> None:
    """删除是唯一「做完收不回来」的动作：他没说要删，这一步就不动。

    重点在**不动之后的样子**：一条 skipped 的工具事件，不是 error、不画红框，
    运行照常收尾——用户看到的是「这一步没动」，不是「脚本执行失败」。
    """
    script = [
        chat_result(
            "", [ToolCall(id="c1", name="file_delete", arguments={"files": ["周报.docx"]})]
        ),
        chat_result("旧稿我留着没动，要删你说一声。"),
    ]
    engine, _router, gate, ctx = build_engine_and_ctx(script, message="这份周报再顺一下")
    events = collect_events(engine, ctx, gate)

    assert "approval.required" not in [event.event for event in events]
    finished = [
        event
        for event in events
        if event.event == "tool.finished" and event.data["tool"] == "file.delete"
    ]
    assert finished and finished[0].data["ok"] is False
    assert finished[0].data["output"]["skipped"] is True
    assert "error" not in finished[0].data, "跳过不是故障，不该带 error"
    assert events[-1].event == "run.completed"


def test_delivered_files_are_listed_in_system_prompt() -> None:
    """上一轮已经交付过文件：这一轮要摆到它眼前。

    用户说「你自己斟酌吧」时指的是在手上这版继续改。模型看不到已经有什么，
    就会从零再产一份，产物里于是多出 `X(2)`、`X(3)`。
    """
    engine, _router, _gate, ctx = build_engine_and_ctx(
        [chat_result("好，我先看《周报.docx》。")], message="你自己斟酌吧"
    )
    ctx.delivered = [
        {"filename": "周报.docx", "type": "docx", "created_at": "2026-11-09T22:00:00+08:00"}
    ]

    system = engine._initial_messages(ctx)[0]["content"]
    assert "本会话已交付的文件" in system
    assert "周报.docx" in system
    # 必须把「别另存成 (2)」说透，否则它照样会存一份新的
    assert "(2)" in system


def test_live_artifact_ids_drops_deleted_and_duplicates() -> None:
    """中途被删掉的产物不能再报给前端：界面上那张卡点开就是「产物不存在」。"""
    artifacts = FakeArtifacts()
    kept = Artifact(
        id="art_keep",
        thread_id="th_test",
        type="txt",
        filename="留着的.txt",
        path="artifacts/留着的.txt",
        size=1,
        sha256="aa",
        created_at=now_iso(),
    )
    artifacts.add(kept)
    tool_ctx = SimpleNamespace(artifact_ids=["art_keep", "art_deleted", "art_keep"])

    alive = RealEngine._live_artifact_ids(SimpleNamespace(artifacts=artifacts), tool_ctx)

    assert alive == ["art_keep"], "已删的、重复的都要清掉"
