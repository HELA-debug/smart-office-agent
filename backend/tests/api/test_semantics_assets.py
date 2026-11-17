"""其余资源的语义矩阵：设置、模型、模板、技能、存储、项目、反馈、用量、审计。"""

from __future__ import annotations

import uuid

import pytest
from tests.api.matrix import MATRIX_PREFIX

SETTINGS = f"{MATRIX_PREFIX}/settings"
MODELS = f"{MATRIX_PREFIX}/models"
TEMPLATES = f"{MATRIX_PREFIX}/templates"
SKILLS = f"{MATRIX_PREFIX}/skills"
STORAGE = f"{MATRIX_PREFIX}/storage"
PROJECTS = f"{MATRIX_PREFIX}/projects"


# ---------------------------------------------------------------- 设置
def test_settings_shape(api_client):
    body = api_client.get(SETTINGS).json()
    for key in ("model_provider", "model_name", "mock_mode", "approval_rules", "sources"):
        assert key in body, f"设置缺字段 {key}"
    assert isinstance(body["sources"], dict)


def test_settings_update_is_applied(api_client):
    original = api_client.get(SETTINGS).json()["max_upload_mb"]
    updated = api_client.put(SETTINGS, json={"max_upload_mb": 7})
    assert updated.status_code == 200
    assert updated.json()["max_upload_mb"] == 7
    assert updated.json()["sources"]["max_upload_mb"] == "db"
    restored = api_client.put(SETTINGS, json={"max_upload_mb": original})
    assert restored.json()["max_upload_mb"] == original


@pytest.mark.parametrize("value", [0, -3, 201, 9999])
def test_settings_max_upload_out_of_range_is_400(api_client, value: int):
    response = api_client.put(SETTINGS, json={"max_upload_mb": value})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_settings_rejects_unknown_key(api_client):
    """extra=forbid：拼错的字段必须报错，不能静默吞掉。"""
    response = api_client.put(SETTINGS, json={"not_a_setting": 1})
    assert response.status_code == 400


def test_settings_accepts_list_form_for_rules(api_client):
    original = api_client.get(SETTINGS).json()["approval_rules"]
    response = api_client.put(SETTINGS, json={"approval_rules": ["file.delete"]})
    assert response.status_code == 200
    assert list(response.json()["approval_rules"]) == ["file.delete"]
    api_client.put(SETTINGS, json={"approval_rules": original})


# ---------------------------------------------------------------- 模型
def test_models_list_has_builtin(api_client):
    models = api_client.get(MODELS).json()["models"]
    assert models
    assert any(item["builtin"] for item in models)


def test_model_fields_never_leak_key(api_client):
    for item in api_client.get(MODELS).json()["models"]:
        assert "api_key" not in item
        assert item["api_key_ref"] == "" or item["api_key_ref"].startswith("env:")


