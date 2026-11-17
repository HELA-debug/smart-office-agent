"""Agent 引擎协议：mock / real / deepagents 适配器都实现同一协议，事件协议不变。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.config import Settings
from ..domain.entities import UploadInfo
from ..domain.ports import (
    ApprovalGate,
    ApprovalRepository,
    ArtifactRepository,
    FileStorage,
    MessageRepository,
)
from ..tools.registry import ToolRegistry


@dataclass
class RunContext:
    """一次运行引擎可用的全部依赖（全部为 domain 端口，便于替换实现）。"""

    thread_id: str
    run_id: str
    trace_id: str
    message: str
    mode: str
    model: str
    degraded: bool
    settings: Settings
    messages: MessageRepository
    artifacts: ArtifactRepository
    approvals: ApprovalRepository
    storage: FileStorage
    approval_gate: ApprovalGate
    tools: ToolRegistry
    approval_tools: list[str]
    uploads: list[UploadInfo] = field(default_factory=list)
    llm_text: str = ""
    output_format: str = "docx"
    """本轮追加的系统提示词（需求路由的规范包 + 项目说明）；为空表示不追加。"""
    prompt_extra: str = ""
    """本轮关联的项目（左栏「项目」里选中的文档文件夹），无项目时为 None。"""
    project: dict[str, Any] | None = None
    """本轮关联的项目（左栏「项目」里选中的文档文件夹），无项目时为 None。"""
    approval_mode: str = "risky"
    """信任档位：always_ask（谨慎：模棱两可就别动）/ risky（标准，默认）/ all_allow（放手）。

    它调的是门控的放行线：写操作该不该放行由 `policy.decide_write` 自己判，判不过就
    拦下并让模型解释，**不弹卡问人**。审批闸门仍然留在端口上——外部接入或未来的
    「真停下来问一句」按 `ApprovalGate.create/wait` 发起时，界面那侧的确认卡片接得住。
    """
    history: list[dict[str, Any]] = field(default_factory=list)
    """历史对话（已按预算裁切/压缩，成对编排好），直接拼在 system 与本轮用户消息之间。"""
    context_summary: str = ""
    """被挤出窗口的更早轮次的抽取式摘要（空串表示没有压缩）。"""
    context_meta: dict[str, Any] = field(default_factory=dict)
    """上下文装配的统计信息（turns_total / kept_turns / dropped_turns / summary_chars）。"""
    doc_style: dict[str, Any] = field(default_factory=dict)
    """用户在「文档格式」里点的那几项（字体/字号/字型/行距/首行缩进/对齐）。

    空字典 = 这一轮没点，全部由 Agent 自己判断。工具层只覆盖真正给了值的字段，
    不拿默认值把版式预设整个顶掉。
    """
    delivered: list[dict[str, Any]] = field(default_factory=list)
    """本会话已经交付过的产物（新的在后，最多几条）。

    为什么每轮都要带上：用户说「你自己斟酌吧」这类话时，他指的是**手上这版**继续改，
    模型却很容易当成一次新任务，从零再产一份（同名就成了 `X(2)`）。把已交付的文件
    摆在它眼前，它才会先打开去改。只放文件名与时间，不放内容——正文走 file.read。
    """

    @property
    def tool_names(self) -> list[str]:
        return self.tools.names()


APPROVAL_MODES = ("always_ask", "risky", "all_allow")


def normalize_approval_mode(value: str | None) -> str:
    """非法值一律回落到 risky：宁可多问一句，也不要静默放行高风险动作。"""
    mode = (value or "").strip().lower()
    return mode if mode in APPROVAL_MODES else "risky"


@dataclass(frozen=True)
class EngineEvent:
    """引擎输出：正常事件写库 + 推送；comment 为 SSE 注释心跳（不写库）。"""

    event: str
    data: dict[str, Any]
    comment: str | None = None


class AgentEngine(Protocol):
    name: str

    def run(self, ctx: RunContext) -> AsyncIterator[EngineEvent]: ...


# ---------------------------------------------------------------------------
# deepagents（LangGraph）适配位（计划书 7.9 / ADR-0003）
#
# 接入方式：新增 `agents/deepagents_engine.py` 实现上面的 AgentEngine 协议，并在
# `agents/registry.py` 的工厂里按配置返回；事件协议、工具注册表、审批策略、前端均不改。
# 需要做的映射（差异只允许留在适配层内）：
#   deepagents todos        -> plan.updated.todos（id/content/status 同构）
#   tool call / tool result -> tool.started / tool.finished（input/output 用 ToolContext 同构）
#   interrupt / HITL        -> approval.required（复用 ApprovalGate.create/wait）
#   subagent 调用           -> 主事件流内追加 tool.finished.subagent（字段只追加）
#   final state             -> run.completed（tokens/cost 由 ModelRouter 汇总）
# 本版不引入 deepagents 依赖（避免重依赖），只保留协议与文档位置。
# ---------------------------------------------------------------------------
