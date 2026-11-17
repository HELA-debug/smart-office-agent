"""格式矩阵：产物 / 上传 / 沙箱三处口径必须同源。

这些断言的价值不在覆盖率，而在**挡住口径漂移**。以前「产物支持 md」
「上传不收 csv」「沙箱里有四个工具库」三句话各写在各处，模型照着描述承诺，
实现里那行走不到——用户拿到的是一份被悄悄降级成 docx 的产物，或者一句
「不支持的文件类型」，谁也说不清是谁的错。

所以这里锁三件事：

1. 表本身自洽（每一行都答得出「能不能传、能不能产、用哪个库」）；
2. 由表派生出来的清单（白名单、产物键、工具库）确实是从表算的，不是手抄；
3. pptx 这条新链路端到端通：生成 → 上传校验 → 解析 → 登记产物。
"""

from __future__ import annotations

import importlib
import io
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.agents.policy import decide_write
from app.agents.reading import COMMIT_AUTHORIZED, STANCE_DIRECT, TurnReading
from app.core.config import Settings
from app.core.security import validate_upload
from app.domain.entities import Artifact
from app.domain.enums import ArtifactType
from app.domain.formats import (
    FORMAT_DISPLAY,
    FORMAT_LABELS,
    FORMATS,
    OOXML_ROOTS,
    OUTPUT_FORMAT_KEYS,
    UPLOAD_EXTS,
    UTIL_MODULES,
    spec_of,
    util_index,
)
from app.infra.parsing import parse_bytes
from app.infra.storage import LocalFileStorage
from app.services import pptx_utils
from app.tools.builtin.doc import generate_report
from app.tools.spec import ToolContext

# ---------------------------------------------------------------- 表本身


def test_every_row_answers_four_questions():
    """一行不完整，下游就会有一处靠猜。"""
    for spec in FORMATS:
        assert spec.key and spec.key.islower(), spec.key
        assert spec.ext == f".{spec.key}"
        assert spec.mime == spec.content_type.split(";")[0].strip()
        assert spec.artifact_type in {item.value for item in ArtifactType}, spec.key
        assert spec.display, f"{spec.key} 缺中文名（前端要逐字对应）"
        assert spec.utils is None or spec.utils.endswith("_utils")
    # 每个工具库在清单里都要有一行「先用哪些函数」，否则提示词里只剩个光秃秃的名字
    assert {spec.utils for spec in FORMATS if spec.utils} == set(UTIL_MODULES)


def test_output_and_upload_sets_are_derived_not_handwritten():
    assert tuple(s.key for s in FORMATS if s.can_output) == OUTPUT_FORMAT_KEYS
    assert {s.ext for s in FORMATS if s.can_upload} == UPLOAD_EXTS
    # 产物菜单里有 pptx；md / csv 只能当素材
    assert "pptx" in OUTPUT_FORMAT_KEYS
    assert {"md", "csv"}.isdisjoint(OUTPUT_FORMAT_KEYS)
    assert {".md", ".csv"} <= UPLOAD_EXTS


def test_every_uploadable_format_can_actually_be_parsed():
    """白名单允许上传的，解析器必须认得；否则用户上传成功、读的时候才报错。"""
    for ext in UPLOAD_EXTS:
        spec = spec_of(ext.lstrip("."))
        assert spec is not None
        assert ext in OOXML_ROOTS or spec.mime.startswith("text/") or ext == ".pdf"


def test_pptx_is_a_real_artifact_type():
    spec = spec_of("pptx")
    assert spec is not None
    assert spec.artifact_type == ArtifactType.PPTX.value
    assert spec.ooxml_root == "ppt/"


# ---------------------------------------------------------------- 沙箱工具库


def test_util_modules_cover_every_format_without_duplicates():
    assert len(UTIL_MODULES) == len(set(UTIL_MODULES))
    assert "pptx_utils" in UTIL_MODULES
    base = Path(__file__).resolve().parents[2] / "app" / "services"
    for module in UTIL_MODULES:
        assert (base / f"{module}.py").is_file(), f"{module}.py 不存在，脚本里会 ImportError"


def test_util_index_only_names_functions_that_exist():
    """提示词是模型唯一的 API 文档：写一个不存在的函数，它就会照着调用。"""
    modules = {spec.utils: spec for spec in FORMATS if spec.utils}
    for module_name, body in re.findall(r"(\w+_utils)（([^）]*)）", util_index()):
        module = modules[module_name].utils
        exports = set(importlib.import_module(f"app.services.{module}").__all__)
        for part in body.split("/"):
            name = part.strip().split("(")[0].strip()
            assert name in exports, f"{module_name} 里没有 {name}"


def test_util_modules_carry_a_hint_block():
    from app.domain.formats import util_bullets

    bullets = util_bullets()
    assert len(bullets) == len(UTIL_MODULES)
    assert all(line.startswith("- ") for line in bullets)


