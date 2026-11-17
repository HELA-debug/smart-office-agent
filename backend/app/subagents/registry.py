"""子智能体注册表：导入各实现模块触发注册（1 实现 + 2 占位）。"""

from __future__ import annotations

from . import doc_agent, research_agent, sheet_agent  # noqa: F401
from .spec import REGISTRY, SubagentRegistry, SubagentSpec, subagent

__all__ = ["REGISTRY", "SubagentRegistry", "SubagentSpec", "subagent"]
