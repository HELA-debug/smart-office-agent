"""0001 基线：对齐 v0.1 的四张表（threads/messages/approvals/artifacts）。

对已有 v0.1 SQLite 库做幂等处理：表已存在则跳过，保证 `alembic upgrade head`
既能在空库建库，也能在现有 data/app.db 上原地升级。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    existing = _tables()

    if "threads" not in existing:
        op.create_table(
            "threads",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("updated_at", sa.String(40), nullable=False),
            sa.Column("extra", sa.Text(), nullable=True),
        )

    if "messages" not in existing:
        op.create_table(
            "messages",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("extra", sa.Text(), nullable=True),
        )
        op.create_index("ix_messages_thread_created", "messages", ["thread_id", "created_at"])

    if "approvals" not in existing:
        op.create_table(
            "approvals",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=True),
            sa.Column("tool", sa.String(120), nullable=False),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("decision", sa.String(16), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("decided_at", sa.String(40), nullable=True),
            sa.Column("extra", sa.Text(), nullable=True),
        )
        op.create_index("ix_approvals_thread_run", "approvals", ["thread_id", "run_id"])

    if "artifacts" not in existing:
        op.create_table(
            "artifacts",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=True),
            sa.Column("type", sa.String(32), nullable=False),
            sa.Column("filename", sa.String(200), nullable=False),
            sa.Column("path", sa.String(500), nullable=False),
            sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("content_type", sa.String(120), nullable=False, server_default=""),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("extra", sa.Text(), nullable=True),
        )
        op.create_index("ix_artifacts_thread_run", "artifacts", ["thread_id", "run_id"])


def downgrade() -> None:
    # 基线不删除已有 v0.1 表：回滚 0002 后再手工处理
    pass
