"""存储目录接口（GET /storage/paths、POST /storage/reveal）。

目的：设置页要能真的「访问」存储路径，而不是只显示一行 `./data/uploads` 字符串。
这里锁住三件事：
1. 返回的是服务端解析后的绝对路径；
2. 只会打开 uploads / artifacts 两个固定目录，随便传别的 kind 直接 422；
3. 唤起文件管理器失败时不抛 500，而是 opened=false + 原因。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.api.v1 import storage as storage_module


def test_paths_return_absolute_dirs(client: httpx.Client) -> None:
    response = client.get("/api/v1/storage/paths")
    assert response.status_code == 200, response.text
    body = response.json()

    for kind in ("uploads", "artifacts"):
        path = Path(body[kind]["path"])
        assert path.is_absolute()
        assert path.name in {"uploads", "artifacts"}
        assert body[kind]["exists"] is True
        assert isinstance(body[kind]["files"], int)


def test_reveal_opens_configured_dir(client: httpx.Client, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        storage_module,
        "_open_in_file_manager",
        lambda path: opened.append(str(path)) or (True, None),
    )

    response = client.post("/api/v1/storage/reveal", json={"kind": "uploads"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["opened"] is True
    assert body["kind"] == "uploads"
    assert opened == [body["path"]]


def test_reveal_reports_failure_without_500(
    client: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        storage_module, "_open_in_file_manager", lambda _path: (False, "没有文件管理器")
    )
    response = client.post("/api/v1/storage/reveal", json={"kind": "artifacts"})
    assert response.status_code == 200
    assert response.json()["opened"] is False
    assert response.json()["error"] == "没有文件管理器"


def test_reveal_rejects_unknown_kind(client: httpx.Client) -> None:
    response = client.post("/api/v1/storage/reveal", json={"kind": "../../etc"})
    assert response.status_code in {400, 422}  # 校验失败：不允许任意路径


def test_browse_lists_subdirs_only(client: httpx.Client, tmp_path: Path) -> None:
    (tmp_path / "报告").mkdir()
    (tmp_path / "素材").mkdir()
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    response = client.get("/api/v1/storage/browse", params={"path": str(tmp_path)})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["path"] == str(tmp_path)
    names = [item["name"] for item in body["dirs"]]
    assert names == ["报告", "素材"]  # 只列目录，文件不出现
    assert body["error"] is None
    assert body["roots"]  # 起点列表不为空，界面上要能跳盘符/主目录


def test_browse_missing_path_falls_back_to_existing_parent(
    client: httpx.Client, tmp_path: Path
) -> None:
    """目录被删掉之后点进来，别报错，退到还在的上级目录。"""
    gone = tmp_path / "已经不在了" / "子目录"
    response = client.get("/api/v1/storage/browse", params={"path": str(gone)})
    assert response.status_code == 200
    assert response.json()["path"] == str(tmp_path)


def test_browse_without_path_starts_at_home(client: httpx.Client) -> None:
    response = client.get("/api/v1/storage/browse")
    assert response.status_code == 200
    assert Path(response.json()["path"]) == Path.home()


def test_mkdir_creates_folder(client: httpx.Client, tmp_path: Path) -> None:
    response = client.post(
        "/api/v1/storage/browse/mkdir", json={"path": str(tmp_path), "name": "Agent 产物"}
    )
    body = response.json()
    assert body["ok"] is True
    assert (tmp_path / "Agent 产物").is_dir()


def test_mkdir_rejects_separators_and_duplicates(client: httpx.Client, tmp_path: Path) -> None:
    bad = client.post(
        "/api/v1/storage/browse/mkdir", json={"path": str(tmp_path), "name": "../逃逸"}
    )
    assert bad.json()["ok"] is False

    (tmp_path / "重名").mkdir()
    dup = client.post("/api/v1/storage/browse/mkdir", json={"path": str(tmp_path), "name": "重名"})
    assert dup.json()["ok"] is False
    assert "同名" in dup.json()["error"]
