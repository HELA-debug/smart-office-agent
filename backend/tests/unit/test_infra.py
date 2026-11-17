"""解析 / 模型路由 / 引擎选择的单元测试（不访问网络）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from app.infra.parsing import LocalFileParser, ParseFailure, parse_bytes
from app.infra.storage import LocalFileStorage


def test_parse_txt_and_errors():
    assert parse_bytes("本周完成 3 项。".encode("gb18030"), ".txt") == "本周完成 3 项。"
    # csv / md 能当素材读（表格与笔记都是真实素材），但都不作为产物格式
    assert "张三 | 80%" in parse_bytes("姓名,进度\n张三,80%".encode(), ".csv")
    assert parse_bytes("# 标题\n正文".encode(), ".md") == "# 标题\n正文"
    with pytest.raises(ParseFailure):
        parse_bytes(b"x", ".exe")
    with pytest.raises(ParseFailure):
        parse_bytes(b"", ".txt")
    with pytest.raises(ParseFailure):
        parse_bytes(b"not a docx", ".docx")


def test_local_storage_paths(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        upload_dir=str(tmp_path / "uploads"),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    settings.ensure_dirs()
    storage = LocalFileStorage(settings)
    stored, ext = storage.save_upload("th_1", "../危险:文件.txt", "你好".encode())
    assert ext == ".txt"
    assert stored.parent == settings.uploads_path.resolve()
    text_path = storage.save_text(stored, "你好")
    assert storage.read_text(str(text_path)) == "你好"
    artifact_path = storage.new_artifact_path("周报.docx")
    assert artifact_path.parent == settings.artifacts_path.resolve()
    assert storage.preview_path(artifact_path).name == "周报.preview.html"


def test_parser_supported_exts():
    # 支持列表与格式表同源：解析器能读的，必须就是白名单允许上传的
    from app.domain.formats import UPLOAD_EXTS

    assert LocalFileParser().supported_exts == set(UPLOAD_EXTS)
    assert {".docx", ".pdf", ".xlsx", ".pptx", ".txt", ".md", ".csv"} == set(UPLOAD_EXTS)


def test_model_router_providers_without_network(tmp_path: Path):
    settings = Settings(
        mock_mode=False,
        model_provider="deepseek",
        model_name="deepseek-chat",
        deepseek_api_key="sk-test-not-real",
        model_fallback_chain="deepseek,qwen,glm,mock",
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        upload_dir=str(tmp_path / "u"),
        artifact_dir=str(tmp_path / "a"),
    )
    from app.agents.model_router import ModelRouter

    router = ModelRouter(settings)
    providers = router.providers()
    names = [item["provider"] for item in providers]
    assert names[0] == "deepseek"
    assert all("api_key" not in item for item in providers), "不得返回明文 Key 字段"
    assert providers[0]["api_key_ref"] == "env:DEEPSEEK_API_KEY"
    assert providers[0]["configured"] is True
    assert router.active_provider == "deepseek"
    assert router.active_model == "deepseek-chat"
