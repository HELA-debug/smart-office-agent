"""0002 新增 V2.1 四张表（runs/run_events/settings/model_configs）与索引、列。

- 新表：runs / run_events / settings / model_configs
- 新列：threads.pinned、threads.deleted_at、artifacts.deleted_at、approvals.policy_version
- 索引：runs(thread_id, started_at)、run_events(run_id, seq)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    existing = _tables()

    if "runs" not in existing:
        op.create_table(
            "runs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("mode", sa.String(16), nullable=False, server_default="mock"),
            sa.Column("engine", sa.String(32), nullable=False, server_default="mock"),
            sa.Column("provider", sa.String(32), nullable=False, server_default="mock"),
            sa.Column("model", sa.String(80), nullable=False, server_default="mock-scripted"),
            sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_cny", sa.Float(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.String(40), nullable=False),
            sa.Column("finished_at", sa.String(40), nullable=True),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("extra", sa.JSON(), nullable=True),
        )
    if "ix_runs_thread_started" not in _indexes("runs"):
        op.create_index("ix_runs_thread_started", "runs", ["thread_id", "started_at"])

    if "run_events" not in existing:
        op.create_table(
            "run_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("event", sa.String(64), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
        )
    if "ix_run_events_run_seq" not in _indexes("run_events"):
        op.create_index("ix_run_events_run_seq", "run_events", ["run_id", "seq"])

    if "settings" not in existing:
        op.create_table(
            "settings",
            sa.Column("key", sa.String(120), primary_key=True),
            sa.Column("scope", sa.String(32), nullable=False, server_default="global"),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.String(40), nullable=False),
        )

    if "model_configs" not in existing:
        op.create_table(
            "model_configs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("base_url", sa.String(300), nullable=False, server_default=""),
            sa.Column("model", sa.String(120), nullable=False, server_default=""),
            sa.Column("api_key_ref", sa.String(200), nullable=False, server_default=""),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("extra", sa.JSON(), nullable=True),
        )

    if "threads" in _tables():
        columns = _columns("threads")
        if "pinned" not in columns:
            op.add_column(
                "threads",
                sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            )
        if "deleted_at" not in columns:
            op.add_column("threads", sa.Column("deleted_at", sa.String(40), nullable=True))

    if "artifacts" in _tables() and "deleted_at" not in _columns("artifacts"):
        op.add_column("artifacts", sa.Column("deleted_at", sa.String(40), nullable=True))

    if "approvals" in _tables() and "policy_version" not in _columns("approvals"):
        op.add_column(
            "approvals",
            sa.Column("policy_version", sa.String(32), nullable=False, server_default="v1"),
        )


def downgrade() -> None:
    op.drop_index("ix_run_events_run_seq", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_runs_thread_started", table_name="runs")
    op.drop_table("runs")
    op.drop_table("settings")
    op.drop_table("model_configs")
    op.drop_column("threads", "pinned")
    op.drop_column("threads", "deleted_at")
    op.drop_column("artifacts", "deleted_at")
    op.drop_column("approvals", "policy_version")
