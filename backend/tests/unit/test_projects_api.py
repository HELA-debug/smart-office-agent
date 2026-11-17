"""项目接口（/projects）：登记本地文档文件夹、浏览文件、随运行带入素材。

锁住四件事：
1. 只接受存在的文件夹，重复添加给 409，不存在的路径给 400（不是 500）；
2. 文件列表只列文档类扩展名，按修改时间倒序，带相对路径与大小；
3. 移除项目只取消登记，不删用户文件；
4. 带 project_id 发起运行时，项目文档会真实进入会话素材（file_read 才能读到）。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.api.v1 import projects as projects_module


def _make_project_dir(root: Path) -> Path:
    folder = root / "我的合同"
    (folder / "2026").mkdir(parents=True)
    (folder / "合同A.txt").write_text("合同 A\n甲方：甲公司\n", encoding="utf-8")
    (folder / "2026" / "补充协议.txt").write_text("补充条款", encoding="utf-8")
    # 非文档文件不该出现在项目文件列表里
    (folder / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return folder


def _add(client: httpx.Client, path: Path, name: str | None = None) -> dict:
    response = client.post("/api/v1/projects", json={"path": str(path), "name": name})
    assert response.status_code == 201, response.text
    return response.json()["project"]


def test_add_lists_and_removes_project(client: httpx.Client, tmp_path: Path) -> None:
    folder = _make_project_dir(tmp_path)
    project = _add(client, folder)
    try:
        assert project["name"] == "我的合同"
        assert project["missing"] is False
        assert project["file_count"] == 2

        listed = client.get("/api/v1/projects").json()["projects"]
        assert any(item["id"] == project["id"] for item in listed)
    finally:
        removed = client.delete(f"/api/v1/projects/{project['id']}")
        assert removed.json()["removed"] is True

    # 只取消登记，用户目录与文件必须还在
    assert (folder / "合同A.txt").is_file()
    remaining = client.get("/api/v1/projects").json()["projects"]
    assert all(item["id"] != project["id"] for item in remaining)


def test_add_rejects_missing_path_and_files(client: httpx.Client, tmp_path: Path) -> None:
    missing = client.post("/api/v1/projects", json={"path": str(tmp_path / "不存在")})
    assert missing.status_code == 400
    assert "打不开" in missing.json()["error"]["message"]

    single = tmp_path / "单个文件.txt"
    single.write_text("x", encoding="utf-8")
    response = client.post("/api/v1/projects", json={"path": str(single)})
    assert response.status_code == 400
    assert "文件夹" in response.json()["error"]["message"]


def test_duplicate_project_conflicts(client: httpx.Client, tmp_path: Path) -> None:
    folder = _make_project_dir(tmp_path)
    project = _add(client, folder)
    try:
        again = client.post("/api/v1/projects", json={"path": str(folder).upper()})
        assert again.status_code == 409
    finally:
        client.delete(f"/api/v1/projects/{project['id']}")


def test_project_files_are_documents_only(client: httpx.Client, tmp_path: Path) -> None:
    folder = _make_project_dir(tmp_path)
    project = _add(client, folder)
    try:
        body = client.get(f"/api/v1/projects/{project['id']}/files").json()
        names = [item["name"] for item in body["files"]]
        assert "合同A.txt" in names
        assert "补充协议.txt" in names
        assert "logo.png" not in names
        item = next(item for item in body["files"] if item["name"] == "合同A.txt")
        assert item["rel_path"] == "合同A.txt"
        assert item["ext"] == "txt"
        assert item["path"].endswith("合同A.txt")
        assert body["project"]["id"] == project["id"]
    finally:
        client.delete(f"/api/v1/projects/{project['id']}")


def test_project_patch_rename_and_pin(client: httpx.Client, tmp_path: Path) -> None:
    folder = _make_project_dir(tmp_path)
    project = _add(client, folder)
    try:
        patched = client.patch(
            f"/api/v1/projects/{project['id']}", json={"name": "重点合同", "pinned": True}
        )
        assert patched.status_code == 200
        assert patched.json()["project"]["name"] == "重点合同"
        assert patched.json()["project"]["pinned"] is True

        empty = client.patch(f"/api/v1/projects/{project['id']}", json={"name": "   "})
        assert empty.status_code == 400
    finally:
        client.delete(f"/api/v1/projects/{project['id']}")


def test_project_reveal_opens_folder(
    client: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _make_project_dir(tmp_path)
    project = _add(client, folder)
    opened: list[str] = []
    monkeypatch.setattr(
        projects_module,
        "_open_in_file_manager",
        lambda path: opened.append(str(path)) or (True, None),
    )
    try:
        body = client.post(f"/api/v1/projects/{project['id']}/reveal").json()
        assert body["opened"] is True
        assert opened and opened[0].endswith("我的合同")
    finally:
        client.delete(f"/api/v1/projects/{project['id']}")


def test_project_file_goes_into_run_materials(client: httpx.Client, tmp_path: Path) -> None:
    """带 project_id 运行时，项目里的文档要被搬进会话素材（否则 file_read 读不到）。"""
    folder = _make_project_dir(tmp_path)
    project = _add(client, folder)
    thread_id = client.post("/api/v1/threads", json={}).json()["thread_id"]
    try:
        with client.stream(
            "POST",
            f"/api/v1/threads/{thread_id}/runs/stream",
            json={"message": "看一下项目里的合同", "mode": "mock", "project_id": project["id"]},
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("event: run.started"):
                    break

        files = client.get(f"/api/v1/threads/{thread_id}/files").json()["files"]
        names = {item["filename"] for item in files}
        assert {"合同A.txt", "补充协议.txt"} <= names
    finally:
        client.delete(f"/api/v1/projects/{project['id']}")


def test_run_rejects_unknown_project(client: httpx.Client) -> None:
    thread_id = client.post("/api/v1/threads", json={}).json()["thread_id"]
    response = client.post(
        f"/api/v1/threads/{thread_id}/runs/stream",
        json={"message": "hi", "mode": "mock", "project_id": "prj_nope"},
    )
    assert response.status_code == 404
    assert "项目不存在" in response.json()["error"]["message"]


def test_project_scan_skips_hidden_dirs(client: httpx.Client, tmp_path: Path) -> None:
    folder = tmp_path / "资料库"
    (folder / ".git").mkdir(parents=True)
    (folder / ".git" / "config.txt").write_text("secret", encoding="utf-8")
    (folder / "说明.txt").write_text("说明", encoding="utf-8")
    project = _add(client, folder)
    try:
        names = [
            item["name"]
            for item in client.get(f"/api/v1/projects/{project['id']}/files").json()["files"]
        ]
        assert names == ["说明.txt"]
    finally:
        client.delete(f"/api/v1/projects/{project['id']}")
