"""OCR 引擎适配层的测试。

重点不是「模型准不准」（那要真图真模型），而是**各家返回结构能不能被正确理解**：

- PaddleOCR 3.x 给 `rec_texts / rec_scores / rec_polys / rec_boxes`（dict 子类，可能还包一层 `res`）；
- PaddleOCR 2.x 给 `[[[box, (text, score)], ...]]`；
- RapidOCR 给 `txts / scores / boxes` 三份并行列表；
- 参数冲突时 Paddle 3.x 不抛异常，而是回一个 `{"error": ...}`。

这些差异只要有一处认错，下游的分行、分栏、表格还原就全乱——而且是「错得看着挺像」的那种乱。
"""

from __future__ import annotations

import sys
import types
from typing import Any, ClassVar

import numpy as np
import pytest
from app.services.ocr_engine import (
    ENGINE_PADDLE,
    ENGINE_RAPID,
    OcrEngineError,
    build_engine,
    error_message,
    normalize_result,
)


def _fake_paddle_module(pipeline: Any) -> types.ModuleType:
    """伪造 `paddleocr` 模块：本机不一定装了 Paddle，装没装都该能测这条链路。"""
    module = types.ModuleType("paddleocr")
    module.PaddleOCR = lambda **kwargs: pipeline  # type: ignore[attr-defined]
    return module


class _DictResult(dict):
    """PaddleOCR 3.x 的 OCRResult 就是 dict 的子类。"""


# --------------------------------------------------------------------------- #
# 归一化：PaddleOCR 3.x
# --------------------------------------------------------------------------- #


def test_paddle_v3_polys_become_boxes():
    result = _DictResult(
        rec_texts=["星期一", "语文"],
        rec_scores=[0.99, 0.87],
        rec_polys=[
            [[10, 20], [110, 20], [110, 50], [10, 50]],
            [[200, 20], [260, 20], [260, 50], [200, 50]],
        ],
    )
    lines = normalize_result(result)
    assert [line.text for line in lines] == ["星期一", "语文"]
    assert lines[0].left == 10 and lines[0].right == 110
    assert lines[0].top == 20 and lines[0].bottom == 50
    assert lines[1].score == pytest.approx(0.87)


def test_paddle_v3_rec_boxes_are_xyxy_not_four_points():
    """`rec_boxes` 是 [x1,y1,x2,y2] 四个数。按四点框解析会把 int 当 point[0] 下标，直接崩。"""
    result = _DictResult(
        rec_texts=["合计"],
        rec_scores=[0.95],
        rec_boxes=[[12, 34, 56, 78]],
    )
    line = normalize_result(result)[0]
    assert (line.left, line.top, line.right, line.bottom) == (12.0, 34.0, 56.0, 78.0)


def test_paddle_v3_numpy_arrays_are_fine():
    """真实返回里 rec_scores / rec_polys 都是 ndarray，写成 `value or []` 会抛真值歧义。"""
    result = _DictResult(
        rec_texts=np.array(["第一节", "第二节"]),
        rec_scores=np.array([0.9, 0.8], dtype=np.float32),
        rec_polys=np.array(
            [
                [[0, 0], [50, 0], [50, 20], [0, 20]],
                [[0, 30], [50, 30], [50, 50], [0, 50]],
            ]
        ),
    )
    lines = normalize_result(result)
    assert [line.text for line in lines] == ["第一节", "第二节"]
    assert lines[1].top == 30 and lines[1].bottom == 50


def test_paddle_v3_nested_res_key():
    """有的版本把结果包在 `{"res": {...}}` 里（CLI 输出就是这个形状）。"""
    result = {"res": {"rec_texts": ["备注"], "rec_scores": [0.77], "rec_boxes": [[1, 2, 3, 4]]}}
    lines = normalize_result(result)
    assert lines[0].text == "备注"
    assert lines[0].score == pytest.approx(0.77)


# --------------------------------------------------------------------------- #
# 归一化：PaddleOCR 2.x / RapidOCR / 退化情况
# --------------------------------------------------------------------------- #


def test_paddle_v2_nested_list():
    """2.x：`[[[box, (text, score)], ...]]`，外层是页。"""
    result = [
        [
            [[[0, 0], [40, 0], [40, 12], [0, 12]], ("课程表", 0.93)],
            [[[0, 20], [40, 20], [40, 32], [0, 32]], ("周一", 0.88)],
        ]
    ]
    lines = normalize_result(result)
    assert [line.text for line in lines] == ["课程表", "周一"]
    assert lines[0].top == 0 and lines[1].top == 20


