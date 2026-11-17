"""产物记录原地替换：同一份文件被重写时，id 不能变。

线上症状：脚本在同一条运行里重跑，写出同名文件，产物列表里出现 `X.txt` 和 `X(2).txt`；
而界面上那张卡还指着被软删的旧记录，点预览就是「产物不存在」（404）。
"""

from __future__ import annotations

from pathlib import Path

from app.domain.entities import Artifact
from app.infra.db.models import Base
from app.infra.db.repositories.artifact_repo import SqlArtifactRepository
from app.infra.db.session import create_database_engine
from sqlalchemy.orm import Session, sessionmaker


def _repo(tmp_path: Path) -> SqlArtifactRepository:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'artifacts.db'}")
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return SqlArtifactRepository(factory)


def _artifact() -> Artifact:
    return Artifact(
        id="art_1",
        thread_id="th_1",
        run_id="r_1",
        type="txt",
        filename="说明.txt",
        path="data/artifacts/说明.txt",
        size=10,
        sha256="old-hash",
        created_at="2026-11-09T22:00:00+08:00",
        extra={"source": "code.run_python"},
    )


def test_replace_file_updates_content_fields_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.add(_artifact())

    repo.replace_file("art_1", size=200, sha256="new-hash", created_at="2026-11-09T22:30:00+08:00")

    row = repo.get("art_1")
    assert row is not None
    assert row.size == 200
    assert row.sha256 == "new-hash"
    assert row.created_at == "2026-11-09T22:30:00+08:00"
    # 同一份交付物：文件名与来源标记都不该被换掉
    assert row.filename == "说明.txt"
    assert row.extra["source"] == "code.run_python"
    assert len(repo.list(thread_id="th_1")) == 1, "同一条记录，不该变成两条"


def test_replace_file_revives_a_deleted_record(tmp_path: Path) -> None:
    """被软删过又重写的，应当是活的——否则前端拿到的还是 404。"""
    repo = _repo(tmp_path)
    repo.add(_artifact())
    repo.soft_delete("art_1", "2026-11-09T22:10:00+08:00")
    assert repo.get("art_1") is None

    repo.replace_file("art_1", size=200, sha256="new-hash", created_at="2026-11-09T22:30:00+08:00")

    assert repo.get("art_1") is not None


def test_replace_file_ignores_unknown_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.replace_file("art_missing", size=1, sha256="x", created_at="2026-11-09T22:30:00+08:00")
