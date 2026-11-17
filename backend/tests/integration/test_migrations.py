"""Alembic 迁移测试：空库 upgrade head + v0.1 旧库原地升级。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import Settings
from app.infra.db.session import run_migrations

EXPECTED_TABLES = {
    "threads",
    "messages",
    "runs",
    "run_events",
    "approvals",
    "artifacts",
    "settings",
    "model_configs",
    "model_calls",
}

LEGACY_SCHEMA = """
CREATE TABLE threads (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, extra TEXT DEFAULT '{}'
);
CREATE TABLE messages (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, role TEXT NOT NULL,
    content TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL, extra TEXT DEFAULT '{}'
);
CREATE TABLE approvals (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, run_id TEXT, tool TEXT NOT NULL,
    payload TEXT DEFAULT '{}', decision TEXT, comment TEXT,
    created_at TEXT NOT NULL, decided_at TEXT, extra TEXT DEFAULT '{}'
);
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, run_id TEXT, type TEXT NOT NULL,
    filename TEXT NOT NULL, path TEXT NOT NULL, size INTEGER DEFAULT 0,
    sha256 TEXT DEFAULT '', content_type TEXT DEFAULT '', created_at TEXT NOT NULL,
    extra TEXT DEFAULT '{}'
);
INSERT INTO threads (id, title, created_at, updated_at) VALUES ('th_legacy', '旧会话', '2026-10-01T10:00:00+08:00', '2026-10-01T10:00:00+08:00');
INSERT INTO messages (id, thread_id, role, content, created_at) VALUES ('m_legacy', 'th_legacy', 'user', '旧消息', '2026-10-01T10:00:01+08:00');
INSERT INTO approvals (id, thread_id, tool, payload, created_at) VALUES ('a_legacy', 'th_legacy', 'file.delete', '{}', '2026-10-01T10:00:02+08:00');
INSERT INTO artifacts (id, thread_id, type, filename, path, size, created_at) VALUES ('art_legacy', 'th_legacy', 'upload', 'old.txt', '/tmp/old.txt', 3, '2026-10-01T10:00:03+08:00');
"""


def _settings(db_path: Path, tmp_path: Path) -> Settings:
    return Settings(
        model_provider="mock",
        mock_mode=True,
        database_url=f"sqlite:///{db_path}",
        upload_dir=str(tmp_path / "uploads"),
        artifact_dir=str(tmp_path / "artifacts"),
    )


def _tables(db_path: Path) -> set[str]:
    connection = sqlite3.connect(str(db_path))
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        connection.close()


def _columns(db_path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def test_empty_database_upgrade_head(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    run_migrations(_settings(db_path, tmp_path))
    tables = _tables(db_path)
    assert tables >= EXPECTED_TABLES
    assert "alembic_version" in tables
    assert {"pinned", "deleted_at", "sort_index"} <= _columns(db_path, "threads")
    assert {"deleted_at"} <= _columns(db_path, "artifacts")
    assert {"policy_version"} <= _columns(db_path, "approvals")
    # 账本的 run_id 必须可空：探测/标题/增强这些请求不属于任何运行
    assert {"run_id", "purpose", "status", "request_id"} <= _columns(db_path, "model_calls")

    connection = sqlite3.connect(str(db_path))
    try:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        connection.close()
    assert version == "0004"

    # 幂等：再执行一次不报错
    run_migrations(_settings(db_path, tmp_path))


def test_legacy_v01_database_upgrades_in_place(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(str(db_path))
    try:
        connection.executescript(LEGACY_SCHEMA)
        connection.commit()
    finally:
        connection.close()
    assert _tables(db_path) == {"threads", "messages", "approvals", "artifacts"}

    run_migrations(_settings(db_path, tmp_path))

    assert _tables(db_path) >= EXPECTED_TABLES
    assert {"pinned", "deleted_at"} <= _columns(db_path, "threads")
    assert {"policy_version"} <= _columns(db_path, "approvals")

    connection = sqlite3.connect(str(db_path))
    try:
        assert (
            connection.execute("SELECT title FROM threads WHERE id='th_legacy'").fetchone()[0]
            == "旧会话"
        )
        assert (
            connection.execute("SELECT content FROM messages WHERE id='m_legacy'").fetchone()[0]
            == "旧消息"
        )
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
        assert (
            connection.execute("SELECT pinned FROM threads WHERE id='th_legacy'").fetchone()[0] == 0
        )
    finally:
        connection.close()
