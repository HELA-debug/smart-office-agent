#!/usr/bin/env python
"""导出契约快照（V2.1）：OpenAPI v1 + SSE 事件 JSON Schema。

产物（入库，CI `contract` 门禁校验 diff 为空）：
    contracts/openapi.v1.json           # FastAPI 生成的 OpenAPI 3.x（/api/v1 全量）
    contracts/events.v1.schema.json     # SSE 帧 + 事件 data 的 JSON Schema（draft-07）

用法：
    python scripts/export_openapi.py                 # 写入 contracts/
    python scripts/export_openapi.py --check         # 只校验快照是否与代码一致（不写文件）
    python scripts/export_openapi.py --output-dir /tmp/contracts

设计约束：
- 不读取/打印任何密钥；导入 app 时强制 MOCK_MODE=true、内存数据库，避免副作用。
- 输出确定性（sort_keys + 固定缩进 + 末尾换行），保证「导出→diff」稳定。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"

# 导入 app 前先隔离：mock 模式、内存库、临时存储目录（不触碰 data/ 与 .env 中的真实 Key）。
os.environ["MOCK_MODE"] = "true"
os.environ["MODEL_PROVIDER"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
sys.path.insert(0, str(ROOT / "backend"))

from app.core.events import (  # noqa: E402
    EVENT_NAMES,
    EVENT_VERSION,
    REQUIRED_FIELDS,
    TERMINAL_EVENTS,
)
from app.main import app  # noqa: E402


def dump_json(data: Any, *, sort_keys: bool = True) -> str:
    """确定性 JSON 序列化（供快照 diff 使用）。

    OpenAPI 保留声明顺序（与 /openapi.json 完全一致，前端 openapi-typescript
    从快照生成的结果才能与从服务端生成的结果逐字节一致）；事件 Schema 用 sort_keys。
    """
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n"


def build_openapi() -> dict[str, Any]:
    return app.openapi()


def build_events_schema() -> dict[str, Any]:
    """由 core/events.py 的单一事实来源生成 SSE 帧 JSON Schema（draft-07）。"""
    common_props: dict[str, Any] = {
        "version": {"const": EVENT_VERSION, "description": "事件协议版本，当前固定 1"},
        "run_id": {"type": "string", "minLength": 1, "description": "本次运行 ID"},
        "trace_id": {"type": "string", "description": "请求追踪 ID（可选）"},
    }
    # 每类事件的 data 必填字段条件（if event == X then data.required 包含 ...）
    per_event: list[dict[str, Any]] = []
    for name in EVENT_NAMES:
        required = ["version", "run_id", *REQUIRED_FIELDS.get(name, ())]
        per_event.append(
            {
                "if": {"properties": {"event": {"const": name}}},
                "then": {"properties": {"data": {"required": required}}},
            }
        )

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "contracts/events.v1.schema.json",
        "title": "office-agent SSE frame v1.1（只追加）",
        "description": (
            "POST /api/v1/threads/{thread_id}/runs/stream 的 SSE 帧与 data 契约。"
            "version 固定为 1；v1.1 仅追加 run.cancelled / tool.started / heartbeat，"
            "不修改 v1 已有事件语义。"
        ),
        "type": "object",
        "required": ["id", "event", "data"],
        "additionalProperties": False,
        "properties": {
            "id": {
                "type": "integer",
                "minimum": 1,
                "description": "事件序号，与 run_events.seq 一致（从 1 递增）",
            },
            "event": {"enum": list(EVENT_NAMES)},
            "data": {
                "type": "object",
                "required": ["version", "run_id"],
                "additionalProperties": True,
                "properties": common_props,
            },
        },
        "allOf": per_event,
        "x-terminal-events": sorted(TERMINAL_EVENTS),
        "x-event-version": EVENT_VERSION,
    }


def write_or_check(path: Path, payload: dict[str, Any], check: bool, *, sort_keys: bool) -> bool:
    content = dump_json(payload, sort_keys=sort_keys)
    if check:
        if not path.exists():
            print(f"[MISS] {path} 不存在，请先运行：python scripts/export_openapi.py")
            return False
        existing = path.read_text(encoding="utf-8")
        if existing != content:
            print(f"[DIFF] {path} 与代码不一致（契约变更需提交快照并说明兼容性）")
            return False
        print(f"[OK]   {path}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"[WRITE] {path}（{len(content)} 字符）")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出/校验 OpenAPI 与事件契约快照")
    parser.add_argument("--output-dir", default=str(CONTRACTS_DIR), help="输出目录")
    parser.add_argument("--check", action="store_true", help="只校验快照是否最新，不写文件")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    openapi = build_openapi()
    events = build_events_schema()

    ok = True
    ok &= write_or_check(out_dir / "openapi.v1.json", openapi, args.check, sort_keys=False)
    ok &= write_or_check(out_dir / "events.v1.schema.json", events, args.check, sort_keys=True)

    if not ok:
        return 1
    if not args.check:
        paths = len(openapi.get("paths", {}))
        operations = sum(len(item) for item in openapi.get("paths", {}).values())
        print(
            f"完成：{paths} 条路径 / {operations} 个操作 / {len(EVENT_NAMES)} 类事件"
            f"（event version={EVENT_VERSION}）"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
