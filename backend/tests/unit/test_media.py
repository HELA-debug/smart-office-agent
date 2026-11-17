"""媒体素材：图片 OCR、会议记录、录音 / 视频转写。

用户要的不只是「能传图片」，而是「传进来能拿到字」。这条链路有三处最容易悄悄
坏掉，这里逐条钉住：

1. **白名单**：图片 / 音视频 / 转写稿必须被 `validate_upload` 放行，但**不能**混进
   `OUTPUT_FORMATS`（否则产物下拉里会多出点不出来的 PNG、MP3）；扩展名对、内容
   不对的文件（把 .exe 改成 .mp4）要当场拒掉。
2. **拿到字**：图片走 OCR、录音走转写、srt/vtt 直接按文本解析；识别不出内容时给
   的是「可重试的失败」，不是一段空文本 —— 空文本会让模型拿着文件名编会议纪要。
3. **时序**：上传立刻返回「识别中」，后台出字后才变成「可用 N 字」；识别没完就
   发任务必须被拦下（前端拦一次，这里再拦一次）。

识别引擎本身不进单测（真实推理一次几秒且依赖模型文件），这里用假引擎替换，只验
「拿到结果之后怎么落状态、怎么落盘、怎么报错」。真机实跑另有人工验证。
"""

from __future__ import annotations

import base64
import io
import wave
from pathlib import Path
from typing import Any, ClassVar

import pytest
from app.core.config import Settings
from app.core.security import (
    SUPPORTED_UPLOAD_EXTS,
    UploadValidationError,
    _mime_matches_media,
    validate_upload,
)
from app.core.utils import count_chars
from app.domain.entities import Artifact
from app.domain.formats import FORMATS
from app.domain.media import (
    KIND_AUDIO,
    KIND_IMAGE,
    KIND_LABELS,
    KIND_TRANSCRIPT,
    KIND_VIDEO,
    MEDIA_EXTS,
    MEDIA_SPECS,
    media_kind,
    media_label,
    media_spec,
    needs_recognition,
)
from app.infra.db.models import Base
from app.infra.db.repositories.artifact_repo import SqlArtifactRepository
from app.infra.db.session import create_database_engine
from app.infra.parsing import ParseFailure, parse_bytes
from app.infra.storage import LocalFileStorage
from app.services.artifact_service import ArtifactService
from app.services.conversation_service import ConversationService
from app.services.media_service import MediaError, MediaRecognizer, RecognitionResult
from app.services.run_service import RunService
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

# --------------------------------------------------------------------------
# 夹具：真实文件字节
# --------------------------------------------------------------------------


