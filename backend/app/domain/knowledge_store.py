"""知识库检索服务：持久化语料 → 可检索索引，页面与 Agent 工具共用一条链。

语料是 scripts/ingest_knowledge.py 灌进来的 ``DATA_ROOT/data/knowledge/corpus.jsonl``，
每行一个片段。索引按文件 mtime + size 缓存，加书之后下一次请求自动重建。

规模边界（写清楚，别把这一层误当成「海量」已完成）：
当前是内存 BM25（domain/rag.py），几万块以内够用；到十万 / 百万级要换成
FTS5 / 向量服务 + embedding / rerank，但 ``search()`` 的返回形状不变，
上层页面和 knowledge.search 工具都不用改——这就是留给后续大规模化的接口。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import DATA_ROOT
from .rag import Block, Index, format_passages, match_level

CORPUS_PATH = DATA_ROOT / "data" / "knowledge" / "corpus.jsonl"


@dataclass(frozen=True)
class Passage:
    id: str
    source: str
    section: str
    text: str
    kind: str
    tags: tuple[str, ...]
    updated_at: str

    def to_block(self) -> Block:
        return Block(
            id=self.id,
            file=self.source,
            seq=0,
            heading=self.section,
            text=self.text,
            start=0,
        )


class KnowledgeStore:
    """只读语料库；写入一律走灌入脚本，避免运行中的请求改动语料。"""

    def __init__(self, path: Path = CORPUS_PATH) -> None:
        self.path = path
        self._stamp: tuple[int, int] | None = None
        self._passages: list[Passage] = []
        self._index: Index | None = None

    def _stamp_of(self) -> tuple[int, int]:
        try:
            stat = self.path.stat()
        except OSError:
            return (0, 0)
        return (stat.st_mtime_ns, stat.st_size)

    def _load(self) -> None:
        stamp = self._stamp_of()
        if self._index is not None and self._stamp == stamp:
            return
        passages: list[Passage] = []
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except ValueError:
                    continue
                passages.append(
                    Passage(
                        id=str(raw.get("id") or ""),
                        source=str(raw.get("source") or ""),
                        section=str(raw.get("section") or ""),
                        text=str(raw.get("text") or ""),
                        kind=str(raw.get("kind") or "document"),
                        tags=tuple(str(tag) for tag in (raw.get("tags") or [])),
                        updated_at=str(raw.get("updated_at") or ""),
                    )
                )
        self._passages = passages
        self._index = Index([passage.to_block() for passage in passages])
        self._stamp = stamp

    def stats(self) -> dict[str, Any]:
        self._load()
        return {
            "blocks": len(self._passages),
            "documents": len({passage.source for passage in self._passages}),
            "kinds": sorted({passage.kind for passage in self._passages}),
            "tags": sorted({tag for passage in self._passages for tag in passage.tags})[:40],
        }

    def _hit(self, passage: Passage, score: float) -> dict[str, Any]:
        return {
            "id": passage.id,
            "title": passage.section or passage.source,
            "source": passage.source,
            "section": passage.section,
            "snippet": passage.text,
            "kind": passage.kind,
            "tags": list(passage.tags),
            "score": round(score, 4),
            "updatedAt": passage.updated_at,
        }

    def search(self, query: str, top_k: int = 8) -> dict[str, Any]:
        started = time.perf_counter()
        self._load()
        index = self._index
        if index is None:  # 不会发生：_load 必然赋值；显式兜住类型检查
            index = Index([])
        limit = max(1, min(top_k, 50))

        # 空查询 = 浏览书架（前 N 块），不假装是「检索命中」
        if not query.strip():
            hits = [self._hit(passage, 0.0) for passage in self._passages[:limit]]
            return {
                "hits": hits,
                "total": len(self._passages),
                "level": "browsing",
                "tookMs": round((time.perf_counter() - started) * 1000, 2),
                "passages": "",
            }

        ranked = index.search(query, top_k=limit)
        by_id = {passage.id: passage for passage in self._passages}
        hits = [
            self._hit(by_id[hit.block.id], hit.score) for hit in ranked if hit.block.id in by_id
        ]
        level = match_level(ranked)
        return {
            "hits": hits,
            "total": len(self._passages),
            "level": level,
            "tookMs": round((time.perf_counter() - started) * 1000, 2),
            "passages": format_passages(ranked, len(self._passages), level) if ranked else "",
        }


_STORE = KnowledgeStore()


def knowledge_store() -> KnowledgeStore:
    return _STORE
