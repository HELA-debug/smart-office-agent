"""分页下推到 SQL（P2-15）。

旧实现在服务层先 `list_recent(limit=2000)` / `list_by_thread(limit=500)` 再内存切片：
- 超过上限的数据永远翻不到；
- 每次翻页都把前 N 条整行读进内存。

这里直接用临时 SQLite 验证仓储层的 COUNT + LIMIT/OFFSET 行为，
不经过 HTTP，跑得快也不依赖 mock 引擎。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.domain.entities import Artifact, Run, Thread
from app.infra.db.models import Base
from app.infra.db.repositories.artifact_repo import SqlArtifactRepository
from app.infra.db.repositories.run_repo import SqlRunRepository
from app.infra.db.session import create_database_engine
from sqlalchemy.orm import Session, sessionmaker

RUNS = 260
ARTIFACTS = 130
DELETED_ARTIFACTS = 30


@pytest.fixture()
def repos(tmp_path: Path) -> Iterator[tuple[SqlRunRepository, SqlArtifactRepository]]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'paging.db'}")
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    runs = SqlRunRepository(factory)
    artifacts = SqlArtifactRepository(factory)

    for index in range(RUNS):
        # started_at 递增，保证 desc 排序结果确定（同秒再用 id 兜底）
        stamp = f"2026-10-24T{index // 3600:02d}:{(index // 60) % 60:02d}:{index % 60:02d}"
        runs.add(
            Run(
                id=f"r{index:04d}",
                thread_id="th_1" if index % 2 == 0 else "th_2",
                status="failed" if index % 4 == 0 else "completed",
                mode="mock",
                engine="mock",
                provider="mock",
                model="mock-scripted",
                started_at=stamp,
            )
        )

    for index in range(ARTIFACTS):
        artifacts.add(
            Artifact(
                id=f"a{index:04d}",
                thread_id="th_1",
                type="upload" if index % 10 == 0 else "txt",
                filename=f"文件{index}.txt",
                path=f"data/artifacts/文件{index}.txt",
                size=index,
                sha256="",
                created_at=f"2026-10-24T00:00:{index % 60:02d}",
                deleted_at="2026-10-25T00:00:00" if index < DELETED_ARTIFACTS else None,
            )
        )

    yield runs, artifacts
    engine.dispose()


def test_run_count_and_offset_paging(repos):
    runs, _ = repos
    assert runs.count() == RUNS
    assert runs.count(thread_id="th_1") == RUNS // 2
    assert runs.count(status="failed") == RUNS // 4

    # 第 1 页取最新 20 条；desc 排序 + id 兜底 → 最后一条是 r0259
    first_page = runs.list_recent(limit=20, offset=0)
    assert len(first_page) == 20
    assert first_page[0].id == f"r{RUNS - 1:04d}"

    # 第 13 页（offset 240）只回 20 条里的第 241-260 条，且与首页不重叠
    last_page = runs.list_recent(limit=20, offset=240)
    assert len(last_page) == 20
    assert {run.id for run in last_page}.isdisjoint({run.id for run in first_page})

    # 越界页返回空，而不是报错或回退到首页
    assert runs.list_recent(limit=20, offset=RUNS) == []


def test_run_status_filter_happens_in_sql(repos):
    runs, _ = repos
    failed = runs.list_recent(limit=50, offset=0, status="failed")
    assert len(failed) == 50
    assert {run.status for run in failed} == {"failed"}
    # 过滤 + 分页组合：第 2 页仍是 failed，且不重复
    second = runs.list_recent(limit=50, offset=50, status="failed")
    assert {run.status for run in second} == {"failed"}
    assert {run.id for run in second}.isdisjoint({run.id for run in failed})


def test_run_list_by_thread_pages_independently(repos):
    runs, _ = repos
    page_one = runs.list_by_thread("th_1", limit=10, offset=0)
    page_two = runs.list_by_thread("th_1", limit=10, offset=10)
    assert len(page_one) == 10 and len(page_two) == 10
    assert {run.thread_id for run in page_one + page_two} == {"th_1"}
    assert {run.id for run in page_two}.isdisjoint({run.id for run in page_one})


def test_artifact_count_excludes_soft_deleted(repos):
    _, artifacts = repos
    assert artifacts.count() == ARTIFACTS - DELETED_ARTIFACTS
    assert artifacts.count(include_deleted=True) == ARTIFACTS
    # upload 每 10 条一个（0/10/…/120 共 13 条），前 30 条被软删 → 存活 10 条
    assert artifacts.count(type="upload") == 10
    assert artifacts.count(type="upload", include_deleted=True) == 13
    assert artifacts.count(thread_id="th_1") == ARTIFACTS - DELETED_ARTIFACTS


def test_artifact_offset_paging_is_stable(repos):
    _, artifacts = repos
    live = ARTIFACTS - DELETED_ARTIFACTS

    first = artifacts.list(limit=10, offset=0)
    assert len(first) == 10
    # 软删的不出现在结果里
    assert all(item.deleted_at is None for item in first)

    tail = artifacts.list(limit=10, offset=live - 5)
    assert len(tail) == 5

    beyond = artifacts.list(limit=10, offset=live)
    assert beyond == []

    # 顺序 asc + 不重叠：拼起来正好覆盖全部存活条目
    collected: list[str] = []
    for offset in range(0, live, 25):
        collected.extend(item.id for item in artifacts.list(limit=25, offset=offset))
    assert len(collected) == len(set(collected)) == live


class _FakeRunRepo:
    """只实现导出用到的分页方法，记录每批的 (limit, offset)。"""

    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[tuple[int, int]] = []

    def list_by_thread(
        self, thread_id: str, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[Run]:
        self.calls.append((limit, offset))
        stop = min(offset + limit, self.total)
        return [
            Run(
                id=f"r{index:04d}",
                thread_id=thread_id,
                status="completed",
                mode="mock",
                engine="mock",
                provider="mock",
                model="mock-scripted",
                started_at=f"2026-10-24T00:00:{index % 60:02d}",
            )
            for index in range(offset, stop)
        ]


class _FakeThreadService:
    def __init__(self, threads: list[Thread]) -> None:
        self._threads = threads
        self.threads = self

    def get(self, thread_id: str) -> Thread | None:
        return next((item for item in self._threads if item.id == thread_id), None)

    def list(self, limit: int = 100, offset: int = 0, q: str | None = None) -> list[Thread]:
        return self._threads[offset : offset + limit]


def _thread(index: int) -> Thread:
    return Thread(
        id=f"th_{index:04d}",
        title=f"会话{index}",
        created_at="2026-10-24T00:00:00",
        updated_at="2026-10-24T00:00:00",
    )


def test_export_iterates_all_runs_past_one_batch():
    """审计导出不再截断在 500 条 / 一次载入全部线程。"""
    from app.services.run_service import RunService

    service = RunService.__new__(RunService)
    repo = _FakeRunRepo(total=450)
    service.runs = repo  # type: ignore[assignment]

    runs = list(service._iter_thread_runs("th_1"))

    assert len(runs) == 450
    assert [call[1] for call in repo.calls] == [0, 200, 400]
    assert {call[0] for call in repo.calls} == {RunService._EXPORT_BATCH}


def test_export_threads_are_iterated_in_batches():
    from app.services.run_service import RunService

    service = RunService.__new__(RunService)
    service.threads = _FakeThreadService([_thread(index) for index in range(450)])  # type: ignore[assignment]

    threads = list(service._iter_export_threads(None))

    assert len(threads) == 450
    assert threads[0].id == "th_0000"
    assert threads[-1].id == "th_0449"


def test_export_single_thread_short_circuits():
    from app.services.run_service import RunService

    service = RunService.__new__(RunService)
    service.threads = _FakeThreadService([_thread(1), _thread(2)])  # type: ignore[assignment]

    assert [item.id for item in service._iter_export_threads("th_0002")] == ["th_0002"]
    assert list(service._iter_export_threads("th_missing")) == []
