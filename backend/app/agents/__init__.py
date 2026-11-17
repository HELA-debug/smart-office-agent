"""Agent 引擎包：协议 + mock/real 实现 + 模型路由 + 运行时装配。"""

from .engine_protocol import AgentEngine, EngineEvent, RunContext
from .registry import build_mock_engine, build_real_engine, engine_capabilities
from .runtime import AgentRuntime, EngineSelection, build_runtime

__all__ = [
    "AgentEngine",
    "AgentRuntime",
    "EngineEvent",
    "EngineSelection",
    "RunContext",
    "build_mock_engine",
    "build_real_engine",
    "build_runtime",
    "engine_capabilities",
]
