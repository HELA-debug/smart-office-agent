"""官方用量接口的解析与错误映射。

这些接口是平台网页端自用的私有接口，结构没有对外承诺。测试锁住的是
「读得懂就归一到统一口径，读不懂就老实说读不懂」，而不是某个具体 schema。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from app.core.config import Settings
from app.services import provider_usage_service as mod
from app.services.provider_usage_service import (
    ProviderUsageError,
    ProviderUsageService,
    _clean_token,
    _parse_balance,
    scan_usage,
)


@pytest.fixture(autouse=True)
def _reset_state() -> Any:
    mod._TOKEN_STORE.clear()
    mod._CACHE.clear()
    yield
    mod._TOKEN_STORE.clear()
    mod._CACHE.clear()


class _Resp:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status
        self.text = json.dumps(data, ensure_ascii=False)

    def json(self) -> Any:
        return self._data


class _Client:
    """按 URL 片段回放预设响应，顺带记录被请求过的地址。"""

    def __init__(self, mapping: dict[str, Any]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _Resp:
        self.calls.append(url)
        for key, value in self.mapping.items():
            if key in url:
                return _Resp(value)
        return _Resp({"code": 0, "data": {}})


def _patch(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, Any]) -> _Client:
    client = _Client(mapping)
    monkeypatch.setattr(mod, "build_http_client", lambda *args, **kwargs: client)
    return client


AMOUNT = {
    "code": 0,
    "data": {
        "days": [
            {
                "date": "2026-11-01",
                "data": [
                    {
                        "model": "deepseek-flash",
                        "PROMPT_CACHE_HIT_TOKEN": 1000,
                        "PROMPT_CACHE_MISS_TOKEN": 200,
                        "RESPONSE_TOKEN": 300,
                        "REQUEST": 7,
                    }
                ],
            },
            {
                "date": "2026-10-31",
                "data": [
                    {
                        "model": "deepseek-flash",
                        "PROMPT_CACHE_HIT_TOKEN": 500,
                        "PROMPT_CACHE_MISS_TOKEN": 100,
                        "RESPONSE_TOKEN": 50,
                        "REQUEST": 3,
                    }
                ],
            },
        ]
    },
}
COST = {
    "code": 0,
    "data": {
        "days": [
            {"date": "2026-11-01", "data": [{"model": "deepseek-flash", "COST": 0.02}]},
            {"date": "2026-10-31", "data": [{"model": "deepseek-flash", "COST": 0.01}]},
        ]
    },
}
SUMMARY = {"code": 0, "data": {"balance_infos": []}}


# ---------- token 清洗 ----------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  abc123456789012345  ", "abc123456789012345"),
        ('"abc123456789012345"', "abc123456789012345"),
        ('{"value":"tok_from_json_123456","expire":1}', "tok_from_json_123456"),
        ('{"token":"another_token_987654"}', "another_token_987654"),
        ("", ""),
    ],
)
def test_clean_token_accepts_what_browser_copies(raw: str, expected: str) -> None:
    assert _clean_token(raw) == expected


# ---------- 解析 ----------
def test_scan_usage_reads_dates_from_outer_and_values_from_inner() -> None:
    """官方是「日期包一层、明细再包一层」，只看单个节点必然漏数据。"""
    days: dict[str, dict[str, float]] = {}
    totals = scan_usage(AMOUNT, mod._TOKEN_FIELDS, days)

    assert totals["requests"] == 10
    assert totals["tokens"] == 2150
    assert days["2026-11-01"]["tokens"] == 1500
    assert days["2026-10-31"]["tokens"] == 650


def test_scan_usage_prefers_daily_detail_over_total_to_avoid_double_count() -> None:
    payload = {
        "data": {
            "total": {"PROMPT_CACHE_HIT_TOKEN": 9999, "RESPONSE_TOKEN": 9999, "REQUEST": 99},
            "days": [
                {
                    "date": "2026-11-01",
                    "PROMPT_CACHE_HIT_TOKEN": 10,
                    "RESPONSE_TOKEN": 5,
                    "REQUEST": 1,
                }
            ],
        }
    }
    days: dict[str, dict[str, float]] = {}
    totals = scan_usage(payload, mod._TOKEN_FIELDS, days)
    assert totals["requests"] == 1  # 只认明细，不把总计再加一遍
    assert totals["tokens"] == 15


def test_scan_usage_falls_back_to_flat_totals_when_no_dates() -> None:
    payload = {"data": {"PROMPT_CACHE_HIT_TOKEN": 10, "RESPONSE_TOKEN": 3, "REQUEST": 2}}
    days: dict[str, dict[str, float]] = {}
    totals = scan_usage(payload, mod._TOKEN_FIELDS, days)
    assert totals["requests"] == 2
    assert totals["tokens"] == 13
    assert days == {}


# ---------- 端到端（假 HTTP） ----------
def test_fetch_merges_amount_and_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {"usage/amount": AMOUNT, "usage/cost": COST, "get_user_summary": SUMMARY})
    service = ProviderUsageService(Settings())
    service.set_token("deepseek", "x" * 24)

    data = asyncio.run(service.fetch("deepseek", year=2026, month=11))

    assert data["available"] is True
    assert data["requests"] == 10
    assert data["tokens"] == 2150
    assert data["cost_cny"] == pytest.approx(0.03)
    assert [day["date"] for day in data["days"]] == ["2026-10-31", "2026-11-01"]


def test_fetch_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {"usage/amount": {"code": 40003, "msg": "Authorization Failed"}})
    service = ProviderUsageService(Settings())
    service.set_token("deepseek", "y" * 24)

    with pytest.raises(ProviderUsageError) as excinfo:
        asyncio.run(service.fetch("deepseek", year=2026, month=11))
    assert excinfo.value.code == "TOKEN_EXPIRED"


def test_fetch_without_token_explains_the_credential_trap() -> None:
    """报错必须点明「API Key 不管用」，否则用户会一直拿 API Key 重试。"""
    service = ProviderUsageService(Settings())
    with pytest.raises(ProviderUsageError) as excinfo:
        asyncio.run(service.fetch("deepseek"))
    assert excinfo.value.code == "NO_TOKEN"
    assert "API Key" in excinfo.value.message


def test_fetch_reports_unparsed_instead_of_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    """结构变了就带回原始响应，别猜一个看着合理的数字。"""
    weird = {"data": {"rows": [{"something": "new"}]}}
    _patch(monkeypatch, {"usage/amount": weird, "usage/cost": weird, "get_user_summary": weird})
    service = ProviderUsageService(Settings())
    service.set_token("deepseek", "z" * 24)

    data = asyncio.run(service.fetch("deepseek", year=2026, month=11))
    assert data["available"] is True
    assert data["unparsed"] is True
    assert data["raw"]


def test_set_token_requires_plausible_length() -> None:
    service = ProviderUsageService(Settings())
    with pytest.raises(ProviderUsageError):
        service.set_token("deepseek", "short")
    with pytest.raises(ProviderUsageError):
        service.set_token("deepseek", "   ")


def test_token_is_masked_and_cleared() -> None:
    service = ProviderUsageService(Settings())
    token = "abcdefghijklmnopqrstuvwxyz"
    result = service.set_token("deepseek", token)
    assert result["has_token"] is True
    assert token not in result["token_preview"]
    assert result["token_preview"].startswith("abcd")

    service.clear_token("deepseek")
    assert service.status("deepseek")["has_token"] is False


def test_parse_balance_reads_cny_entry() -> None:
    payload = {
        "is_available": True,
        "balance_infos": [
            {"currency": "USD", "total_balance": "1.00"},
            {
                "currency": "CNY",
                "total_balance": "6.05",
                "granted_balance": "5.15",
                "topped_up_balance": "0.89",
            },
        ],
    }
    parsed = _parse_balance(payload)
    assert parsed["currency"] == "CNY"
    assert parsed["total"] == "6.05"
    assert parsed["granted"] == "5.15"