def _png_bytes(size: tuple[int, int] = (80, 30), text: str = "") -> bytes:
    """造一张真 PNG（Pillow 能解码、能过 magic 校验）。"""
    image = Image.new("RGB", size, (255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _wav_bytes(seconds: float = 0.2, rate: int = 8000) -> bytes:
    """造一段真 WAV：容器校验（av 探测流）过不了的话，测试会变成「假文件被拒」。"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


SRT_SAMPLE = """1
00:00:00,000 --> 00:00:02,400
张伟：今天先过一下三季度的进度。

2
00:00:02,400 --> 00:00:05,120
李娜：华东区已经完成 82%，比计划快一点。

3
00:00:05,120 --> 00:00:07,000
张伟：&lt;b&gt;好&lt;/b&gt;，剩下的风险点下周对齐。
"""

VTT_SAMPLE = """WEBVTT
Kind: captions
Language: zh-CN

NOTE 这段由会议系统自动生成

00:00:01.000 --> 00:00:03.000
<i>大家好</i>，这是本周例会。

00:00:03.000 --> 00:00:05.500
第一项议题：预算。

00:00:05.500 --> 00:00:08.000
我们下周一再对一次
时间定在下午三点
"""


class _FakeThreads:
    """够用的会话仓储：上传后要 touch 一下更新时间。"""

    def __init__(self) -> None:
        self.items: dict[str, Any] = {"th_1": _Thread()}

    def get(self, thread_id: str) -> Any:
        return self.items.get(thread_id)

    def update(self, thread: Any) -> None:
        self.items[thread.id] = thread


class _Thread:
    id = "th_1"
    updated_at = "2026-11-01T00:00:00+08:00"


class _FakeArtifacts:
    def __init__(self) -> None:
        self.items: dict[str, Artifact] = {}

    def add(self, artifact: Artifact) -> Artifact:
        self.items[artifact.id] = artifact
        return artifact

    def get(self, artifact_id: str, include_deleted: bool = False) -> Artifact | None:
        return self.items.get(artifact_id)

    def list(
        self,
        thread_id: str | None = None,
        run_id: str | None = None,
        type: str | None = None,
        include_deleted: bool = False,
        limit: int = 200,
        **_: Any,
    ) -> list[Artifact]:
        return [
            item
            for item in self.items.values()
            if (thread_id is None or item.thread_id == thread_id)
            and (type is None or item.type == type)
            and not item.deleted_at
        ][:limit]

    def count_by_thread(self, thread_id: str) -> int:
        return len([item for item in self.items.values() if item.thread_id == thread_id])

    def update_extra(self, artifact_id: str, extra: dict[str, Any]) -> None:
        self.items[artifact_id].extra = dict(extra)


class _FakeParser:
    supported_exts: ClassVar[set[str]] = {".txt", ".docx", ".srt", ".vtt"}

    def parse(self, data: bytes, ext: str) -> str:
        return data.decode("utf-8", errors="ignore")


class _FakeMedia(MediaRecognizer):
    """假识别引擎：不加载模型，只按预设返回文本或抛错。"""

    def __init__(self, *, text: str = "", error: MediaError | None = None) -> None:
        self.settings = Settings()
        self.text = text
        self.error = error
        self.calls: list[str] = []
        self.last_hotwords: list[str] | None = None

    def ocr(self, data: bytes) -> RecognitionResult:
        self.calls.append("ocr")
        if self.error is not None:
            raise self.error
        return RecognitionResult(text=self.text, meta={"engine": "fake-ocr", "lines": 2})

    def transcribe(self, data: bytes, *, hotwords: Any = None) -> RecognitionResult:
        self.calls.append("asr")
        self.last_hotwords = list(hotwords or [])
        if self.error is not None:
            raise self.error
        return RecognitionResult(text=self.text, meta={"engine": "fake-asr", "duration": 12.0})


def _service(tmp_path: Path, media: _FakeMedia) -> tuple[ArtifactService, _FakeArtifacts]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        upload_dir=str(tmp_path / "uploads"),
        artifact_dir=str(tmp_path / "artifacts"),
        max_upload_mb=20,
        max_media_mb=200,
    )
    settings.ensure_dirs()
    artifacts = _FakeArtifacts()
    service = ArtifactService(
        artifacts=artifacts,  # type: ignore[arg-type]
        threads=_FakeThreads(),  # type: ignore[arg-type]
        storage=LocalFileStorage(settings),
        parser=_FakeParser(),  # type: ignore[arg-type]
        settings=settings,
        media=media,
    )
    return service, artifacts


# --------------------------------------------------------------------------
# 1. 格式表与白名单
# --------------------------------------------------------------------------


def test_media_exts_are_uploadable_but_never_output_formats():
    """媒体能「进来」但不能「产出」：混进产物菜单就成了点不出来的空项。"""
    output_exts = {spec.ext for spec in FORMATS}
    assert MEDIA_EXTS, "媒体格式表不能为空"
    assert MEDIA_EXTS & output_exts == set()
    for ext in MEDIA_EXTS:
        assert ext in SUPPORTED_UPLOAD_EXTS, f"{ext} 没进上传白名单"


def test_every_media_ext_has_label_and_mimes():
    """kind 决定徽标文案与「要不要识别」：缺一条界面上就会显示成空白行。"""
    for spec in MEDIA_SPECS:
        assert spec.kind in KIND_LABELS, spec.ext
        assert spec.mimes, f"{spec.ext} 至少要有一个 MIME"
        assert spec.ext == spec.ext.lower() and spec.ext.startswith(".")
        # 有文字可取的类别必须能判断出来，否则上传后会静默只剩一个文件名
        assert needs_recognition(spec.kind) is (spec.kind != KIND_TRANSCRIPT), spec.ext


@pytest.mark.parametrize(
    ("ext", "kind", "need"),
    [
        (".PNG", KIND_IMAGE, True),
        (".jpeg", KIND_IMAGE, True),
        (".srt", KIND_TRANSCRIPT, False),
        (".vtt", KIND_TRANSCRIPT, False),
        (".mp3", KIND_AUDIO, True),
        (".m4a", KIND_AUDIO, True),
        (".mp4", KIND_VIDEO, True),
        (".mov", KIND_VIDEO, True),
        (".docx", None, False),
    ],
)
def test_media_kind_and_recognition_flag(ext: str, kind: str | None, need: bool):
    assert media_kind(ext) == kind
    assert needs_recognition(kind) is need
    # 大小写混着传（用户从 Windows 资源管理器拖进来常是大写后缀）
    assert media_kind(ext.lower()) == kind


def test_media_spec_tolerates_suffix_without_dot():
    """调用方有时拿到的是 extra["ext"] 这种没有点号的值。"""
    assert media_spec("png") is not None
    assert media_spec(".png") is not None
    assert media_spec("") is None
    assert media_label(KIND_AUDIO) == "会议录音"


# --------------------------------------------------------------------------
# 2. 上传校验：扩展名对、内容不对要拒
# --------------------------------------------------------------------------


def test_image_upload_passes_magic_check():
    validate_upload("截图.png", "image/png", _png_bytes())


def test_image_with_text_content_is_rejected():
    """把 txt 改成 .png：MIME 能骗过浏览器，解码骗不过 Pillow。"""
    with pytest.raises(UploadValidationError) as err:
        validate_upload("假的.png", "image/png", b"this is not an image at all")
    assert err.value.reason == "magic_mismatch"


def test_media_mime_is_lenient_but_not_unbounded():
    """iPhone 录音是 audio/x-m4a，不该因为 MIME 与官方值不同就拒收。"""
    assert _mime_matches_media("audio/x-m4a", media_spec(".m4a"))
    assert _mime_matches_media("audio/mp4", media_spec(".m4a"))
    assert _mime_matches_media("", media_spec(".mp3"))  # 有的客户端什么都不报
    # 类别对不上就是真的不对
    assert not _mime_matches_media("application/pdf", media_spec(".png"))
    with pytest.raises(UploadValidationError) as err:
        validate_upload("会议.png", "application/pdf", _png_bytes())
    assert err.value.reason == "mime_mismatch"


def test_transcript_uploads_are_parsed_as_text():
    validate_upload("会议记录.srt", "application/x-subrip", SRT_SAMPLE.encode())
    validate_upload("会议记录.vtt", "text/vtt", VTT_SAMPLE.encode())


def test_transcript_with_binary_content_is_rejected():
    with pytest.raises(UploadValidationError) as err:
        validate_upload("会议记录.srt", "text/plain", b"\x00\x01\x02binary")
    assert err.value.reason == "magic_mismatch"


def test_audio_container_is_checked_when_decoder_available():
    """音视频走容器探测：装了 av 才验内容，没装时至少不误拦。"""
    pytest.importorskip("av")
    with pytest.raises(UploadValidationError) as err:
        validate_upload("会议录音.mp3", "audio/mpeg", b"ID3 but nothing after it")
    assert err.value.reason == "magic_mismatch"


def test_empty_media_is_rejected():
    with pytest.raises(UploadValidationError) as err:
        validate_upload("截图.png", "image/png", b"")
    assert err.value.reason == "empty"


# --------------------------------------------------------------------------
# 3. 会议记录：srt / vtt 转纯文本
# --------------------------------------------------------------------------


def test_srt_is_stripped_to_sentences():
    text = parse_bytes(SRT_SAMPLE.encode(), ".srt")
    lines = text.split("\n")
    # 序号、时间轴都不要；一句一行，方便引用「谁在第几分钟说了什么」
    assert lines == [
        "张伟：今天先过一下三季度的进度。",
        "李娜：华东区已经完成 82%，比计划快一点。",
        "张伟：好，剩下的风险点下周对齐。",  # 行内标签剥掉、HTML 实体还原
    ]
    assert "-->" not in text and "00:00:02,400" not in text


def test_vtt_skips_header_notes_and_tags():
    text = parse_bytes(VTT_SAMPLE.encode(), ".vtt")
    assert "WEBVTT" not in text
    assert "NOTE" not in text
    assert "<i>" not in text
    # 同一条字幕被折成两行是同一句话，拼回一句再交付
    assert text.split("\n") == [
        "大家好，这是本周例会。",
        "第一项议题：预算。",
        "我们下周一再对一次时间定在下午三点",
    ]


def test_transcript_with_only_timeline_raises():
    with pytest.raises(ParseFailure):
        parse_bytes(b"1\n00:00:00,000 --> 00:00:01,000\n\n2\n", ".srt")


def test_image_and_audio_cannot_be_parsed_as_documents():
    """图片 / 录音必须先识别：直接解析等于给模型一段空文本。"""
    for ext, data in ((".png", _png_bytes()), (".mp3", b"ID3")):
        with pytest.raises(ParseFailure) as err:
            parse_bytes(data, ext)
        assert "识别" in str(err.value)


# --------------------------------------------------------------------------
# 4. 识别引擎：OCR / 转写的输出格式（用假引擎，不加载模型）
# --------------------------------------------------------------------------


class _FakeOcrResult:
    """引擎输出替身：真实 RapidOCR 有 txts / scores / boxes 三份并行列表。"""

    def __init__(
        self,
        txts: list[str],
        scores: list[float] | None = None,
        boxes: list[list[list[float]]] | None = None,
    ) -> None:
        self.txts = txts
        self.scores = scores
        self.boxes = boxes


class _Segment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _Info:
    def __init__(self, duration: float, language: str = "zh") -> None:
        self.duration = duration
        self.language = language


class _FakeWhisper:
    def __init__(self, segments: list[_Segment], duration: float = 12.0) -> None:
        self._segments = segments
        self._duration = duration
        self.kwargs: dict[str, Any] = {}

    def transcribe(self, source: Any, **kwargs: Any) -> tuple[list[_Segment], _Info]:
        self.kwargs = kwargs
        return list(self._segments), _Info(self._duration)


def _recognizer(**overrides: Any) -> MediaRecognizer:
    settings = Settings(**overrides)
    return MediaRecognizer(settings)


def test_ocr_joins_lines_and_reports_meta():
    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(["第一行文字", "  ", "第二行文字"])
    result = engine.ocr(_png_bytes((900, 400)))
    assert result.text == "第一行文字\n第二行文字"
    assert result.meta["lines"] == 2
    # 尺寸要如实上报：识别不准时，用户第一个要确认的就是「这张图多大」
    assert result.meta["size"] == [900, 400]
    assert result.meta["scaled"] is False


def test_ocr_without_text_is_a_non_retryable_failure():
    """纯照片不是故障：重试一百次也没有字，提示要说清原因。"""
    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult([])
    with pytest.raises(MediaError) as err:
        engine.ocr(_png_bytes((900, 400)))
    assert err.value.retryable is False
    assert "没有识别到文字" in err.value.message


def test_transcribe_prefixes_timestamps_and_asks_for_zh():
    engine = _recognizer(asr_language="zh")
    whisper = _FakeWhisper(
        [_Segment(0.0, 2.0, " 大家好 "), _Segment(65.0, 68.0, "进入第二项议题")],
        duration=68.4,
    )
    engine._asr = whisper
    result = engine.transcribe(b"fake")
    assert result.text.split("\n") == [
        "[00:00] 大家好",
        "[01:05] 进入第二项议题",
    ]
    meta = result.meta
    assert meta["segments"] == 2
    assert meta["duration"] == 68.4
    # VAD 必须开：静音段会被模型「幻想」出句子
    assert whisper.kwargs["vad_filter"] is True
    assert whisper.kwargs["language"] == "zh"
    # 中文要给前置提示（让模型走普通话、带标点），但必须短：whisper 把 prompt
    # 当「前文」续写，长指令会被整句复读进正文第一行
    prompt = whisper.kwargs["initial_prompt"]
    assert "普通话" in prompt
    assert len(prompt) <= 20


def test_transcribe_leaves_other_languages_alone():
    """英文会议不该被塞中文提示（会把词带偏），也不做繁简转换。"""
    engine = _recognizer(asr_language="en")
    whisper = _FakeWhisper([_Segment(0.0, 2.0, " hello team")], duration=2.0)
    engine._asr = whisper
    result = engine.transcribe(b"fake")
    assert "initial_prompt" not in whisper.kwargs
    assert result.text == "[00:00] hello team"


def test_traditional_chinese_is_converted_to_simplified():
    """whisper 对中文经常吐繁体：纪要里跳出「週／壓／張」必须转成简体。"""
    pytest.importorskip("opencc")
    from app.services.media_service import _to_simplified

    assert _to_simplified("下週一完成壓測報告，張偉跟進") == "下周一完成压测报告，张伟跟进"
    # 已经是简体的原样返回（不能把「干」「面」这类多义字改坏）
    assert _to_simplified("本周完成 3 项") == "本周完成 3 项"


def test_simplify_degrades_gracefully_without_opencc(monkeypatch: pytest.MonkeyPatch):
    """没装 opencc 时不能因为少一个可选包让整段转写失败。"""
    import app.services.media_service as media

    monkeypatch.setattr(media, "_SIMPLIFIER", False)
    assert media._to_simplified("壓測報告") == "壓測報告"


def test_transcribe_truncates_beyond_configured_minutes():
    """两小时的全员会不能把整段文字塞进提示词（成本与超时）。"""
    engine = _recognizer(asr_max_minutes=1)
    engine._asr = _FakeWhisper(
        [_Segment(0.0, 5.0, "前段"), _Segment(70.0, 75.0, "超出上限")],
        duration=75.0,
    )
    result = engine.transcribe(b"fake")
    assert "超出上限" not in result.text
    assert "只转写了前 1 分钟" in result.text
    assert result.meta["truncated"] is True


def test_transcribe_silence_raises_retryable_message():
    engine = _recognizer()
    engine._asr = _FakeWhisper([_Segment(0.0, 1.0, "   ")], duration=1.0)
    with pytest.raises(MediaError) as err:
        engine.transcribe(b"fake")
    assert "没有识别到说话内容" in err.value.message


def test_transcribe_wraps_engine_crash():
    """底层解码失败要变成一句人话，而不是把 traceback 甩给用户。"""

    class _Broken:
        def transcribe(self, source: Any, **kwargs: Any) -> Any:
            raise RuntimeError("decode error")

    engine = _recognizer()
    engine._asr = _Broken()
    with pytest.raises(MediaError) as err:
        engine.transcribe(b"fake")
    assert "转写失败" in err.value.message


def test_capabilities_tell_the_truth_about_installed_engines():
    caps = _recognizer(asr_model="small", asr_max_minutes=30).capabilities()
    assert set(caps) == {
        "ocr",
        "ocr_engine",
        "ocr_engine_configured",
        "ocr_engines",
        "asr",
        "asr_model",
        "asr_language",
        "asr_endpoint",
        "max_minutes",
        "ocr_max_side",
        "ocr_min_score",
        "ocr_lang",
        "ocr_textline_orientation",
        "ocr_mkldnn",
        "hotword_limit",
        "people",
        "proper_nouns",
        "proofread",
        "simplify",
    }
    assert caps["asr_model"] == "small"
    assert caps["max_minutes"] == 30
    # 识别率的两个旋钮要能看到当前值，否则「调了没生效」根本无从判断
    assert caps["ocr_max_side"] > 0
    assert 0 <= caps["ocr_min_score"] < 1
    # 「用哪家引擎」必须能查：Paddle 装没装、现在实际跑的是谁，界面上要能说清
    assert caps["ocr_engine_configured"] in ("auto", "paddle", "rapid")
    assert set(caps["ocr_engines"]) == {"paddle", "rapid"}
    assert caps["ocr"] == caps["ocr_engines"][caps["ocr_engine"] or "rapid"]
    assert isinstance(caps["ocr"], bool)
    # oneDNN 默认关：Paddle 3.3 在部分 Windows CPU 上开着它推理必崩，
    # 这个值要能在健康检查里看到，否则「图片识别失败」只能靠猜
    assert caps["ocr_mkldnn"] is False
    assert isinstance(caps["simplify"], bool)
    # 同音字校对默认开：这是「改了就改内容」的一步，得能在健康检查里看见
    assert caps["proofread"] is True
    assert caps["hotword_limit"] > 0
    # 人名与专名的自动学习默认开着：它们从素材里学，不额外发给任何外部服务
    assert caps["people"] > 0
    assert caps["proper_nouns"] > 0


# --------------------------------------------------------------------------
# 5. 落库与时序：上传 →（后台识别）→ 可用
# --------------------------------------------------------------------------


def test_image_upload_returns_processing_then_ready(tmp_path: Path):
    media = _FakeMedia(text="截图里的三行文字\n第二行\n第三行")
    service, artifacts = _service(tmp_path, media)

    result = service.upload("th_1", "周会截图.png", _png_bytes())
    # 上传必须立刻返回：真机上识别一张截图要几秒，同步等会把请求挂死
    assert result["status"] == "processing"
    assert result["parsed"] is False
    assert result["media"]["kind"] == KIND_IMAGE
    assert result["media"]["label"] == "图片"
    # 此时素材还发不出去（文字还没出来）
    assert media.calls == [] or media.calls == ["ocr"]

    service.wait_for_recognition(timeout=10)
    stored = artifacts.items[result["artifact_id"]]
    assert stored.extra["media"]["status"] == "ready"
    assert stored.extra["parsed"] is True
    assert stored.extra["chars"] == count_chars("截图里的三行文字\n第二行\n第三行")
    assert "截图里的三行" in stored.extra["text_preview"]
    assert Path(stored.extra["text_path"]).read_text(encoding="utf-8").startswith("截图里的三行")


def test_audio_failure_is_marked_retryable_then_retry_recovers(tmp_path: Path):
    """模型没下下来不是数据问题：用户点一次「重试」就该继续，不用删了重传。"""
    failing = _FakeMedia(error=MediaError("语音识别模型（base）加载失败：timeout", retryable=True))
    service, artifacts = _service(tmp_path, failing)

    result = service.upload("th_1", "会议录音.wav", _wav_bytes())
    service.wait_for_recognition(timeout=10)
    stored = artifacts.items[result["artifact_id"]]
    assert stored.extra["media"]["status"] == "failed"
    assert stored.extra["media"]["retryable"] is True
    assert "加载失败" in stored.extra["media"]["error"]

    # 换成能跑通的引擎再点重试
    service.media = _FakeMedia(text="[00:00] 会议开始了")
    retried = service.retry_recognition(result["artifact_id"])
    assert retried["status"] == "processing"
    service.wait_for_recognition(timeout=10)
    stored = artifacts.items[result["artifact_id"]]
    assert stored.extra["media"]["status"] == "ready"
    assert "error" not in stored.extra["media"]
    assert stored.extra["chars"] == count_chars("[00:00] 会议开始了")


def test_retry_rejects_non_media_and_running_jobs(tmp_path: Path):
    service, artifacts = _service(tmp_path, _FakeMedia(text="x"))
    # 文档没有「识别」这一步
    doc = service.upload("th_1", "周报.txt", "本周完成 3 项。".encode())
    with pytest.raises(Exception) as err:
        service.retry_recognition(doc["artifact_id"])
    assert "不需要识别" in str(err.value)

    # 正在识别时再点重试：重复入队只会白跑一遍同一个文件
    image = service.upload("th_1", "截图.png", _png_bytes())
    service.wait_for_recognition(timeout=10)
    artifacts.items[image["artifact_id"]].extra["media"]["status"] = "processing"
    with pytest.raises(Exception) as err:
        service.retry_recognition(image["artifact_id"])
    assert "正在识别中" in str(err.value)


def test_retryable_marker_only_appears_when_it_really_failed(tmp_path: Path):
    """「可重试」只对失败有意义：识别中/已可用还标着它，界面会摆一个没用的按钮。"""
    ok = _FakeMedia(text="识别出来的字")
    service, artifacts = _service(tmp_path, ok)
    result = service.upload("th_1", "截图.png", _png_bytes())
    assert "retryable" not in (result["media"] or {})

    failable = _FakeMedia(error=MediaError("模型加载失败", retryable=True))
    service.media = failable
    bad = service.upload("th_1", "录音.wav", _wav_bytes())
    service.wait_for_recognition(timeout=10)
    media = artifacts.items[bad["artifact_id"]].extra["media"]
    assert media["status"] == "failed"
    assert media["retryable"] is True

    # 点了重试：回到识别中，「可重试」随之收掉
    service.media = _FakeMedia(text="重试成功")
    retried = service.retry_recognition(bad["artifact_id"])
    assert retried["status"] == "processing"
    assert "retryable" not in retried["media"]
    service.wait_for_recognition(timeout=10)


def test_list_files_exposes_status_for_polling(tmp_path: Path):
    service, _ = _service(tmp_path, _FakeMedia(text="识别出来的字"))
    result = service.upload("th_1", "截图.png", _png_bytes())
    listing = service.list_files("th_1")
    assert [item["file_id"] for item in listing] == [result["artifact_id"]]
    assert listing[0]["status"] in {"processing", "ready"}
    assert listing[0]["media"]["label"] == "图片"

    service.wait_for_recognition(timeout=10)
    listing = service.list_files("th_1")
    assert listing[0]["status"] == "ready"
    assert listing[0]["chars"] == count_chars("识别出来的字")


def test_media_upload_uses_the_bigger_size_budget(tmp_path: Path):
    """会议录音动辄几百兆：按文档那档 20MB 拦，用户永远传不进来。

    两档上限用「0MB 文档档 + 200MB 媒体档」区分：同一个服务里，文档被拒、录音
    放行，说明真按类别取了不同预算，而不是共用同一个数。
    """
    service, _ = _service(tmp_path, _FakeMedia(text="x"))
    service.settings = Settings(max_upload_mb=0, max_media_mb=200)

    result = service.upload("th_1", "会议录音.wav", _wav_bytes())
    assert result["media"]["kind"] == KIND_AUDIO
    service.wait_for_recognition(timeout=10)

    with pytest.raises(Exception) as err:
        service.upload("th_1", "周报.txt", "正文".encode())
    assert "超过 0MB" in str(err.value)


def test_update_extra_persists_nested_media_status(tmp_path: Path):
    """识别在线程里只改 extra 一块 JSON：真仓储必须写得下去。

    SQLAlchemy 默认不追踪 dict 的原地修改，所以 `update_extra` 整块替换而不是
    `extra["media"]["status"] = ...`——这里用真 SQLite 钉住，避免「内存里变了、
    库里没变」，用户看到永远停在「识别中」。
    """
    engine = create_database_engine(f"sqlite:///{tmp_path / 'extra.db'}")
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    repo = SqlArtifactRepository(factory)
    repo.add(
        Artifact(
            id="ar_1",
            thread_id="th_1",
            type="upload",
            filename="截图.png",
            path="x.png",
            size=10,
            sha256="x",
            created_at="2026-11-01T00:00:00+08:00",
            extra={
                "ext": "png",
                "parsed": False,
                "media": {"kind": "image", "status": "processing"},
            },
        )
    )
    repo.update_extra(
        "ar_1",
        {"ext": "png", "parsed": True, "chars": 42, "media": {"kind": "image", "status": "ready"}},
    )

    again = repo.get("ar_1")
    assert again is not None
    assert again.extra["media"]["status"] == "ready"
    assert again.extra["chars"] == 42
    assert again.extra["parsed"] is True


# --------------------------------------------------------------------------
# 6. 识别没完不许发任务
# --------------------------------------------------------------------------


def _run_service(artifacts: _FakeArtifacts, tmp_path: Path) -> RunService:
    """只装配 validate_attachments 需要的那一层（真 RunService 太重）。"""
    service = object.__new__(RunService)
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'db.sqlite'}")
    service.settings = settings
    service.conversation = ConversationService(
        settings,
        _FakeMessages(),  # type: ignore[arg-type]
        artifacts,  # type: ignore[arg-type]
    )
    return service


class _FakeMessages:
    def list_by_thread(self, thread_id: str, include_run_summary: bool = True) -> list[Any]:
        return []

    def add(self, message: Any) -> Any:
        return message


def test_sending_while_recognizing_is_blocked(tmp_path: Path):
    """识别中发出去，模型只看得到文件名，会凭空编一份会议纪要。"""
    artifacts = _FakeArtifacts()
    artifacts.add(
        Artifact(
            id="ar_img",
            thread_id="th_1",
            type="upload",
            filename="周会截图.png",
            path="x.png",
            size=10,
            sha256="x",
            created_at="2026-11-01T00:00:00+08:00",
            extra={
                "ext": "png",
                "chars": 0,
                "parsed": False,
                "media": {"kind": "image", "status": "processing"},
            },
        )
    )
    service = _run_service(artifacts, tmp_path)
    with pytest.raises(Exception) as err:
        service.validate_attachments("th_1", ["ar_img"])
    assert "还在识别中" in str(err.value)
    assert "周会截图.png" in str(err.value)

    # 识别完成后放行
    artifacts.items["ar_img"].extra["media"]["status"] = "ready"
    artifacts.items["ar_img"].extra["parsed"] = True
    service.validate_attachments("th_1", ["ar_img"])


def test_unknown_attachment_still_reported_before_pending(tmp_path: Path):
    """拼错 id 与「识别中」是两回事：前者是错误，后者只是等一下。"""
    artifacts = _FakeArtifacts()
    service = _run_service(artifacts, tmp_path)
    with pytest.raises(Exception) as err:
        service.validate_attachments("th_1", ["ar_missing"])
    assert "不属于该会话" in str(err.value)


# --------------------------------------------------------------------------
# 5. 图片 OCR 的预处理与结果整理（假引擎，不加载模型）
#
# 这些是「识别率莫名下降」的真正来源：照片躺倒了、透明底糊成黑块、4000px 原图
# 跑十几秒、低置信度乱码混进正文。都发生在调用引擎之前或之后，能脱离模型验。
# --------------------------------------------------------------------------


def _box(x: float, y: float, w: float = 100.0, h: float = 20.0) -> list[list[float]]:
    """一个四点标注框（左上 / 右上 / 右下 / 左下）。"""
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_ocr_reads_blocks_in_visual_order():
    """引擎按检测顺序返回，多栏界面会左右穿插：要按位置重排成「先上后下、先左后右」。"""
    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(
        ["第二行内容", "82%", "华东区完成"],
        scores=[0.9, 0.9, 0.9],
        boxes=[_box(20, 120), _box(180, 40), _box(20, 40)],
    )
    result = engine.ocr(_png_bytes((900, 400)))
    assert result.text.split("\n") == ["华东区完成82%", "第二行内容"]


def test_ocr_drops_low_confidence_blocks():
    """反光、遮挡处模型会吐乱码：宁可少一行，也别让模型把乱码当结论引用。"""
    engine = _recognizer(ocr_min_score=0.5)
    engine._ocr = lambda data: _FakeOcrResult(
        ["季度交付进度", "洍乂亂碼"],
        scores=[0.97, 0.21],
        boxes=[_box(10, 10), _box(10, 60)],
    )
    result = engine.ocr(_png_bytes((900, 400)))
    assert result.text == "季度交付进度"
    assert result.meta["dropped"] == 1
    assert result.meta["score"] == 0.97


def test_ocr_keeps_long_block_below_score():
    """长句里个别字没认准会把平均分拉到线下：文字是对的，整块扔了就是「少一行」。"""
    engine = _recognizer(ocr_min_score=0.5)
    engine._ocr = lambda data: _FakeOcrResult(
        ["三季度华东区完成率是百分之八十二", "洍乂亂碼"],
        scores=[0.45, 0.21],
        boxes=[_box(10, 10, 300), _box(10, 60)],
    )
    result = engine.ocr(_png_bytes((900, 400)))
    assert "三季度华东区完成率是百分之八十二" in result.text
    assert "洍乂亂碼" not in result.text


def test_ocr_keeps_table_rows_with_column_separator():
    """表格每行都在同一位置断开才叫列缝：认出来就按行列，不能串成一句话。"""
    engine = _recognizer()
    cells = [
        ("名称", 20),
        ("数量", 200),
        ("金额", 340),
        ("华东区", 20),
        ("82", 200),
        ("1200", 340),
        ("华南区", 20),
        ("75", 200),
        ("980", 340),
    ]
    engine._ocr = lambda data: _FakeOcrResult(
        [text for text, _ in cells],
        scores=[0.95] * len(cells),
        boxes=[_box(x, 40 + 40 * (i // 3), 60) for i, (_, x) in enumerate(cells)],
    )
    result = engine.ocr(_png_bytes((900, 400)))
    # 三行三列 = 表格：输出 markdown 表，第一行当表头
    lines = result.text.split("\n")
    assert lines[0].startswith("（以下是表格：3 列 × 3 行")
    assert lines[2] == "| 名称 | 数量 | 金额 |"
    assert lines[3] == "| --- | --- | --- |"
    assert lines[4] == "| 华东区 | 82 | 1200 |"
    assert lines[5] == "| 华南区 | 75 | 980 |"
    assert result.meta["shape"] == "table"


def _grid_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith("|")]


def test_ocr_table_keeps_empty_cells_so_columns_do_not_shift():
    """**空格子必须占位**。

    线上故障：一张课表上「周三没课」，流水式输出把这一格整个丢了，下游按顺序往
    表格里填，周四、周五的课就整体左移一格（周五的课被填到周一）。所以表格要么
    还原成带 `—` 的矩阵，要么就别声称自己是表格。
    """
    engine = _recognizer()
    # 三列三行，中间一列第二、三行是空的（只有标题行有字）
    cells = [
        ("时间", 20, 40),
        ("周一", 200, 40),
        ("周三", 380, 40),
        ("8:00", 20, 90),
        ("语文", 200, 90),
        ("9:00", 20, 140),
        ("语文", 200, 140),
    ]
    engine._ocr = lambda data: _FakeOcrResult(
        [text for text, _, _ in cells],
        scores=[0.95] * len(cells),
        boxes=[_box(x, y, 60) for _, x, y in cells],
    )
    result = engine.ocr(_png_bytes((900, 400)))
    rows = _grid_lines(result.text)
    assert rows[0] == "| 时间 | 周一 | 周三 |"
    # 第二行：周三那格是空的，必须留出「—」，否则会被当成只有两列
    assert rows[2] == "| 8:00 | 语文 | — |"
    assert rows[3] == "| 9:00 | 语文 | — |"
    assert all(row.count("|") == 4 for row in rows)


def test_ocr_table_keeps_wrapped_lines_in_the_same_column():
    """一格折成两行时，两行都要落在**同一列**，也不能把隔壁列的内容挤走。

    行方向故意不合并（哪几行属于同一格，靠文字坐标判不出来），但列必须稳——
    折行挤到隔壁列，就是「周五的课填到周一」那类错误的另一种长相。
    """
    engine = _recognizer()
    cells = [
        ("时间", 20, 40),
        ("周一", 200, 40),
        ("周三", 380, 40),
        ("8:00", 20, 90),
        ("移动应用服务器", 200, 80),
        ("编程 卢欣欣", 200, 104),
        ("9:00", 20, 140),
        ("物理", 380, 140),
    ]
    engine._ocr = lambda data: _FakeOcrResult(
        [text for text, _, _ in cells],
        scores=[0.95] * len(cells),
        boxes=[_box(x, y, 60) for _, x, y in cells],
    )
    result = engine.ocr(_png_bytes((900, 400)))
    rows = _grid_lines(result.text)
    assert rows[0] == "| 时间 | 周一 | 周三 |"
    # 折开的两段都在第二列（周一），没有一段跑到周三列去
    assert "移动应用服务器" in rows[2].split("|")[2]
    assert "编程 卢欣欣" in rows[3].split("|")[2]
    assert rows[2].split("|")[3].strip() == "—"
    assert rows[3].split("|")[3].strip() == "—"
    assert "物理" in rows[4]


def test_ocr_all_low_confidence_says_blurry_not_no_text():
    """「有字但认不出」和「图里没字」是两种原因，提示不能混着说。"""
    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(["洍乂"], scores=[0.1], boxes=[_box(10, 10)])
    with pytest.raises(MediaError) as err:
        engine.ocr(_png_bytes((900, 400)))
    assert "模糊" in err.value.message
    assert err.value.retryable is False


def test_ocr_scales_down_huge_photo_before_engine():
    """手机原图 4000px 宽直接送检测要十几秒，缩到上限以内又快又准。"""
    received: dict[str, Any] = {}

    def fake(data: bytes) -> _FakeOcrResult:
        received["image"] = Image.open(io.BytesIO(data))
        return _FakeOcrResult(["文字"])

    engine = _recognizer(ocr_max_side=1200)
    engine._ocr = fake
    result = engine.ocr(_png_bytes((4000, 2400)))
    assert received["image"].width == 1200
    # 原始尺寸要留下来：用户判断「是不是传错图」靠它
    assert result.meta["size"] == [4000, 2400]
    assert result.meta["processed_size"] == [1200, 720]
    assert result.meta["scaled"] is True


def test_ocr_enlarges_tiny_screenshot():
    """微信转两遍的截图只剩 300px 宽，字挤在一起检测框落不上去。"""
    received: dict[str, Any] = {}

    def fake(data: bytes) -> _FakeOcrResult:
        received["image"] = Image.open(io.BytesIO(data))
        return _FakeOcrResult(["文字"])

    engine = _recognizer()
    engine._ocr = fake
    result = engine.ocr(_png_bytes((300, 150)))
    assert received["image"].width == 600
    assert result.meta["scaled"] is True


def test_ocr_flattens_transparency_onto_white():
    """透明底直接转 RGB 会变黑底：深色文字连同背景一起糊掉，等于白传。"""
    transparent = Image.new("RGBA", (900, 400), (0, 0, 0, 0))
    buffer = io.BytesIO()
    transparent.save(buffer, format="PNG")
    received: dict[str, Any] = {}

    def fake(data: bytes) -> _FakeOcrResult:
        received["image"] = Image.open(io.BytesIO(data))
        return _FakeOcrResult(["文字"])

    engine = _recognizer()
    engine._ocr = fake
    engine.ocr(buffer.getvalue())
    assert received["image"].mode == "RGB"
    assert received["image"].getpixel((5, 5)) == (255, 255, 255)


def test_ocr_applies_exif_orientation():
    """手机竖拍是 Orientation=6：不转过来，模型看到的是躺倒的横排字。"""
    upright = Image.new("RGB", (800, 400), (255, 255, 255))
    exif = Image.Exif()
    exif[274] = 6  # 顺时针 90°
    buffer = io.BytesIO()
    upright.save(buffer, format="JPEG", exif=exif)
    received: dict[str, Any] = {}

    def fake(data: bytes) -> _FakeOcrResult:
        received["size"] = Image.open(io.BytesIO(data)).size
        return _FakeOcrResult(["文字"])

    engine = _recognizer()
    engine._ocr = fake
    result = engine.ocr(buffer.getvalue())
    assert received["size"] == (400, 800)
    assert result.meta["size"] == [800, 400]


def test_ocr_rejects_corrupt_image_without_crashing():
    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(["x"])
    with pytest.raises(MediaError) as err:
        engine.ocr(b"not an image at all")
    assert "打不开" in err.value.message
    assert err.value.retryable is False


def test_ocr_rejects_degenerate_and_oversized_images(monkeypatch: pytest.MonkeyPatch):
    import app.services.media_service as media

    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(["x"])
    with pytest.raises(MediaError) as err:
        engine.ocr(_png_bytes((4, 4)))
    assert "几个像素" in err.value.message

    monkeypatch.setattr(media, "_MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(MediaError) as err:
        engine.ocr(_png_bytes((200, 200)))
    assert "太大" in err.value.message


def test_ocr_mentions_only_first_page_of_multipage_tiff():
    """多页 TIFF（扫描件常见）只认第一页：不说清楚，用户会以为后面没内容。"""
    pages = [Image.new("RGB", (900, 400), (255, 255, 255)) for _ in range(3)]
    buffer = io.BytesIO()
    pages[0].save(buffer, format="TIFF", save_all=True, append_images=pages[1:])
    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(["第一页内容"])
    result = engine.ocr(buffer.getvalue())
    assert "3 页 TIFF" in result.text
    assert result.meta["frames"] == 3


# --------------------------------------------------------------------------
# 6. 会议录音 / 视频：音轨探测、重复句、语种
# --------------------------------------------------------------------------

#: 一个只有视频流、没有音轨的 mp4（64×64、10 帧、1170 字节）。
#: 录屏时忘了开麦就是这个样子：不能报「模型坏了」，要说「没有音轨」。
NO_AUDIO_MP4 = base64.b64decode(
    "AAAAHGZ0eXBpc29tAAACAGlzb21pc28ybXA0MQAAAAhmcmVlAAABAm1kYXQAAAGzABAHAAAB"
    "thDAo5bfxtt/G238bbfvAACgkctv422/jbb+Ntv3AADAkctv422/jbb+Ntv3AADgkctv422/"
    "jbb+Ntv3AAABtlHgR98AAKCeAADAngAA4J4AAAG2UsBH3wAAoJ4AAMCeAADgngAAAbZT4Eff"
    "AACgngAAwJ4AAOCeAAABtlTAR98AAKCeAADAngAA4J4AAAG2VeBH3wAAoJ4AAMCeAADgngAA"
    "AbZWwEffAACgngAAwJ4AAOCeAAABtlfgR98AAKCeAADAngAA4J4AAAG2WMBH3wAAoJ4AAMCe"
    "AADgngAAAbZZ4EffAACgngAAwJ4AAOCeAAADbG1vb3YAAABsbXZoZAAAAAAAAAAAAAAAAAAA"
    "A+gAAAPoAAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAA"
    "QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAKXdHJhawAAAFx0a2hkAAAAAwAA"
    "AAAAAAAAAAAAAQAAAAAAAAPoAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAA"
    "AAAAAAAAAAAAAAAAQAAAAABAAAAAQAAAAAAAJGVkdHMAAAAcZWxzdAAAAAAAAAABAAAD6AAA"
    "AAAAAQAAAAACD21kaWEAAAAgbWRoZAAAAAAAAAAAAAAAAAAAKAAAACgAVcQAAAAAAC1oZGxy"
    "AAAAAAAAAAB2aWRlAAAAAAAAAAAAAAAAVmlkZW9IYW5kbGVyAAAAAbptaW5mAAAAFHZtaGQA"
    "AAABAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAF6c3Ri"
    "bAAAANpzdHNkAAAAAAAAAAEAAADKbXA0dgAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAABAAEAA"
    "SAAAAEgAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABj//wAAAGBl"
    "c2RzAAAAAAOAgIBPAAEABICAgEEgEQAAAAAAB9AAAAAABYCAgC8AAAGwAQAAAbWJEwAAAQAA"
    "AAEgAMSNiABVAgQIFEMAAAGyTGF2YzYxLjE5LjEwMQaAgIABAgAAABRidHJ0AAAAAAAAB9AA"
    "AAAAAAAAGHN0dHMAAAAAAAAAAQAAAAoAAAQAAAAAFHN0c3MAAAAAAAAAAQAAAAEAAAAcc3Rz"
    "YwAAAAAAAAABAAAAAQAAAAoAAAABAAAAPHN0c3oAAAAAAAAAAAAAAAoAAABGAAAAFAAAABQA"
    "AAAUAAAAFAAAABQAAAAUAAAAFAAAABQAAAAUAAAAFHN0Y28AAAAAAAAAAQAAACwAAABhdWR0"
    "YQAAAFltZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAAACxpbHN0"
    "AAAAJKl0b28AAAAcZGF0YQAAAAEAAAAATGF2ZjYxLjcuMTAw"
)


def test_video_without_audio_says_so():
    """没音轨的录屏：说明白「听不到声音」，而不是甩一句解码失败。"""
    pytest.importorskip("av")
    engine = _recognizer()
    whisper = _FakeWhisper([_Segment(0.0, 1.0, "不该走到这里")])
    engine._asr = whisper
    with pytest.raises(MediaError) as err:
        engine.transcribe(NO_AUDIO_MP4)
    assert "没有音轨" in err.value.message
    # 模型根本不该被叫起来：白跑一遍要几十秒
    assert whisper.kwargs == {}


def test_transcribe_reports_track_info_from_real_wav():
    pytest.importorskip("av")
    engine = _recognizer()
    engine._asr = _FakeWhisper([_Segment(0.0, 0.2, "大家好")], duration=99.0)
    result = engine.transcribe(_wav_bytes(0.2))
    assert result.meta["source"] == "audio"
    assert result.meta["audio_codec"] == "pcm_s16le"
    # 容器里的时长优先于解码器报的：用户看到的是「这段多长」
    assert result.meta["duration"] == 0.2


def test_transcribe_collapses_repeated_hallucination():
    """静音、掌声处模型会把同一句连着吐好几遍，纪要里不该出现复读。"""
    engine = _recognizer()
    engine._asr = _FakeWhisper(
        [
            _Segment(0.0, 1.0, "谢谢大家"),
            _Segment(1.2, 2.0, "谢谢大家"),
            _Segment(2.2, 3.0, "谢谢大家"),
            _Segment(20.0, 21.0, "谢谢大家"),  # 隔了 20 秒，可能是真的又说了一遍
        ]
    )
    result = engine.transcribe(b"fake")
    assert result.text.count("谢谢大家") == 2
    assert result.meta["repeats"] == 2


def test_transcribe_auto_language_lets_model_decide():
    """asr_language=auto：语种交给模型判断，也不塞中文前置提示。"""
    engine = _recognizer(asr_language="auto")
    whisper = _FakeWhisper([_Segment(0.0, 1.0, " hello")], duration=1.0)
    engine._asr = whisper
    engine.transcribe(b"fake")
    assert whisper.kwargs["language"] is None
    assert "initial_prompt" not in whisper.kwargs


def test_transcribe_merges_tiny_fragments():
    """whisper 会把「嗯」「对」切成 0.5 秒一段：一段一行，纪要根本没法读。"""
    engine = _recognizer(asr_language="zh")
    engine._asr = _FakeWhisper(
        [
            _Segment(0.0, 0.6, "嗯"),
            _Segment(0.6, 3.0, "我们这个方案下周再定"),
        ]
    )
    result = engine.transcribe(b"fake")
    assert result.text == "[00:00] 嗯我们这个方案下周再定"
    assert result.meta["segments"] == 1


def test_transcribe_drops_prompt_echo():
    """initial_prompt 是当「前文」续写的：首段偶尔把提示语本身吐出来，不是人说的话。"""
    engine = _recognizer(asr_language="zh")
    engine._asr = _FakeWhisper(
        [
            _Segment(0.0, 1.0, "以下是普通话会议录音"),
            _Segment(1.0, 3.0, "今天讨论交付进度"),
        ]
    )
    result = engine.transcribe(b"fake")
    assert result.text == "[00:01] 今天讨论交付进度"


def test_transcribe_vad_keeps_sentence_pauses():
    """静音阈值太短会把一句话切碎：中文句间三四百毫秒停顿很常见。"""
    engine = _recognizer(asr_language="zh")
    whisper = _FakeWhisper([_Segment(0.0, 1.0, "大家好")])
    engine._asr = whisper
    engine.transcribe(b"fake")
    assert whisper.kwargs["vad_parameters"]["min_silence_duration_ms"] >= 800


def test_transcribe_puts_hotwords_into_the_prompt():
    """热词进 prompt 才有用：模型据此在「验收 / 厌收」之间选字。"""
    engine = _recognizer(asr_language="zh")
    whisper = _FakeWhisper([_Segment(0.0, 1.0, "大家好")])
    engine._asr = whisper
    result = engine.transcribe(b"fake", hotwords=["验收", "回款"])
    prompt = whisper.kwargs["initial_prompt"]
    assert "验收" in prompt and "回款" in prompt
    # 记下来才能诊断「当时到底给了哪些词」
    assert result.meta["hotwords"] == ["验收", "回款"]


def test_transcribe_ignores_hotwords_for_other_languages():
    """英文会议塞中文词只会把输出带偏。"""
    engine = _recognizer(asr_language="en")
    whisper = _FakeWhisper([_Segment(0.0, 1.0, " hello")])
    engine._asr = whisper
    result = engine.transcribe(b"fake", hotwords=["验收"])
    assert "initial_prompt" not in whisper.kwargs
    assert "hotwords" not in result.meta


def test_hotwords_put_hand_written_words_before_learned_ones(tmp_path, monkeypatch):
    """手填的词（人名、黑话）必须排最前，后面才是从素材里统计出来的高频词。"""
    service, _ = _service(tmp_path, _FakeMedia(text="x"))
    service.settings.asr_hotwords = "张伟，华东区"
    service.settings.asr_hotword_limit = 5
    monkeypatch.setattr(service, "_hotword_corpus", lambda: "回款回款回款，客户验收，验收")
    words = service._hotwords()
    assert words[:4] == ["张伟", "华东区", "回款", "验收"]


def test_hotwords_learn_people_and_models_from_materials(tmp_path, monkeypatch):
    """人名与型号不该靠手填：素材里写过一次，转写就该带上，而且要排在通用词前面。"""
    service, _ = _service(tmp_path, _FakeMedia(text="x"))
    service.settings.asr_hotword_limit = 6
    monkeypatch.setattr(
        service,
        "_hotword_corpus",
        lambda: "记录人：王芳参会：张伟、李娜\nOLED 与 DHT22 联调，DHT22 接 GPIO4。回款回款",
    )
    words = service._hotwords()
    assert words[:3] == ["王芳", "张伟", "李娜"]
    assert "DHT22" in words
    assert "回款" in words


def test_recognition_passes_hotwords_to_the_transcriber(tmp_path):
    """接线本身也要钉住：热词算出来了，但没传下去等于白算。"""
    media = _FakeMedia(text="[00:00] 大家好")
    service, _ = _service(tmp_path, media)
    service.settings.asr_hotwords = "张伟"
    service.upload("th_1", "会议录音.wav", _wav_bytes())
    service.wait_for_recognition(timeout=10)
    assert "张伟" in (media.last_hotwords or [])


# --------------------------------------------------------------------------
# 7. 会议记录（srt / vtt）解析
# --------------------------------------------------------------------------


def test_srt_merges_wrapped_subtitle_lines():
    """一条字幕被屏幕宽度切成两行，是同一句话，不能当两句引用。"""
    data = (
        "1\n00:00:00,000 --> 00:00:03,000\n我们下周一再对一次\n时间定在下午三点\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\n好，我来订会议室。\n"
    ).encode()
    assert parse_bytes(data, ".srt").split("\n") == [
        "我们下周一再对一次时间定在下午三点",
        "好，我来订会议室。",
    ]


def test_vtt_voice_tag_keeps_the_speaker():
    """谁说的对纪要是关键信息：<v 张伟> 要变成「张伟：」，不能当标签扔掉。"""
    data = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v 张伟>预算这块我来盯。\n\n"
        "00:00:03.000 --> 00:00:05.000\n<v.loud 李娜>好，我配合。\n"
    ).encode()
    assert parse_bytes(data, ".vtt").split("\n") == [
        "张伟：预算这块我来盯。",
        "李娜：好，我配合。",
    ]


def test_vtt_voice_tag_is_not_doubled():
    """台词本身已经写了「张伟：」，别再加一层前缀。"""
    data = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v 张伟>张伟：我来说。\n".encode()
    assert parse_bytes(data, ".vtt") == "张伟：我来说。"


def test_transcript_collapses_duplicate_cues():
    """有的导出工具会把同一条字幕重复导一次。"""
    data = (
        "1\n00:00:00,000 --> 00:00:02,000\n先过预算。\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\n先过预算。\n\n"
        "3\n00:00:04,000 --> 00:00:06,000\n再过排期。\n"
    ).encode()
    assert parse_bytes(data, ".srt").split("\n") == ["先过预算。", "再过排期。"]


def test_transcript_handles_bare_cr_line_endings():
    """老工具导出的 srt 只有 \\r：按 \\n 切会整段粘成一行，时间轴都认不出来。"""
    data = "1\r00:00:00,000 --> 00:00:02,000\r开会。\r\r".encode()
    assert parse_bytes(data, ".srt") == "开会。"


def test_numeric_line_inside_cue_is_kept():
    """台词里单独一行的「2026」是内容，不是 SRT 段序号。"""
    data = "1\n00:00:00,000 --> 00:00:02,000\n2026\n年度目标。\n".encode()
    assert parse_bytes(data, ".srt") == "2026年度目标。"


def test_numeric_only_cue_is_kept():
    """整条字幕就只有「2026」：这是台词，不能被当成序号吞掉。"""
    data = (
        "1\n00:00:00,000 --> 00:00:02,000\n2026\n\n2\n00:00:02,000 --> 00:00:04,000\n继续。\n"
    ).encode()
    assert parse_bytes(data, ".srt").split("\n") == ["2026", "继续。"]


def test_utf16_transcript_is_decoded_not_garbled():
    """Windows 存的字幕是 UTF-16：落到 gb18030 会「成功」解出满屏怪字还不报错。"""
    raw = VTT_SAMPLE.replace("\n", "\r\n").encode("utf-16-le")
    text = parse_bytes(raw, ".vtt")
    assert "大家好" in text
    assert "预算" in text


def test_vtt_multiline_note_block_does_not_leak():
    """NOTE 是块不是行：只跳过开头那行，第二行就成了「谁说的话」。"""
    data = "WEBVTT\n\nNOTE 这段由会议系统自动生成\n第二行说明\n\n00:00:00.000 --> 00:00:01.000\n大家早上好\n".encode()
    assert parse_bytes(data, ".vtt") == "大家早上好"


def _washed_out_png() -> bytes:
    """造一张「灰蒙蒙」的图：白底被压成 150 灰，字只剩 120 灰，动态范围只有 30。"""
    image = Image.new("RGB", (900, 400), (150, 150, 150))
    for x in range(100, 800, 16):
        for y in range(180, 220):
            image.putpixel((x, y), (120, 120, 120))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_ocr_stretches_washed_out_photo_before_engine():
    """翻拍、曝光不足的图整片发灰：不拉对比度，检测框能落上去但字连成一片。"""
    received: dict[str, Any] = {}

    def fake(data: bytes) -> _FakeOcrResult:
        received["range"] = Image.open(io.BytesIO(data)).convert("L").getextrema()
        return _FakeOcrResult(["文字"])

    engine = _recognizer()
    engine._ocr = fake
    result = engine.ocr(_washed_out_png())

    assert result.meta.get("enhanced") is True
    low, high = received["range"]
    # 原来是 120~150（跨度 30），拉过之后要撑开到接近满量程
    assert high - low > 96


def test_ocr_leaves_normal_screenshot_alone():
    """白底黑字的截图不该被「增强」：动了只会让细笔画黏在一起。"""
    image = Image.new("RGB", (900, 400), (255, 255, 255))
    for x in range(80, 820, 12):
        for y in range(180, 220):
            image.putpixel((x, y), (10, 10, 10))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(["文字"])
    result = engine.ocr(buffer.getvalue())
    assert "enhanced" not in result.meta


def test_ocr_retries_sideways_photo_and_reports_rotation():
    """手机横着拍的纸：正着认出来是一堆低分乱码，转 90° 才对。"""
    sizes: list[tuple[int, int]] = []

    def fake(data: bytes) -> _FakeOcrResult:
        sizes.append(Image.open(io.BytesIO(data)).size)
        if len(sizes) == 1:
            # 躺倒时模型会「自信地认错」，给一堆低分块
            return _FakeOcrResult(
                ["洍乂", "匕丂", "匚凵"],
                scores=[0.2, 0.21, 0.19],
                boxes=[_box(20, 20), _box(20, 60), _box(20, 100)],
            )
        return _FakeOcrResult(["周一 语文 数学"], scores=[0.95], boxes=[_box(20, 40, 300.0, 40.0)])

    engine = _recognizer()
    engine._ocr = fake
    result = engine.ocr(_png_bytes((900, 400)))

    assert "周一 语文 数学" in result.text
    assert result.meta["rotated"] == 90
    # 转对了就停：不再白试 270°
    assert len(sizes) == 2
    assert sizes[1] == (400, 900)


def test_ocr_does_not_rotate_when_page_is_simply_blank():
    """图里一个字都没有时不该转三遍：那是纯照片，转 270° 也一样没字，只白等三倍时间。"""
    calls: list[int] = []

    def fake(data: bytes) -> _FakeOcrResult:
        calls.append(1)
        return _FakeOcrResult([])

    engine = _recognizer()
    engine._ocr = fake
    with pytest.raises(MediaError) as err:
        engine.ocr(_png_bytes((900, 400)))
    assert "没有识别到文字" in err.value.message
    assert len(calls) == 1


def test_ocr_reports_which_engine_did_the_work():
    """识别结果不对时，第一句要问的是「当时用的哪家引擎」。"""
    engine = _recognizer()
    engine._ocr = lambda data: _FakeOcrResult(["文字"])
    assert engine.ocr(_png_bytes((900, 400))).meta["engine"] == "custom"

    class _Named:
        name = "paddle"

        def recognize(self, image: bytes) -> list[Any]:
            from app.services.ocr_engine import OcrLine

            return [OcrLine(text="文字", score=0.9, left=0, top=0, right=40, bottom=20)]

    engine._ocr = _Named()
    assert engine.ocr(_png_bytes((900, 400))).meta["engine"] == "paddle"


def test_ocr_works_end_to_end_through_paddle_engine(monkeypatch: pytest.MonkeyPatch):
    """把 PaddleOCR 接进识别链路跑一遍：写临时文件 → predict → 归一化 → 分栏。

    本机没装 paddlepaddle（装它要 100MB + 首次联网下模型），所以这里用假模块
    验证**接线本身**对不对：真引擎接错了是 TypeError，接对了才有资格谈精度。
    """
    import sys
    import types

    from app.services import ocr_engine

    class _Pipeline:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def predict(self, path: str) -> list[dict[str, Any]]:
            return [
                {
                    "rec_texts": ["姓名", "部门", "张伟", "华东大区"],
                    "rec_scores": [0.99, 0.98, 0.97, 0.96],
                    "rec_boxes": [
                        [10, 10, 60, 30],
                        [120, 10, 180, 30],
                        [10, 50, 60, 70],
                        [120, 50, 220, 70],
                    ],
                }
            ]

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = _Pipeline  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", module)

    engine = _recognizer()
    engine._ocr = ocr_engine.PaddleOcrEngine(engine.settings)
    result = engine.ocr(_png_bytes((900, 400)))

    assert result.meta["engine"] == "paddle"
    # 两行两列：列缝纵向贯穿 → 按 ` | ` 连成一行一条
    assert result.text.split("\n") == ["姓名 | 部门", "张伟 | 华东大区"]
    assert result.meta["lines"] == 2