# ---------------------------------------------------------------- 展示名


def test_display_names_are_shared_with_the_frontend():
    """前端 `OUTPUT_FORMAT_COMPACT` / `OUTPUT_FORMAT_LABELS` 与这里逐字对应。"""
    assert set(FORMAT_LABELS) == set(OUTPUT_FORMAT_KEYS)
    assert set(OUTPUT_FORMAT_KEYS) <= set(FORMAT_DISPLAY)
    for key in OUTPUT_FORMAT_KEYS:
        assert FORMAT_LABELS[key] == f"{FORMAT_DISPLAY[key]}（{key}）"
    assert FORMAT_LABELS["pptx"] == "PPT 演示文稿（pptx）"


# ---------------------------------------------------------------- pptx 链路


def _deck_bytes(tmp_path: Path) -> bytes:
    pages = [
        {"title": "四季度复盘", "subtitle": "数据组"},
        {"title": "关键结论", "bullets": ["退款率降到 1.2%", "客单价环比 +8%"]},
    ]
    path = tmp_path / "复盘.pptx"
    pptx_utils.write_deck(path, pages, title="四季度复盘")
    return path.read_bytes()


def test_pptx_passes_upload_validation(tmp_path: Path):
    data = _deck_bytes(tmp_path)
    validate_upload(
        "复盘.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        data,
    )
    # 浏览器偶尔把 OOXML 报成 zip，也要放行
    validate_upload("复盘.pptx", "application/zip", data)
    with pytest.raises(ValueError):
        # 改后缀骗白名单：内容是 docx，缺 ppt/ 目录
        docx_bytes = io.BytesIO()
        with zipfile.ZipFile(docx_bytes, "w") as archive:
            archive.writestr("word/document.xml", "<w/>")
        validate_upload("复盘.pptx", "application/zip", docx_bytes.getvalue())


def test_pptx_parses_into_page_text(tmp_path: Path):
    text = parse_bytes(_deck_bytes(tmp_path), ".pptx")
    assert text.startswith("【共 2 页】")
    assert "【第 1 页】四季度复盘" in text
    assert "退款率降到 1.2%" in text


def test_pptx_read_report_accepts_bytes(tmp_path: Path):
    """上传解析手上是字节，不该为了读一份文件先落盘。"""
    report = pptx_utils.read_report(_deck_bytes(tmp_path))
    assert report["ok"] is True
    assert report["pages"] == 2
    assert report["titles"] == ["四季度复盘", "关键结论"]


class _ArtifactRepo:
    def __init__(self) -> None:
        self.items: list[Artifact] = []

    def add(self, artifact: Artifact) -> Artifact:
        self.items.append(artifact)
        return artifact


def _doc_context(tmp_path: Path) -> ToolContext:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        artifact_dir=str(tmp_path / "artifacts"),
        upload_dir=str(tmp_path / "uploads"),
    )
    settings.ensure_dirs()
    return ToolContext(
        thread_id="th_1",
        run_id="run_1",
        trace_id="tr_1",
        settings=settings,
        artifacts=_ArtifactRepo(),  # type: ignore[arg-type]
        storage=LocalFileStorage(settings),
        material_text="本周进展\n退款率降到 1.2%。\n下周计划\n补上复购口径。",
        material_sources=[{"filename": "周报.docx", "text": "退款率降到 1.2%。"}],
    )


def test_generate_report_can_output_pptx(tmp_path: Path):
    ctx = _doc_context(tmp_path)
    result = generate_report(ctx, template="summary", format="pptx")
    assert result["format"] == "pptx"
    artifact = ctx.artifacts.items[0]  # type: ignore[attr-defined]
    assert artifact.type == ArtifactType.PPTX.value
    assert artifact.content_type.endswith("presentationml.presentation")
    # 封面 + 至少一节
    report = pptx_utils.read_report(artifact.path)
    assert report["pages"] >= 2
    # 前端预览不了 pptx，所以要有一份文本预览兜底
    assert artifact.extra["text_path"]


def test_unknown_format_falls_back_to_docx(tmp_path: Path):
    ctx = _doc_context(tmp_path)
    result = generate_report(ctx, template="summary", format="keynote")
    assert result["format"] == "docx"


# ---------------------------------------------------------------- 子智能体门控


def test_doc_agent_is_gated_even_without_a_reading():
    """子智能体直接调 handler，绕开了引擎的门控点；它得自己过同一道门。"""
    from app.subagents.doc_agent import run as run_doc_agent

    ctx = SimpleNamespace(reading=None)
    result = run_doc_agent(ctx, task="写一份周报")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["reason"] == "not_authorized"


def test_doc_agent_passes_when_the_user_actually_asked():
    reading = TurnReading(
        stance=STANCE_DIRECT,
        commitment=COMMIT_AUTHORIZED,
        confidence=0.9,
        goal="生成周报",
    )
    assert decide_write("high", reading).allow is True
