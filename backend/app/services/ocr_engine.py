"""图片文字识别引擎：PaddleOCR 首选，RapidOCR 兜底。

为什么要一个适配层，而不是在 `media_service` 里直接 `from paddleocr import PaddleOCR`：

- **两家的返回结构完全不同。** PaddleOCR 3.x 的 `predict()` 返回一串 dict 子类
  （`rec_texts` / `rec_scores` / `rec_polys` / `rec_boxes`），2.x 的 `ocr()` 返回
  `[[[box, (text, score)], ...]]` 这种套娃数组，RapidOCR 给的是 `txts/scores/boxes`
  三份并行列表。下游（分行、`|` 分栏、表格还原）只该认一种东西——带坐标的文本块。
  把这些差异全关在这一个文件里，`media_service` 才不会又一次变成「猜字段名」现场。

- **装不上不能等于用不了。** PaddleOCR 需要 `paddlepaddle`（Windows 的 cp313 wheel
  约 105MB）外加首次使用要联网下模型；RapidOCR 的模型随 wheel 附带、纯 onnxruntime、
  离线可用。默认 `auto`：装了 Paddle 就用它，没装就退回 Rapid，而不是让「图片识别」
  整个入口变灰。想强制某一家就配 `OCR_ENGINE=paddle|rapid`，缺组件时错误信息里带命令。

- **坐标顺序是个真坑。** `rec_boxes` 是 `[x1, y1, x2, y2]` 四个数，`rec_polys` /
  `dt_polys` 是四个点的数组。老代码只按「四个点」解析，换成 Paddle 直接把 int 当
  point[0] 下标，第一个块就崩。`_bounds()` 两种都认。
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ENGINE_PADDLE = "paddle"
ENGINE_RAPID = "rapid"

#: 显式指定引擎时允许的名字（配置里大小写、空格都不计较）
ENGINE_NAMES = (ENGINE_PADDLE, ENGINE_RAPID)


class OcrEngineError(Exception):
    """引擎不可用或识别失败。`message` 直接给用户看，`retryable` 决定界面上要不要给重试。"""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class OcrLine:
    """一块识别出来的文字：文案 + 置信度 + 外接框。

    外接框（而不是四点框）就够下游用了：分行看纵向中心，分列看横向范围，
    表格还原看格子边界。旋转过的框取极值即可，没必要留着四个角。
    """

    text: str
    score: float
    left: float
    top: float
    right: float
    bottom: float

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


class OcrEngine(Protocol):
    """引擎只需要一个方法：给 PNG 字节，回一串带坐标的文字块。"""

    name: str

    def recognize(self, image: bytes) -> list[OcrLine]: ...


# --------------------------------------------------------------------------- #
# 输出归一化
# --------------------------------------------------------------------------- #


def _sequence(value: Any) -> list[Any]:
    """把 numpy 数组 / 元组 / 生成器都变成 list。

    不能写 `value or []`：numpy 数组的布尔值会抛 `ambiguous truth value`，
    PaddleOCR 的 `rec_scores` 恰好就是 ndarray。
    """
    if value is None:
        return []
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        listed = tolist()
        return listed if isinstance(listed, list) else [listed]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _points(box: Any) -> list[tuple[float, float]]:
    """框 → 顶点列表。两种形态都认：`[x1, y1, x2, y2]` 与四点数组。"""
    if box is None:
        return []
    tolist = getattr(box, "tolist", None)
    if callable(tolist):
        box = tolist()
    if not isinstance(box, (list, tuple)):
        return []
    if len(box) == 4 and all(isinstance(item, (int, float)) for item in box):
        x1, y1, x2, y2 = (float(item) for item in box)
        return [(x1, y1), (x2, y2)]
    points: list[tuple[float, float]] = []
    for item in box:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                points.append((float(item[0]), float(item[1])))
            except (TypeError, ValueError):
                continue
    return points


def _bounds(box: Any) -> tuple[float, float, float, float] | None:
    points = _points(box)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _lines_from(texts: list[Any], scores: list[Any], boxes: list[Any]) -> list[OcrLine]:
    """三份并行列表 → OcrLine 列表。缺坐标时退化成「一行一块」，顺序照旧。"""
    out: list[OcrLine] = []
    for index, raw in enumerate(texts):
        # 多行文本塞进一个框（整段被当成一块）时压成一行：下游按行切，
        # 块里再带换行会把「一行」和「一整段」混成一回事
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        score = 1.0
        if index < len(scores):
            try:
                score = float(scores[index])
            except (TypeError, ValueError):
                score = 1.0
        bounds = _bounds(boxes[index]) if index < len(boxes) else None
        if bounds is None:
            left, top, right, bottom = 0.0, float(index), float(len(text)), float(index) + 1.0
        else:
            left, top, right, bottom = bounds
        out.append(OcrLine(text=text, score=score, left=left, top=top, right=right, bottom=bottom))
    return out


def _lines_from_mapping(payload: Any) -> list[OcrLine] | None:
    """PaddleOCR 3.x 的结果对象（dict 子类，或外面还包了一层 `res`）。"""
    if not isinstance(payload, dict):
        return None
    data = payload.get("res")
    if not isinstance(data, dict):
        data = payload
    texts = _sequence(data.get("rec_texts"))
    if not texts:
        return None
    boxes = _sequence(data.get("rec_polys")) or _sequence(data.get("rec_boxes"))
    return _lines_from(texts, _sequence(data.get("rec_scores")), boxes)


def _lines_from_legacy(payload: list[Any]) -> list[OcrLine]:
    """PaddleOCR 2.x：`[[[box, (text, score)], ...]]`（外层是页）。"""
    texts: list[Any] = []
    scores: list[Any] = []
    boxes: list[Any] = []
    for page in payload:
        for item in _sequence(page):
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            box, content = item[0], item[1]
            if not isinstance(content, (list, tuple)) or len(content) < 2:
                continue
            texts.append(content[0])
            scores.append(content[1])
            boxes.append(box)
    return _lines_from(texts, scores, boxes)


def normalize_result(result: Any) -> list[OcrLine]:
    """引擎原始返回 → OcrLine 列表。认不出的结构返回空（上层会报「没识别到文字」）。"""
    if result is None:
        return []
    # RapidOCR 3.x：一个带 txts / scores / boxes 的对象
    txts = getattr(result, "txts", None)
    if txts is not None:
        return _lines_from(
            _sequence(txts),
            _sequence(getattr(result, "scores", None)),
            _sequence(getattr(result, "boxes", None)),
        )
    mapping = _lines_from_mapping(result)
    if mapping is not None:
        return mapping
    # 有些版本把结果挂在 `.json` 上（`{"res": {...}}`）
    payload = getattr(result, "json", None)
    if payload is not None:
        mapping = _lines_from_mapping(payload)
        if mapping is not None:
            return mapping
    if isinstance(result, (list, tuple)):
        return _lines_from_legacy(list(result))
    return []


def error_message(result: Any) -> str:
    """PaddleOCR 3.x 参数冲突/子模型缺失时不抛异常，而是返回 `{"error": ...}`。"""
    candidates = result if isinstance(result, (list, tuple)) else [result]
    for item in candidates:
        if isinstance(item, dict) and item.get("error"):
            return str(item["error"]).replace("\n", " ").strip()
    return ""


# --------------------------------------------------------------------------- #
# 引擎实现
# --------------------------------------------------------------------------- #


@contextmanager
def _temp_image(image: bytes) -> Iterator[Path]:
    """PaddleOCR 各版本对 bytes 入参支持不一（2.x 只吃路径），落个临时文件最稳。"""
    handle, name = tempfile.mkstemp(prefix="ocr_", suffix=".png")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(image)
        yield Path(name)
    finally:
        # 删不掉不影响识别结果：Windows 上偶发被杀软占着句柄
        with contextlib.suppress(OSError):
            os.unlink(name)


#: Paddle 3.3 的已知组合缺陷：oneDNN 加速 + PIR 执行器 + 部分 Windows CPU，
#: 推理时抛 `ConvertPirAttribute2RuntimeAttribute not support
#: [pir::ArrayAttribute<pir::DoubleAttribute>]`（栈顶在 onednn_instruction.cc）。
#: 这不是参数配错，关掉加速重跑一次就好 —— 认这几个关键词是为了自动降级。
_ONEDNN_HINTS = ("onednn", "mkldnn", "convertpirattribute2runtimeattribute")


def _is_onednn_failure(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(hint in text for hint in _ONEDNN_HINTS)


class PaddleOcrEngine:
    """PaddleOCR（PP-OCR 中文模型，检测 + 识别 + 单行方向）。

    模型首次使用时从官方源下载（几十 MB），所以「第一次很慢」是正常的，
    之后走本地缓存。加载失败要把这句带进错误里，否则用户只会看到一句超时。
    """

    name = ENGINE_PADDLE

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._pipeline: Any = None
        self._lock = threading.Lock()
        # oneDNN 默认关（配置项 OCR_MKLDNN）。关掉不只是「保守」：Paddle 3.3.1 在
        # Windows CPU 上开着它会崩在 PIR 执行器（见 `_is_onednn_failure`），
        # 而 OCR 是「要么出字要么报错」的路径，宁可慢一点也不能整张图认不出来。
        self._mkldnn = bool(getattr(settings, "ocr_mkldnn", False))

    def _options(self) -> dict[str, Any]:
        settings = self._settings
        options: dict[str, Any] = {
            "lang": str(getattr(settings, "ocr_lang", "ch") or "ch"),
            # 整页方向分类会多下一个模型、多跑一遍分类，默认关；
            # 躺倒的图由 `media_service` 的旋转重试兜（那条路不额外下模型）
            "use_doc_orientation_classify": bool(getattr(settings, "ocr_doc_orientation", False)),
            "use_doc_unwarping": False,
            # 单行方向：表格里偶尔有倒着盖的章、竖着写的标注，开着更稳
            "use_textline_orientation": bool(getattr(settings, "ocr_textline_orientation", True)),
            "enable_mkldnn": self._mkldnn,
        }
        version = str(getattr(settings, "ocr_version", "") or "").strip()
        if version:
            # 留空 = 用当前 PaddleOCR 的默认模型，不写死 v5/v6：
            # 上游换默认模型时不该被迫改代码
            options["ocr_version"] = version
        return options

    def _load(self) -> Any:
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise OcrEngineError(
                    "图片识别组件 PaddleOCR 未安装：执行 "
                    "pip install paddlepaddle paddleocr 后重启后端",
                    retryable=True,
                ) from exc

            options = self._options()
            attempts: list[dict[str, Any]] = [options]
            # 3.x 早期版本没有 enable_mkldnn 这个键（它是 PaddleX 预测器的参数）
            attempts.append({k: v for k, v in options.items() if k != "enable_mkldnn"})
            # 2.x 只有 use_angle_cls / lang，上面那些开关一个都不认
            attempts.append({"lang": options["lang"]})

            last: Exception | None = None
            for candidate in attempts:
                try:
                    self._pipeline = PaddleOCR(**candidate)
                except TypeError as exc:
                    # 「参数不认」才往下换写法；其它异常是模型或依赖的问题，换参数没用
                    last = exc
                    continue
                except Exception as exc:
                    raise OcrEngineError(
                        "PaddleOCR 初始化失败（首次使用需要联网下载模型）："
                        f"{type(exc).__name__}: {exc}",
                        retryable=True,
                    ) from exc
                return self._pipeline

            raise OcrEngineError(
                f"PaddleOCR 初始化失败：{type(last).__name__}: {last}", retryable=True
            ) from last

    def _drop_mkldnn(self) -> None:
        """关掉 oneDNN 并丢掉已建好的流水线，让下一次 `_load()` 重建。"""
        self._mkldnn = False
        with self._lock:
            self._pipeline = None

    def recognize(self, image: bytes) -> list[OcrLine]:
        pipeline = self._load()
        with _temp_image(image) as path:
            try:
                raw = self._predict(pipeline, path)
            except Exception as exc:
                if not (self._mkldnn and _is_onednn_failure(exc)):
                    raise OcrEngineError(
                        f"图片识别失败：{type(exc).__name__}: {exc}", retryable=True
                    ) from exc
                # 用户把 OCR_MKLDNN 打开了、这台机器的 Paddle 恰好踩中那个缺陷：
                # 关掉加速重建一次，别让他对着「图片识别失败」猜哪里配错了
                self._drop_mkldnn()
                try:
                    raw = self._predict(self._load(), path)
                except Exception as retry_exc:
                    raise OcrEngineError(
                        f"图片识别失败：{type(retry_exc).__name__}: {retry_exc}", retryable=True
                    ) from retry_exc

        pages = list(raw) if isinstance(raw, (list, tuple)) else [raw]
        failure = error_message(pages)
        if failure:
            raise OcrEngineError(f"图片识别引擎报错：{failure}", retryable=True)
        lines: list[OcrLine] = []
        for page in pages:
            lines.extend(normalize_result(page))
        return lines

    @staticmethod
    def _predict(pipeline: Any, path: str) -> Any:
        if hasattr(pipeline, "predict"):
            return pipeline.predict(str(path))
        return pipeline.ocr(str(path), cls=True)  # pragma: no cover - 2.x


class RapidOcrEngine:
    """RapidOCR（PP-OCR onnx 版，模型随 wheel 附带、离线可用）。

    留作兜底：Paddle 装不上、或临时没有网络下模型时，图片识别仍能出字。
    精度略低于 Paddle 的 server 模型，但对截图 / 白板这类规整输入够用。
    """

    name = ENGINE_RAPID

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._pipeline: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise OcrEngineError(
                    "图片文字识别组件未安装：执行 pip install rapidocr onnxruntime 后重启后端",
                    retryable=True,
                ) from exc
            try:
                # 关掉每张图都打的 INFO 日志，否则识别跑起来满屏都是模型路径
                self._pipeline = RapidOCR(params={"Global.log_level": "error"})
            except Exception as exc:  # pragma: no cover - 模型文件损坏
                raise OcrEngineError(
                    f"图片识别引擎加载失败：{type(exc).__name__}: {exc}", retryable=True
                ) from exc
            return self._pipeline

    def recognize(self, image: bytes) -> list[OcrLine]:
        engine = self._load()
        try:
            raw = engine(image)
        except Exception as exc:
            raise OcrEngineError(
                f"图片识别失败：{type(exc).__name__}: {exc}", retryable=True
            ) from exc
        return normalize_result(raw)


# --------------------------------------------------------------------------- #
# 选哪一家
# --------------------------------------------------------------------------- #

#: `find_spec` 只查「有没有装」，不执行模块代码：paddleocr 真正 import 要好几秒，
#: 放在每次健康检查里会把接口拖慢。结果缓存，进程内模块装了就不会再变。
_AVAILABILITY: dict[str, bool] | None = None
_AVAILABILITY_LOCK = threading.Lock()


def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):  # pragma: no cover - 坏掉的安装
        return False


def available(*, refresh: bool = False) -> dict[str, bool]:
    """哪几家引擎能真的用起来（模块装了才算）。"""
    global _AVAILABILITY
    with _AVAILABILITY_LOCK:
        if _AVAILABILITY is None or refresh:
            _AVAILABILITY = {
                # PaddleOCR 只是壳，真正跑推理的是 paddlepaddle，两个都得在
                ENGINE_PADDLE: _installed("paddleocr") and _installed("paddle"),
                ENGINE_RAPID: _installed("rapidocr"),
            }
        return dict(_AVAILABILITY)


def configured(settings: Any) -> str:
    raw = str(getattr(settings, "ocr_engine", "auto") or "auto").strip().lower()
    return raw if raw in ENGINE_NAMES else "auto"


def build_engine(settings: Any) -> OcrEngine:
    """按配置选引擎。这里**只造对象、不加载模型**，所以可以在健康检查里调用。"""
    choice = configured(settings)
    if choice == ENGINE_PADDLE:
        return PaddleOcrEngine(settings)
    if choice == ENGINE_RAPID:
        return RapidOcrEngine(settings)
    usable = available()
    if usable[ENGINE_PADDLE]:
        return PaddleOcrEngine(settings)
    return RapidOcrEngine(settings)


def active(settings: Any) -> tuple[OcrEngine, bool]:
    """(引擎对象, 现在是否真的可用)。不可用时上层给安装指引，而不是静默降级。"""
    engine = build_engine(settings)
    return engine, available().get(engine.name, False)
