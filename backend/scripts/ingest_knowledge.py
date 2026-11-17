"""往知识库里「加书」：把目录里的文档切成片段，增量写进持久语料库。

可反复运行，按 (来源 + 正文) 的哈希去重；--source DIR 可以反复追加新资料，
这就是从「一批示例」长成「图书馆」的入口。默认把项目内已有的跨领域文档
（docs/ 与根目录几份 md）作为第一批真实语料灌进去——合规、离线、无需外部授权。

后续接更多形态：docx / pdf / xlsx 走 infra.parsing.parse_bytes，
srt / vtt 走 media 转写，网页走抓取器；本脚本只负责「切块 + 去重 + 落盘」。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import DATA_ROOT  # noqa: E402
from app.domain.rag import split_blocks  # noqa: E402

TEXT_EXTS = {".md", ".markdown", ".txt", ".srt", ".vtt", ".csv", ".json", ".jsonl", ".html", ".htm"}
DEFAULT_SOURCES = [REPO_ROOT / "docs"] + [
    REPO_ROOT / name
    for name in ("README.md", "CHANGELOG.md", "KNOWN_ISSUES.md", "PROJECT_ANALYSIS.md")
]


def kind_of(ext: str) -> str:
    if ext in {".csv", ".jsonl"}:
        return "spreadsheet"
    if ext in {".srt", ".vtt"}:
        return "transcript"
    if ext in {".json"}:
        return "structured"
    if ext in {".html", ".htm"}:
        return "webpage"
    return "document"


def tags_of(relative: Path) -> list[str]:
    parts = [part for part in relative.parts[:-1] if part not in {".", ".."}]
    return parts[:2] or ["通用"]


def collect(paths: list[Path]) -> list[dict[str, Any]]:
    """目录递归 / 单文件，统一成 [{filename, text, kind, tags, date}]。"""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in TEXT_EXTS))
        elif path.is_file() and path.suffix.lower() in TEXT_EXTS:
            files.append(path)
    sources: list[dict[str, Any]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        try:
            relative = path.relative_to(REPO_ROOT)
        except ValueError:
            relative = Path(path.name)
        stat = path.stat()
        sources.append(
            {
                "filename": relative.as_posix(),
                "text": text,
                "kind": kind_of(path.suffix.lower()),
                "tags": tags_of(relative),
                "date": datetime.fromtimestamp(stat.st_mtime).date().isoformat(),
            }
        )
    return sources


def load_existing(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            seen.add(str(json.loads(line).get("sha") or ""))
        except ValueError:
            continue
    seen.discard("")
    return seen


def main() -> None:
    parser = argparse.ArgumentParser(description="增量灌入知识库语料")
    parser.add_argument("--source", action="append", default=[], help="额外资料目录/文件，可重复")
    parser.add_argument(
        "--out", default=None, help="语料文件（默认 DATA_ROOT/data/knowledge/corpus.jsonl）"
    )
    parser.add_argument("--reset", action="store_true", help="清空后重灌（默认增量追加）")
    args = parser.parse_args()

    out = Path(args.out) if args.out else DATA_ROOT / "data" / "knowledge" / "corpus.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.reset:
        out.write_text("", encoding="utf-8")

    sources = collect(DEFAULT_SOURCES + [Path(item) for item in args.source])
    meta = {item["filename"]: item for item in sources}
    blocks = split_blocks(sources)
    seen = load_existing(out)
    added = 0
    with out.open("a", encoding="utf-8") as handle:
        for block in blocks:
            digest = hashlib.sha256(f"{block.file}\n{block.text}".encode()).hexdigest()[:16]
            if digest in seen:
                continue
            seen.add(digest)
            info = meta.get(block.file, {})
            handle.write(
                json.dumps(
                    {
                        "id": f"K{digest[:12]}",
                        "sha": digest,
                        "source": block.file,
                        "section": block.heading,
                        "text": block.text,
                        "kind": info.get("kind") or "document",
                        "tags": info.get("tags") or [],
                        "updated_at": info.get("date") or "",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            added += 1

    total = sum(1 for line in out.read_text(encoding="utf-8").splitlines() if line.strip())
    print(f"新增片段 {added} · 语料总量 {total} · 来源文档 {len(sources)} · 文件 {out}")


if __name__ == "__main__":
    main()
