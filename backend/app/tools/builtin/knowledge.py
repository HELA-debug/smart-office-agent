"""knowledge.search：Agent 从持久化知识库按需取片段。

与页面 /knowledge/search 共用 KnowledgeStore，命中片段带 [K…] 编号，
成文时可以回溯到出处；检索不到时 level=none，明确告诉模型「没找到」，别编。
"""

from __future__ import annotations

from typing import Any

from ...domain.knowledge_store import knowledge_store
from ..spec import ToolContext, tool


@tool(
    "knowledge.search",
    "检索知识库：按问题召回跨领域语料片段（带引用编号，成文时可引用）",
    risk="low",
)
def knowledge_search(ctx: ToolContext, query: str, top_k: int = 5) -> dict[str, Any]:
    del ctx  # 只读全局语料库，不需要会话里的上传素材
    result = knowledge_store().search(query, top_k)
    return {
        "ok": True,
        "query": query,
        "level": result["level"],
        "total_blocks": result["total"],
        "passages": result["passages"],
        "hits": [
            {
                "id": hit["id"],
                "source": hit["source"],
                "section": hit["section"],
                "score": hit["score"],
            }
            for hit in result["hits"]
        ],
    }
