"""会话手动排序（sort_index）与「N 产物」的口径。

两件事都在仓储层就能验证清楚，不用起 HTTP：
1. 拖动排序要落库——重排后按 list() 读出来必须是新顺序，且置顶仍在前；
2. 左栏「N 产物」只数 Agent 生成的文件，上传素材不算（产物中心本来也不列素材，
   算进去会出现「产物中心清空了，会话行还显示 2 产物」）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.domain.entities import Artifact, Thread
from app.infra.db.models import Base
from app.infra.db.repositories.artifact_repo import SqlArtifactRepository
from app.infra.db.repositories.thread_repo import SqlThreadRepository
from app.infra.db.session import create_database_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture()
def repos(tmp_path: Path) -> Iterator[tuple[SqlThreadRepository, SqlArtifactRepository]]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'order.db'}")
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield SqlThreadRepository(factory), SqlArtifactRepository(factory)
    engine.dispose()


def _thread(thread_id: str, *, stamp: str, pinned: bool = False) -> Thread:
    return Thread(
        id=thread_id,
        title=thread_id,
        created_at=stamp,
        updated_at=stamp,
        pinned=pinned,
    )


def test_reorder_persists_and_wins_over_updated_at(repos) -> None:
    threads, _ = repos
    # 更新时间：a 最新、c 最旧；重排后要求完全不按时间走
    threads.add(_thread("a", stamp="2026-10-30T10:00:00+08:00"))
    threads.add(_thread("b", stamp="2026-10-30T09:00:00+08:00"))
    threads.add(_thread("c", stamp="2026-10-30T08:00:00+08:00"))

    before = [row.id for row in threads.list()]
    assert before == ["a", "b", "c"]

    assert threads.reorder(["c", "a", "b"]) == 3
    after = [row.id for row in threads.list()]
    assert after == ["c", "a", "b"]

    # 新会话取「最小序号 - 1」插到最前面，其余的手动顺序原样保留
    lowest = threads.min_sort_index()
    assert lowest == 0.0
    fresh = _thread("d", stamp="2026-10-30T11:00:00+08:00")
    fresh.sort_index = lowest - 1.0
    threads.add(fresh)
    assert [row.id for row in threads.list()] == ["d", "c", "a", "b"]


def test_pinned_group_stays_on_top_after_reorder(repos) -> None:
    threads, _ = repos
    threads.add(_thread("a", stamp="2026-10-30T10:00:00+08:00"))
    threads.add(_thread("p", stamp="2026-10-30T09:00:00+08:00", pinned=True))

    threads.reorder(["a", "p"])
    assert [row.id for row in threads.list()] == ["p", "a"]


def test_reorder_ignores_unknown_ids(repos) -> None:
    threads, _ = repos
    threads.add(_thread("a", stamp="2026-10-30T10:00:00+08:00"))
    assert threads.reorder(["a", "ghost"]) == 1
    assert [row.id for row in threads.list()] == ["a"]


def test_artifact_count_excludes_uploads(repos) -> None:
    threads, artifacts = repos
    threads.add(_thread("th", stamp="2026-10-30T10:00:00+08:00"))

    def _artifact(artifact_id: str, kind: str, filename: str, path: str) -> Artifact:
        return Artifact(
            id=artifact_id,
            thread_id="th",
            type=kind,
            filename=filename,
            path=path,
            size=1024,
            sha256="0" * 64,
            created_at="2026-10-30T10:00:00+08:00",
        )

    for index in range(2):
        artifacts.add(
            _artifact(
                f"art_{index}", "docx", f"产物{index}.docx", f"data/artifacts/产物{index}.docx"
            )
        )
    artifacts.add(_artifact("up_1", "upload", "素材.docx", "data/uploads/素材.docx"))

    assert artifacts.count_by_thread("th") == 2

    # 软删一份产物后计数跟着降（会话行不该继续显示旧数字）
    artifacts.soft_delete("art_0", "2026-10-30T12:00:00+08:00")
    assert artifacts.count_by_thread("th") == 1
