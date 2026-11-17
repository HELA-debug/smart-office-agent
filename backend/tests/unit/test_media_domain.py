"""媒体格式表（`domain/media.py`）的边界测试。

这一层不碰文件内容，只回答「后缀是什么、MIME 认不认、要不要识别」。所以测试
也只钉这三件事，外加两条**结构性**约束 —— 它们才是这次重构的目的：

1. 格式表写歪时必须**当场**报错，而不是等用户传到某个后缀才发现（自检本身要
   被测，否则自检写错了没人知道）；
2. 「要不要识别」只能有一个来源。以前是 `MEDIA_SPECS` + `NEEDS_RECOGNITION`
   两份，加了新格式忘了改另一份，表现就是上传后一直停在「识别中」。

真实上传校验（解码、容器探测）在 `test_media.py` 里，这里不重复。
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest
from app.domain import media
from app.domain.media import (
    KIND_AUDIO,
    KIND_IMAGE,
    KIND_LABELS,
    KIND_TRANSCRIPT,
    KIND_VIDEO,
    MEDIA_SPECS,
    MediaSpec,
    media_kind,
    media_label,
    media_spec,
    media_specs_for_mime,
    needs_recognition,
)

# --------------------------------------------------------------------------
# 1. 后缀归一化：调用方传来的形式很杂，必须都能落到同一个规格
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [".PNG", "png", " .png ", ".Png", "\t.PNG\n"])
def test_media_spec_normalises_case_dot_and_whitespace(raw):
    """资源管理器给大写、`extra["ext"]` 给不带点的、拼接时带空白 —— 都要等价。"""
    assert media_spec(raw) is media_spec(".png")
    assert media_spec(raw).ext == ".png"


@pytest.mark.parametrize("raw", ["", ".", "   ", "pngx", "tar.gz", None])
def test_media_spec_returns_none_for_non_media(raw):
    """不认识的输入返回 None，让上游回落到文档解析，而不是抛异常。"""
    assert media_spec(raw) is None
    assert media_kind(raw) is None


def test_media_spec_returns_the_shared_frozen_instance():
    """表里那一个对象被多处共享，所以必须不可变 —— 顺手改它会污染所有调用方。"""
    spec = media_spec(".png")
    assert spec is media_spec(".PNG")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.ext = ".gif"  # type: ignore[misc]


# --------------------------------------------------------------------------
# 2. MIME 反查索引：一个 MIME 可能对应多个后缀
# --------------------------------------------------------------------------


def test_mime_index_is_one_to_many():
    """`.jpg` / `.jpeg` 共用 image/jpeg，反查必须两个都给出，不能只留最后一个。"""
    jpeg = media_specs_for_mime("image/jpeg")
    assert {spec.ext for spec in jpeg} == {".jpg", ".jpeg"}
    mp4 = media_specs_for_mime("video/mp4")
    assert {spec.ext for spec in mp4} == {".mp4", ".m4v"}


def test_mime_lookup_normalises_case_whitespace_and_parameters():
    """浏览器对 `<audio>` / `<video>` 常带 `;codecs=…`，不切掉就永远匹配不上。"""
    assert media_spec(".mp3") in media_specs_for_mime("  AUDIO/MPEG ; codecs=mp3 ")
    assert media_spec(".mp4") in media_specs_for_mime("video/mp4;codecs=avc1")


@pytest.mark.parametrize("raw", ["", "   ", "application/pdf", None, ";"])
def test_mime_lookup_returns_empty_set_for_unknown(raw):
    """空集合 = 「没有任何规格声明过它」；前缀兜底由 security 层负责。"""
    assert media_specs_for_mime(raw) == frozenset()


def test_mime_index_covers_every_declared_mime():
    """索引是派生出来的，不能漏任何一条声明 —— 漏了就等于那条 MIME 白写。"""
    for spec in MEDIA_SPECS:
        for mime in spec.mimes:
            assert spec in media_specs_for_mime(mime), f"{spec.ext} 的 {mime} 没进索引"


# --------------------------------------------------------------------------
# 3. 「要不要识别」只能有一个来源
# --------------------------------------------------------------------------


def test_recognition_flag_has_no_second_hand_written_list():
    """手写的 NEEDS_RECOGNITION 集合已删除，判断只能来自规格字段。"""
    assert not hasattr(media, "NEEDS_RECOGNITION")
    for spec in MEDIA_SPECS:
        assert needs_recognition(spec.kind) is spec.needs_recognition, spec.ext


def test_recognition_flag_is_false_only_for_transcripts():
    """图 / 音 / 视频要异步出字；srt、vtt 本身就是文字，上传即完成。"""
    assert needs_recognition(KIND_TRANSCRIPT) is False
    assert needs_recognition(KIND_IMAGE) is True
    assert needs_recognition(KIND_AUDIO) is True
    assert needs_recognition(KIND_VIDEO) is True


@pytest.mark.parametrize("kind", [None, "", "spreadsheet", "IMAGE "])
def test_recognition_flag_is_false_for_unknown_kind(kind):
    """未知 kind 不进识别队列：把空 kind 塞给识别器只会得到一条无意义的失败。"""
    assert needs_recognition(kind) is False


def test_media_label_falls_back_to_empty_string():
    """徽标会被直接拼进界面，未知值必须返回空串而不是 None / "None"。"""
    assert media_label(KIND_AUDIO) == "会议录音"
    assert media_label(None) == ""
    assert media_label("spreadsheet") == ""


# --------------------------------------------------------------------------
# 4. 导入自检本身
# --------------------------------------------------------------------------


def test_specs_are_unique_lowercase_and_labelled():
    """正常表的底线：唯一、小写带点、kind 有文案。写歪了由 `_check_specs` 拦。"""
    exts = [spec.ext for spec in MEDIA_SPECS]
    assert len(exts) == len(set(exts)), "后缀重复：后面的会静默覆盖前面的"
    for spec in MEDIA_SPECS:
        assert spec.ext.startswith(".") and spec.ext == spec.ext.lower(), spec.ext
        assert spec.kind in KIND_LABELS, spec.ext
        assert spec.mimes, spec.ext


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        (MediaSpec("PNG", KIND_IMAGE, ("image/png",)), "小写"),
        (MediaSpec("png", KIND_IMAGE, ("image/png",)), "点号"),
        (MediaSpec(".png", "spreadsheet", ("text/csv",)), "KIND_LABELS"),
        (MediaSpec(".png", KIND_IMAGE, ()), "MIME"),
        (MediaSpec(".png", KIND_IMAGE, ("image/PNG",)), "小写"),
        (MediaSpec(".png", KIND_IMAGE, ("image/png; codecs=x",)), "参数"),
        (MediaSpec(".png", KIND_IMAGE, ("image",)), "type/subtype"),
    ],
)
def test_spec_checker_rejects_broken_entry(monkeypatch, broken, expected):
    """每条自检规则都要有一条能把它触发出来的用例，否则规则等于没写。"""
    monkeypatch.setattr(media, "MEDIA_SPECS", (broken,))
    with pytest.raises(RuntimeError) as err:
        media._check_specs()
    assert expected in str(err.value)


def test_spec_checker_rejects_duplicate_ext(monkeypatch):
    """`_BY_EXT` 是 dict：重复定义不会报错，只会让前一条永远取不到。"""
    duplicate = (
        MediaSpec(".png", KIND_IMAGE, ("image/png",)),
        MediaSpec(".png", KIND_IMAGE, ("image/png",)),
    )
    monkeypatch.setattr(media, "MEDIA_SPECS", duplicate)
    with pytest.raises(RuntimeError) as err:
        media._check_specs()
    assert "重复" in str(err.value)


def test_spec_checker_rejects_inconsistent_flag_within_one_kind(monkeypatch):
    """同一个 kind 一半识别一半不识别，前端只能靠猜，必须拦下。"""
    inconsistent = (
        MediaSpec(".srt", KIND_TRANSCRIPT, ("text/plain",), needs_recognition=False),
        MediaSpec(".vtt", KIND_TRANSCRIPT, ("text/vtt",), needs_recognition=True),
    )
    monkeypatch.setattr(media, "MEDIA_SPECS", inconsistent)
    with pytest.raises(RuntimeError) as err:
        media._check_specs()
    assert "不一致" in str(err.value)


def test_spec_checker_rejects_empty_table(monkeypatch):
    """空表会让媒体白名单整体消失，且反查索引无从构建。"""
    monkeypatch.setattr(media, "MEDIA_SPECS", ())
    with pytest.raises(RuntimeError) as err:
        media._check_specs()
    assert "为空" in str(err.value)


def test_broken_table_fails_at_import_time(tmp_path):
    """自检必须挂在**导入**路径上：写歪的表不能等用户传到那个后缀才暴露。

    这里把源文件里的 `.png` 改成大写 `PNG` 再执行一遍模块顶层，模拟一次真实的
    「有人手滑」——正常表早已在测试 import 时通过，这条只验坏表会当场炸。
    """
    source = Path(media.__file__).read_text(encoding="utf-8")
    broken = source.replace(
        'MediaSpec(".png", KIND_IMAGE, ("image/png",)),',
        'MediaSpec("PNG", KIND_IMAGE, ("image/png",)),',
    )
    assert broken != source, "源码里 .png 的定义变了，更新这条测试的替换目标"

    path = tmp_path / "broken_media.py"
    path.write_text(broken, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("broken_media", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 模块用了 `from __future__ import annotations`，dataclass 要回头查模块命名空间
    # 解析字符串注解，所以必须先注册进 sys.modules，否则 exec 阶段就 AttributeError
    sys.modules["broken_media"] = module
    try:
        with pytest.raises(RuntimeError) as err:
            spec.loader.exec_module(module)
    finally:
        sys.modules.pop("broken_media", None)
    assert "小写" in str(err.value)


# --------------------------------------------------------------------------
# 5. 职责边界：这张表只描述后缀与 MIME
# --------------------------------------------------------------------------


def test_spec_carries_no_size_or_duration_fields():
    """体积上限、时长上限属于 Settings 与识别服务，不该混进格式表。"""
    assert set(MediaSpec.__dataclass_fields__) == {
        "ext",
        "kind",
        "mimes",
        "needs_recognition",
    }
