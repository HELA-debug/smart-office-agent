"""模型调用账本：每一次真正发往供应商的请求，都留一条记录。

## 为什么要单独一张表

`runs.extra.usage` 是「运行内 + 成功」的聚合：它够用来看某次运行花了多少，
但拿去和供应商控制台对账就必然对不上——实测同一天应用内记 ¥0.43、控制台
¥2.72、请求 153 次对 1909 次。差额不是算错，是**统计范围**：

- 连通性探测（每次打开设置页/健康检查都会 ping 一次）；
- 会话标题、提示词增强、技能起草——它们不属于任何一次 run；
- 失败与重试：限流重试、`max_tokens` 截断后的放大重试、供应商切换。
  这些请求供应商照样计费，但失败的那次没有 usage 可记。

这些事只能逐条记才说得清。表在 `infra/db`，这里只放**协议与安装点**：
agents / providers 层不该知道数据库长什么样，它们只管「有件事发生了」。

## 记账绝不能影响业务

记一条失败就当没记：账本是为了事后对账，不是为了在运行时制造新故障。
所有异常在这里被吞掉并打一条 warning —— 这一点和审计日志同构。
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .logging import get_logger
from .utils import now_iso

logger = get_logger("app.core.call_journal")

#: 请求用途。决定「这笔钱算在谁头上」，也是审计页分组的依据。
PURPOSES: tuple[str, ...] = (
    "engine",  # 主循环（ReAct 每一步）
    "reading",  # 理解层：这一轮他到底要什么
    "probe",  # 连通性探测
    "title",  # 会话标题
    "enhance",  # 提示词增强
    "skill",  # 技能起草
    "other",
)


@dataclass(frozen=True)
class CallEntry:
    """一次外部模型请求的结果。字段与 `model_calls` 表一一对应。"""

    provider: str
    model: str
    purpose: str = "engine"
    status: str = "ok"  # ok / failed
    run_id: str | None = None
    thread_id: str | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    cost_cny: float = 0.0
    peak: bool = False
    latency_ms: int = 0
    attempt: int = 1
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = field(default_factory=now_iso)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class CallJournal(Protocol):
    def record(self, entry: CallEntry) -> None: ...


_JOURNAL: CallJournal | None = None


def install(journal: CallJournal | None) -> None:
    """应用启动时装一次；传 `None` 用于测试里关掉真实落库。"""
    global _JOURNAL
    _JOURNAL = journal


def installed() -> CallJournal | None:
    return _JOURNAL


def record(entry: CallEntry) -> None:
    journal = _JOURNAL
    if journal is None:
        return
    try:
        journal.record(entry)
    except Exception as exc:  # 记账失败不能反过来打断一次成功的调用
        logger.warning(
            "调用账本写入失败 provider=%s purpose=%s：%s",
            entry.provider,
            entry.purpose,
            str(exc)[:200],
            extra={"event": "call_journal_failed", "provider": entry.provider},
        )


# ---------- 上下文：这笔钱属于哪次运行、哪段用途 ----------


@dataclass(frozen=True)
class CallScope:
    run_id: str | None = None
    thread_id: str | None = None
    purpose: str = "engine"


_SCOPE: ContextVar[CallScope | None] = ContextVar("oa_call_scope", default=None)
#: 没有绑定过运行时的默认作用域（探测、全局脚本调用都会落到这里）。
_EMPTY_SCOPE = CallScope()


def _scope() -> CallScope:
    return _SCOPE.get() or _EMPTY_SCOPE


def bind_scope(*, run_id: str | None = None, thread_id: str | None = None) -> Token:
    """绑定「当前这次运行」。asyncio Task 会复制上下文，并发会话互不串账。"""
    current = _scope()
    return _SCOPE.set(
        CallScope(
            run_id=run_id if run_id is not None else current.run_id,
            thread_id=thread_id if thread_id is not None else current.thread_id,
            purpose=current.purpose,
        )
    )


def bind_purpose(purpose: str) -> Token:
    current = _scope()
    return _SCOPE.set(
        CallScope(run_id=current.run_id, thread_id=current.thread_id, purpose=purpose)
    )


def reset(token: Token) -> None:
    # 跨上下文 reset（比如在线程池里收尾）会抛 ValueError，忽略即可
    with contextlib.suppress(ValueError):
        _SCOPE.reset(token)


def current_scope() -> CallScope:
    return _scope()


def entry_for(**fields: Any) -> CallEntry:
    """按当前上下文补齐 run_id / thread_id / purpose，再构造条目。"""
    scope = _scope()
    fields.setdefault("run_id", scope.run_id)
    fields.setdefault("thread_id", scope.thread_id)
    fields.setdefault("purpose", scope.purpose)
    return CallEntry(**fields)


__all__ = [
    "PURPOSES",
    "CallEntry",
    "CallJournal",
    "CallScope",
    "bind_purpose",
    "bind_scope",
    "current_scope",
    "entry_for",
    "install",
    "installed",
    "record",
    "reset",
]
