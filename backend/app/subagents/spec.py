"""子智能体规格（声明式注册，占位也实现协议）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubagentSpec:
    name: str
    description: str
    prompt: str
    tools: list[str] = field(default_factory=list)
    status: str = "implemented"  # implemented | placeholder
    step_limit: int = 8
    runner: Callable[..., dict[str, Any]] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
            "status": self.status,
            "step_limit": self.step_limit,
        }


class SubagentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, SubagentSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        prompt: str,
        tools: list[str] | None = None,
        status: str = "implemented",
        step_limit: int = 8,
    ) -> Callable[[Callable[..., dict[str, Any]] | None], Callable[..., dict[str, Any]] | None]:
        def decorator(runner: Callable[..., dict[str, Any]] | None = None) -> Any:
            self._agents[name] = SubagentSpec(
                name=name,
                description=description,
                prompt=prompt,
                tools=list(tools or []),
                status=status,
                step_limit=step_limit,
                runner=runner,
            )
            return runner if runner is not None else (lambda *args, **kwargs: {})

        return decorator

    def get(self, name: str) -> SubagentSpec | None:
        return self._agents.get(name)

    def all(self) -> list[SubagentSpec]:
        return sorted(self._agents.values(), key=lambda spec: spec.name)

    def snapshot(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self.all()]


REGISTRY = SubagentRegistry()
subagent = REGISTRY.register
