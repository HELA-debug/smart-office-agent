"""调用账本：上下文归口、逐次记账、汇总口径。

这些用例盯的是「账本能不能替人去跟供应商对账」，所以重点不在「有没有记」，
而在三件容易漏的事：

1. 一次逻辑调用可能发出**多次** HTTP 请求（`max_tokens` 截断后放大重试），
   只记最后一次，账本就会稳定地少算一半；
2. 失败的请求也要留痕：对面收了、可能也计了费，只是没给 usage；
3. 账本挂了不能反过来打断一次成功的模型调用。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from app.core import call_journal
from app.core.call_journal import CallEntry
from app.core.config import Settings
from app.infra.db.ledger import DbCallJournal, summarize
from app.infra.db.models import Base
from app.infra.db.session import Database
from app.providers import DeepSeekProvider, ProviderError


class MemoryJournal:
    def __init__(self) -> None:
        self.entries: list[CallEntry] = []

    def record(self, entry: CallEntry) -> None:
        self.entries.append(entry)


@pytest.fixture()
def journal() -> Any:
    item = MemoryJournal()
    call_journal.install(item)
    try:
        yield item
    finally:
        call_journal.install(None)


def make_settings() -> Settings:
    return Settings(
        mock_mode=False,
        model_provider="deepseek",
        model_name="deepseek-chat",
        model_fallback_chain="deepseek,mock",
        deepseek_api_key="sk-test-deepseek",
        openai_api_key="",
        database_url="sqlite:///:memory:",
    )


def make_provider(handler: Any) -> DeepSeekProvider:
    def factory(_settings: Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False, timeout=5.0
        )

    return DeepSeekProvider(make_settings(), http_client_factory=factory)


def completion(
    *,
    content: str = "",
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def test_entry_inherits_run_scope(journal: MemoryJournal) -> None:
    """记账条目要从上下文补 run / thread / purpose，而不是每个调用点自己拼。"""
    scope = call_journal.bind_scope(run_id="r_1", thread_id="th_1")
    purpose = call_journal.bind_purpose("reading")
    try:
        call_journal.record(call_journal.entry_for(provider="deepseek", model="deepseek-flash"))
    finally:
        call_journal.reset(purpose)
        call_journal.reset(scope)

    entry = journal.entries[0]
    assert (entry.run_id, entry.thread_id, entry.purpose) == ("r_1", "th_1", "reading")


def test_successful_call_is_recorded(journal: MemoryJournal) -> None:
    provider = make_provider(lambda request: httpx.Response(200, json=completion(content="在。")))
    asyncio.run(provider.chat([{"role": "user", "content": "你好"}]))

    assert len(journal.entries) == 1
    entry = journal.entries[0]
    assert entry.status == "ok"
    assert entry.request_id == "chatcmpl-test"
    assert (entry.input_tokens, entry.output_tokens) == (11, 7)
    assert entry.run_id is None, "run 外调用（探测/标题）本来就不属于任何运行"


def test_failed_call_is_recorded(journal: MemoryJournal) -> None:
    """失败的请求没有 usage，但次数和错误码必须留下——差额一半在这里。"""
    provider = make_provider(lambda request: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(ProviderError):
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))

    assert len(journal.entries) == 1
    entry = journal.entries[0]
    assert entry.status == "failed"
    assert entry.error_code and "401" in entry.error_code
    assert entry.input_tokens == 0


def test_truncated_call_records_every_attempt(journal: MemoryJournal) -> None:
    """`max_tokens` 截断后的放大重试是两次独立请求，必须记两条。

    只记最后一次，账本就会稳定地少算一半——而这正是「应用内 ¥0.43、
    控制台 ¥2.72」这种差额的主要来源之一。
    """
    sent = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        sent["count"] += 1
        return httpx.Response(
            200,
            json=completion(content="", completion_tokens=100, finish_reason="length"),
        )

    provider = make_provider(handler)
    with pytest.raises(ProviderError):
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}], max_tokens=100))

    assert sent["count"] == 2, "截断后应当放大预算再发一次"
    assert len(journal.entries) == 2, "两次请求都要有账"
    assert all(entry.status == "ok" for entry in journal.entries)


def test_broken_journal_never_breaks_the_call() -> None:
    class Broken:
        def record(self, entry: CallEntry) -> None:
            raise RuntimeError("db down")

    call_journal.install(Broken())
    try:
        call_journal.record(CallEntry(provider="deepseek", model="deepseek-chat"))
    finally:
        call_journal.install(None)


def test_summarize_groups_by_purpose(tmp_path: Any) -> None:
    database = Database(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'ledger.db'}",
            upload_dir=str(tmp_path / "u"),
            artifact_dir=str(tmp_path / "a"),
        )
    )
    Base.metadata.create_all(database.engine)
    try:
        writer = DbCallJournal(database)
        writer.record(
            CallEntry(
                provider="deepseek",
                model="deepseek-flash",
                purpose="engine",
                input_tokens=1000,
                output_tokens=500,
                cache_miss_tokens=1000,
            )
        )
        writer.record(
            CallEntry(
                provider="deepseek",
                model="deepseek-flash",
                purpose="reading",
                input_tokens=200,
                output_tokens=100,
                cache_miss_tokens=200,
            )
        )
        writer.record(
            CallEntry(
                provider="deepseek",
                model="deepseek-flash",
                purpose="probe",
                status="failed",
                error_code="timeout",
            )
        )

        summary = summarize(database, range_key="all")
    finally:
        database.dispose()

    assert summary["calls"] == 3
    assert summary["failed_calls"] == 1
    assert summary["tokens"] == 1800
    # 金额按现价重算：写入时不算钱，否则改一次价历史账就自相矛盾
    assert summary["cost_cny"] > 0
    by_purpose = {item["purpose"]: item for item in summary["by_purpose"]}
    assert by_purpose["reading"]["calls"] == 1
    assert by_purpose["probe"]["failed_calls"] == 1
    assert by_purpose["probe"]["cost_cny"] == 0


class _EmptyRuns:
    """RunRepository 的最小桩：这里只关心账本那一栏。"""

    def list_recent(self, limit: int = 500) -> list[Any]:
        return []

    def list_by_thread(self, thread_id: str, limit: int = 500) -> list[Any]:
        return []


def test_usage_summary_embeds_ledger(tmp_path: Any) -> None:
    from app.services.usage_service import UsageService

    database = Database(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'usage.db'}",
            upload_dir=str(tmp_path / "u"),
            artifact_dir=str(tmp_path / "a"),
        )
    )
    Base.metadata.create_all(database.engine)
    try:
        DbCallJournal(database).record(
            CallEntry(
                provider="deepseek",
                model="deepseek-flash",
                purpose="probe",
                input_tokens=10,
                output_tokens=5,
                cache_miss_tokens=10,
            )
        )
        summary = UsageService(_EmptyRuns(), database).summary(range_key="all")  # type: ignore[arg-type]
    finally:
        database.dispose()

    assert summary["runs"] == 0, "运行内口径不受账本影响"
    assert summary["ledger"] is not None
    assert summary["ledger"]["calls"] == 1
    assert summary["ledger"]["by_purpose"][0]["purpose"] == "probe"


def test_usage_summary_says_none_when_ledger_is_unavailable() -> None:
    """账本不可用要返回 None，不能用 `calls=0` 冒充「没花过钱」。"""
    from app.services.usage_service import UsageService

    summary = UsageService(_EmptyRuns()).summary(range_key="all")  # type: ignore[arg-type]
    assert summary["ledger"] is None
