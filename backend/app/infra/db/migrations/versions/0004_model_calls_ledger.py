"""0004 新增 model_calls 表：模型调用全量账本。

## 为什么需要它

`runs.extra.usage` 只统计「运行内、成功」的调用，拿它和供应商控制台对账必然
对不上（实测同一天：应用内 ¥0.43 / 153 次，控制台 ¥2.72 / 1909 次）。差的
那部分不是算错，是根本没被记过：

- 连通性探测、会话标题、提示词增强、技能起草 —— 不属于任何一次 run；
- 限流重试、max_tokens 截断后的放大重试、供应商切换 —— 失败的请求也计费。

这张表逐条记，`run_id` 允许为空，正是为了让「run 外的钱」有地方落。

## 历史补不回来

表是空的，历史请求的 token 已经丢了。所以审计页必须同时给出 `since`
（账本从哪一刻开始完整），否则用户会拿一段不完整的账去对一整个月的账单。

索引按三个真实查询建：按时间倒序翻页、按 run 回查、按用途分组。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "model_calls" in _tables():
        return
    op.create_table(
        "model_calls",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("purpose", sa.String(length=24), nullable=False, server_default="engine"),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_miss_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cny", sa.Float(), nullable=False, server_default="0"),
        sa.Column("peak", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_model_calls_created", "model_calls", ["created_at"])
    op.create_index("ix_model_calls_run", "model_calls", ["run_id"])
    op.create_index("ix_model_calls_purpose", "model_calls", ["purpose", "created_at"])


def downgrade() -> None:
    if "model_calls" not in _tables():
        return
    op.drop_index("ix_model_calls_purpose", table_name="model_calls")
    op.drop_index("ix_model_calls_run", table_name="model_calls")
    op.drop_index("ix_model_calls_created", table_name="model_calls")
    op.drop_table("model_calls")
