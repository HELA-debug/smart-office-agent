"""数据库会话与 Alembic 迁移执行。SQLite / PostgreSQL 共用同一迁移链。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ...core.config import DATA_ROOT, Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def build_database_url(settings: Settings) -> str:
    """SQLite 相对路径统一解析为数据根下绝对路径，避免受启动 cwd 影响。

    数据根：源码态 = 仓库根，打包态 = 用户数据目录（见 core/paths.py）。
    """
    url = settings.database_url
    if url.startswith("sqlite:///") and ":memory:" not in url:
        raw = url.split("sqlite:///", 1)[-1]
        path = Path(raw)
        if not path.is_absolute():
            path = DATA_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"
    return url


def create_database_engine(url: str) -> Engine:
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """短事务上下文：正常退出 commit，异常 rollback，最后关闭。"""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Database:
    def __init__(self, settings: Settings):
        self.url = build_database_url(settings)
        self.engine = create_database_engine(self.url)
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        with session_scope(self.session_factory) as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()


def run_migrations(settings: Settings) -> None:
    """启动时执行 `alembic upgrade head`（空库建表 / v0.1 旧库原地升级均幂等）。"""
    import logging

    from alembic import command
    from alembic.config import Config

    # Alembic 自身日志降噪（启动时只关心业务日志）
    logging.getLogger("alembic").setLevel(logging.WARNING)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", build_database_url(settings))
    command.upgrade(config, "head")
