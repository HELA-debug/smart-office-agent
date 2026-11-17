#!/usr/bin/env python
"""四张表导出 / 回灌脚本（计划书 7.5「数据导出」、附录 A E10）。

用法：
    python scripts/export.py                          # 导出到 data/export/export.json
    python scripts/export.py --out backup.json        # 指定输出文件
    python scripts/export.py --db data/app.db         # 指定 SQLite 文件
    python scripts/export.py --import backup.json     # 回灌（默认 upsert）
    python scripts/export.py --import backup.json --replace   # 先清空目标表再写入

支持 DATABASE_URL=sqlite:///data/app.db 形式；PostgreSQL 需安装 psycopg 后自行扩展（见下）。
导出结构：
    {"version":1,"exported_at":"...","source":"...","tables":{
        "threads":[...],"messages":[...],"approvals":[...],"artifacts":[...]}}
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

TABLES = ["threads", "messages", "approvals", "artifacts"]
DEFAULT_OUT = Path("data/export/export.json")
DEFAULT_DATABASE_URL = "sqlite:///data/app.db"


def sqlite_path(database_url: str | None, db_override: str | None) -> Path:
    """把 DATABASE_URL 解析成 SQLite 文件路径。"""
    if db_override:
        return Path(db_override)
    url = database_url or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    # sqlite:///data/app.db → data/app.db；sqlite:////app/data/app.db → /app/data/app.db
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):] or "data/app.db")
    raise SystemExit(
        f"不支持的 DATABASE_URL：{url}\n"
        "本脚本内置 SQLite 实现。PostgreSQL 导出可安装 psycopg 后按 TABLES 列表扩展读取逻辑。"
    )


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def export_data(db: Path) -> dict[str, Any]:
    if not db.exists():
        raise SystemExit(
            f"数据库文件不存在：{db}\n"
            "先在 mock 模式下建会话/上传/跑一次任务（或确认 DATABASE_URL）后再导出。"
        )

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        tables: dict[str, list[dict[str, Any]]] = {}
        for name in TABLES:
            if not table_exists(conn, name):
                tables[name] = []
                continue
            rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
            # 按 created_at 排序（若有），保证导出可比对
            columns = rows[0].keys() if rows else []
            if "created_at" in columns:
                rows = sorted(rows, key=lambda r: str(r["created_at"] or ""))
            tables[name] = [dict(r) for r in rows]
    finally:
        conn.close()

    return {
        "version": 1,
        "exported_at": _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "source": str(db),
        "tables": tables,
    }


def import_data(db: Path, payload: dict[str, Any], replace: bool) -> dict[str, int]:
    tables = payload.get("tables") or {}
    conn = sqlite3.connect(db)
    counts: dict[str, int] = {}
    try:
        conn.execute("PRAGMA foreign_keys=OFF")  # 回灌允许乱序，先关外键
        for name in TABLES:
            rows = tables.get(name) or []
            if not table_exists(conn, name):
                print(f"  [跳过] 表 {name} 不存在（请先建表/迁移）", file=sys.stderr)
                counts[name] = 0
                continue
            if replace:
                conn.execute(f'DELETE FROM "{name}"')
            if rows:
                # 按目标表现有列裁剪，兼容导出后新增列的情况
                existing_cols = {
                    r[1] for r in conn.execute(f'PRAGMA table_info("{name}")').fetchall()
                }
                cols = [c for c in rows[0].keys() if c in existing_cols]
                placeholders = ",".join("?" for _ in cols)
                col_sql = ",".join(f'"{c}"' for c in cols)
                sql = f'INSERT OR REPLACE INTO "{name}" ({col_sql}) VALUES ({placeholders})'
                conn.executemany(sql, [[row.get(c) for c in cols] for row in rows])
            counts[name] = len(rows)
        conn.commit()
    finally:
        conn.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出/回灌 threads/messages/approvals/artifacts")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="导出文件路径")
    parser.add_argument("--db", default=None, help="SQLite 文件路径（优先于 DATABASE_URL）")
    parser.add_argument("--database-url", default=None, help="覆盖 DATABASE_URL")
    parser.add_argument("--import", dest="import_file", default=None, help="回灌的 JSON 文件")
    parser.add_argument("--replace", action="store_true", help="回灌前清空目标表")
    args = parser.parse_args(argv)

    db = sqlite_path(args.database_url, args.db)

    if args.import_file:
        src = Path(args.import_file)
        if not src.exists():
            raise SystemExit(f"导入文件不存在：{src}")
        payload = json.loads(src.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            print(f"警告：导出文件 version={payload.get('version')}，当前支持 v1", file=sys.stderr)
        db.parent.mkdir(parents=True, exist_ok=True)
        counts = import_data(db, payload, args.replace)
        print(f"已回灌到 {db}：", ", ".join(f"{k}={v}" for k, v in counts.items()))
        return 0

    payload = export_data(db)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = ", ".join(f"{k}={len(v)}" for k, v in payload["tables"].items())
    print(f"已导出到 {out}（{out.stat().st_size} 字节）：{summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
