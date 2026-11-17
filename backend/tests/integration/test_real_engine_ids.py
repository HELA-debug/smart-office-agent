"""B4R2 回归：真实引擎消息主键必须全局唯一（跨 thread / 同 thread 连续 run）。

复现的是 `messages.id` 主键冲突（旧实现用 `m_step{step}`）；这里用真实 SQLite 仓储跑
fake-model RealEngine，连跑多个 run，验证不再触发 UNIQUE constraint。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.engine_protocol import EngineEvent, RunContext
from app.agents.real_engine import RealEngine
from app.core.config import Settings
from app.core.utils import new_id, now_iso
from app.domain.entities import Thread
from app.infra.db.repositories.message_repo import SqlMessageRepository
from app.infra.db.repositories.thread_repo import SqlThreadRepository
from app.infra.db.session import Database, run_migrations
from app.providers import ToolCall
from tests.unit.test_real_engine import (
    FakeApprovals,
    FakeArtifacts,
    FakeGate,
    FakeRouter,
    FakeStorage,
    chat_result,
    make_tools,
)

MATERIAL = "本周完成登录联调，接口覆盖 12 个；工作台 SSE 流式渲染上线。"


def _db_settings(tmp_path: Path) -> Settings:
    root = tmp_path / "data"
    return Settings(
        mock_mode=False,
        model_provider="deepseek",
        model_name="deepseek-chat",
        model_fallback_chain="deepseek,mock",
        deepseek_api_key="sk-fake",
        model_max_steps=4,
        model_max_tokens=500,
        approval_timeout_seconds=2,
        approval_rules="file.delete",
        mock_model_speed=0,
        database_url=f"sqlite:///{root / 'app.db'}",
        upload_dir=str(root / "uploads"),
        artifact_dir=str(root / "artifacts"),
    )


def _new_thread(threads: SqlThreadRepository) -> str:
    thread_id = new_id("th")
    threads.add(
        Thread(
            id=thread_id,
            title="B4R2 消息 ID 回归",
            created_at=now_iso(),
            updated_at=now_iso(),
        )
    )
    return thread_id


def _run_once(
    settings: Settings,
    messages: SqlMessageRepository,
    thread_id: str,
) -> tuple[str, list[EngineEvent]]:
    run_id = new_id("r")
    artifacts = FakeArtifacts()
    gate = FakeGate()
    tools = make_tools(artifacts, MATERIAL)
    router = FakeRouter(
        [
            chat_result(
                "收到，先读取素材。", [ToolCall(id=new_id("call"), name="file_read", arguments={})]
            ),
            chat_result("处理完成。"),
        ],
        available=True,
    )
    engine = RealEngine(tools, ["file.delete"], router)  # type: ignore[arg-type]
    ctx = RunContext(
        thread_id=thread_id,
        run_id=run_id,
        trace_id="tr_b4r2",
        message="处理素材并给出结论",  # 中性任务，不触发兜底
        mode="real",
        model="deepseek-chat",
        degraded=False,
        settings=settings,
        messages=messages,
        artifacts=artifacts,
        approvals=FakeApprovals(),
        storage=FakeStorage(),
        approval_gate=gate,
        tools=tools,
        approval_tools=["file.delete"],
        uploads=[],
    )

    async def runner() -> list[EngineEvent]:
        return [event async for event in engine.run(ctx)]

    return run_id, asyncio.run(runner())


def test_message_ids_unique_across_threads_and_runs(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path)
    run_migrations(settings)
    database = Database(settings)
    try:
        threads = SqlThreadRepository(database.session_factory)
        messages = SqlMessageRepository(database.session_factory)
        thread_a = _new_thread(threads)
        thread_b = _new_thread(threads)

        completed_runs: list[str] = []
        for thread_id in (thread_a, thread_b):
            run_id, events = _run_once(settings, messages, thread_id)
            assert events[-1].event == "run.completed"
            completed_runs.append(run_id)

        # 同一 thread 连续第二次 run（旧实现会再次插入 m_step1）
        run_id, events = _run_once(settings, messages, thread_a)
        assert events[-1].event == "run.completed"
        completed_runs.append(run_id)

        rows = messages.list_by_thread(thread_a) + messages.list_by_thread(thread_b)
        ids = [message.id for message in rows]
        # 3 个 run × 1 条正式回复：中间旁白（channel=process）只活在本次运行的
        # 「执行过程」里，不落库——否则重开会话又变回一串带抬头的助手气泡
        assert len(ids) == 3
        assert len(ids) == len(set(ids)), f"messages.id 冲突：{ids}"
        for run_id in completed_runs:
            assert any(message_id.startswith(f"{run_id}_m") for message_id in ids), run_id
    finally:
        database.dispose()


def test_real_engine_marks_message_ids_with_run_prefix(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path)
    run_migrations(settings)
    database = Database(settings)
    try:
        threads = SqlThreadRepository(database.session_factory)
        messages = SqlMessageRepository(database.session_factory)
        thread_id = _new_thread(threads)
        run_id, events = _run_once(settings, messages, thread_id)
        message_ids = [
            str(event.data["message_id"]) for event in events if event.event == "message.completed"
        ]
        assert message_ids
        assert all(message_id.startswith(f"{run_id}_m") for message_id in message_ids)
        assert len(message_ids) == len(set(message_ids))
        # 只有正式回复落库。动手前那句「收到，先读取素材」是过程播报，
        # 走 message.* 的 channel=process，同样不该进库——重开会话只该看到
        # 用户的问题和最后的结论。
        replies = [
            str(event.data["message_id"])
            for event in events
            if event.event == "message.completed" and event.data.get("channel", "reply") == "reply"
        ]
        stored = [message.id for message in messages.list_by_thread(thread_id)]
        assert set(stored) == set(replies)
        assert len(replies) == 1
        notes = [
            str(event.data["content"])
            for event in events
            if event.event == "message.completed" and event.data.get("channel") == "process"
        ]
        assert notes, "过程播报应该走 process 通道"
        assert all(message.content not in notes for message in messages.list_by_thread(thread_id))
    finally:
        database.dispose()
