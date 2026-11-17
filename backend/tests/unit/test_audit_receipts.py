"""审计回执字段：让人能拿本地记录去官方控制台对账。

两个字段是关键：
- `request_ids`：供应商返回的请求 id，控制台里能查到的那次调用就是它；
- `provider_model`：供应商回执里的真实模型名，可能和配置名不同
  （deepseek-chat 会被官方路由到 deepseek-flash，账单按后者归类）。

少了这两个字段，用户只能看到「已完成」，既不知道花了钱没有，
也会因为名字对不上误判成「根本没调用」。
"""

from __future__ import annotations

from app.services.run_service import _provider_model, _request_ids


def _extra(model: str | None, ids: list[str]) -> dict:
    calls_detail = [
        {"provider": "deepseek", "model": model, "request_id": rid, "verified": True} for rid in ids
    ]
    return {
        "usage": {
            "by_provider": [{"provider": "deepseek", "model": model}],
            "calls_detail": calls_detail,
        }
    }


def test_provider_model_comes_from_the_receipt() -> None:
    assert _provider_model(_extra("deepseek-flash", ["ab-1"])) == "deepseek-flash"


def test_provider_model_is_none_without_receipt() -> None:
    """拿不到回执就不能编一个模型名出来 —— 那等于伪造凭据。"""
    assert _provider_model({}) is None
    assert _provider_model({"usage": {"calls_detail": []}}) is None


def test_request_ids_keep_only_recent_ones() -> None:
    extra = _extra("deepseek-flash", ["a", "b", "c", "d"])
    assert _request_ids(extra) == ["b", "c", "d"]


def test_request_ids_drop_blank_receipts() -> None:
    extra = {"usage": {"calls_detail": [{"request_id": ""}, {"request_id": None}, {}]}}
    assert _request_ids(extra) == []
