"""文件工具：file.list / file.read / file.search（低风险）+ file.delete（高风险，不动手就删不掉）。

**素材是这一层的主语**。解析后的正文只有两种命运：短素材整段注入，长素材
只注入开头。后者是幻觉的重灾区——模型不知道「后面还有」，会把没读到的部分
写成通顺的猜测，语气和真读到一样笃定。所以这里做两件事：

- 超长时给出**分节目录**，并明说「只注入了前 N 块、还剩多少块」；
- 提供 `file.search`，让它按问题取回具体片段，而不是靠印象补全。
"""

from __future__ import annotations

from typing import Any

from ...core.utils import count_chars, now_iso
from ...domain.rag import Index, format_passages, match_level, outline, pack_blocks, split_blocks
from ..spec import EFFECT_DESTRUCTIVE, ToolContext, tool

# 单次 file.read 注入给模型的正文预算。与引擎的 MATERIAL_OBSERVATION_LIMIT 对齐：
# 超过这个量再往里塞，模型对中段的注意力就开始掉，而账单是实打实的。
READ_BUDGET_CHARS = 24_000
# 目录本身也要占地方，先扣掉再装箱，免得「正文 + 目录」超预算又被引擎截一刀。
_OUTLINE_RESERVE = 1_500


def _sources_of(ctx: ToolContext, uploads: list[Any]) -> list[dict[str, Any]]:
    """把上传素材读成 `[{filename, text, chars, path}]`；解析失败的不进列表。"""
    sources: list[dict[str, Any]] = []
    for upload in uploads:
        text = ""
        if upload.text_path and ctx.storage.exists(upload.text_path):
            text = ctx.storage.read_text(upload.text_path)
        if not text.strip():
            continue
        # path 是给下游「搬运配图」用的（doc.generate_report 要把源 docx 里的照片嵌进摘要），
        # 只在本进程内传递，不写进材料正文、也不返回给模型
        sources.append(
            {
                "filename": upload.filename,
                "text": text,
                "chars": count_chars(text),
                "path": upload.path,
            }
        )
    return sources


def _index_of(ctx: ToolContext, sources: list[dict[str, Any]]) -> Index:
    """按素材清单缓存索引：一轮里模型可能检索十几次，不该每次重切几万字。"""
    key = "|".join(f"{source['filename']}:{source['chars']}" for source in sources)
    if ctx.rag_index is not None and ctx.rag_key == key:
        return ctx.rag_index
    index = Index(split_blocks(sources))
    ctx.rag_index = index
    ctx.rag_key = key
    return index


def _block_id(value: str) -> str:
    """`S3` / `s3` / `[3]` / `3` 都认成一个块号。"""
    token = str(value).strip().strip("[]").upper()
    return f"S{token}" if token.isdigit() else token


@tool("file.list", "列出当前会话已上传的素材文件（文件名、字数、解析状态）", risk="low")
def list_files(ctx: ToolContext, files: list[str] | None = None) -> dict[str, Any]:
    uploads = ctx.find_uploads(files)
    items: list[dict[str, Any]] = [
        {
            "filename": upload.filename,
            "chars": upload.chars,
            "ext": upload.ext,
            "parsed": upload.parsed,
        }
        for upload in uploads
    ]
    total = sum(item["chars"] for item in items)
    summary = (
        f"共 {len(items)} 个素材文件，合计 {total:,} 字"
        if items
        else "当前会话没有上传素材，将按默认模板生成"
    )
    return {"files": items, "count": len(items), "chars": total, "_summary": summary}


