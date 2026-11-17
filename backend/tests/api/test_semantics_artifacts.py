"""产物生命周期矩阵：过滤、下载、预览、软删、回收站、恢复、彻底删除、批量删除。"""

from __future__ import annotations

import pytest
from tests.api.matrix import MATRIX_PREFIX

ARTIFACTS = f"{MATRIX_PREFIX}/artifacts"


@pytest.fixture()
def artifact(api_client, seed) -> str:
    """从种子里借一个可删的产物（种子留给只读断言的那个不动）。"""
    picked = seed.take_artifact()
    if not picked:
        pytest.skip("种子产物已被用完")
    return picked


def test_list_artifacts_by_thread(api_client, seed):
    result = api_client.get(f"{ARTIFACTS}?thread_id={seed.ids['thread_id']}").json()
    assert result["total"] >= 1
    assert all(item["thread_id"] == seed.ids["thread_id"] for item in result["artifacts"])


def test_list_artifacts_by_run(api_client, seed):
    result = api_client.get(
        f"{ARTIFACTS}?run_id={seed.ids['run_id']}&thread_id={seed.ids['thread_id']}"
    ).json()
    assert all(item.get("run_id") in (None, seed.ids["run_id"]) for item in result["artifacts"])


@pytest.mark.parametrize("kind", ["docx", "pdf", "xlsx", "txt"])
def test_list_artifacts_type_filter(api_client, kind: str):
    result = api_client.get(f"{ARTIFACTS}?type={kind}").json()
    assert all(item["type"] == kind for item in result["artifacts"])


def test_list_artifacts_unknown_type_is_empty(api_client):
    """已下线的格式不是报错，而是「筛不到东西」——前端下拉里根本不会出现它。"""
    result = api_client.get(f"{ARTIFACTS}?type=pptx")
    assert result.status_code == 200
    assert result.json()["artifacts"] == []


@pytest.mark.parametrize(("page", "page_size"), [(1, 1), (1, 20), (2, 1), (9, 20)])
def test_list_artifacts_pagination(api_client, page: int, page_size: int):
    result = api_client.get(f"{ARTIFACTS}?page={page}&page_size={page_size}").json()
    assert result["page"] == page
    assert len(result["artifacts"]) <= page_size


def test_include_uploads_flag(api_client, seed):
    without = api_client.get(f"{ARTIFACTS}?thread_id={seed.ids['thread_id']}").json()
    with_uploads = api_client.get(
        f"{ARTIFACTS}?thread_id={seed.ids['thread_id']}&include_uploads=true"
    ).json()
    assert with_uploads["total"] >= without["total"]


def test_artifact_detail(api_client, seed):
    detail = api_client.get(f"{ARTIFACTS}/{seed.ids['artifact_id']}").json()
    assert detail["artifact_id"] == seed.ids["artifact_id"]
    assert detail["filename"]
    assert detail["size"] >= 0
    assert detail["type"] in {"docx", "pdf", "xlsx", "txt"}


def test_artifact_download_headers(api_client, seed):
    response = api_client.get(f"{ARTIFACTS}/{seed.ids['artifact_id']}/download")
    assert response.status_code == 200
    assert response.content, "下载内容为空"
    assert "attachment" in response.headers["content-disposition"]


def test_artifact_download_inline_for_preview(api_client, seed):
    response = api_client.get(f"{ARTIFACTS}/{seed.ids['artifact_id']}/download?inline=true")
    assert response.status_code == 200
    assert "inline" in response.headers["content-disposition"]


def test_artifact_preview_is_html(api_client, seed):
    response = api_client.get(f"{ARTIFACTS}/{seed.ids['artifact_id']}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<" in response.text


def test_artifact_soft_delete_hides_it(api_client, artifact: str):
    response = api_client.delete(f"{ARTIFACTS}/{artifact}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert api_client.get(f"{ARTIFACTS}/{artifact}").status_code == 404
    assert api_client.get(f"{ARTIFACTS}/{artifact}/download").status_code == 404


def test_artifact_appears_in_trash(api_client, artifact: str):
    api_client.delete(f"{ARTIFACTS}/{artifact}")
    trash = api_client.get(f"{ARTIFACTS}/trash").json()
    ids = [item["artifact_id"] for item in trash["artifacts"]]
    assert artifact in ids
    entry = next(item for item in trash["artifacts"] if item["artifact_id"] == artifact)
    assert entry["deleted_at"]
    assert entry["restorable"] is True


def test_artifact_restore(api_client, artifact: str):
    api_client.delete(f"{ARTIFACTS}/{artifact}")
    restored = api_client.post(f"{ARTIFACTS}/{artifact}/restore")
    assert restored.status_code == 200
    assert api_client.get(f"{ARTIFACTS}/{artifact}").status_code == 200


def test_restore_active_artifact_is_noop_or_conflict(api_client, artifact: str):
    response = api_client.post(f"{ARTIFACTS}/{artifact}/restore")
    assert response.status_code in (200, 409), response.text


def test_artifact_purge_removes_from_trash(api_client, artifact: str):
    api_client.delete(f"{ARTIFACTS}/{artifact}")
    purged = api_client.delete(f"{ARTIFACTS}/{artifact}/purge")
    assert purged.status_code == 200
    trash = api_client.get(f"{ARTIFACTS}/trash").json()
    assert all(item["artifact_id"] != artifact for item in trash["artifacts"])


def test_purge_unknown_artifact_is_404(api_client):
    response = api_client.delete(f"{ARTIFACTS}/art_nope/purge")
    assert response.status_code == 404


def test_delete_unknown_artifact_is_404(api_client):
    assert api_client.delete(f"{ARTIFACTS}/art_nope").status_code == 404


def test_batch_delete_partial_success(api_client, artifact: str):
    response = api_client.post(
        f"{ARTIFACTS}/batch-delete",
        json={"artifact_ids": [artifact, "art_nope"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["requested"] == 2
    assert body["deleted"] == 1
    assert any(item["artifact_id"] == "art_nope" and not item["deleted"] for item in body["failed"])


def test_batch_delete_dedupes(api_client, artifact: str):
    response = api_client.post(
        f"{ARTIFACTS}/batch-delete", json={"artifact_ids": [artifact, artifact, artifact]}
    )
    assert response.status_code == 200
    assert response.json()["requested"] == 1


def test_batch_delete_empty_list_is_noop(api_client):
    response = api_client.post(f"{ARTIFACTS}/batch-delete", json={"artifact_ids": []})
    assert response.status_code == 200
    assert response.json()["deleted"] == 0


def test_batch_delete_over_limit_is_400(api_client):
    response = api_client.post(
        f"{ARTIFACTS}/batch-delete", json={"artifact_ids": [f"art_{i}" for i in range(201)]}
    )
    assert response.status_code == 400


def test_artifact_moves_file_into_trash_dir(api_client, artifact: str, matrix_settings):
    """软删不是改个标记：文件真的挪进回收站目录，否则「彻底删除」没有意义。"""
    from pathlib import Path

    detail = api_client.get(f"{ARTIFACTS}/{artifact}").json()
    filename = detail["filename"]
    api_client.delete(f"{ARTIFACTS}/{artifact}")
    trash_root = Path(matrix_settings.trash_dir)
    assert trash_root.exists()
    matches = [item for item in trash_root.rglob("*") if item.name == filename]
    assert matches, f"回收站里找不到 {filename}"