def test_rapid_shape_still_works():
    """RapidOCR 的 txts / scores / boxes 三份并行列表（兜底引擎不能因为换引擎而失效）。"""

    class _Rapid:
        txts: ClassVar[list[str]] = ["第一行文字", "  ", "第二行文字"]
        scores: ClassVar[list[float]] = [0.99, 0.5, 0.98]
        boxes: ClassVar[list[Any]] = [
            [[[0, 0], [80, 0], [80, 20], [0, 20]]],
            [[[0, 30], [20, 30], [20, 50], [0, 50]]],
            [[[0, 60], [80, 60], [80, 80], [0, 80]]],
        ]

    lines = normalize_result(_Rapid())
    # 空白块不进结果，否则下游会多出一行空行
    assert [line.text for line in lines] == ["第一行文字", "第二行文字"]


def test_missing_boxes_fall_back_to_engine_order():
    """老引擎 / 测试替身不给坐标时，保持引擎顺序一行一块，而不是整页糊成一块。"""

    class _NoBox:
        txts: ClassVar[list[str]] = ["甲", "乙"]
        scores: ClassVar[list[float]] = [0.9, 0.9]
        boxes: ClassVar[None] = None

    lines = normalize_result(_NoBox())
    assert [(line.text, line.top) for line in lines] == [("甲", 0.0), ("乙", 1.0)]


def test_multiline_block_is_squeezed_to_one_line():
    """整段被当成一块返回时压成一行：块里带换行会跟「按行切」的规则打架。"""

    class _Wrapped:
        txts: ClassVar[list[str]] = ["第一句\n第二句"]
        scores: ClassVar[list[float]] = [0.9]
        boxes: ClassVar[None] = None

    assert normalize_result(_Wrapped())[0].text == "第一句 第二句"


def test_unknown_payload_is_empty_not_an_exception():
    assert normalize_result(None) == []
    assert normalize_result(object()) == []
    assert normalize_result([]) == []


# --------------------------------------------------------------------------- #
# 错误回执
# --------------------------------------------------------------------------- #


def test_error_payload_is_surfaced():
    """3.7 文档写明：参数冲突时返回 {"error": ...} 而不是抛异常。当成「没识别到文字」就误导人了。"""
    payload = [{"error": "use_textline_orientation cannot be changed after init"}]
    assert "use_textline_orientation" in error_message(payload)
    assert error_message([{"rec_texts": ["ok"]}]) == ""


def test_paddle_raises_on_error_payload(monkeypatch: pytest.MonkeyPatch):
    from app.services import ocr_engine

    class _Pipeline:
        def predict(self, path: str) -> list[dict[str, Any]]:
            return [{"error": "model not initialized"}]

    monkeypatch.setitem(sys.modules, "paddleocr", _fake_paddle_module(_Pipeline()))
    engine = ocr_engine.PaddleOcrEngine(settings=object())
    with pytest.raises(OcrEngineError) as err:
        engine.recognize(b"\x89PNG fake")
    assert "model not initialized" in err.value.message
    assert err.value.retryable is True


def test_paddle_missing_package_tells_you_the_command(monkeypatch: pytest.MonkeyPatch):
    """缺组件时的错误必须带安装命令：只说「未安装」，用户不知道装哪个包。"""
    from app.services import ocr_engine

    # 让 `from paddleocr import PaddleOCR` 失败
    monkeypatch.setitem(sys.modules, "paddleocr", None)
    engine = ocr_engine.PaddleOcrEngine(settings=object())
    with pytest.raises(OcrEngineError) as err:
        engine.recognize(b"\x89PNG fake")
    assert "pip install paddlepaddle paddleocr" in err.value.message
    assert err.value.retryable is True


# --------------------------------------------------------------------------- #
# 跑通一次完整调用（临时文件 + predict + 归一化）
# --------------------------------------------------------------------------- #