@tool(
    "file.read",
    "读取会话素材正文。短素材一次读完；超长时只给分节目录与前若干块，并说明还剩几块——"
    '此时用 file_search 按问题检索，或用 block_ids 指定块号（如 ["S12"]）补读。'
    "observation.material 就是本次注入的正文",
    risk="low",
)
def read_files(
    ctx: ToolContext,
    files: list[str] | None = None,
    block_ids: list[str] | None = None,
) -> dict[str, Any]:
    uploads = ctx.find_uploads(files)
    if not uploads:
        ctx.material_text = ""
        ctx.material_sources = []
        ctx.rag_index, ctx.rag_key = None, ""
        return {"files": [], "chars": 0, "_material": "", "_summary": "未找到可读取的素材文件"}

    sources = _sources_of(ctx, uploads)
    if not sources:
        # 收下的文件不一定读得出字：压缩包、未知格式、旧版 .doc 都落在这一档
        # （上传时已经收下并标了「读不出文字」）。这里如实说一句，
        # 别让模型对着「共 0 字」自己猜是工具坏了、还是文件本来就是空的。
        unreadable = "、".join(upload.filename for upload in uploads[:5])
        ctx.material_text = ""
        ctx.material_sources = []
        ctx.rag_index, ctx.rag_key = None, ""
        return {
            "files": [{"filename": upload.filename, "chars": upload.chars} for upload in uploads],
            "chars": 0,
            "blocks": 0,
            "readable": 0,
            "_material": "",
            "_summary": f"{unreadable} 里没有可读文字（压缩包、未知格式、旧版 .doc 都是这样），"
            "现在只能看到文件名；换一份能读出字的格式再试",
        }
    index = _index_of(ctx, sources)
    blocks = index.blocks
    # material_text 始终是**全文**：generate_report 要用它按模板抽句子，
    # 这里少给一段，产物里就少一段真实内容。注入给模型的才是按预算裁剪的版本。
    full = "\n\n".join(f"【{source['filename']}】\n{source['text']}" for source in sources)
    ctx.material_text = full
    ctx.material_sources = sources

    meta = [{"filename": upload.filename, "chars": upload.chars} for upload in uploads]
    total = sum(item["chars"] for item in meta)

    if block_ids:
        wanted = {_block_id(value) for value in block_ids if str(value).strip()}
        picked = [block for block in blocks if block.id in wanted]
        if not picked:
            return {
                "files": meta,
                "chars": total,
                "blocks": len(blocks),
                "_material": "",
                "_summary": f"没有找到块 {', '.join(sorted(wanted))}；"
                f"可用块号 S1–S{len(blocks)}，或先用 file_search 检索",
            }
        shown = "\n\n".join(f"{block.label}\n{block.text}" for block in picked)
        return {
            "files": meta,
            "chars": total,
            "blocks": len(blocks),
            "injected_blocks": len(picked),
            "truncated": len(picked) < len(blocks),
            "_material": shown,
            "_summary": f"已读取 {len(picked)} 块（{'、'.join(b.id for b in picked)}），"
            f"素材共 {len(blocks)} 块",
        }

    if total <= READ_BUDGET_CHARS or not blocks:
        return {
            "files": meta,
            "chars": total,
            "blocks": len(blocks),
            "injected_blocks": len(blocks),
            "truncated": False,
            "_material": full,
            "_summary": f"已读取 {len(meta)} 个文件，共 {total:,} 字",
        }

    body, injected = pack_blocks(blocks, READ_BUDGET_CHARS - _OUTLINE_RESERVE)
    remaining = len(blocks) - injected
    # 这句「还剩几块」是这轮改动的重点：以前截断了只说「已截断，可再次调用」，
    # 而单文件本身超限时再调一次还是同一个开头，模型只能猜。
    shown = (
        f"【素材分节目录】\n{outline(blocks)}\n\n"
        f"【只注入了前 {injected}/{len(blocks)} 块，还有 {remaining} 块没有注入】\n"
        "需要后面的内容：用 file_search 按问题检索（推荐），"
        '或用本工具 block_ids=["S12"] 指定块号。\n\n'
        f"{body}"
    )
    return {
        "files": meta,
        "chars": total,
        "blocks": len(blocks),
        "injected_blocks": injected,
        "remaining_blocks": remaining,
        "truncated": True,
        "_material": shown,
        "_summary": f"已读取 {len(meta)} 个文件，共 {total:,} 字；"
        f"正文过长，仅注入前 {injected}/{len(blocks)} 块",
    }


