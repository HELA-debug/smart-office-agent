"""模型计价：把官方价目表换算成「能拿去对账」的钱。

之前这里是一张拍脑袋的表（输入 ¥2 / 输出 ¥8 一刀切），后来又改成「¥0.05 一刀切」——
两次都是错的，而且错得方向相反：

* DeepSeek 的官方价是**分时 + 缓存分级**的（元 / 百万 tokens，V4.1-Flash）：
  闲时 输入缓存命中 0.02、缓存未命中 1.0、输出 4.0；高峰（工作日 09–12、14–18）翻倍。
* 控制台上「119M tokens 只花了 ¥5.86」看着像 ¥0.05/百万，是因为那 1.19 亿里
  绝大多数是**缓存命中**的输入（¥0.02–0.04/百万）；而本应用每轮都是新的上下文，
  基本都是「缓存未命中」，单价差 50 倍。拿两个平均单价互相解释，越解释越离谱。

所以这里只做一件事：按 run 发生的时间、按 usage 里的缓存命中/未命中拆分，
算出与官方同一口径的金额。口径写在 yaml 里，改价不用改代码。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .utils import TZ, now_dt

PRICE_TABLE_PATH = Path(__file__).resolve().parents[2] / "config" / "model_prices.yaml"

# 拿不到价目表时的兜底：按**高峰、全未命中**估，宁可高估也不低报（低报会让人以为免费）
_FALLBACK_HIT = 0.04
_FALLBACK_MISS = 2.0
_FALLBACK_OUTPUT = 8.0

# 官方高峰时段（北京时间，工作日）：09:00-12:00、14:00-18:00，其余为闲时
_DEFAULT_PEAK_DAYS = (0, 1, 2, 3, 4)
_DEFAULT_PEAK_RANGES = (("09:00", "12:00"), ("14:00", "18:00"))


@dataclass(frozen=True)
class PriceSet:
    """一组单价，单位：元 / 百万 tokens。"""

    cache_hit: float
    cache_miss: float
    output: float
    peak: bool = False
    # 命中价的来源：true 表示价目表里显式给了缓存命中价，false 表示用未命中价兜底
    hit_known: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_cache_hit": self.cache_hit,
            "input_cache_miss": self.cache_miss,
            "output": self.output,
            "peak": self.peak,
        }


_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def load_price_table(path: Path | None = None) -> dict[str, Any]:
    """读取价目表（按文件 mtime 缓存）。

    按 mtime 缓存是有意的：以前价格表在进程启动时读一次，改完 yaml 不重启就还是旧价，
    界面上显示的钱跟文件里写的完全对不上，排查起来像灵异事件。
    """
    target = path or PRICE_TABLE_PATH
    key = str(target)
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return {}
    cached = _CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    table = data if isinstance(data, dict) else {}
    _CACHE[key] = (mtime, table)
    return table


def _minutes(value: Any) -> int | None:
    try:
        hour, minute = str(value).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None


def _peak_windows(table: dict[str, Any]) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    section = table.get("peak")
    if not isinstance(section, dict):
        return _DEFAULT_PEAK_DAYS, tuple(
            (_minutes(start) or 0, _minutes(end) or 0) for start, end in _DEFAULT_PEAK_RANGES
        )
    days_raw = section.get("weekdays")
    days = (
        tuple(int(day) for day in days_raw if isinstance(day, int))
        if isinstance(days_raw, list)
        else _DEFAULT_PEAK_DAYS
    )
    ranges_raw = section.get("ranges")
    ranges: list[tuple[int, int]] = []
    if isinstance(ranges_raw, list):
        for item in ranges_raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                start, end = _minutes(item[0]), _minutes(item[1])
                if start is not None and end is not None and end > start:
                    ranges.append((start, end))
    return days or _DEFAULT_PEAK_DAYS, tuple(ranges) or tuple(
        (_minutes(start) or 0, _minutes(end) or 0) for start, end in _DEFAULT_PEAK_RANGES
    )


def is_peak(at: datetime | None, table: dict[str, Any] | None = None) -> bool:
    """当前是不是官方的高峰时段（北京时间）。"""
    moment = (at or now_dt()).astimezone(TZ)
    days, ranges = _peak_windows(table or {})
    if moment.weekday() not in days:
        return False
    minute = moment.hour * 60 + moment.minute
    return any(start <= minute < end for start, end in ranges)


def _pair(entry: Any) -> tuple[float, float, float, bool] | None:
    """从一段配置里取 (命中, 未命中, 输出, 命中价是否显式给出)；兼容旧的 input/output 写法。"""
    if not isinstance(entry, dict):
        return None
    try:
        miss = float(entry.get("input_cache_miss", entry.get("input")))
        output = float(entry.get("output"))
    except (TypeError, ValueError):
        return None
    raw_hit = entry.get("input_cache_hit")
    hit_known = raw_hit is not None
    try:
        hit = float(raw_hit) if hit_known else 0.0
    except (TypeError, ValueError):
        hit, hit_known = 0.0, False
    return hit, miss, output, hit_known


def price_for(
    provider: str,
    model: str,
    *,
    at: datetime | None = None,
    table: dict[str, Any] | None = None,
) -> PriceSet:
    """查某供应商某模型在 at 时刻的单价（自动判断高峰/闲时与缓存档位）。"""
    book = table if isinstance(table, dict) else load_price_table()
    peak = is_peak(at, book)
    providers = book.get("providers") if isinstance(book.get("providers"), dict) else {}
    entry = providers.get(provider) if isinstance(providers, dict) else None
    picked: tuple[float, float, float, bool] | None = None
    if isinstance(entry, dict):
        models = entry.get("models")
        if isinstance(models, dict):
            picked = _pair(models.get(model))
        if picked is None:
            picked = _pair(entry.get("default"))
    multiplier = 1.0
    if isinstance(entry, dict):
        try:
            multiplier = float(entry.get("peak_multiplier", 1.0)) if peak else 1.0
        except (TypeError, ValueError):
            multiplier = 1.0
    if picked is None:
        picked = _pair(book.get("default")) or (
            _FALLBACK_HIT,
            _FALLBACK_MISS,
            _FALLBACK_OUTPUT,
            True,
        )
    hit, miss, output, hit_known = picked
    if multiplier != 1.0:
        miss = round(miss * multiplier, 6)
        output = round(output * multiplier, 6)
        hit = round(hit * multiplier, 6)
    if not hit_known and hit == 0.0:
        # 没有命中价时用未命中价的一半兜底（官方闲时恰是高峰的一半，不会低报太多）
        hit = round(miss / 2, 6)
    return PriceSet(cache_hit=hit, cache_miss=miss, output=output, peak=peak, hit_known=hit_known)


def cost_for(
    provider: str,
    model: str,
    *,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    output_tokens: int = 0,
    at: datetime | None = None,
    table: dict[str, Any] | None = None,
) -> float:
    """按官方口径算一次调用的钱（元）。"""
    price = price_for(provider, model, at=at, table=table)
    amount = (
        max(0, cache_hit_tokens) / 1_000_000 * price.cache_hit
        + max(0, cache_miss_tokens) / 1_000_000 * price.cache_miss
        + max(0, output_tokens) / 1_000_000 * price.output
    )
    return round(amount, 6)


def parse_iso(value: str | None) -> datetime | None:
    """把 run.started_at 这类 ISO 字符串解析成带时区的时间；失败返回 None。"""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(TZ) if moment.tzinfo else moment.replace(tzinfo=TZ)


__all__ = [
    "PRICE_TABLE_PATH",
    "PriceSet",
    "cost_for",
    "is_peak",
    "load_price_table",
    "parse_iso",
    "price_for",
]
