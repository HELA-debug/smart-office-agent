"""产物回收站：删除→列出→恢复→彻底删除，以及存储目录可修改。"""

from __future__ import annotations

from pathlib import Path

import httpx


def _make_thread(client: httpx.Client, title: str) -> str:
    response = client.post("/api/v1/threads", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["thread_id"]


def _upload(client: httpx.Client, thread_id: str, filename: str, text: str = "回收站测试") -> str:
    response = client.post(
        f"/api/v1/threads/{thread_id}/files",
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["artifact_id"]


def test_uploads_stay_out_of_the_artifact_center(client: httpx.Client):
    """上传素材不是产物：默认查不到，显式要（或按 type=upload 筛）才出现。

    文件名常常一模一样（上传 cet4成绩.pdf → 生成 cet4成绩.pdf），混在产物里用户分不清。
    """
    thread_id = _make_thread(client, "产物中心-不要素材")
    artifact_id = _upload(client, thread_id, "素材不要冒充产物.txt")

    listed = client.get(f"/api/v1/artifacts?thread_id={thread_id}").json()
    assert listed["total"] == 0
    assert [item["artifact_id"] for item in listed["artifacts"]] == []

    # 明着要：素材本身还能查到（工作台的素材列表走的就是这条）
    with_uploads = client.get(
        f"/api/v1/artifacts?thread_id={thread_id}&include_uploads=true"
    ).json()
    assert with_uploads["total"] == 1
    assert with_uploads["artifacts"][0]["artifact_id"] == artifact_id

    # 按类型筛也照旧生效
    by_type = client.get(f"/api/v1/artifacts?thread_id={thread_id}&type=upload").json()
    assert by_type["total"] == 1

    # 回收站同理：默认是「产物」的回收站
    client.delete(f"/api/v1/artifacts/{artifact_id}")
    assert client.get("/api/v1/artifacts/trash").json()["total"] == 0
    assert client.get("/api/v1/artifacts/trash?include_uploads=true").json()["total"] >= 1


def test_deleted_artifact_appears_in_trash(client: httpx.Client):
    thread_id = _make_thread(client, "回收站-列表")
    artifact_id = _upload(client, thread_id, "回收站A.txt")

    assert client.delete(f"/api/v1/artifacts/{artifact_id}").status_code == 200

    body = client.get("/api/v1/artifacts/trash?include_uploads=true").json()
    assert body["total"] >= 1
    entry = next(item for item in body["artifacts"] if item["artifact_id"] == artifact_id)
    assert entry["deleted_at"]
    assert entry["restorable"] is True
    assert entry["filename"] == "回收站A.txt"


def test_restore_brings_file_back(client: httpx.Client):
    thread_id = _make_thread(client, "回收站-恢复")
    artifact_id = _upload(client, thread_id, "回收站B.txt", "恢复后还能下载")

    client.delete(f"/api/v1/artifacts/{artifact_id}")
    response = client.post(f"/api/v1/artifacts/{artifact_id}/restore")
    assert response.status_code == 200, response.text
    assert response.json()["restored"] is True

    # 记录回来了：元数据 / 下载都可用，且不再出现在回收站
    meta = client.get(f"/api/v1/artifacts/{artifact_id}")
    assert meta.status_code == 200
    download = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert download.status_code == 200
    assert "恢复后还能下载" in download.text

    trash_ids = {
        item["artifact_id"]
        for item in client.get("/api/v1/artifacts/trash?include_uploads=true").json()["artifacts"]
    }
    assert artifact_id not in trash_ids


def test_purge_removes_record_and_file(client: httpx.Client):
    thread_id = _make_thread(client, "回收站-彻底删除")
    artifact_id = _upload(client, thread_id, "回收站C.txt")

    client.delete(f"/api/v1/artifacts/{artifact_id}")
    response = client.delete(f"/api/v1/artifacts/{artifact_id}/purge")
    assert response.status_code == 200, response.text
    assert response.json()["purged"] is True

    trash_ids = {
        item["artifact_id"]
        for item in client.get("/api/v1/artifacts/trash?include_uploads=true").json()["artifacts"]
    }
    assert artifact_id not in trash_ids
    # 记录已删：连回收站口径也查不到
    assert client.get(f"/api/v1/artifacts/{artifact_id}").status_code == 404


def test_storage_path_can_be_changed_and_reset(client: httpx.Client, tmp_path: Path):
    target = tmp_path / "custom-artifacts"
    response = client.put("/api/v1/storage/paths", json={"kind": "artifacts", "path": str(target)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["path"] == str(target)
    assert target.exists()

    paths = client.get("/api/v1/storage/paths").json()
    assert paths["artifacts"]["path"] == str(target)

    # 传空 = 恢复默认目录
    reset = client.put("/api/v1/storage/paths", json={"kind": "artifacts", "path": None})
    assert reset.status_code == 200
    assert reset.json()["ok"] is True
    assert reset.json()["path"] != str(target)


def test_open_uses_system_default_app(client: httpx.Client, monkeypatch):
    """「用 WPS 打开」走系统文件关联：这里只验证路由把真实路径交给了打开函数。"""
    from app.services import artifact_service as service_module

    thread_id = _make_thread(client, "系统打开")
    artifact_id = _upload(client, thread_id, "用系统打开.txt")

    opened_paths: list[str] = []

    def fake_open(path):  # 测试替身：只记录路径
        opened_paths.append(str(path))
        return True, None

    monkeypatch.setattr(service_module, "_open_with_system", fake_open)
    response = client.post(f"/api/v1/artifacts/{artifact_id}/open")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["opened"] is True
    assert opened_paths and opened_paths[0].endswith(".txt")