@tool(
    "file.search",
    "在会话素材里检索与问题相关的原文片段，返回带编号（S1/S2）的片段。"
    "回答具体事实、核对数字、确认「素材里到底有没有提到」时用它；"
    "file_read 只注入了开头时也用它取其余内容。"
    "match=none 表示素材里确实没有相关内容——此时如实说明，不要凭印象补",
    risk="low",
)
def search_material(
    ctx: ToolContext,
    query: str,
    files: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"match": "empty", "hits": [], "_passages": "", "_summary": "检索词为空"}

    uploads = ctx.find_uploads(files)
    if not uploads:
        return {
            "match": "empty",
            "hits": [],
            "_passages": "",
            "_summary": "当前会话没有可检索的素材",
        }

    # 缓存只在「覆盖了这次要搜的文件」时才用：上一轮 file.read 可能只读了 A，
    # 直接拿 material_sources 当全量，就会把 B 里的内容漏掉，还查不出是漏了。
    wanted_names = [upload.filename for upload in uploads]
    cached = {source["filename"]: source for source in ctx.material_sources}
    if cached and all(name in cached for name in wanted_names):
        sources = [cached[name] for name in wanted_names]
    else:
        sources = _sources_of(ctx, uploads)
    if not sources:
        return {
            "match": "empty",
            "hits": [],
            "_passages": "",
            "_summary": "素材还没有解析出正文（可能解析失败），无法检索",
        }

    index = _index_of(ctx, sources)
    if not len(index):
        return {"match": "empty", "hits": [], "_passages": "", "_summary": "素材没有可检索的内容"}

    try:
        limit = max(1, min(int(top_k or 5), 10))
    except (TypeError, ValueError):
        limit = 5
    hits = index.search(query, limit)
    level = match_level(hits)

    if level == "none":
        # 检索不到就不注入正文。给几段「沾边但不相关」的文字，模型更可能把它们
        # 当依据写成结论——那比直接说「没找到」糟得多。给小节标题是让它换个词再试。
        headings = [block.heading for block in index.blocks if block.heading]
        unique = list(dict.fromkeys(headings))[:8]
        hint = f"；素材包含的小节：{'、'.join(unique)}" if unique else ""
        return {
            "match": "none",
            "query": query,
            "hits": [],
            "blocks": len(index),
            "_passages": "",
            "_summary": f"素材里没有找到与「{query}」相关的内容{hint}。"
            "请如实说明素材未提及这一点，不要凭印象补数字、结论或出处。",
        }

    passages = format_passages(hits, len(index), level)
    summary = (
        f"在素材中找到 {len(hits)} 段相关内容（共 {len(index)} 块）"
        if level == "strong"
        else f"只找到 {len(hits)} 段相关度偏低的内容，使用前请逐条核对是否真的对得上问题"
    )
    return {
        "match": level,
        "query": query,
        "hits": [
            {
                "id": hit.block.id,
                "file": hit.block.file,
                "heading": hit.block.heading,
                "score": round(hit.score, 2),
                "coverage": round(hit.coverage, 2),
            }
            for hit in hits
        ],
        "blocks": len(index),
        "chars": sum(hit.block.chars for hit in hits),
        "_passages": passages,
        "_summary": summary,
    }


@tool(
    "file.delete",
    "删除当前会话的产物文件（软删：文件移入回收站，记录保留供审计）",
    risk="high",
    # 删除是唯一「做完收不回来」的动作：写产物只需要他让你动手，删除要他说清
    # 删的是哪一份。分档给门控，别和「生成一份新文件」共用一个门槛。
    effect=lambda _args: EFFECT_DESTRUCTIVE,
)
def delete_files(ctx: ToolContext, files: list[str] | None = None) -> dict[str, Any]:
    """删除本会话产物；高危操作，命中审批规则时先暂停等待人工确认。

    作用域严格限制在当前会话（thread_id）内，且不允许删除会话素材（上传文件）。
    """
    candidates = ctx.artifacts.list(thread_id=ctx.thread_id, include_deleted=False, limit=500)
    wanted = {name.strip() for name in (files or []) if name and name.strip()}
    if wanted:
        targets = [item for item in candidates if item.filename in wanted]
        missing = sorted(wanted - {item.filename for item in targets})
    else:
        # 未指定文件名时只删本次运行刚产生的产物，避免误删历史产物
        run_ids = {ctx.run_id}
        targets = [item for item in candidates if item.run_id in run_ids]
        missing = []

    if not targets:
        return {
            "deleted": [],
            "count": 0,
            "missing": missing,
            "_summary": "没有可删除的产物（未匹配到当前会话的产物文件）",
        }

    deleted: list[dict[str, Any]] = []
    trashed: list[str] = []
    for artifact in targets:
        moved = ctx.storage.trash(artifact.path)
        if moved:
            trashed.append(moved)
        extra = artifact.extra or {}
        for key in ("text_path", "preview_path"):
            candidate = extra.get(key)
            if candidate and ctx.storage.exists(str(candidate)):
                moved = ctx.storage.trash(str(candidate))
                if moved:
                    trashed.append(moved)
        ctx.artifacts.soft_delete(artifact.id, now_iso())
        if artifact.id in ctx.artifact_ids:
            ctx.artifact_ids.remove(artifact.id)
        deleted.append({"artifact_id": artifact.id, "filename": artifact.filename})

    summary = f"已删除 {len(deleted)} 个产物（文件已移入回收站）"
    if missing:
        summary += f"；未找到：{', '.join(missing[:5])}"
    return {
        "deleted": deleted,
        "count": len(deleted),
        "missing": missing,
        "trashed": trashed,
        "_summary": summary,
    }
