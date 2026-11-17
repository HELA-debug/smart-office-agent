"""技能草稿：让「当前配的那个模型」把一句话需求写成一张能用的 SKILL.md。

为什么这件事放后端而不是前端拼提示词：

- 技能文件的格式有硬约束（frontmatter 里的 name / title / description / triggers），
  模型自由发挥经常漏字段、加 code fence、把说明也写进去；后端能当场补齐与清洗，
  前端只负责展示预览和一键导入。
- 「现在到底有没有可用模型」只有后端知道（演示模式、没配 Key、Key 失效都算没有）。
  没模型时优雅降级成本地骨架，用户照样能拿到一张便签去改，不会看到红色报错。

产物始终是一份合法的 SKILL.md 文本，交给既有的导入接口校验与落盘，
所以「模型写」和「手写」走的是同一条路径，不存在第二套入库逻辑。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..core.logging import get_logger

logger = get_logger("app.services.skill_drafter")

# 一张便签不该比这更长：超了说明模型在写作文，不是写操作步骤
MAX_DRAFT_CHARS = 8000
MAX_IDEA_CHARS = 300
TIMEOUT_SECONDS = 45.0

# 图标键与前端 ICON_EXPORTS 对齐；给错就干脆不写，让前端用默认图标
_ALLOWED_ICONS = {
    "doc",
    "sheet",
    "minutes",
    "retro",
    "shield",
    "book",
    "terminal",
    "folder",
    "list",
    "puzzle",
}

# 分类沿用技能页的筛选口径
_ALLOWED_CATEGORIES = ("办公文档", "表格数据", "会议协作", "内容写作", "文件处理")

_FRONTMATTER_KEYS = ("name", "title", "description", "triggers", "category", "icon")

_SYSTEM_PROMPT = """你是「技能便签」作者。用户会用一句话说他想要什么效果，你要把它写成一张技能便签。

严格按下面的格式输出，除了这份文件内容不要写任何解释、不要加代码块围栏：

---
name: 英文或中文短语，全小写，用短横线连接
title: 6 到 12 个字的展示名
description: 一句话说清这个技能帮人做什么（不超过 40 字）
triggers: [用户可能说到的词1, 词2, 词3, 词4]
category: 办公文档 / 表格数据 / 会议协作 / 内容写作 / 文件处理 里选一个
icon: doc / sheet / minutes / retro / shield / book / terminal / folder / list / puzzle 里选一个
---

# 怎么做

1. 第一步具体做什么
2. 第二步具体做什么
3. 最后怎么自查

# 注意

- 三到五条「容易做错的地方」

