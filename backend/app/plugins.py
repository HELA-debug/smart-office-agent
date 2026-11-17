"""插件加载：Python entry points（office_agent.plugins）自动注册工具/连接器。

示例插件包在 pyproject 里声明：
[project.entry-points."office_agent.plugins"]
my_plugin = "my_plugin:register"
`register(registry)` 内可调用 `registry.register(...)` 注册工具，或注册连接器。
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .core.logging import get_logger

logger = get_logger("app.plugins")

PLUGIN_GROUP = "office_agent.plugins"


def load_plugins(registry: Any) -> list[str]:
    loaded: list[str] = []
    try:
        discovered = entry_points(group=PLUGIN_GROUP)
    except Exception as exc:
        logger.warning("插件发现失败：%s", exc)
        return loaded
    for entry_point in discovered:
        try:
            handler = entry_point.load()
            handler(registry)
            loaded.append(entry_point.name)
            logger.info("已加载插件 %s", entry_point.name, extra={"event": "plugin_loaded"})
        except Exception as exc:
            logger.warning("插件加载失败 %s：%s", entry_point.name, exc)
    return loaded
