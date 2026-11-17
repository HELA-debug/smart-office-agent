"""降级与恢复：真实模型探测失败会切 mock，但探测恢复后必须切回真实模型。

历史 bug（用户直接感受到的那种）：探测用 `max_tokens=1` 打推理模型，正文必然为空，
被判成「供应商不可用」→ 整个引擎切到 mock；而 `degraded` 只置位不复位，
一次瞬时故障就让进程在重启前一直吐本地脚本内容。用户拿控制台对账自然一条请求都看不到。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.agents.runtime import AgentRuntime
from app.core.config import Settings
from app.services.settings_service import SettingsService
from app.tools.spec import ToolRegistry


class FakeRouter:
    """只回答「探测结果」的假路由；记录被探测了几次。"""

    def __init__(self, results: list[tuple[str | None, str]]) -> None:
        self._results = list(results)
        self.calls = 0
        self.active_model = "deepseek-flash"

    async def probe_chain(self) -> tuple[str | None, str]:
        index = min(self.calls, len(self._results) - 1)
        self.calls += 1
        return self._results[index]

    def model_for(self, provider: str | None = None) -> str:
        return "deepseek-flash"

    def chain(self, start: str | None = None) -> list[str]:
        return ["deepseek", "mock"]


def make_runtime(results: list[tuple[str | None, str]]) -> AgentRuntime:
    settings = Settings(
        mock_mode=False,
        model_provider="deepseek",
        model_name="deepseek-flash",
        deepseek_api_key="sk-test-deepseek",
        model_fallback_chain="deepseek,mock",
    )
    return AgentRuntime(
        settings=settings,
        tools=ToolRegistry(),
        subagents=type("Subs", (), {"all": lambda self: []})(),
        prompt="",
        prompt_version="test",
        skills={},
        router=FakeRouter(results),  # type: ignore[arg-type]
        storage=None,  # type: ignore[arg-type]
        approval_tools=[],
    )


def test_degrade_marks_reason_and_health_reports_it() -> None:
    runtime = make_runtime([(None, "deepseek: 模型返回空内容（既无文本也无 tool_calls）")])

    selection = asyncio.run(runtime.prepare_engine())

    assert selection.mode == "mock"
    assert selection.degraded is True
    health = runtime.health()
    assert health["mode"] == "mock"
    assert health["degraded"] is True
    # 原因要能看懂，不然用户只知道「降级了」，不知道去改 Key 还是改模型名
    assert "空内容" in health["degraded_reason"]


def test_degraded_clears_once_probe_succeeds_again() -> None:
    runtime = make_runtime([(None, "网络错误"), ("deepseek", "")])

    first = asyncio.run(runtime.prepare_engine())
    assert first.mode == "mock" and runtime.degraded is True

    second = asyncio.run(runtime.prepare_engine())
    assert second.mode == "real", "探测通了就应该回到真实模型，而不是一直吐 mock"
    assert runtime.degraded is False
    assert runtime.health()["degraded_reason"] == ""


def test_engine_selection_carries_model_name(monkeypatch: Any) -> None:
    runtime = make_runtime([("deepseek", "")])
    selection = asyncio.run(runtime.prepare_engine())
    assert selection.provider == "deepseek"
    assert selection.model == "deepseek-flash"


class _ResetRouter:
    """只记「有没有被要求丢掉旧实例」。"""

    def __init__(self) -> None:
        self.resets = 0

    def reset_providers(self) -> None:
        self.resets += 1


class _EmptySettingsRepo:
    def list_all(self) -> list[Any]:
        return []


def test_reset_router_clears_stale_degrade() -> None:
    """换 Key / 改地址后，旧的「上次探测失败」结论必须作废。

    历史 bug（用户直接撞到的）：换完新 Key、设置页「测试连接」已经显示连接正常，
    但上面那行还挂着旧 Key 的「API Key 无效或已失效」——因为 degraded 只在
    下一次真实运行探测成功时才复位，而 /health 只读它、不重新探测。
    界面于是把一条过期报错当成现状，用户以为新 Key 白换了。
    """
    router = _ResetRouter()
    runtime = SimpleNamespace(
        router=router,
        degraded=True,
        degraded_reason="deepseek: HTTP 401 Authentication Fails, api key ****7890 is invalid",
    )
    service = SettingsService(
        repo=_EmptySettingsRepo(),  # type: ignore[arg-type]
        settings=Settings(),
    )
    service.runtime = runtime

    service.reset_router()

    assert router.resets == 1, "旧 provider 实例要丢掉，否则还握着一把旧 Key"
    assert runtime.degraded is False
    assert runtime.degraded_reason == ""
