"""Agent 运行时装配：工具注册表 + 子智能体 + 提示词 + 技能 + 模型路由 + 引擎选择。

这是唯一的"内核"装配入口（对应 V2.0 的 backend/agent.py），infra 与 api 只在 main.py 组合。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.logging import get_logger
from ..core.utils import detect_git_sha
from ..domain.ports import FileStorage
from ..subagents.registry import REGISTRY as SUBAGENT_REGISTRY
from ..tools.registry import REGISTRY as TOOL_REGISTRY
from ..tools.registry import ToolRegistry
from .engine_protocol import AgentEngine
from .model_router import ModelRouter
from .registry import build_mock_engine, build_real_engine, engine_capabilities

BACKEND_DIR = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND_DIR / "app"
PROMPTS_DIR = APP_DIR / "prompts"
SKILLS_DIR = APP_DIR / "skills"
CATALOG_DIR = APP_DIR / "skills_catalog"

logger = get_logger("app.agents.runtime")


@dataclass
class SkillInfo:
    name: str
    description: str
    triggers: list[str]
    enabled: bool
    path: str
    content: str
    # 展示用元信息（都来自 SKILL.md frontmatter，缺省就是空串，界面按兜底逻辑渲染）
    title: str = ""
    category: str = ""
    icon: str = ""
    badge: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "enabled": self.enabled,
            "category": self.category,
            "icon": self.icon,
            "badge": self.badge,
        }


@dataclass(frozen=True)
class EngineSelection:
    engine: AgentEngine
    mode: str
    degraded: bool
    provider: str
    model: str


@dataclass
class AgentRuntime:
    settings: Settings
    tools: ToolRegistry
    subagents: Any
    prompt: str
    prompt_version: str
    skills: dict[str, SkillInfo]
    router: ModelRouter
    storage: FileStorage
    approval_tools: list[str]
    degraded: bool = False
    degraded_reason: str = ""
    git_sha: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    # ---------- 引擎选择 ----------
    async def prepare_engine(
        self,
        *,
        force_mock: bool = False,
        approval_tools: list[str] | None = None,
    ) -> EngineSelection:
        active_approval_tools = (
            approval_tools if approval_tools is not None else self.approval_tools
        )
        provider = self.settings.configured_provider
        # 配置为真实模式（MOCK_MODE=false 且 provider != mock）但缺 Key：标 degraded
        expected_real = not self.settings.mock_mode and provider != "mock"
        if force_mock or not self.settings.real_model_configured:
            degraded = False if force_mock else (self.degraded or expected_real)
            engine = build_mock_engine(self.tools, active_approval_tools, self.prompt)
            return EngineSelection(engine, "mock", degraded, "mock", "mock-scripted")

        # 真实模式：按 fallback 链逐家探测（60s 缓存），全部不可用才降级 mock
        ok_provider, reason = await self.router.probe_chain()
        if ok_provider:
            # 探测通了就复位降级标记。以前这里只 set 不清，一次瞬时故障（比如
            # 探测请求被限流）会让进程在重启前一直跑 mock，用户以为在跟大模型对话，
            # 实际看到的是本地脚本生成的内容——这是最伤信任的一类 bug。
            self.degraded = False
            self.degraded_reason = ""
            engine = build_real_engine(self.tools, active_approval_tools, self.router, self.prompt)
            return EngineSelection(
                engine, "real", self.degraded, ok_provider, self.router.model_for(ok_provider)
            )

        logger.warning(
            "真实模型不可用，自动降级 mock：%s",
            reason,
            extra={"event": "engine_degraded", "reason": reason},
        )
        self.degraded = True
        self.degraded_reason = reason
        engine = build_mock_engine(self.tools, active_approval_tools, self.prompt)
        return EngineSelection(engine, "mock", True, provider, "mock-scripted")

    # ---------- 健康检查 ----------
    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": self.settings.version,
            # git_sha 是进程启动那一刻载入的代码版本（长跑进程不会自己变）；
            # git_sha_live 是仓库当前 HEAD。两者不同 = 后端进程比代码旧，该重启了，
            # 别让界面把这种不一致误报成「前端没重新构建」。
            "git_sha": self.git_sha or detect_git_sha(),
            "git_sha_live": detect_git_sha(),
            "mode": "mock"
            if (self.degraded or not self.settings.real_model_configured)
            else "real",
            "provider": self.settings.configured_provider,
            "model": self.router.active_model,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "mock": self.settings.mode == "mock" or self.degraded,
            "tools": len(self.tools.names()),
            "subagents": len(self.subagents.all()),
            "skills": sorted(self.skills),
            "prompt_version": self.prompt_version,
            # 契约里是英文 id 列表（前端 mock 也照这个写），中文展示名不进接口
            "engines": [engine["id"] for engine in engine_capabilities()],
            "approval_tools": list(self.approval_tools),
        }

    def skill_list(self) -> list[dict[str, Any]]:
        return [skill.to_dict() for skill in self.skills.values()]

    def tool_list(self) -> list[dict[str, Any]]:
        return self.tools.snapshot()

    def subagent_list(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self.subagents.all()]


def load_prompt(name: str = "system.md") -> tuple[str, str]:
    path = PROMPTS_DIR / name
    if not path.exists():
        logger.warning("提示词文件不存在：%s", path)
        return "", "0"
    raw = path.read_text(encoding="utf-8")
    match = re.search(r"version:\s*([\w.\-]+)", raw[:200])
    version = match.group(1) if match else "0"
    body = re.sub(r"^\s*<!--.*?-->\s*", "", raw, count=1, flags=re.S).strip()
    return body, version


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip()
    return metadata, parts[2].strip()


def _split_triggers(raw: str) -> list[str]:
    return [trigger.strip() for trigger in raw.strip("[]").split(",") if trigger.strip()]


def read_skill(path: Path) -> SkillInfo:
    """读一份 SKILL.md → SkillInfo（已安装技能和技能库共用这套解析，字段含义一致）。"""
    raw = path.read_text(encoding="utf-8")
    metadata, content = _parse_frontmatter(raw)
    return SkillInfo(
        name=metadata.get("name") or path.parent.name,
        description=metadata.get("description", ""),
        triggers=_split_triggers(metadata.get("triggers", "")),
        enabled=metadata.get("enabled", "true").lower() != "false",
        path=str(path),
        content=content,
        title=metadata.get("title", ""),
        category=metadata.get("category", ""),
        icon=metadata.get("icon", ""),
        badge=metadata.get("badge", ""),
    )


def load_skills(directory: Path | None = None) -> dict[str, SkillInfo]:
    """扫描技能目录（默认 app/skills）；传目录便于测试或指向自定义技能库。"""
    skills: dict[str, SkillInfo] = {}
    root = directory or SKILLS_DIR
    if not root.exists():
        logger.warning("技能目录不存在：%s", root)
        return skills
    for path in sorted(root.glob("*/SKILL.md")):
        info = read_skill(path)
        skills[info.name] = info
        logger.info(
            "已加载技能 %s（enabled=%s，%d 字）",
            info.name,
            info.enabled,
            len(info.content),
            extra={"event": "skill_loaded"},
        )
    return skills


def load_catalog(directory: Path | None = None) -> list[dict[str, Any]]:
    """
    扫描技能库目录（默认 app/skills_catalog）：只列「可以添加」的技能，不进运行时提示词。
    装到 app/skills 之后才算已安装，避免几十个技能一上来就占满上下文。
    """
    root = directory or CATALOG_DIR
    entries: list[dict[str, Any]] = []
    if not root.exists():
        return entries
    for path in sorted(root.glob("*/SKILL.md")):
        info = read_skill(path)
        entries.append(
            {
                **info.to_dict(),
                "slug": path.parent.name,
                "content_chars": len(info.content),
            }
        )
    return entries


def build_runtime(settings: Settings, storage: FileStorage) -> AgentRuntime:
    """装配运行时；main.py 在 lifespan 里调用一次。"""
    prompt, prompt_version = load_prompt()
    skills = load_skills()
    subagents = SUBAGENT_REGISTRY
    tools: ToolRegistry = TOOL_REGISTRY
    approval_tools = tools.approval_tools(settings.approval_tools)
    router = ModelRouter(settings)

    runtime = AgentRuntime(
        settings=settings,
        tools=tools,
        subagents=subagents,
        prompt=prompt,
        prompt_version=prompt_version,
        skills=skills,
        router=router,
        storage=storage,
        approval_tools=approval_tools,
        git_sha=settings.git_sha or detect_git_sha(),
    )
    logger.info(
        "运行时装配完成：工具=%s；子智能体=%s；审批工具=%s；模式=%s",
        ",".join(tools.names()),
        ",".join(spec.name for spec in subagents.all()),
        ",".join(approval_tools) or "无",
        "real" if settings.real_model_configured else "mock",
        extra={"event": "runtime_ready"},
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("系统提示词 %d 字，技能 %s", len(prompt), sorted(skills))
    return runtime
