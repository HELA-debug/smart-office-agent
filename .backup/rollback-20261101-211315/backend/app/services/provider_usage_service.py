"""供应商控制台上的真实用量（对账用）。

为什么需要它
------------
本地账本只能看见「本应用」发出的请求。同一把 Key 只要还被别的工具用过，
或者历史上跑过测试脚本，本地怎么加都对不上官方那本账——数字差得越多，
越像系统在编数据。官方控制台是权威口径，所以单开一条通道把它的数取回来，
和本地账本并排显示：差额就是「本应用之外的消耗」，一眼能看懂。

三个必须交代清楚的事实（都实测过，不是配置遗漏）
------------------------------------------------
1. **用量接口不吃 API Key。** `platform.deepseek.com/api/v0/usage/*` 走的是
   平台网页端的登录态；用 API Key 调只回 `{"code":40003,"msg":"Authorization
   Failed (invalid token)"}`。认 API Key 的只有 `api.deepseek.com/user/balance`。
   两套凭证互不通用，混用是最常见的踩坑点。
2. **userToken 短期有效。** 过期要重新从浏览器 localStorage 里取；这里只放在
   进程内存中，重启即失效，不落盘、不写日志、不回显。
3. **这是官方未承诺的私有接口。** 结构随时可能变，所以解析写成「结构无关的
   递归扫描」：只要字段名还在，层级怎么嵌套都能读出来；真读不出就原样回传原始
   响应，让人自己去看，而不是猜一个看起来合理的数字。

失败绝不影响本地账本：前端拿到 error 就只显示本地数据。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from ..core.config import Settings
from ..core.logging import get_logger
from ..core.utils import now_iso
from ..infra.http import build_http_client

logger = get_logger("app.services.provider_usage")

PLATFORM_BASE = "https://platform.deepseek.com"
BALANCE_URL = "https://api.deepseek.com/user/balance"

# 进程内存里的 userToken：不写库、不落盘。重启即失效，这是刻意的取舍——
# 这个 token 等价于控制台登录态，泄露的后果比 API Key 严重得多。
_TOKEN_STORE: dict[str, str] = {}
# 拉取结果缓存：key = (provider, year, month)，避免每开一次页面就打官方一次
_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 60.0
_CACHE_LOCK = asyncio.Lock()

# 官方字段名在不同层级下出现过的大小写变体，统一按别名收敛
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "cache_hit": ("PROMPT_CACHE_HIT_TOKEN", "prompt_cache_hit_tokens", "cacheHitTokens"),
    "cache_miss": ("PROMPT_CACHE_MISS_TOKEN", "prompt_cache_miss_tokens", "cacheMissTokens"),
    "output": ("RESPONSE_TOKEN", "response_token", "completion_tokens", "responseTokens"),
    "requests": ("REQUEST", "request", "requests", "request_count", "requestCount"),
    "cost": ("COST", "cost", "total_cost", "totalCost", "amount"),
    "date": ("date", "DATE", "day", "DAY", "time", "datetime"),
}


class ProviderUsageError(RuntimeError):
    """拉取官方用量失败。code 是给前端做分支用的稳定标识。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def public(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def _clean_token(raw: str) -> str:
    """把用户从浏览器复制来的内容清洗成裸 token。

    常见几种粘贴形态都要能吃下：
      - 裸 token 字符串
      - `"eyJhbGci..."`（带引号）
      - `{"value":"eyJ...","expire":...}`（localStorage.userToken 的完整值）
    """
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    if text[:1] in "{[":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            for key in ("value", "token", "access_token", "userToken"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip().strip('"')
        return text
    return text


def _pick(node: dict[str, Any], field: str) -> Any:
    for alias in _FIELD_ALIASES[field]:
        if alias in node:
            return node[alias]
    return None


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

# 两类接口各自的取值范围：amount 给 token/请求数，cost 给钱。
# 分开取是为了防止「amount 响应里也带了个总金额」被重复累加。
_TOKEN_FIELDS = ("requests", "cache_hit", "cache_miss", "output")
_COST_FIELDS = ("cost",)
_ALL_FIELDS = ("requests", "cache_hit", "cache_miss", "output", "cost")


def _walk(node: Any, visit: Any, depth: int = 0, date_ctx: str = "") -> None:
    """深度优先遍历，把父节点的 date 一路传给子节点。

    官方的结构是「日期节点套明细节点」：日期在外层、用量在内层。
    只看单个节点会漏掉日期，只跟日期又会漏掉用量，所以必须带着上下文走。
    故意不绑定固定层级：这些是平台前端自用的私有接口，层级没有对外承诺。
    """
    if depth > 12:  # 防病态嵌套
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, visit, depth + 1, date_ctx)
        return
    if not isinstance(node, dict):
        return

    raw_date = _pick(node, "date")
    if isinstance(raw_date, str):
        matched = _DATE_RE.match(raw_date.strip())
        if matched:
            date_ctx = matched.group(0)

    visit(node, date_ctx)
    for value in node.values():
        if isinstance(value, (dict, list)):
            _walk(value, visit, depth + 1, date_ctx)


def _usage_values(node: dict[str, Any], fields: tuple[str, ...]) -> dict[str, float]:
    values = {name: 0.0 for name in fields}
    for name in fields:
        if name == "cost":
            values[name] = _as_float(_pick(node, "cost"))
        else:
            values[name] = float(_as_int(_pick(node, name)))
    return values


def _new_bucket(fields: tuple[str, ...]) -> dict[str, float]:
    bucket = {name: 0.0 for name in fields}
    bucket["tokens"] = 0.0
    return bucket


def scan_usage(
    payload: Any,
    fields: tuple[str, ...],
    days: dict[str, dict[str, float]],
) -> dict[str, float]:
    """从一份官方响应里抽出用量：返回合计，同时把按日明细写进 days。

    优先级是「日期明细 > 无日期的汇总字段」：官方响应常常既有按日表又有总计，
    两张都算就会把同一笔钱记两遍。有明细只认明细，没明细才退回汇总值。
    """
    dated: dict[str, dict[str, float]] = {}
    loose = _new_bucket(fields)

    def visit(node: dict[str, Any], day: str) -> None:
        values = _usage_values(node, fields)
        if not any(values.values()):
            return
        target = dated.setdefault(day, _new_bucket(fields)) if day else loose
        for name, value in values.items():
            target[name] = target.get(name, 0.0) + value

    _walk(payload, visit)

    totals = _new_bucket(fields)
    for day, values in (dated or {"": loose}).items():
        if day:
            bucket = days.setdefault(day, _new_bucket(_ALL_FIELDS))
            for name, value in values.items():
                bucket[name] = bucket.get(name, 0.0) + value
        # 合计始终要累加：明细写 days，汇总写 totals，两者不是二选一
        for name, value in values.items():
            totals[name] = totals.get(name, 0.0) + value
    _refresh_tokens(days)
    _refresh_tokens([totals])
    return totals


def _refresh_tokens(buckets: Any) -> None:
    """tokens 永远等于命中 + 未命中 + 输出，不单独累加，避免两路响应打架。"""
    items = buckets.values() if isinstance(buckets, dict) else buckets
    for bucket in items:
        bucket["tokens"] = (
            bucket.get("cache_hit", 0.0) + bucket.get("cache_miss", 0.0) + bucket.get("output", 0.0)
        )


def _scan(node: Any, days: dict[str, dict[str, float]], totals: dict[str, float]) -> None:
    """兼容旧调用：把一份响应合并进按日明细与合计。"""
    result = scan_usage(node, _TOKEN_FIELDS + _COST_FIELDS, days)
    for name, value in result.items():
        totals[name] = totals.get(name, 0.0) + value


class ProviderUsageService:
    """拉官方控制台用量。token 只在内存，重启即失效。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---------- token 管理 ----------
    def set_token(self, provider: str, token: str) -> dict[str, Any]:
        cleaned = _clean_token(token)
        if not cleaned:
            raise ProviderUsageError(
                "TOKEN_EMPTY", "token 为空：请从浏览器 localStorage 里复制 userToken 的值"
            )
        if len(cleaned) < 16:
            raise ProviderUsageError("TOKEN_TOO_SHORT", "token 太短，看起来不是完整的 userToken")
        _TOKEN_STORE[provider] = cleaned
        _CACHE.clear()  # 换人换账，旧缓存立刻作废
        logger.info("已设置官方用量 token provider=%s（仅内存）", provider)
        return {"provider": provider, "has_token": True, "token_preview": _mask(cleaned)}

    def clear_token(self, provider: str) -> dict[str, Any]:
        _TOKEN_STORE.pop(provider, None)
        _CACHE.clear()
        return {"provider": provider, "has_token": False}

    def status(self, provider: str) -> dict[str, Any]:
        token = _TOKEN_STORE.get(provider)
        return {"provider": provider, "has_token": bool(token), "token_preview": _mask(token or "")}

    # ---------- 拉取 ----------
    async def fetch(
        self,
        provider: str = "deepseek",
        *,
        year: int | None = None,
        month: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        current = now_iso()
        year_value = year or int(current[:4])
        month_value = month or int(current[5:7])
        cache_key = (provider, str(year_value), f"{month_value:02d}")

        token = _TOKEN_STORE.get(provider)
        if not token:
            raise ProviderUsageError(
                "NO_TOKEN",
                "还没有填写官方 token。官方用量接口需要控制台登录态（不是 API Key），"
                "请从浏览器 localStorage.userToken 复制后填入。",
            )

        if not force:
            cached = _CACHE.get(cache_key)
            if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]

        async with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and not force and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]
            data = await self._fetch_uncached(provider, token, year_value, month_value)
            _CACHE[cache_key] = (time.time(), data)
            return data

    async def _fetch_uncached(
        self, provider: str, token: str, year: int, month: int
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Referer": f"{PLATFORM_BASE}/usage",
            "x-app-version": "20240101.0",
        }
        amount_url = f"{PLATFORM_BASE}/api/v0/usage/amount?month={month}&year={year}"
        cost_url = f"{PLATFORM_BASE}/api/v0/usage/cost?month={month}&year={year}"
        summary_url = f"{PLATFORM_BASE}/api/v0/users/get_user_summary"

        payloads: dict[str, Any] = {}
        async with build_http_client(self.settings, timeout=20.0) as client:
            for name, url in (
                ("amount", amount_url),
                ("cost", cost_url),
                ("summary", summary_url),
            ):
                try:
                    response = await client.get(url, headers=headers)
                except (httpx.TimeoutException, httpx.HTTPError) as exc:
                    raise ProviderUsageError(
                        "NETWORK", f"连不上官方平台接口：{type(exc).__name__}"
                    ) from exc
                payloads[name] = _decode(response)

        # 三个接口任一返回鉴权失败，都说明 token 失效了，不必再看别的
        for payload in payloads.values():
            code = payload.get("code") if isinstance(payload, dict) else None
            if code in (40002, 40003, 401):
                raise ProviderUsageError(
                    "TOKEN_EXPIRED",
                    "官方 token 已失效（返回 40002/40003）。请重新登录 platform.deepseek.com，"
                    "从浏览器 localStorage.userToken 复制新的值。",
                )

        days: dict[str, dict[str, float]] = {}
        # 两份响应各管一摊：amount 出 token 与请求数，cost 出钱。
        # 混在一起扫会让「同一笔钱」在两种视角下各记一次。
        tokens_part = scan_usage(payloads.get("amount"), _TOKEN_FIELDS, days)
        cost_part = scan_usage(payloads.get("cost"), _COST_FIELDS, days)
        totals = {
            name: tokens_part.get(name, 0.0) + cost_part.get(name, 0.0) for name in _ALL_FIELDS
        }
        totals["tokens"] = tokens_part.get("tokens", 0.0)

        result: dict[str, Any] = {
            "provider": provider,
            "source": f"{PLATFORM_BASE}/usage",
            "month": f"{year}-{month:02d}",
            "available": True,
            "has_token": True,
            "requests": int(totals["requests"]),
            "tokens": int(totals["tokens"]),
            "cost_cny": round(totals["cost"], 6),
            "cache_hit_tokens": int(totals["cache_hit"]),
            "cache_miss_tokens": int(totals["cache_miss"]),
            "output_tokens": int(totals["output"]),
            "days": [
                {
                    "date": date,
                    "requests": int(values["requests"]),
                    "tokens": int(values["tokens"]),
                    "cost_cny": round(values["cost"], 6),
                }
                for date, values in sorted(days.items())
            ],
            "balance": _parse_balance(payloads.get("summary")),
            "fetched_at": now_iso(),
            "note": "官方口径：按平台账单统计，包含本应用之外（其它工具 / 历史脚本）的消耗。",
        }
        if not result["requests"] and not result["tokens"]:
            # 一个数都没读出来：把原始响应带上，让人自己看结构，别猜
            result["unparsed"] = True
            result["raw"] = {key: _shrink(value) for key, value in payloads.items()}
            result["note"] = (
                "没从官方响应里认出用量字段（接口结构可能变了）。已附原始响应，可据此调整解析。"
            )
        return result

    async def balance(self, provider: str = "deepseek") -> dict[str, Any]:
        """余额走 API Key（这条是公开接口）：和登录态无关，永远可用。"""
        key = self.settings.provider_api_key(provider)
        if not key:
            return {"available": False, "error": {"code": "NO_KEY", "message": "未配置 API Key"}}
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        try:
            async with build_http_client(self.settings, timeout=15.0) as client:
                response = await client.get(BALANCE_URL, headers=headers)
            payload = _decode(response)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            return {
                "available": False,
                "error": {"code": "NETWORK", "message": f"连不上余额接口：{type(exc).__name__}"},
            }
        return _parse_balance(payload)


def _decode(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {"code": response.status_code, "msg": response.text[:200]}
    return data if isinstance(data, dict) else {"data": data}


def _parse_balance(payload: Any) -> dict[str, Any]:
    """把余额响应归一成 CNY 的总额/赠送/充值。"""
    if not isinstance(payload, dict):
        return {"available": False}
    infos = payload.get("balance_infos")
    if not isinstance(infos, list):
        # summary 接口的余额字段可能藏在别处，扫一遍找 total_balance
        found = _find_balance(payload)
        return found or {"available": False}
    for item in infos:
        if not isinstance(item, dict):
            continue
        if str(item.get("currency", "")).upper() == "CNY" or len(infos) == 1:
            return {
                "available": bool(payload.get("is_available", True)),
                "currency": item.get("currency", "CNY"),
                "total": item.get("total_balance"),
                "granted": item.get("granted_balance"),
                "topped_up": item.get("topped_up_balance"),
            }
    first = infos[0] if infos and isinstance(infos[0], dict) else {}
    return {
        "available": bool(payload.get("is_available", True)),
        "currency": first.get("currency", ""),
        "total": first.get("total_balance"),
        "granted": first.get("granted_balance"),
        "topped_up": first.get("topped_up_balance"),
    }


def _find_balance(node: Any, depth: int = 0) -> dict[str, Any] | None:
    if depth > 6:
        return None
    if isinstance(node, dict):
        if "total_balance" in node or "balance" in node:
            return {
                "available": True,
                "currency": node.get("currency", "CNY"),
                "total": node.get("total_balance", node.get("balance")),
                "granted": node.get("granted_balance"),
                "topped_up": node.get("topped_up_balance"),
            }
        for value in node.values():
            if isinstance(value, (dict, list)):
                found = _find_balance(value, depth + 1)
                if found:
                    return found
    elif isinstance(node, list):
        for item in node:
            found = _find_balance(item, depth + 1)
            if found:
                return found
    return None


def _shrink(value: Any, limit: int = 4000) -> Any:
    """原始响应可能很大，截断到可读范围再回传。"""
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if len(text) <= limit:
        return value
    try:
        return json.loads(text[:limit])
    except json.JSONDecodeError:
        return text[:limit]


def _mask(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:4]}…{token[-4:]}"