def test_model_create_and_update(api_client):
    """一个供应商一条登记：POST 同名供应商应改 model，而不是再堆一条重复配置。"""
    suffix = uuid.uuid4().hex[:6]
    before = next(
        item for item in api_client.get(MODELS).json()["models"] if item["provider"] == "openai"
    )
    created = api_client.post(
        MODELS,
        json={
            "id": before["id"],
            "provider": "openai",
            "model": f"gpt-matrix-{suffix}",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["model"] == f"gpt-matrix-{suffix}"
    assert created.json()["id"] == before["id"]

    listed = api_client.get(MODELS).json()["models"]
    same_provider = [item for item in listed if item["provider"] == "openai"]
    assert len(same_provider) == 1, "同一供应商不该出现两条登记"

    api_client.post(
        MODELS,
        json={"id": before["id"], "provider": "openai", "model": before["model"]},
    )


def test_model_rejects_plaintext_key_ref(api_client):
    response = api_client.post(
        MODELS,
        json={"provider": "deepseek", "api_key_ref": "sk-plaintext-should-fail"},
    )
    assert response.status_code == 400
    assert "env:" in response.json()["error"]["message"]


def test_model_accepts_custom_provider(api_client):
    """自定义厂家（自带地址）是支持的：只要有 base_url 就能登记。"""
    suffix = uuid.uuid4().hex[:6]
    response = api_client.post(
        MODELS,
        json={
            "provider": f"custom{suffix}",
            "base_url": "https://example.com/v1",
            "model": "custom-model",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["provider"] == f"custom{suffix}"


def test_model_probe_without_key_fails_gracefully(api_client):
    """没配 Key 时探测应返回 ok=false + 人话原因，而不是 5xx 或异常。"""
    models = api_client.get(MODELS).json()["models"]
    target = next((item for item in models if not item["configured"]), models[0])
    response = api_client.post(f"{MODELS}/{target['id']}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["reason"]


def test_model_probe_unknown_id_is_404(api_client):
    assert api_client.post(f"{MODELS}/nope/test").status_code == 404


# ---------------------------------------------------------------- 模板
def test_template_list_includes_builtin(api_client):
    templates = api_client.get(TEMPLATES).json()["templates"]
    assert any(item["builtin"] for item in templates)


def test_template_create_and_delete(api_client):
    name = f"矩阵模板{uuid.uuid4().hex[:6]}"
    created = api_client.post(
        TEMPLATES,
        json={"name": name, "sections": [{"heading": "进展", "source": "progress"}]},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    assert any(item["id"] == template_id for item in api_client.get(TEMPLATES).json()["templates"])
    deleted = api_client.delete(f"{TEMPLATES}/{template_id}")
    assert deleted.status_code in (200, 204)
    assert all(item["id"] != template_id for item in api_client.get(TEMPLATES).json()["templates"])


def test_template_requires_non_empty_sections(api_client):
    response = api_client.post(TEMPLATES, json={"name": "空模板", "sections": []})
    assert response.status_code == 400


@pytest.mark.parametrize("source", ["progress", "summary", "data", "risk", "plan"])
def test_template_accepts_known_sources(api_client, source: str):
    response = api_client.post(
        TEMPLATES,
        json={
            "name": f"模板-{source}-{uuid.uuid4().hex[:5]}",
            "sections": [{"heading": "一节", "source": source}],
        },
    )
    assert response.status_code == 201, response.text


def test_template_rejects_unknown_source(api_client):
    response = api_client.post(
        TEMPLATES,
        json={"name": "坏模板", "sections": [{"heading": "一节", "source": "nonsense"}]},
    )
    assert response.status_code == 400


def test_template_render_requires_thread_id(api_client, seed):
    response = api_client.post(f"{TEMPLATES}/{seed.ids['template_id']}/render")
    assert response.status_code == 400


def test_template_render_unknown_template_is_404(api_client, seed):
    response = api_client.post(f"{TEMPLATES}/tpl_nope/render?thread_id={seed.ids['thread_id']}")
    assert response.status_code == 404


def test_template_delete_builtin_is_forbidden(api_client):
    builtin = next(
        item for item in api_client.get(TEMPLATES).json()["templates"] if item["builtin"]
    )
    response = api_client.delete(f"{TEMPLATES}/{builtin['id']}")
    assert response.status_code in (400, 403, 409), response.text


# ---------------------------------------------------------------- 技能
def test_skill_list_has_weekly_report(api_client):
    names = [item["name"] for item in api_client.get(SKILLS).json()["skills"]]
    assert "weekly-report" in names


def test_skill_catalog_has_categories(api_client):
    body = api_client.get(f"{SKILLS}/catalog").json()
    assert body["skills"]
    assert isinstance(body["categories"], list)


def test_skill_patch_unknown_is_404(api_client):
    response = api_client.patch(f"{SKILLS}/no-such-skill", json={"enabled": False})
    assert response.status_code == 404


def test_skill_patch_requires_enabled(api_client, seed):
    response = api_client.patch(f"{SKILLS}/{seed.ids['skill_id']}", json={})
    assert response.status_code == 400


def test_skill_toggle_and_delete_roundtrip(api_client):
    """导入 → 停用 → 删除，全程在临时技能目录里跑。"""
    skill_md = (
        "---\n"
        "name: matrix-skill\n"
        "description: 矩阵测试用的技能\n"
        "triggers:\n"
        "  - 矩阵\n"
        "---\n\n"
        "# 矩阵技能\n\n把材料整理成矩阵。\n"
    ).encode()
    imported = api_client.post(
        f"{SKILLS}/import", files={"file": ("SKILL.md", skill_md, "text/markdown")}
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["name"] == "matrix-skill"

    disabled = api_client.patch(f"{SKILLS}/matrix-skill", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    deleted = api_client.delete(f"{SKILLS}/matrix-skill")
    assert deleted.status_code == 200
    names = [item["name"] for item in api_client.get(SKILLS).json()["skills"]]
    assert "matrix-skill" not in names


def test_skill_import_empty_file_is_400(api_client):
    response = api_client.post(
        f"{SKILLS}/import", files={"file": ("SKILL.md", b"", "text/markdown")}
    )
    assert response.status_code == 400


def test_skill_import_without_frontmatter_uses_filename(api_client):
    """没有 frontmatter 时不报错：拿文件名当 name，让人还能看到并改名。"""
    response = api_client.post(
        f"{SKILLS}/import",
        files={"file": ("随手记.md", b"just some text", "text/markdown")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"]
    api_client.delete(f"{SKILLS}/{response.json()['name']}")


def test_skill_draft_returns_skill_markdown(api_client):
    response = api_client.post(f"{SKILLS}/draft", json={"idea": "把会议记录整理成待办清单"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["markdown"].strip()
    assert "name:" in body["markdown"]
    assert body["source"] in {"model", "local"}
    assert body["name"]


@pytest.mark.parametrize("idea", ["", "   "], ids=["empty", "blank"])
def test_skill_draft_requires_idea(api_client, idea: str):
    response = api_client.post(f"{SKILLS}/draft", json={"idea": idea})
    assert response.status_code == 400


def test_skill_draft_rejects_too_long_idea(api_client):
    response = api_client.post(f"{SKILLS}/draft", json={"idea": "长" * 301})
    assert response.status_code == 400


# ---------------------------------------------------------------- 存储
def test_storage_paths_shape(api_client):
    body = api_client.get(f"{STORAGE}/paths").json()
    for kind in ("uploads", "artifacts"):
        assert body[kind]["path"]
        assert isinstance(body[kind]["files"], int)


def test_storage_browse_lists_subdirs(api_client, seed, matrix_settings):
    from pathlib import Path

    root = Path(matrix_settings.upload_dir).parent
    body = api_client.get(f"{STORAGE}/browse?path={root}").json()
    assert body["path"] == str(root)
    assert isinstance(body["dirs"], list)
    assert body["roots"]


def test_storage_browse_missing_path_falls_back(api_client):
    body = api_client.get(f"{STORAGE}/browse?path=/definitely/not/here/xyz").json()
    assert body["path"]
    assert body["error"] is not None or body["dirs"] is not None


def test_storage_mkdir_creates_dir(api_client, matrix_settings):
    from pathlib import Path

    base = Path(matrix_settings.upload_dir).parent
    name = f"mk-{uuid.uuid4().hex[:6]}"
    body = api_client.post(f"{STORAGE}/browse/mkdir", json={"path": str(base), "name": name}).json()
    assert body["ok"] is True, body
    assert (base / name).is_dir()


def test_storage_mkdir_duplicate_reports_error(api_client, matrix_settings):
    from pathlib import Path

    base = Path(matrix_settings.upload_dir).parent
    name = f"dup-{uuid.uuid4().hex[:6]}"
    api_client.post(f"{STORAGE}/browse/mkdir", json={"path": str(base), "name": name})
    again = api_client.post(
        f"{STORAGE}/browse/mkdir", json={"path": str(base), "name": name}
    ).json()
    assert again["ok"] is False
    assert again["error"]


@pytest.mark.parametrize(
    "name",
    ["../逃逸", "a/b", "a\\b", ".", ".."],
    ids=["dotdot", "slash", "backslash", "dot", "dotdot2"],
)
def test_storage_mkdir_rejects_path_separators(api_client, matrix_settings, name: str):
    from pathlib import Path

    base = Path(matrix_settings.upload_dir).parent
    body = api_client.post(f"{STORAGE}/browse/mkdir", json={"path": str(base), "name": name}).json()
    assert body["ok"] is False


def test_storage_reveal_rejects_unknown_kind(api_client):
    response = api_client.post(f"{STORAGE}/reveal", json={"kind": "nope"})
    assert response.status_code == 400


# ---------------------------------------------------------------- 项目
def test_project_create_list_delete(api_client, tmp_path):
    folder = tmp_path / f"proj-{uuid.uuid4().hex[:6]}"
    folder.mkdir()
    (folder / "readme.md").write_text("# hi\n", encoding="utf-8")
    created = api_client.post(PROJECTS, json={"path": str(folder)})
    assert created.status_code == 201, created.text
    project = created.json()["project"]
    assert project["path"] == str(folder.resolve())

    listed = api_client.get(PROJECTS).json()["projects"]
    assert any(item["id"] == project["id"] for item in listed)

    files = api_client.get(f"{PROJECTS}/{project['id']}/files").json()
    assert any(item["name"] == "readme.md" for item in files["files"])

    removed = api_client.delete(f"{PROJECTS}/{project['id']}")
    assert removed.status_code == 200
    assert all(item["id"] != project["id"] for item in api_client.get(PROJECTS).json()["projects"])


def test_project_duplicate_is_409(api_client, tmp_path):
    folder = tmp_path / f"proj-dup-{uuid.uuid4().hex[:6]}"
    folder.mkdir()
    api_client.post(PROJECTS, json={"path": str(folder)})
    again = api_client.post(PROJECTS, json={"path": str(folder)})
    assert again.status_code == 409


@pytest.mark.parametrize(
    "path", ["", "  ", "/definitely/not/a/dir"], ids=["empty", "blank", "missing"]
)
def test_project_rejects_bad_path(api_client, path: str):
    response = api_client.post(PROJECTS, json={"path": path})
    assert response.status_code == 400


def test_project_rename(api_client, tmp_path):
    folder = tmp_path / f"proj-rename-{uuid.uuid4().hex[:6]}"
    folder.mkdir()
    project = api_client.post(PROJECTS, json={"path": str(folder)}).json()["project"]
    renamed = api_client.patch(
        f"{PROJECTS}/{project['id']}", json={"name": "新名字", "pinned": True}
    )
    assert renamed.status_code == 200
    assert renamed.json()["project"]["name"] == "新名字"
    assert renamed.json()["project"]["pinned"] is True
    api_client.delete(f"{PROJECTS}/{project['id']}")


def test_project_files_search(api_client, tmp_path):
    folder = tmp_path / f"proj-q-{uuid.uuid4().hex[:6]}"
    folder.mkdir()
    (folder / "目标文档.txt").write_text("x", encoding="utf-8")
    (folder / "其他.txt").write_text("y", encoding="utf-8")
    project = api_client.post(PROJECTS, json={"path": str(folder)}).json()["project"]
    found = api_client.get(f"{PROJECTS}/{project['id']}/files?q=目标").json()["files"]
    assert [item["name"] for item in found] == ["目标文档.txt"]
    api_client.delete(f"{PROJECTS}/{project['id']}")


def test_project_unknown_is_404(api_client):
    assert api_client.get(f"{PROJECTS}/prj_nope/files").status_code == 404


# ---------------------------------------------------------------- 反馈 / 用量 / 审计
def test_feedback_accepts_minimal_payload(api_client):
    response = api_client.post(f"{MATRIX_PREFIX}/feedback", json={"message": "矩阵反馈"})
    assert response.status_code in (200, 201, 202), response.text


@pytest.mark.parametrize("message", ["", "   "], ids=["empty", "blank"])
def test_feedback_rejects_empty_message(api_client, message: str):
    response = api_client.post(f"{MATRIX_PREFIX}/feedback", json={"message": message})
    assert response.status_code == 400


def test_feedback_rejects_too_long_message(api_client):
    response = api_client.post(f"{MATRIX_PREFIX}/feedback", json={"message": "长" * 1501})
    assert response.status_code == 400


@pytest.mark.parametrize("range_key", ["7d", "30d", "all", "today"])
def test_usage_summary_ranges(api_client, range_key: str):
    response = api_client.get(f"{MATRIX_PREFIX}/usage/summary?range={range_key}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["range"] == range_key
    assert body["runs"] >= 0
    assert body["tokens"] >= 0


@pytest.mark.parametrize("range_key", ["90d", "nonsense", ""], ids=["90d", "word", "blank"])
def test_usage_summary_rejects_unknown_range(api_client, range_key: str):
    response = api_client.get(f"{MATRIX_PREFIX}/usage/summary?range={range_key}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_usage_summary_by_thread(api_client, seed):
    body = api_client.get(f"{MATRIX_PREFIX}/usage/summary?thread_id={seed.ids['thread_id']}").json()
    assert body["runs"] >= 1


def test_audit_export_json(api_client, seed):
    response = api_client.get(
        f"{MATRIX_PREFIX}/audit/export?format=json&thread_id={seed.ids['thread_id']}"
    )
    assert response.status_code == 200
    assert response.json() is not None


def test_audit_export_csv(api_client):
    response = api_client.get(f"{MATRIX_PREFIX}/audit/export?format=csv")
    assert response.status_code == 200
    assert response.text.startswith("\ufeff") or "," in response.text


def test_audit_export_rejects_unknown_format(api_client):
    response = api_client.get(f"{MATRIX_PREFIX}/audit/export?format=xml")
    assert response.status_code in (200, 400)


def test_thread_audit_lists_runs(api_client, seed):
    body = api_client.get(f"{MATRIX_PREFIX}/threads/{seed.ids['thread_id']}/audit").json()
    assert body["thread_id"] == seed.ids["thread_id"]
    assert body["runs"], "审计里应该能看到这个会话跑过什么"
    assert body["runs"][0]["run_id"]


# ---------------------------------------------------------------- 工具 / 子代理 / 提示词包
def test_tools_catalog(api_client):
    body = api_client.get(f"{MATRIX_PREFIX}/tools").json()
    names = [item["name"] for item in body["tools"]]
    assert "doc.generate_report" in names
    for item in body["tools"]:
        assert item["risk"] in {"low", "medium", "high"}


def test_subagents_catalog(api_client):
    body = api_client.get(f"{MATRIX_PREFIX}/subagents").json()
    assert body["subagents"]
    for item in body["subagents"]:
        assert item["name"] and item["description"]


def test_prompt_packs_catalog(api_client):
    body = api_client.get(f"{MATRIX_PREFIX}/prompt-packs").json()
    assert body["packs"]
    assert body["max_per_run"] == 2
