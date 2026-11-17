"""提示词包：把《Agent 提示词合集》里的 7 段规范做成按需求路由注入的片段。

为什么不在 system.md 里全量堆进去：7 段规范合起来近万字符，每轮都塞给模型既贵又会互相干扰
（文档排版规范对表格清洗没有任何帮助）。这里按本轮用户消息匹配 1–2 段最相关的注入，
既保证「专业规范在场」，又不把上下文撑爆。

包文件：`app/prompts/packs/*.md`，首行注释声明元数据：
`<!-- id: doc-decision; title: 文档处理·多方案决策; keywords: 排版,格式,... -->`
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PACK_DIR = Path(__file__).resolve().parents[1] / "prompts" / "packs"

MAX_PACKS_PER_RUN = 2
"""一轮最多注入几段：再多就开始互相打断（典型是「整理成周报」同时像排版又像摘要）。"""

MAX_INJECT_CHARS = 4200
"""注入总字符上限：超过就把后面匹配度低的包丢掉，避免挤占素材正文的上下文。"""

_HEADER_RE = re.compile(r"^<!--\s*(?P<body>.*?)\s*-->\s*$", re.S)


@dataclass(frozen=True)
class PromptPack:
    id: str
    title: str
    keywords: tuple[str, ...]
    body: str
    path: str = ""

    def score(self, text: str) -> int:
        """关键词命中计分：长关键词更具体，权重更高（「前端评审」比「整理」更能说明意图）。"""
        lowered = text.lower()
        total = 0
        for keyword in self.keywords:
            needle = keyword.lower()
            if needle and needle in lowered:
                total += 3 if len(needle) >= 3 else 2
        return total

    def to_dict(self) -> dict[str, Any]:
        # body 一起返回：界面要把规范原文摊开给人看（只读），
        # 单独再给个「读单个包」的接口不值当——7 段加起来才几 KB。
        return {
            "id": self.id,
            "title": self.title,
            "keywords": list(self.keywords),
            "chars": len(self.body),
            "body": self.body,
        }


def _parse(path: Path) -> PromptPack | None:
    text = path.read_text(encoding="utf-8")
    match = _HEADER_RE.match(text.split("\n", 1)[0])
    meta: dict[str, str] = {}
    if match:
        for part in match.group("body").split(";"):
            if ":" in part:
                key, value = part.split(":", 1)
                meta[key.strip()] = value.strip()
        text = text.split("\n", 1)[1] if "\n" in text else ""
    title = meta.get("title") or path.stem
    body = text.strip()
    if not body:
        return None
    keywords = tuple(item.strip() for item in meta.get("keywords", "").split(",") if item.strip())
    return PromptPack(
        id=meta.get("id") or path.stem,
        title=title,
        keywords=keywords,
        body=body,
        path=str(path),
    )


@lru_cache(maxsize=1)
def _load_cached(directory: str, stamp: tuple[tuple[str, float], ...]) -> tuple[PromptPack, ...]:
    # stamp 参与缓存键：改 md 文件后自动重载（本地开发期体验，不用重启）
    del stamp
    packs: list[PromptPack] = []
    for path in sorted(Path(directory).glob("*.md")):
        pack = _parse(path)
        if pack is not None:
            packs.append(pack)
    return tuple(packs)


def load_packs(directory: Path | None = None) -> tuple[PromptPack, ...]:
    target = directory or PACK_DIR
    try:
        stamp = tuple((str(item), item.stat().st_mtime) for item in sorted(target.glob("*.md")))
    except OSError:
        return ()
    return _load_cached(str(target), stamp)


@dataclass
class PromptPackService:
    directory: Path = field(default_factory=lambda: PACK_DIR)

    def list_packs(self) -> list[dict[str, Any]]:
        return [pack.to_dict() for pack in load_packs(self.directory)]

    def select(self, message: str) -> list[PromptPack]:
        text = (message or "").strip()
        if not text:
            return []
        scored = [(pack.score(text), pack) for pack in load_packs(self.directory)]
        hits = sorted((item for item in scored if item[0] > 0), key=lambda item: -item[0])
        return [pack for _, pack in hits[:MAX_PACKS_PER_RUN]]

    def render(self, message: str) -> str:
        packs = self.select(message)
        if not packs:
            return ""
        blocks: list[str] = []
        used = 0
        for pack in packs:
            body = pack.body
            if used + len(body) > MAX_INJECT_CHARS:
                continue
            used += len(body)
            blocks.append(f"## {pack.title}\n{body}")
        if not blocks:
            return ""
        header = "# 本轮任务规范（按需求匹配，冲突时以用户明确要求优先）"
        return header + "\n\n" + "\n\n".join(blocks)