def test_paddle_predict_round_trip(monkeypatch: pytest.MonkeyPatch):
    from app.services import ocr_engine

    seen: dict[str, Any] = {}

    class _Pipeline:
        def __init__(self, **kwargs: Any) -> None:
            seen["kwargs"] = kwargs

        def predict(self, path: str) -> list[_DictResult]:
            # 真引擎吃的是路径；这里顺手确认传进来的确实是写盘的临时文件
            seen["path"] = path
            from pathlib import Path

            seen["exists"] = Path(path).exists()
            seen["bytes"] = Path(path).read_bytes()
            return [
                _DictResult(
                    rec_texts=["周三", "数学"],
                    rec_scores=[0.99, 0.96],
                    rec_boxes=[[0, 0, 40, 20], [50, 0, 120, 20]],
                )
            ]

    monkeypatch.setitem(sys.modules, "paddleocr", types.ModuleType("paddleocr"))
    monkeypatch.setattr(sys.modules["paddleocr"], "PaddleOCR", _Pipeline, raising=False)

    engine = ocr_engine.PaddleOcrEngine(settings=object())
    lines = engine.recognize(b"\x89PNG body")

    assert [line.text for line in lines] == ["周三", "数学"]
    assert seen["exists"] is True
    assert seen["bytes"] == b"\x89PNG body"
    # 传路径而不是 bytes：2.x 只吃路径，3.x 也都认
    assert str(seen["path"]).endswith(".png")


def test_paddle_options_come_from_settings():
    from app.services import ocr_engine

    class _Settings:
        ocr_lang = "ch"
        ocr_version = "PP-OCRv5"
        ocr_doc_orientation = True
        ocr_textline_orientation = False

    options = ocr_engine.PaddleOcrEngine(settings=_Settings())._options()
    assert options["lang"] == "ch"
    assert options["ocr_version"] == "PP-OCRv5"
    assert options["use_doc_orientation_classify"] is True
    assert options["use_textline_orientation"] is False
    # 畸变矫正（把拍弯的纸拉直）耗时翻倍，截图场景用不上，永远关
    assert options["use_doc_unwarping"] is False


def test_empty_version_means_engine_default():
    """`ocr_version` 留空就不传：上游换默认模型时不该被迫改代码。"""
    from app.services import ocr_engine

    class _Settings:
        ocr_lang = "ch"
        ocr_version = ""

    assert "ocr_version" not in ocr_engine.PaddleOcrEngine(settings=_Settings())._options()


# --------------------------------------------------------------------------- #
# 选哪一家
# --------------------------------------------------------------------------- #


def test_engine_choice_follows_config_and_availability(monkeypatch: pytest.MonkeyPatch):
    from app.services import ocr_engine

    def _settings(choice: str) -> Any:
        return types.SimpleNamespace(ocr_engine=choice)

    monkeypatch.setattr(
        ocr_engine, "available", lambda refresh=False: {ENGINE_PADDLE: True, ENGINE_RAPID: True}
    )
    assert build_engine(_settings("auto")).name == ENGINE_PADDLE
    assert build_engine(_settings("rapid")).name == ENGINE_RAPID
    # 显式指定就照办：没装也不是「悄悄换一家」，而是到加载时报清楚的错
    assert build_engine(_settings("paddle")).name == ENGINE_PADDLE

    monkeypatch.setattr(
        ocr_engine, "available", lambda refresh=False: {ENGINE_PADDLE: False, ENGINE_RAPID: True}
    )
    assert build_engine(_settings("auto")).name == ENGINE_RAPID
    assert build_engine(_settings("paddle")).name == ENGINE_PADDLE


def test_unknown_engine_name_falls_back_to_auto(monkeypatch: pytest.MonkeyPatch):
    """配错名字（大小写、拼错）不该让整条链路不可用，静默按 auto 走。"""
    from app.services import ocr_engine

    monkeypatch.setattr(
        ocr_engine, "available", lambda refresh=False: {ENGINE_PADDLE: True, ENGINE_RAPID: False}
    )
    settings = types.SimpleNamespace(ocr_engine="PaddleOCR")
    assert ocr_engine.configured(settings) == "auto"
    assert build_engine(settings).name == ENGINE_PADDLE


def test_paddle_turns_onednn_off_by_default():
    """oneDNN 默认关。

    Paddle 3.3.1 在 Windows CPU 上开着它会崩在 PIR 执行器
    （`ConvertPirAttribute2RuntimeAttribute`），整张图一个字都认不出来。
    加速是「快一点」的事，识别是「有没有」的事，默认值只能选后者。
    """
    from app.services import ocr_engine

    options = ocr_engine.PaddleOcrEngine(settings=object())._options()
    assert options["enable_mkldnn"] is False


