"""模型供应商路由：fallback 链 + 错误分类 + 重试/熔断 + 成本估算 + 用量累计。

计划书 7.3：
- 按 `MODEL_FALLBACK_CHAIN=deepseek,qwen,glm,mock` 依次尝试；`mock` 表示"没有可用模型"，
  由引擎降级到 MockEngine（路由本身不伪造模型输出）；
- 错误分类 → 重试 1 次 → 切下一家 → 全部失败抛 `ModelUnavailableError` 并标 degraded；
- 成本表在 `backend/config/model_prices.yaml`（元/百万 tokens，可配置），
  每次调用累计 input/output tokens 与 cost，供 run.completed / 审计页使用；
- 所有外部 HTTP 走注入的客户端工厂（默认 `app.infra.http.build_http_client`）。
"""

from __future__ import annotations

import asyncio
import itertools
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..core import call_journal
from ..core.config import Settings
from ..core.logging import get_logger
from ..core.pricing import PriceSet, cost_for, price_for
from ..core.pricing import load_price_table as _load_price_table
from ..infra.http import build_http_client
from ..providers import (
    API_KEY_ENV,
    DEFAULT_MODELS,
    ErrorCategory,
    HttpClientFactory,
    ModelProvider,
    ProviderError,
    ToolCall,
    build_provider,
    provider_error_summary,
)

logger = get_logger("app.agents.model_router")

PRICE_TABLE_PATH = Path(__file__).resolve().parents[2] / "config" / "model_prices.yaml"

PROBE_CACHE_TTL_SECONDS = 60.0
RETRY_BACKOFF_SECONDS = 1.0
CIRCUIT_COOLDOWN_SECONDS = 60.0
TOKEN_BUDGET_PER_RUN = 1_000_000
# 单次运行最多保留多少条调用回执（超出只统计、不再追加明细）
RECEIPT_LIMIT = 40


# 当前运行的用量计（每个 run 一个）。
#
# 改造前 `begin_run()` 把 `self._usage` 换掉，`chat_with_tools` 再往 `self._usage` 里加：
# 路由是进程内单例，两个会话同时跑时，B 的 begin_run 会把 A 已经累计的 tokens 清零，
# 随后 A、B 的调用又都记到同一个桶里 —— 账单与预算判断全错。
# 用 ContextVar 之后，每个 run 在自己的任务上下文里拿到自己的计，互不可见。
# 槽位里带 router 身份：同一进程里可能有多个路由实例（测试、灰度），
# 不能把「上一个实例留下的计」当成自己的。
_CURRENT_METER: ContextVar[_MeterSlot | None] = ContextVar("oa_model_usage", default=None)


@dataclass(frozen=True)
class ChatResult:
    """一次模型调用的归一化结果（文本 + 工具调用 + 用量）。"""

    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    cost_cny: float = 0.0
    # 输入的缓存拆分与本次计价（高峰/闲时、命中/未命中单价）：审计页据此解释这笔钱怎么来的
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    peak: bool = False
    # 供应商回执：请求 id 是「真的打到了官方接口」的凭据，延迟用于排查慢调用
    request_id: str = ""
    latency_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def public_usage(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.prompt_tokens,
            "output_tokens": self.completion_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "peak": self.peak,
            "total_tokens": self.total_tokens,
            "cost_cny": self.cost_cny,
            "request_id": self.request_id,
            "latency_ms": self.latency_ms,
        }


