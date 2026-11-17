"""工具注册表（兼容装饰器写法）。"""

from __future__ import annotations

# 导入 builtin 触发注册（新增工具文件时在这里加一行）
from . import builtin  # noqa: F401
from .spec import REGISTRY, ToolContext, ToolRegistry, ToolSpec, build_schema, tool

__all__ = [
    "REGISTRY",
    "ToolContext",
    "ToolRegistry",
    "ToolSpec",
    "build_schema",
    "tool",
]