def test_paddle_onednn_can_be_turned_on_from_settings():
    from app.services import ocr_engine

    settings = types.SimpleNamespace(ocr_mkldnn=True)
    assert ocr_engine.PaddleOcrEngine(settings=settings)._options()["enable_mkldnn"] is True


def test_paddle_drops_the_kwarg_when_this_version_does_not_take_it(monkeypatch: pytest.MonkeyPatch):
    """3.x 早期版本的 PaddleOCR 没有 `enable_mkldnn` 这个参数。

    构造时抛 TypeError 只是「这版不认这个键」，摘掉它重试就好；
    要是当成致命错误，用户会看到「PaddleOCR 初始化失败」而其实引擎是好的。
    """
    from app.services import ocr_engine

    built: list[dict[str, Any]] = []

    class _Pipeline:
        def __init__(self, **kwargs: Any) -> None:
            if "enable_mkldnn" in kwargs:
                raise TypeError("__init__() got an unexpected keyword argument 'enable_mkldnn'")
            built.append(kwargs)

        def predict(self, path: str) -> list[_DictResult]:
            return [_DictResult(rec_texts=["好"], rec_scores=[0.9], rec_boxes=[[0, 0, 10, 10]])]

    monkeypatch.setitem(sys.modules, "paddleocr", types.ModuleType("paddleocr"))
    monkeypatch.setattr(sys.modules["paddleocr"], "PaddleOCR", _Pipeline, raising=False)

    lines = ocr_engine.PaddleOcrEngine(settings=object()).recognize(b"\x89PNG body")

    assert [line.text for line in lines] == ["好"]
    assert built and "enable_mkldnn" not in built[-1]
    # 其余参数照旧传下去：摘掉的只该是这一个键
    assert built[-1]["use_textline_orientation"] is True


def test_paddle_retries_without_onednn_when_the_engine_crashes(
    monkeypatch: pytest.MonkeyPatch,
):
    """用户手动打开 OCR_MKLDNN、机器恰好踩中那个缺陷 → 关掉加速重建一次。

    报错原文（`ConvertPirAttribute2RuntimeAttribute not support`）对用户毫无意义，
    直接抛上去只会被当成「图片识别坏了」。能自愈的就自愈。
    """
    from app.services import ocr_engine

    built: list[bool] = []

    class _Pipeline:
        def __init__(self, **kwargs: Any) -> None:
            self.mkldnn = bool(kwargs.get("enable_mkldnn"))
            built.append(self.mkldnn)

        def predict(self, path: str) -> list[_DictResult]:
            if self.mkldnn:
                raise NotImplementedError(
                    "(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support "
                    "[pir::ArrayAttribute<pir::DoubleAttribute>] "
                    "(at ..\\paddle\\fluid\\framework\\new_executor\\instruction\\onednn\\"
                    "onednn_instruction.cc:118)"
                )
            return [_DictResult(rec_texts=["好"], rec_scores=[0.9], rec_boxes=[[0, 0, 10, 10]])]

    monkeypatch.setitem(sys.modules, "paddleocr", types.ModuleType("paddleocr"))
    monkeypatch.setattr(sys.modules["paddleocr"], "PaddleOCR", _Pipeline, raising=False)

    engine = ocr_engine.PaddleOcrEngine(settings=types.SimpleNamespace(ocr_mkldnn=True))
    lines = engine.recognize(b"\x89PNG body")

    assert [line.text for line in lines] == ["好"]
    # 第一次带 oneDNN 崩了，第二次关掉就过了；而且只降级一次，不平白多跑
    assert built == [True, False]


def test_paddle_does_not_retry_when_onednn_is_not_the_cause(
    monkeypatch: pytest.MonkeyPatch,
):
    """别的失败照旧报错：什么都重试一遍只会把一张图的耗时翻倍。"""
    from app.services import ocr_engine

    calls: list[int] = []

    class _Pipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def predict(self, path: str) -> list[_DictResult]:
            calls.append(1)
            raise RuntimeError("模型文件损坏")

    monkeypatch.setitem(sys.modules, "paddleocr", types.ModuleType("paddleocr"))
    monkeypatch.setattr(sys.modules["paddleocr"], "PaddleOCR", _Pipeline, raising=False)

    engine = ocr_engine.PaddleOcrEngine(settings=types.SimpleNamespace(ocr_mkldnn=True))
    with pytest.raises(OcrEngineError) as err:
        engine.recognize(b"\x89PNG body")

    assert "模型文件损坏" in err.value.message
    assert len(calls) == 1
