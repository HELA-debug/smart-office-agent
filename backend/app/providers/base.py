"""ModelProvider 协议：OpenAI 兼容供应商的统一适配层。

职责边界（计划书 7.2）：Provider 只负责**鉴权、请求构造、响应解析、错误分类**，
不参与计划与工具决策。上层 ReAct 循环、工具 schema、事件协议与供应商无关。

- 所有外部 HTTP 走 `app.infra.http.build_http_client`（trust_env=False + 显式代理），
  规避 Windows `NO_PROXY=[::1]` 导致 httpx `InvalidURL` 的问题；
- 密钥只从 Settings/env 读取，日志与接口只显示引用（`env:XXX_API_KEY`）或掩码；
- 错误统一收敛为 `ProviderError`，由 ModelRouter 决定"重试 / 切换 / 降级"。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import httpx

from ..core import call_journal
from ..core.config import PROVIDER_DEFAULTS, Settings
from ..core.logging import get_logger
from ..core.net_guard import UnsafeUrlError, validate_outbound_url
from ..infra.http import build_http_client

logger = get_logger("app.providers")

HttpClientFactory = Callable[[Settings], httpx.AsyncClient]

# 有些模型（deepseek-flash 偶发）会把工具调用写成正文里的标记，而不是结构化 tool_calls：
#   <｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name="file_read">…
# 这种片段既不能执行、也不该给人看，原样吐到对话里就是一段乱码。
# 这里在归一化阶段切掉；切完如果什么都不剩，上层会当「空回复」重试/兜底。
_TOOL_MARKUP_STARTS = (
    "<｜｜DSML｜｜",
    "<||DSML||",
    "<|tool▁calls▁begin|>",
    "<|tool_calls_begin|>",
)


def strip_tool_markup(text: str) -> str:
    """去掉正文里泄漏的工具调用标记（从第一个标记起整段丢弃）。"""
    trimmed = text or ""
    cut = min(
        (index for index in (trimmed.find(marker) for marker in _TOOL_MARKUP_STARTS) if index >= 0),
        default=-1,
    )
    if cut >= 0:
        trimmed = trimmed[:cut]
    return trimmed.strip()


_DSML_INVOKE_RE = re.compile(r'invoke\s+name="([A-Za-z0-9_.\-]+)"(.*?)(?:</[^>]*invoke>|\Z)', re.S)
_DSML_PARAM_RE = re.compile(
    r'parameter\s+name="([A-Za-z0-9_.\-]+)"([^>]*)>(.*?)(?:</[^>]*parameter>|\Z)', re.S
)
_DSML_TAG_RE = re.compile(r"</?[^>]*>", re.S)


def recover_tool_calls(text: str) -> tuple[ToolCall, ...]:
    """从泄漏的 DSML 标记里把工具调用捞回来。

    标记只是「调用没走结构化通道」，信息本身是完整的：谁、带什么参数。
    捞回来这一轮就能继续，不必把整次运行降级成「模型不可用」。
    """
    if not any(marker in text for marker in _TOOL_MARKUP_STARTS):
        return ()
    calls: list[ToolCall] = []
    for index, match in enumerate(_DSML_INVOKE_RE.finditer(text)):
        name, body = match.group(1), match.group(2)
        arguments: dict[str, Any] = {}
        for param in _DSML_PARAM_RE.finditer(body):
            key, attrs, raw = param.group(1), param.group(2), param.group(3)
            value: Any = _DSML_TAG_RE.sub("", raw).strip()
            # 标记里用 string="true|false" 区分「原样字符串」和「JSON 值」
            if 'string="true"' not in attrs:
                with contextlib.suppress(TypeError, ValueError):
                    value = json.loads(value)
            arguments[key] = value
        calls.append(
            ToolCall(
                id=f"call_recovered_{index}",
                name=name,
                arguments=arguments,
                raw_arguments=json.dumps(arguments, ensure_ascii=False),
            )
        )
    return tuple(calls)


# 各供应商默认模型名（可被 Settings.model_name 覆盖当前主供应商）
DEFAULT_MODELS: dict[str, str] = {
    # 用官方 /v1/models 里的真名。`deepseek-chat` 是旧别名，官方会静默路由到 flash，
    # 回执 model 与配置名不符，控制台按回执名归账，容易让人以为「没调用」。
    "deepseek": "deepseek-flash",
    "qwen": "qwen-plus",
    "glm": "glm-4-plus",
    "openai": "gpt-4o-mini",
    # WorkBuddy 的模型名按账号给，默认值只是占位，可在「设置接口」里改
    "workbuddy": "workbuddy-chat",
}

# 密钥引用名：设置中心只展示 `env:XXX`，绝不回显明文
API_KEY_ENV: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "GLM_API_KEY",
    "openai": "OPENAI_API_KEY",
    "workbuddy": "WORKBUDDY_API_KEY",
}


class ErrorCategory(StrEnum):
    """错误分类（计划书表 7-3）。"""

    AUTH = "auth"  # 401 / 403：立即切换下一家
    RATE_LIMIT = "rate_limit"  # 429：退避 1s 重试 1 次，仍失败切换
    TIMEOUT = "timeout"  # 连接/读取超时：重试 1 次，仍失败切换
    SERVER = "server"  # 5xx：立即切换
    BAD_FORMAT = "bad_format"  # 缺 choices / tool_calls 不合法：切换
    NETWORK = "network"  # 连接失败 / DNS / 代理错误：重试 1 次
    UNCONFIGURED = "unconfigured"  # 无 Key / 无 Base URL：跳过


class ProviderError(Exception):
    """供应商调用失败（携带机器可读分类，供路由决策）。"""

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.body = body

    @property
    def retryable(self) -> bool:
        return self.category in (
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.TIMEOUT,
            ErrorCategory.NETWORK,
        )

    def public(self) -> dict[str, Any]:
        """可写入事件/日志的摘要（不含任何密钥）。"""
        return {
            "provider": self.provider,
            "category": self.category.value,
            "status_code": self.status_code,
            "message": self.message[:300],
        }

    def __str__(self) -> str:
        return f"[{self.category.value}] {self.message}"


@dataclass(frozen=True)
class ToolCall:
    """归一化后的工具调用（不同供应商的 tool_calls 结构在此收敛）。"""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass(frozen=True)
class ProviderResult:
    text: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    # 输入侧缓存拆分：DeepSeek 按「缓存命中 / 未命中」两档计价，单价差 50 倍。
    # 不记这两个数，成本只能按「全部未命中」上限估，跟控制台账单必然对不上。
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    # 供应商给这次请求的 id（DeepSeek/OpenAI 都有）。它是「这真是一次外部调用」的凭据：
    # 控制台对账、排查「为什么本地有 token 账单、控制台却没有」，都靠它。
    request_id: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@runtime_checkable
class ModelProvider(Protocol):
    """供应商适配协议：新增供应商 = 新增一个类 + 一行注册。"""

    name: str
    model: str
    base_url: str

    @property
    def configured(self) -> bool: ...

    @property
    def api_key_ref(self) -> str: ...

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        allow_empty: bool = False,
    ) -> ProviderResult: ...

    async def probe(self) -> tuple[bool, str]: ...


def _finish_reason(data: dict[str, Any]) -> str:
    """回执里的 finish_reason（取第一条 choice）；拿不到就返回空串。"""
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return str(choices[0].get("finish_reason") or "")
    return ""


def resolve_api_key(settings: Settings, provider: str) -> str:
    """解析供应商密钥。

    - deepseek / glm / openai / workbuddy 走 Settings 字段；
    - qwen 兼容 `DASHSCOPE_API_KEY`（Settings 尚未声明该字段，B3 设置中心后续收口）；
    - deepseek 兼容 v0.1 通用 `OPENAI_API_KEY`（DeepSeek 的 OpenAI 兼容场景）；
    - workbuddy 额外读一次环境变量，便于容器里只注入 env 的场景。
    """
    if provider == "deepseek":
        return settings.deepseek_api_key or settings.openai_api_key
    if provider == "qwen":
        return settings.qwen_api_key or os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if provider == "glm":
        return settings.glm_api_key
    if provider == "openai":
        return settings.openai_api_key
    if provider == "workbuddy":
        # 没有默认端点，也没有跨供应商兜底：只认用户自己粘进来的那把 Key
        return settings.workbuddy_api_key or os.environ.get("WORKBUDDY_API_KEY", "").strip()
    return ""


def resolve_model(settings: Settings, provider: str) -> str:
    """模型名可配：主供应商用 Settings.model_name，备用供应商用默认模型。"""
    default = DEFAULT_MODELS.get(provider, "")
    if provider == settings.configured_provider:
        configured = (settings.model_name or "").strip()
        if configured and configured != "mock-scripted":
            return configured
    return default


def resolve_base_url(settings: Settings, provider: str) -> str:
    return settings.provider_base_url(provider) or PROVIDER_DEFAULTS.get(provider, "").rstrip("/")


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        text = text.replace(secret, "***")
    return text[:300]


class OpenAICompatibleProvider:
    """OpenAI `/chat/completions` 兼容实现（DeepSeek / 千问 / GLM / OpenAI 公用）。"""

    def __init__(
        self,
        settings: Settings,
        *,
        provider: str,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client_factory: HttpClientFactory = build_http_client,
    ) -> None:
        self.settings = settings
        self.name = provider
        self.model = model or resolve_model(settings, provider)
        self.base_url = (base_url or resolve_base_url(settings, provider)).rstrip("/")
        self._api_key = resolve_api_key(settings, provider) if api_key is None else api_key
        self._http_factory = http_client_factory

    # ---------- 描述 ----------
    @property
    def configured(self) -> bool:
        return bool(self._api_key and self.base_url and self.model)

    @property
    def api_key_ref(self) -> str:
        return f"env:{API_KEY_ENV.get(self.name, f'{self.name.upper()}_API_KEY')}"

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "configured": self.configured,
            "api_key_ref": self.api_key_ref,
        }

    # ---------- 调用 ----------
    def _assert_base_url_allowed(self) -> None:
        """出网前兜底 SSRF 校验：请求会带 Authorization 头，目标必须是可信外网地址。

        登记接口已校验一次，但 base_url 之后仍可能被环境变量/DB 覆盖，
        因此在真正发请求前再校验一次（不可重试，避免放大风险）。
        """
        try:
            validate_outbound_url(
                self.base_url,
                allowlist=self.settings.model_base_url_allowlist_hosts or None,
            )
        except UnsafeUrlError as exc:
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                f"base_url 不安全，已拒绝请求：{exc.message}",
                provider=self.name,
            ) from exc

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        allow_empty: bool = False,
    ) -> ProviderResult:
        """发一次对话请求。

        max_tokens：`None` 表示**不限制**——请求里干脆不带这个字段，让供应商按模型
        自身的输出上限走。这是默认行为：它是上限不是花费，按实际输出计费，卡紧了
        只会在推理模型上把正文挤成空串，不省钱。

        allow_empty：允许「有合法回执但正文为空」。推理模型（如 deepseek-flash）
        会先写 reasoning_content，`max_tokens` 太小时正文就是空串，但这**不是**故障；
        探测用它判断端点通不通，别把正常回执当格式错误。
        """
        if not self.configured:
            raise ProviderError(
                ErrorCategory.UNCONFIGURED,
                f"供应商未配置（缺 Key 或 Base URL）：{self.name}",
                provider=self.name,
            )
        self._assert_base_url_allowed()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        # 不限制时**不要**带这个字段：带个天文数字容易被网关/代理当成非法参数拒绝，
        # 而省略它正是「按模型上限走」在 OpenAI 兼容协议里的标准写法。
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        async def _post(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
            """发一次 HTTP 请求，返回 (回执, 耗时)。

            记账放在这里而不是上层：`max_tokens` 被截断时这一层会**再发一次**，
            两次都是供应商真的收到、真的计费的请求。上层只看得见最后那次回执，
            按上层记账就会少算一次——那正是账本要对齐的那部分差额。
            """
            posted_at = time.perf_counter()
            try:
                async with self._http_factory(self.settings) as client:
                    response = await client.post(url, json=body, headers=headers)
            except httpx.TimeoutException as exc:
                self._note_failure(
                    ErrorCategory.TIMEOUT, str(exc), int((time.perf_counter() - posted_at) * 1000)
                )
                raise ProviderError(
                    ErrorCategory.TIMEOUT,
                    f"模型调用超时：{_redact(str(exc), self._api_key)}",
                    provider=self.name,
                ) from exc
            except httpx.HTTPError as exc:
                self._note_failure(
                    ErrorCategory.NETWORK, str(exc), int((time.perf_counter() - posted_at) * 1000)
                )
                raise ProviderError(
                    ErrorCategory.NETWORK,
                    f"模型网络错误：{_redact(str(exc), self._api_key)}",
                    provider=self.name,
                ) from exc

            latency_ms = int((time.perf_counter() - posted_at) * 1000)
            if response.status_code >= 400:
                error = self._error_from_response(response)
                self._note_failure(
                    error.category, error.message, latency_ms, status_code=response.status_code
                )
                raise error
            try:
                data = response.json()
            except ValueError as exc:
                self._note_failure(ErrorCategory.BAD_FORMAT, "响应不是合法 JSON", latency_ms)
                raise ProviderError(
                    ErrorCategory.BAD_FORMAT,
                    "响应不是合法 JSON",
                    provider=self.name,
                    status_code=response.status_code,
                    body=_redact(response.text, self._api_key),
                ) from exc
            if not isinstance(data, dict):
                self._note_failure(ErrorCategory.BAD_FORMAT, "响应结构不是对象", latency_ms)
                raise ProviderError(
                    ErrorCategory.BAD_FORMAT,
                    "响应结构不是对象",
                    provider=self.name,
                    status_code=response.status_code,
                )
            return data, latency_ms

        # 推理模型（deepseek-flash 默认就带思考）会先把 `max_tokens` 花在 reasoning_content 上：
        # 预算给少了，回执里正文是空串、finish_reason=length —— 这不是「供应商挂了」，
        # 是预算不够。以前直接判失败并降级收尾，用户看到「模型服务暂时不可用」，
        # 明明调用成功、钱也扣了。所以这里放大预算再要一次。
        #
        # 不限制（None）时没有「放大」这回事：本来就没设上限，再被截断只可能是模型自身的
        # 输出上限到了，再要一次结果一样，只会白等一轮。
        budgets: list[int | None] = [max_tokens]
        if max_tokens is not None and not allow_empty:
            # 推理模型先写 reasoning，工具参数又是一整段 JSON（常是几十行脚本）：
            # 2000 的输出预算很容易在参数中间被截断，回执里 tool_calls.arguments 不完整。
            # 这不是模型坏了，是预算不够，放大再要一次。
            bumped = min(max(max_tokens * 3, 6000), 16000)
            if bumped > max_tokens:
                budgets.append(bumped)

        result: ProviderResult | None = None
        for index, budget in enumerate(budgets):
            if budget is None:
                payload.pop("max_tokens", None)
            else:
                payload["max_tokens"] = budget
            data, latency_ms = await _post(payload)
            truncated = _finish_reason(data) == "length"
            try:
                # 先按「允许空」解析：空正文要不要报错，由下面的业务判断决定
                result = self._parse_result(data, allow_empty=True)
            except ProviderError as exc:
                # 回执解析不了也是花了钱的：对面收到了请求、给了回执。
                self._note_failure(exc.category, exc.message, latency_ms)
                # 工具参数被截断 → JSON 解析失败。只有「确实是被 budget 截断」才重试，
                # 否则会把真正的坏回执也一起掩盖掉。
                if (
                    truncated
                    and exc.category == ErrorCategory.BAD_FORMAT
                    and index < len(budgets) - 1
                ):
                    logger.info(
                        "回执被 max_tokens 截断（%s），放大预算重试 provider=%s %s->%s",
                        exc.message[:80],
                        self.name,
                        budget,
                        budgets[index + 1],
                        extra={"event": "model_truncated_retry", "provider": self.name},
                    )
                    continue
                raise
            self._note_success(result, latency_ms, attempt=index + 1)
            if allow_empty or result.text or result.tool_calls:
                break
            if not truncated or index == len(budgets) - 1:
                break
            logger.info(
                "正文为空但 finish_reason=length，放大 max_tokens 重试 provider=%s %s->%s",
                self.name,
                budget,
                budgets[index + 1],
                extra={"event": "model_empty_retry", "provider": self.name},
            )
        if result is None:  # pragma: no cover - budgets 至少一项
            raise ProviderError(ErrorCategory.BAD_FORMAT, "模型没有返回结果", provider=self.name)
        if not allow_empty and not result.text and not result.tool_calls:
            budget_note = (
                "未设输出上限"
                if max_tokens is None
                else f"输出预算已放大到 {payload.get('max_tokens')}"
            )
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                "模型返回空内容（既无文本也无 tool_calls）；"
                f"finish_reason={result.finish_reason or '-'}，{budget_note}，"
                "仍被思考过程占满",
                provider=self.name,
            )
        return result

    async def probe(self) -> tuple[bool, str]:
        """连通性探测：失败只返回原因，不抛异常、不泄露 Key。

        判据是「端点是否给出合法回执」，不是「有没有正文」：
        推理模型在小 max_tokens 下只吐 reasoning_content，正文为空属正常。
        以前这里要正文非空，deepseek-flash 必然探测失败，进而把整个引擎
        静默降级成 mock——用户以为在跟大模型说话，其实是本地脚本。
        """
        if not self.configured:
            return False, "未配置（缺少 Key 或 Base URL）"
        try:
            await self.chat(
                [{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=32,
                allow_empty=True,
            )
        except ProviderError as exc:
            logger.warning(
                "模型探测失败 provider=%s category=%s status=%s",
                self.name,
                exc.category.value,
                exc.status_code,
                extra={"event": "model_probe_failed", "provider": self.name},
            )
            return False, _redact(exc.message, self._api_key)
        logger.info(
            "模型探测成功 provider=%s model=%s key=%s",
            self.name,
            self.model,
            self.api_key_ref,
            extra={"event": "model_probe_ok", "provider": self.name},
        )
        return True, ""

    # ---------- 内部 ----------
    def _note_success(self, result: ProviderResult, latency_ms: int, *, attempt: int = 1) -> None:
        """把一次成功回执记进账本。

        金额不在这里算：账本汇总时按现价重算（与 `UsageService` 同一口径），
        否则价格表一改，历史账就自相矛盾。
        """
        call_journal.record(
            call_journal.entry_for(
                provider=self.name,
                model=result.model or self.model,
                status="ok",
                request_id=result.request_id,
                finish_reason=result.finish_reason,
                input_tokens=result.prompt_tokens,
                output_tokens=result.completion_tokens,
                cache_hit_tokens=result.cache_hit_tokens,
                cache_miss_tokens=result.cache_miss_tokens,
                latency_ms=latency_ms,
                attempt=attempt,
            )
        )

    def _note_failure(
        self,
        category: ErrorCategory,
        message: str,
        latency_ms: int,
        *,
        status_code: int | None = None,
    ) -> None:
        """失败的请求也记账：对面收到了、可能也扣了钱，只是没给 usage。

        金额记 0（没有 usage usable），但次数与错误码要留 —— 「为什么控制台的
        请求数比应用内多」的答案，一半落在这类行里。
        """
        code = category.value if status_code is None else f"{category.value}:{status_code}"
        call_journal.record(
            call_journal.entry_for(
                provider=self.name,
                model=self.model,
                status="failed",
                latency_ms=latency_ms,
                error_code=code[:64],
                error_message=_redact(str(message), self._api_key)[:400],
            )
        )

    def _error_from_response(self, response: httpx.Response) -> ProviderError:
        status = response.status_code
        body = _redact(response.text, self._api_key)
        if status in (401, 403):
            category = ErrorCategory.AUTH
        elif status == 429:
            category = ErrorCategory.RATE_LIMIT
        elif status >= 500:
            category = ErrorCategory.SERVER
        else:
            category = ErrorCategory.BAD_FORMAT
        return ProviderError(
            category,
            f"HTTP {status}：{body}",
            provider=self.name,
            status_code=status,
            body=body,
        )

    def _parse_result(self, data: dict[str, Any], *, allow_empty: bool = False) -> ProviderResult:
        choices = data.get("choices") or []
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                "响应缺少 choices",
                provider=self.name,
            )
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                "响应缺少 message",
                provider=self.name,
            )
        text = strip_tool_markup(str(message.get("content") or ""))
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        if not tool_calls:
            # 调用被写进了正文（DSML 标记）：捞回来继续，别让整次运行降级
            tool_calls = recover_tool_calls(str(message.get("content") or ""))
        if not text and not tool_calls and not allow_empty:
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                "模型返回空内容（既无文本也无 tool_calls）",
                provider=self.name,
            )
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        # DeepSeek 会给 prompt_cache_hit_tokens / prompt_cache_miss_tokens；
        # OpenAI 只在 prompt_tokens_details.cached_tokens 里给命中数。两种都认。
        details = usage.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}
        hit_raw = usage.get("prompt_cache_hit_tokens", details.get("cached_tokens"))
        try:
            cache_hit = int(hit_raw) if hit_raw is not None else 0
        except (TypeError, ValueError):
            cache_hit = 0
        miss_raw = usage.get("prompt_cache_miss_tokens")
        try:
            cache_miss = (
                int(miss_raw) if miss_raw is not None else max(0, prompt_tokens - cache_hit)
            )
        except (TypeError, ValueError):
            cache_miss = max(0, prompt_tokens - cache_hit)
        return ProviderResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=str(choice.get("finish_reason") or ""),
            model=str(data.get("model") or self.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cache_hit_tokens=max(0, cache_hit),
            cache_miss_tokens=max(0, cache_miss),
            request_id=str(data.get("id") or ""),
        )

    def _parse_tool_calls(self, raw_calls: Any) -> tuple[ToolCall, ...]:
        if raw_calls is None:
            return ()
        if not isinstance(raw_calls, list):
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                "tool_calls 不是数组",
                provider=self.name,
            )
        calls: list[ToolCall] = []
        for index, raw in enumerate(raw_calls):
            if not isinstance(raw, dict):
                raise ProviderError(
                    ErrorCategory.BAD_FORMAT,
                    "tool_calls 元素不是对象",
                    provider=self.name,
                )
            function = raw.get("function")
            if not isinstance(function, dict):
                raise ProviderError(
                    ErrorCategory.BAD_FORMAT,
                    "tool_calls 缺少 function",
                    provider=self.name,
                )
            name = str(function.get("name") or "").strip()
            if not name:
                raise ProviderError(
                    ErrorCategory.BAD_FORMAT,
                    "tool_calls 缺少函数名",
                    provider=self.name,
                )
            raw_arguments = function.get("arguments")
            arguments = self._parse_arguments(raw_arguments)
            calls.append(
                ToolCall(
                    id=str(raw.get("id") or f"call_{index}"),
                    name=name,
                    arguments=arguments,
                    raw_arguments=raw_arguments if isinstance(raw_arguments, str) else "",
                )
            )
        return tuple(calls)

    def _parse_arguments(self, raw_arguments: Any) -> dict[str, Any]:
        if raw_arguments is None or raw_arguments == "":
            return {}
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not isinstance(raw_arguments, str):
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                "tool_calls arguments 类型非法",
                provider=self.name,
            )
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                f"tool_calls arguments 不是合法 JSON：{raw_arguments[:120]}",
                provider=self.name,
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                ErrorCategory.BAD_FORMAT,
                "tool_calls arguments 必须是对象",
                provider=self.name,
            )
        return parsed


def provider_error_summary(exc: Exception) -> dict[str, Any]:
    """把任意异常压成可写日志/事件的摘要（不泄露密钥）。"""
    if isinstance(exc, ProviderError):
        return exc.public()
    return {"provider": "", "category": "unknown", "message": str(exc)[:300]}