@dataclass
class UsageAccumulator:
    """一次 run 内的用量累计（按供应商/模型分组）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    cost_cny: float = 0.0
    calls: int = 0
    by_provider: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 单次运行 token 预算：由 Settings.model_token_budget 注入（默认沿用常量）
    budget: int = TOKEN_BUDGET_PER_RUN
    # 每次外部调用的回执（provider / model / request_id / tokens / 延迟）。
    # 只留最近 N 条：一次运行最多十来次调用，全留也不占地方，但别让它无限长。
    receipts: list[dict[str, Any]] = field(default_factory=list)

    def add(self, result: ChatResult) -> None:
        self.calls += 1
        self.input_tokens += result.prompt_tokens
        self.output_tokens += result.completion_tokens
        self.cache_hit_tokens += result.cache_hit_tokens
        self.cache_miss_tokens += result.cache_miss_tokens
        self.cost_cny = round(self.cost_cny + result.cost_cny, 6)
        key = f"{result.provider}:{result.model}"
        bucket = self.by_provider.setdefault(
            key,
            {
                "provider": result.provider,
                "model": result.model,
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_hit_tokens": 0,
                "cache_miss_tokens": 0,
                "cost_cny": 0.0,
            },
        )
        bucket["calls"] = int(bucket["calls"]) + 1
        bucket["input_tokens"] = int(bucket["input_tokens"]) + result.prompt_tokens
        bucket["output_tokens"] = int(bucket["output_tokens"]) + result.completion_tokens
        bucket["cache_hit_tokens"] = int(bucket["cache_hit_tokens"]) + result.cache_hit_tokens
        bucket["cache_miss_tokens"] = int(bucket["cache_miss_tokens"]) + result.cache_miss_tokens
        bucket["cost_cny"] = round(float(bucket["cost_cny"]) + result.cost_cny, 6)
        if len(self.receipts) < RECEIPT_LIMIT:
            self.receipts.append(
                {
                    "provider": result.provider,
                    "model": result.model,
                    "request_id": result.request_id,
                    # 没有 request_id 说明对面不是官方接口（或自建网关没透传），
                    # 界面上要能看出来这一笔「对不上账」
                    "verified": bool(result.request_id),
                    "input_tokens": result.prompt_tokens,
                    "output_tokens": result.completion_tokens,
                    "cache_hit_tokens": result.cache_hit_tokens,
                    "cache_miss_tokens": result.cache_miss_tokens,
                    "peak": result.peak,
                    "cost_cny": result.cost_cny,
                    "latency_ms": result.latency_ms,
                }
            )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "total_tokens": self.total_tokens,
            "cost_cny": self.cost_cny,
            "calls": self.calls,
            "by_provider": list(self.by_provider.values()),
            # 逐次回执：审计页据此显示请求 id，用来和供应商控制台对账
            "calls_detail": list(self.receipts),
            "verified_calls": sum(1 for item in self.receipts if item.get("verified")),
            "budget": self.budget,
            "currency": "CNY",
        }


class ModelUnavailableError(RuntimeError):
    """所有供应商均不可用：引擎据此降级到 MockEngine / 收尾。"""

    def __init__(self, message: str, *, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []

    def public(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "attempts": [
                {
                    "provider": item.get("provider", ""),
                    "result": item.get("result", ""),
                    "category": item.get("category", ""),
                    "message": str(item.get("message", ""))[:200],
                }
                for item in self.attempts
            ],
        }


def load_price_table(path: Path | None = None) -> dict[str, Any]:
    """读取价格表（委托 core.pricing：按 mtime 缓存，改价不用重启）。"""
    return _load_price_table(path)


@dataclass(frozen=True)
class _MeterSlot:
    """上下文里那一格：属于哪个路由实例 + 该实例当前运行的用量计。"""

    owner: int
    meter: UsageAccumulator


_ROUTER_KEYS = itertools.count(1)


class ModelRouter:
    def __init__(
        self,
        settings: Settings,
        http_client_factory: HttpClientFactory = build_http_client,
        *,
        providers: dict[str, ModelProvider] | None = None,
        price_table: dict[str, Any] | None = None,
        retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
        probe_cache_ttl: float = PROBE_CACHE_TTL_SECONDS,
    ) -> None:
        self.settings = settings
        self._http_factory = http_client_factory
        self._providers: dict[str, ModelProvider] = dict(providers or {})
        # None = 跟随 backend/config/model_prices.yaml（每次按 mtime 取最新）；
        # 测试/灰度传入固定表时用传入的那份。
        self._prices = price_table
        self._retry_backoff = max(0.0, retry_backoff_seconds)
        self._probe_ttl = max(0.0, probe_cache_ttl)
        self._probe_cache: dict[str, tuple[bool, str, float]] = {}
        self._circuit_open_until: dict[str, float] = {}
        self._preferred: str | None = None
        self._degraded = False
        self._attempts: list[dict[str, Any]] = []
        self._usage = UsageAccumulator(budget=self.settings.model_token_budget)
        # 实例身份：ContextVar 里的槽位要能认出「这只计属于哪个路由」
        self._instance_key = next(_ROUTER_KEYS)

    # ---------- 描述 ----------
    def chain(self, start: str | None = None) -> list[str]:
        """调用顺序：指定起点 -> 主供应商 -> fallback 链（去重、去掉 mock）。"""
        order: list[str] = []
        candidates = [start, self.settings.configured_provider, *self.settings.fallback_chain]
        for name in candidates:
            name = (name or "").strip().lower()
            if name and name != "mock" and name not in order:
                order.append(name)
        return order

    def providers(self) -> list[dict[str, Any]]:
        """供 /api/v1/models 展示（不返回任何 Key，只给引用）。"""
        chain = self.chain()
        configured = self.settings.configured_provider
        rows: list[dict[str, Any]] = []
        for priority, name in enumerate(chain, start=1):
            provider = self._provider(name)
            if provider is None:
                rows.append(
                    {
                        "provider": name,
                        "base_url": self.settings.provider_base_url(name),
                        "model": DEFAULT_MODELS.get(name, ""),
                        "configured": False,
                        "api_key_ref": f"env:{API_KEY_ENV.get(name, name.upper() + '_API_KEY')}",
                        "enabled": False,
                        "priority": priority,
                        "last_probe": None,
                    }
                )
                continue
            cached = self._probe_cache.get(name)
            rows.append(
                {
                    "provider": name,
                    "base_url": provider.base_url,
                    "model": provider.model,
                    "configured": provider.configured,
                    "api_key_ref": provider.api_key_ref,
                    "enabled": name == configured,
                    "priority": priority,
                    "last_probe": (
                        {"ok": cached[0], "reason": cached[1]} if cached is not None else None
                    ),
                }
            )
        return rows

    @property
    def active_provider(self) -> str:
        provider = self.settings.configured_provider
        if provider == "mock":
            return "mock"
        return self._preferred or provider

    @property
    def active_model(self) -> str:
        if not self.settings.real_model_configured:
            return "mock-scripted"
        return self.model_for(self.active_provider)

    @property
    def available_provider(self) -> str | None:
        for name in self.chain(start=self._preferred):
            provider = self._provider(name)
            if provider is not None and provider.configured and not self._circuit_open(name):
                return name
        return None

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def last_attempts(self) -> list[dict[str, Any]]:
        return list(self._attempts)

    def model_for(self, provider: str) -> str:
        if provider == "mock" or not provider:
            return "mock-scripted"
        instance = self._provider(provider)
        if instance is not None:
            return instance.model
        return DEFAULT_MODELS.get(provider, self.settings.model_name)

    # ---------- run 生命周期 ----------
    def begin_run(self, preferred: str | None = None) -> UsageAccumulator:
        """开始一次运行：为本任务上下文换一只新的用量计，返回它（调用方一般直接用快照）。

        只影响当前任务（asyncio Task 会复制上下文），不同会话并发跑互不串账。
        """
        meter = UsageAccumulator(budget=self.settings.model_token_budget)
        _CURRENT_METER.set(_MeterSlot(owner=self._instance_key, meter=meter))
        self._usage = meter  # 保留进程级引用，兼容「没有上下文」的脚本/测试调用
        self._attempts = []
        self._degraded = False
        if preferred:
            self._preferred = preferred
        return meter

    def current_usage(self) -> UsageAccumulator:
        """当前运行的用量计；没有 begin_run 过（脚本/测试直接用路由）时回落到进程级那只。"""
        slot = _CURRENT_METER.get()
        if slot is None or slot.owner != self._instance_key:
            return self._usage
        return slot.meter

    def usage_snapshot(self) -> dict[str, Any]:
        return self.current_usage().as_dict()

    # ---------- 调用 ----------
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.3,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        purpose: str = "engine",
    ) -> ChatResult:
        """显式 provider：只调该供应商；否则走 fallback 链。

        `purpose` 只影响账本归类（engine / reading / probe / title …），
        不改变调用行为。账本是按「谁花的钱」分组的，缺了它所有开销都会
        被算到主循环头上。
        """
        if provider:
            instance = self._provider(provider)
            if instance is None or not instance.configured:
                raise ModelUnavailableError(
                    f"供应商未配置：{provider}",
                    attempts=[{"provider": provider, "result": "skipped", "message": "未配置"}],
                )
            try:
                return await self._invoke(
                    instance,
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    purpose=purpose,
                )
            except ProviderError as exc:
                raise ModelUnavailableError(
                    f"{provider} 调用失败：{exc.message[:200]}",
                    attempts=[{"provider": provider, "result": "failed", **exc.public()}],
                ) from exc
        return await self.chat_with_tools(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            purpose=purpose,
        )

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        purpose: str = "engine",
    ) -> ChatResult:
        """按 fallback 链调用，返回首次成功的结果；全部失败抛 ModelUnavailableError。"""
        self._attempts = []
        for name in self.chain(start=self._preferred):
            instance = self._provider(name)
            if instance is None or not instance.configured:
                self._attempts.append(
                    {"provider": name, "result": "skipped", "message": "未配置（缺少 Key）"}
                )
                continue
            if self._circuit_open(name):
                self._attempts.append(
                    {"provider": name, "result": "skipped", "message": "熔断冷却中"}
                )
                continue
            result = await self._call_with_retry(
                instance,
                messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=max_tokens,
                purpose=purpose,
            )
            if result is not None:
                self._preferred = instance.name
                self._degraded = False
                self._attempts.append({"provider": instance.name, "result": "ok"})
                return result
        self._degraded = True
        logger.warning(
            "全部模型供应商不可用，降级 mock：%s",
            self._attempts,
            extra={"event": "model_degraded"},
        )
        raise ModelUnavailableError("全部模型供应商不可用", attempts=self._attempts)

    async def probe(self, provider: str | None = None, *, force: bool = False) -> tuple[bool, str]:
        """探测单个供应商（带 60s 缓存）；失败只返回原因，不抛异常。"""
        name = provider or self.settings.configured_provider
        if name == "mock" or not name:
            return False, "未配置真实模型"
        now = time.monotonic()
        cached = self._probe_cache.get(name)
        if not force and cached is not None and now - cached[2] <= self._probe_ttl:
            return cached[0], cached[1]
        instance = self._provider(name)
        if instance is None or not instance.configured:
            result = (False, "未配置（缺少 Key 或 Base URL）")
            self._probe_cache[name] = (result[0], result[1], now)
            return result
        try:
            token = call_journal.bind_purpose("probe")
            try:
                ok, reason = await instance.probe()
            finally:
                call_journal.reset(token)
        except Exception as exc:  # 探测绝不冒泡
            ok, reason = False, str(exc)[:200]
        self._probe_cache[name] = (ok, reason, now)
        if ok:
            self._preferred = name
            self._circuit_open_until.pop(name, None)
        elif ok is False:
            logger.info(
                "供应商不可用 provider=%s reason=%s",
                name,
                reason,
                extra={"event": "model_probe_unavailable", "provider": name},
            )
        return ok, reason

    async def probe_chain(self) -> tuple[str | None, str]:
        """按优先级探测 fallback 链，返回首个可用供应商；全部失败返回原因。"""
        reasons: list[str] = []
        for name in self.chain():
            instance = self._provider(name)
            if instance is None or not instance.configured:
                continue
            ok, reason = await self.probe(name)
            if ok:
                self._preferred = name
                return name, ""
            reasons.append(f"{name}: {reason}")
        if not reasons:
            return None, "未配置任何真实模型（缺少 API Key）"
        return None, "；".join(reasons)

    def ensure_available(self) -> bool:
        """不发网络请求的可用性判断（供引擎决定是否直接降级 mock）。

        依据：供应商已配置 + 未被熔断 + 最近的探测没有明确失败。
        """
        now = time.monotonic()
        for name in self.chain(start=self._preferred):
            provider = self._provider(name)
            if provider is None or not provider.configured or self._circuit_open(name):
                continue
            cached = self._probe_cache.get(name)
            if cached is not None and now - cached[2] <= self._probe_ttl and not cached[0]:
                continue
            return True
        return False

    # ---------- 兼容旧接口 ----------
    async def generate_report_body(self, material: str, title: str) -> str:
        prompt = (
            "你是办公助理。请根据下面的素材，写一段 200 字以内的中文周报摘要，"
            "只陈述素材中出现的进展、数据与风险，不要编造。直接输出正文，不要标题。\n"
            f"报告标题：{title}\n素材：\n{material[:6000]}"
        )
        result = await self.chat(
            [
                {"role": "system", "content": "你是严谨的中文办公写作助手。"},
                {"role": "user", "content": prompt},
            ],
            # 0 当「不限制」：settings.model_max_tokens 的 0 是「不带这个字段」，
            # 不能原样传下去——`max_tokens=0` 会被供应商当成「不要输出」。
            max_tokens=self.settings.model_max_tokens or None,
        )
        if not result.text:
            raise RuntimeError("模型返回空正文")
        return result.text

    # ---------- 生命周期 ----------
    def reset_providers(self) -> None:
        """设置里的地址/模型改了：丢掉缓存的 provider 实例，下次按新配置重建。

        provider 构造时把 base_url 与模型名拍成了快照。用户刚在设置页填完接口地址，
        如果不丢缓存，要重启后端才生效——这条路用户根本猜不到。
        探测缓存与熔断也一起清掉：它们描述的是「旧地址」的健康状况。
        """
        self._providers.clear()
        self._probe_cache.clear()
        self._circuit_open_until.clear()

    # ---------- 内部 ----------
    def _provider(self, name: str) -> ModelProvider | None:
        existing = self._providers.get(name)
        if existing is not None:
            return existing
        if not name or name == "mock":
            return None
        try:
            instance: ModelProvider = build_provider(
                self.settings, name, http_client_factory=self._http_factory
            )
        except (ValueError, httpx.HTTPError):  # 未知供应商 / 客户端构造失败
            return None
        self._providers[name] = instance
        return instance

    async def _invoke(
        self,
        provider: ModelProvider,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        temperature: float,
        max_tokens: int | None,
        purpose: str = "engine",
    ) -> ChatResult:
        started = time.perf_counter()
        # 用途打在 ContextVar 上：真正记账的是 provider 那一层（它才知道
        # 「这次请求到底发出去了没有、发了几次」），而它不该关心这是主循环
        # 还是标题生成——那是上层的语义。
        token = call_journal.bind_purpose(purpose)
        try:
            result = await provider.chat(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        finally:
            call_journal.reset(token)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not result.request_id:
            # 官方接口都会回 id。没有 id 多半是自建网关/代理把回执吃掉了——
            # 调用本身可能还是真的，但「拿什么去控制台对账」就没了，记一条告警。
            logger.warning(
                "模型响应缺少 request id provider=%s model=%s（无法与供应商控制台对账）",
                provider.name,
                result.model or provider.model,
                extra={"event": "model_call_unverified", "provider": provider.name},
            )
        price = self.price_for(result.model or provider.model, provider.name)
        cost = self.estimate_cost(
            result.model or provider.model,
            provider.name,
            result.prompt_tokens,
            result.completion_tokens,
            cache_hit_tokens=result.cache_hit_tokens,
            # 0 当「没给」处理：供应商没回这字段时，未命中数按 prompt-hit 推，别把输入算成免费
            cache_miss_tokens=result.cache_miss_tokens or None,
        )
        chat_result = ChatResult(
            text=result.text,
            provider=provider.name,
            model=result.model or provider.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            tool_calls=result.tool_calls,
            finish_reason=result.finish_reason,
            cost_cny=cost,
            cache_hit_tokens=result.cache_hit_tokens,
            cache_miss_tokens=result.cache_miss_tokens,
            peak=price.peak,
            request_id=result.request_id,
            latency_ms=latency_ms,
        )
        meter = self.current_usage()
        meter.add(chat_result)
        logger.info(
            "模型调用成功 provider=%s model=%s request_id=%s tokens=%d+%d cost=%s latency=%dms calls=%d",
            chat_result.provider,
            chat_result.model,
            chat_result.request_id or "-",
            chat_result.prompt_tokens,
            chat_result.completion_tokens,
            chat_result.cost_cny,
            chat_result.latency_ms,
            meter.calls,
            extra={
                "event": "model_call",
                "provider": chat_result.provider,
                "model": chat_result.model,
                "request_id": chat_result.request_id,
            },
        )
        return chat_result

    async def _call_with_retry(
        self,
        provider: ModelProvider,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        temperature: float,
        max_tokens: int | None,
        purpose: str = "engine",
    ) -> ChatResult | None:
        """单供应商重试策略：限流/超时类重试 1 次；鉴权/5xx/格式异常立即切换。"""
        for attempt in range(2):
            try:
                return await self._invoke(
                    provider,
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    purpose=purpose,
                )
            except ProviderError as exc:
                self._attempts.append(
                    {
                        "provider": provider.name,
                        "result": "failed",
                        "attempt": attempt + 1,
                        **exc.public(),
                    }
                )
                logger.warning(
                    "模型调用失败 provider=%s category=%s attempt=%d message=%s",
                    provider.name,
                    exc.category.value,
                    attempt + 1,
                    exc.message[:200],
                    extra={"event": "model_call_failed", "provider": provider.name},
                )
                if exc.category == ErrorCategory.AUTH:
                    self._open_circuit(provider.name)
                    return None
                if attempt == 0 and exc.retryable:
                    if self._retry_backoff > 0:
                        await asyncio.sleep(self._retry_backoff)
                    continue
                return None
        return None

    def estimate_cost(
        self,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        cache_hit_tokens: int = 0,
        cache_miss_tokens: int | None = None,
        at: datetime | None = None,
    ) -> float:
        """按官方口径（分时 + 缓存分级）估算一次调用的钱。

        `cache_miss_tokens` 缺省时按「输入全部未命中」算——这是上限，宁可高估也不低报。
        """
        hit = max(0, cache_hit_tokens)
        miss = (
            max(0, cache_miss_tokens)
            if cache_miss_tokens is not None
            else max(0, prompt_tokens - hit)
        )
        return cost_for(
            provider,
            model,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            output_tokens=completion_tokens,
            at=at,
            table=self._price_book(),
        )

    def price_for(self, provider: str, model: str, *, at: datetime | None = None) -> PriceSet:
        """某供应商某模型在 at 时刻的单价（元 / 百万 tokens，含高峰/闲时与缓存档位）。"""
        return price_for(provider, model, at=at, table=self._price_book())

    def _price_book(self) -> dict[str, Any]:
        # 构造时传了 price_table（测试）就用它；否则每次跟文件走，改价不用重启
        if isinstance(self._prices, dict):
            return self._prices
        return load_price_table()

    def _circuit_open(self, name: str) -> bool:
        until = self._circuit_open_until.get(name)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._circuit_open_until.pop(name, None)
            return False
        return True

    def _open_circuit(self, name: str) -> None:
        self._circuit_open_until[name] = time.monotonic() + CIRCUIT_COOLDOWN_SECONDS
        logger.info(
            "供应商熔断（鉴权失败） provider=%s cooldown=%ss",
            name,
            CIRCUIT_COOLDOWN_SECONDS,
            extra={"event": "provider_circuit_open", "provider": name},
        )


def summarize_exception(exc: Exception) -> dict[str, Any]:
    """错误摘要（可与事件一起追加，不含密钥）。"""
    if isinstance(exc, ModelUnavailableError):
        return exc.public()
    return provider_error_summary(exc)
