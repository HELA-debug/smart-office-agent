"""知识库检索 API：页面与 Agent 工具读同一份持久语料。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...domain.knowledge_store import knowledge_store

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeHitOut(BaseModel):
    id: str
    title: str
    source: str
    section: str = ""
    snippet: str
    kind: str
    tags: list[str] = Field(default_factory=list)
    score: float
    updatedAt: str = ""


class KnowledgeSearchOut(BaseModel):
    hits: list[KnowledgeHitOut] = Field(default_factory=list)
    total: int = Field(description="库内片段总量，不等于本次返回条数")
    level: str = Field(description="browsing | strong | weak | none")
    tookMs: float = 0.0
    passages: str = Field(default="", description="给 Agent 注入的带编号片段文本")


class KnowledgeStatsOut(BaseModel):
    blocks: int
    documents: int
    kinds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


@router.get("/search", response_model=KnowledgeSearchOut, summary="检索知识库语料片段")
async def search(q: str = "", top_k: int = Query(8, ge=1, le=50)) -> dict[str, Any]:
    return knowledge_store().search(q, top_k)


@router.get("/stats", response_model=KnowledgeStatsOut, summary="知识库语料规模")
async def stats() -> dict[str, Any]:
    return knowledge_store().stats()
