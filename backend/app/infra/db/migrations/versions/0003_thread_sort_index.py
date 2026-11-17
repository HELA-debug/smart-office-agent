"""0003 会话支持手动排序：threads.sort_index。

左栏的会话行可以拖着换位置（用户要的「自由移动会话所处的位置」）。
顺序必须落库，否则刷新一次就回到「按最近更新」——拖了等于白拖。

- 新列：threads.sort_index（REAL，可空）。NULL = 没手动排过，仍按最近更新排；
  值越小越靠前，新建会话时取「当前最小值 - 1」插到最前面。
- 用 REAL 而不是 INTEGER：只调整被拖动的那一条时，取前后两条的中点，
  不必把整张表重编号（翻页时前端只知道自己这一页的 ID）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if "threads" in sa.inspect(op.get_bind()).get_table_names() and "sort_index" not in _columns(
        "threads"
    ):
        op.add_column("threads", sa.Column("sort_index", sa.Float(), nullable=True))


def downgrade() -> None:
    if "sort_index" in _columns("threads"):
        op.drop_column("threads", "sort_index")
