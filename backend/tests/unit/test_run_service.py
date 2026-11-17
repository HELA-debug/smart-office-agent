"""RunService 的零碎逻辑：这一轮要告诉模型「本会话已交付哪些文件」。

只测纯逻辑（不装配整个服务），因为它依赖的东西很少：一个能按页取产物的仓储。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.run_service import RunService


class _Repo:
    def __init__(self, rows: list[Any], *, boom: bool = False) -> None:
        self.rows = rows
        self.boom = boom
        self.calls: list[dict[str, Any]] = []

    def count(self, **_kwargs: Any) -> int:
        if self.boom:
            raise RuntimeError("db down")
        return len(self.rows)

    def list(self, **kwargs: Any) -> list[Any]:
        self.calls.append(kwargs)
        offset = int(kwargs.get("offset", 0))
        limit = int(kwargs.get("limit", 200))
        return self.rows[offset : offset + limit]


def _artifact(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        filename=f"第{index}份.txt", type="txt", created_at=f"2026-11-09T2{index % 10}:00:00+08:00"
    )


def test_delivered_files_returns_the_latest_ones() -> None:
    """会话里攒了几十份文件：只要最近几条，全塞进提示词会把它淹了。"""
    rows = [_artifact(index) for index in range(20)]
    repo = _Repo(rows)
    service = SimpleNamespace(artifacts=repo)

    delivered = RunService._delivered_files(service, "th_1", limit=5)  # type: ignore[arg-type]

    assert [item["filename"] for item in delivered] == [
        "第15份.txt",
        "第16份.txt",
        "第17份.txt",
        "第18份.txt",
        "第19份.txt",
    ]
    # 只查产物、不掺上传素材
    assert repo.calls[-1]["exclude_type"] == "upload"


def test_delivered_files_is_empty_when_storage_fails() -> None:
    """读不到历史就当没有：一份清单取不到，不该让整轮请求起不来。"""
    service = SimpleNamespace(artifacts=_Repo([], boom=True))

    assert RunService._delivered_files(service, "th_1") == []  # type: ignore[arg-type]