写作要求：
- 每一条都要是能直接执行的动作，不要写「根据需求处理」这种空话；
- 步骤控制在 3 到 6 步，全文 300 到 900 字；
- 不虚构材料里没有的数字、人名、日期；
- 用第二人称「你」或祈使句，不要写「本技能」；
- 如果用户提到字数、格式、篇幅，必须写进要求里。"""


def _squash(text: str) -> str:
    return " ".join((text or "").split())


def _slugify(text: str, fallback: str = "my-skill") -> str:
    """把任意文本压成可做目录名的短标识（保留中文，其余换成短横线）。"""
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", text or "").strip("-").lower()
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:32] or fallback


def _unique_name(base: str, taken: set[str]) -> str:
    """撞名就加数字后缀：导入接口遇到同名会 409，用户没必要为此重来一次。"""
    if base not in taken:
        return base
    for index in range(2, 100):
        candidate = f"{base}-{index}"
        if candidate not in taken:
            return candidate
    return f"{base}-{len(taken) + 1}"


def _strip_fence(text: str) -> str:
    """模型常把整份文件塞进 ```markdown 里，导进去 frontmatter 就不是第一行了。"""
    body = (text or "").strip()
    if not body.startswith("```"):
        return body
    body = re.sub(r"^```[a-zA-Z]*\s*", "", body)
    return re.sub(r"\s*```$", "", body).strip()


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """极简 frontmatter 解析：只认 `key: value`，够用且不会引入 YAML 依赖。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        if key in _FRONTMATTER_KEYS:
            meta[key] = value.strip()
    return meta, parts[2].lstrip("\n")


def _parse_triggers(raw: str) -> list[str]:
    """`[周报, 写周报]` / `周报，写周报` 两种写法都吃得下，顺带去重。"""
    body = (raw or "").strip().strip("[]")
    pieces = re.split(r"[,，、;；|]", body)
    seen: list[str] = []
    for piece in pieces:
        item = piece.strip().strip("\"'“”‘’")
        if item and item not in seen:
            seen.append(item)
    return seen[:8]


def _format_triggers(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]"


def _fallback_meta(idea: str, taken: set[str]) -> dict[str, Any]:
    """模型没给出可用字段时，用用户那句话本身凑一份能用的元信息。"""
    short = _squash(idea)
    title = short[:16] or "我的技能"
    return {
        "name": _unique_name(_slugify(short, "my-skill"), taken),
        "title": title,
        "description": short[:60],
        "triggers": [word for word in [short[:8], short[:4]] if word],
    }


def _local_body(idea: str) -> str:
    return (
        "# 怎么做\n\n"
        f"1. 先读我这次给的素材，确认要做的是「{idea}」这件事\n"
        "2. 按上面的要求一步一步做，中途不要跳步\n"
        "3. 做完自己检查一遍：该有的部分齐不齐、有没有编造的内容\n"
        "4. 最后给一句结论，说明这次交付了什么\n\n"
        "# 注意\n\n"
        "- 材料里没有的数字、人名、日期不要编\n"
        "- 拿不准的地方直接标出来，不要猜\n"
        "- 篇幅按我说的来，我加码就压缩重点，不要删结论\n"
    )


def _local_draft(idea: str, taken: set[str], *, model: str = "", note: str = "") -> dict[str, Any]:
    meta = _fallback_meta(idea, taken)
    markdown = (
        "---\n"
        f"name: {meta['name']}\n"
        f"title: {meta['title']}\n"
        f"description: {meta['description']}\n"
        f"triggers: {_format_triggers(meta['triggers'])}\n"
        "---\n\n" + _local_body(idea)
    )
    return {
        "markdown": markdown,
        "name": meta["name"],
        "title": meta["title"],
        "description": meta["description"],
        "triggers": meta["triggers"],
        "model": model,
        "source": "local",
        "note": note or "先给了你一张空便签：把第 2 步那几条换成你自己的做法就能用。",
    }


def _normalize(markdown: str, idea: str, taken: set[str]) -> dict[str, Any]:
    """把模型产出收拾成一份字段齐全的 SKILL.md。"""
    text = _strip_fence(markdown)
    meta, body = _split_frontmatter(text)
    if not body.strip():
        # 只剩 frontmatter 或干脆是空壳：正文用本地骨架补上，比给用户一份空文件强
        body = _local_body(idea)
    # 先给正文留出 frontmatter 的位置，拼完才不会超出上限
    body = body.strip()[: MAX_DRAFT_CHARS - 400].rstrip()

    fallback = _fallback_meta(idea, taken)
    name = _slugify(meta.get("name", ""), fallback["name"])
    name = _unique_name(name, taken)
    title = (meta.get("title") or fallback["title"]).strip("\"'“”").strip()[:24]
    description = (meta.get("description") or fallback["description"]).strip()[:80]
    triggers = _parse_triggers(meta.get("triggers", "")) or fallback["triggers"]

    lines = [
        "---",
        f"name: {name}",
        f"title: {title}",
        f"description: {description}",
        f"triggers: {_format_triggers(triggers)}",
    ]
    category = (meta.get("category") or "").strip()
    if category in _ALLOWED_CATEGORIES:
        lines.append(f"category: {category}")
    icon = (meta.get("icon") or "").strip().lower()
    if icon in _ALLOWED_ICONS:
        lines.append(f"icon: {icon}")
    lines.append("---")
    markdown_out = ("\n".join(lines) + "\n\n" + body.strip() + "\n")[:MAX_DRAFT_CHARS]

    return {
        "markdown": markdown_out,
        "name": name,
        "title": title,
        "description": description,
        "triggers": triggers,
        "source": "model",
        "note": "核对一下步骤对不对；不满意可以再让模型写一版，或直接改文件。",
    }


async def draft_skill(
    router: Any,
    settings: Any,
    idea: str,
    *,
    taken: set[str] | None = None,
) -> dict[str, Any]:
    """让当前模型把一句话需求写成 SKILL.md；没有可用模型时返回本地骨架。

    调用方（api 层）只在 idea 为空时抛 400，其余情况一定拿到一份可导入的文本。
    """
    taken = set(taken or ())
    idea_text = _squash(idea)[:MAX_IDEA_CHARS]

    if router is None or not getattr(settings, "real_model_configured", False):
        return _local_draft(
            idea_text,
            taken,
            note="现在没有可用的模型（演示模式或还没配 Key），先给你一张空便签，照着改两行就能用。",
        )

    try:
        result = await asyncio.wait_for(
            router.chat_with_tools(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"我想要的效果：{idea_text}"},
                ],
                tools=None,
                temperature=0.4,
                max_tokens=1400,
                purpose="skill",
            ),
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:  # 网络 / 未配置 / 超时都不该阻断导入
        logger.info("技能草稿生成失败，退回本地骨架：%s", exc)
        return _local_draft(
            idea_text,
            taken,
            note="模型这次没调通，先给你一张空便签；也可以过一会儿再点「让模型写」。",
        )

    text = getattr(result, "text", "") or ""
    model = getattr(result, "model", "") or ""
    if not text.strip():
        return _local_draft(idea_text, taken, model=model)

    draft = _normalize(text, idea_text, taken)
    draft["model"] = model
    logger.info(
        "技能草稿已生成 name=%s model=%s chars=%s",
        draft["name"],
        model,
        len(draft["markdown"]),
        extra={"event": "skill_draft_created", "model": model},
    )
    return draft
