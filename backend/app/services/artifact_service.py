"""产物/素材服务：多文件上传校验、解析、产物登记、分页、软删入回收站、预览。"""

from __future__ import annotations

import html
import mimetypes
import os
import platform
import re
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.security import (
    SUPPORTED_UPLOAD_EXTS,
    UploadLimits,
    UploadValidationError,
    safe_filename,
    validate_upload,
)
from ..core.utils import count_chars, new_id, now_iso, sha256_bytes
from ..domain.entities import Artifact
from ..domain.enums import ArtifactType
from ..domain.media import (
    KIND_IMAGE,
    KIND_TRANSCRIPT,
    media_kind,
    media_label,
    needs_recognition,
)
from ..domain.ports import ArtifactRepository, FileParser, FileStorage, ThreadRepository
from ..infra.parsing import ParseFailure
from . import asr_lexicon, asr_proofread
from .media_service import MediaError, MediaRecognizer, RecognitionResult

# 预览页排版：以前只有一行 <h1> + 一整块 <pre>，字号巨大又没行距，看着很难读。
_PREVIEW_STYLE = (
    "font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;"
    "line-height:1.75;color:#1f2937;padding:24px 28px;max-width:820px;margin:0 auto;"
    "background:#fff;font-size:15px;"
)
_PREVIEW_HEADER_STYLE = "margin:0 0 18px;border-bottom:1px solid #eef0f4;padding-bottom:12px;"
_PREVIEW_TITLE_STYLE = "margin:0;font-size:19px;font-weight:600;color:#111827;line-height:1.5;"
_PREVIEW_META_STYLE = "margin:4px 0 0;font-size:12px;color:#98a2b3;letter-spacing:.02em;"
_PREVIEW_BODY_STYLE = "white-space:pre-wrap;word-break:break-word;font-size:15px;line-height:1.85;"
_PREVIEW_SHEET_STYLE = "margin:18px 0 8px;font-size:14px;font-weight:600;color:#374151;"
_CODE_STYLE = (
    "background:#f7f8fa;border:1px solid #eef0f4;border-radius:6px;padding:10px 12px;"
    "font-size:13px;overflow-x:auto;white-space:pre-wrap;"
)
_LIST_STYLE = "margin:6px 0;padding-left:20px;"
_TABLE_STYLE = "border-collapse:collapse;font-size:13px;min-width:100%;"
_CELL_STYLE = (
    "border:1px solid #e5e7eb;padding:4px 8px;text-align:left;"
    "white-space:nowrap;max-width:280px;overflow:hidden;text-overflow:ellipsis;"
)


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _inline_md(text: str) -> str:
    """行内 Markdown：粗体 / 行内代码 / 链接，其余按纯文本转义。"""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noreferrer">\1</a>',
        escaped,
    )
    return escaped


def _open_with_system(path: Path) -> tuple[bool, str | None]:
    """用系统文件关联打开文件：Windows 上由默认程序决定（装了 WPS 通常就是 WPS）。"""
    try:
        if platform.system() == "Windows":
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                return False, "当前运行环境不支持打开本地文件"
            startfile(str(path))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603, S607 - 固定命令 + 已校验路径
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607
    except Exception as exc:  # 任何失败都回给界面
        return False, str(exc)
    return True, None


@dataclass(frozen=True)
class UploadInput:
    filename: str
    content_type: str | None
    data: bytes


#: 识别线程池：单 worker 就够（一个用户不会同时传十段录音），也让 OCR / ASR 排着跑，
#: 不会十段录音一起抢 CPU 把整机拖死。进程内共用，所以放在模块级。
_RECOGNIZE_POOL: ThreadPoolExecutor | None = None
_RECOGNIZE_POOL_LOCK = threading.Lock()


def _recognize_pool() -> ThreadPoolExecutor:
    global _RECOGNIZE_POOL
    with _RECOGNIZE_POOL_LOCK:
        if _RECOGNIZE_POOL is None:
            _RECOGNIZE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-recog")
        return _RECOGNIZE_POOL


#: 学热词时最多读几份素材、多少字。扫全库没必要：最近这些足够代表用户当前
#: 在做什么，读太多只是白花 IO。
_HOTWORD_SOURCES = 60
_HOTWORD_CORPUS_CHARS = 200_000

#: 热词快照的存活时间。每传一段录音就重扫一遍素材库，代价是几 MB 的 IO；
#: 五分钟内的转写用同一份就够 —— 期间新加入的词最多晚一次生效。
_HOTWORD_TTL_SECONDS = 300


class ArtifactService:
    def __init__(
        self,
        artifacts: ArtifactRepository,
        threads: ThreadRepository,
        storage: FileStorage,
        parser: FileParser,
        settings: Settings,
        media: MediaRecognizer | None = None,
    ):
        self.artifacts = artifacts
        self.threads = threads
        self.storage = storage
        self.parser = parser
        self.settings = settings
        self.media = media or MediaRecognizer(settings)
        #: 排着队等识别的任务，测试与优雅退出时可以等它们跑完
        self._pending: set[Future[Any]] = set()
        self._pending_lock = threading.Lock()
        #: 热词快照：(取到的时间, 词表)
        self._hotwords_cache: tuple[float, list[str]] = (0.0, [])

    # ---------- 上传 ----------
    def upload(self, thread_id: str, filename: str, data: bytes) -> dict[str, Any]:
        results = self.upload_many(
            thread_id,
            [UploadInput(filename=filename, content_type=None, data=data)],
        )
        return results[0]

    def upload_many(self, thread_id: str, uploads: list[UploadInput]) -> list[dict[str, Any]]:
        if self.threads.get(thread_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, f"会话不存在：{thread_id}")
        if not uploads:
            raise AppError(ErrorCode.BAD_REQUEST, "未收到文件（字段 file 或 files）")
        if len(uploads) > 10:
            raise AppError(ErrorCode.BAD_REQUEST, "单次最多上传 10 个文件")
        results = [self._upload_one(thread_id, item) for item in uploads]
        self._touch(thread_id)
        return results

    def _upload_limits(self) -> UploadLimits:
        """解析防护阈值（压缩炸弹/超大文档），来自 Settings。"""
        return UploadLimits.from_settings(self.settings)

    def _upload_one(self, thread_id: str, item: UploadInput) -> dict[str, Any]:
        safe_name = safe_filename(item.filename or "upload.bin")
        ext = Path(safe_name).suffix.lower()
        kind = media_kind(ext)
        # 录音 / 视频按另一档上限：文档 20MB 够了，一段两小时的全员会不止这个数
        is_media_file = kind is not None and kind != KIND_TRANSCRIPT
        limit_mb = self.settings.max_media_mb if is_media_file else self.settings.max_upload_mb
        max_bytes = limit_mb * 1024 * 1024
        if len(item.data) > max_bytes:
            raise AppError(
                ErrorCode.PAYLOAD_TOO_LARGE,
                f"文件 {safe_name} 超过 {limit_mb}MB 限制",
                details={"filename": safe_name, "max_mb": limit_mb},
            )
        try:
            validate_upload(safe_name, item.content_type, item.data, limits=self._upload_limits())
        except UploadValidationError as exc:
            code = (
                ErrorCode.FILE_PARSE_ERROR
                if exc.reason == "empty"
                else ErrorCode.UNSUPPORTED_FILE_TYPE
            )
            raise AppError(
                code,
                f"{safe_name}：{exc.message}",
                details={"filename": safe_name, "reason": exc.reason},
            ) from exc

        # 图片 / 录音 / 视频要跑识别，先把文件收下、立刻返回「识别中」：
        # 转写一段半小时的录音要几分钟，同步等会把上传请求挂死。
        pending_recognition = needs_recognition(kind)
        note: str | None = None
        if not pending_recognition:
            try:
                text = self.parser.parse(item.data, ext)
            except ParseFailure as exc:
                if ext in SUPPORTED_UPLOAD_EXTS:
                    # 认得的格式解析失败 = 文件坏了，这时候不该装作收下了
                    raise AppError(
                        ErrorCode.FILE_PARSE_ERROR,
                        f"{safe_name}：{exc.message}；支持类型：{', '.join(sorted(SUPPORTED_UPLOAD_EXTS))}",
                        details={"filename": safe_name},
                    ) from exc
                # 白名单外的文件：收下，但如实说清楚「文字读不出来」。
                # 拒收会让人卡在「到底能传什么」上；收下 + 一句照做的话才有下一步。
                text = ""
                note = exc.message
        else:
            text = ""

        stored_path, stored_ext = self.storage.save_upload(thread_id, safe_name, item.data)
        text_path = self.storage.save_text(stored_path, text)
        preview = text[:200]
        media_info: dict[str, Any] | None = None
        if kind is not None:
            media_info = {
                "kind": kind,
                "label": media_label(kind),
                "status": "processing" if pending_recognition else "ready",
            }
        artifact = Artifact(
            id=new_id("art"),
            thread_id=thread_id,
            type=ArtifactType.UPLOAD.value,
            filename=safe_name,
            path=str(stored_path),
            size=len(item.data),
            sha256=sha256_bytes(item.data),
            content_type=item.content_type or "application/octet-stream",
            created_at=now_iso(),
            extra={
                "chars": count_chars(text),
                "parsed": not pending_recognition and note is None,
                "ext": stored_ext.lstrip("."),
                "text_path": str(text_path),
                "text_preview": preview,
                **({"note": note} if note else {}),
                **({"media": media_info} if media_info else {}),
            },
        )
        self.artifacts.add(artifact)
        if pending_recognition:
            self._enqueue_recognition(artifact, stored_path, ext, str(kind))
        return {
            "file_id": artifact.id,
            "artifact_id": artifact.id,
            "filename": artifact.filename,
            "size": artifact.size,
            "type": stored_ext.lstrip("."),
            "ext": stored_ext.lstrip("."),
            "chars": artifact.extra["chars"],
            "parsed": not pending_recognition and note is None,
            "status": "processing" if pending_recognition else "ready",
            "note": note,
            "media": media_info,
            "text_preview": preview,
        }

    # ---------- 识别（图片 OCR / 音视频转写）----------
    def _enqueue_recognition(
        self, artifact: Artifact, stored_path: Path, ext: str, kind: str
    ) -> None:
        future = _recognize_pool().submit(self._recognize, artifact.id, stored_path, ext, kind)
        with self._pending_lock:
            self._pending.add(future)
        future.add_done_callback(self._forget_pending)

    def _forget_pending(self, future: Future[Any]) -> None:
        with self._pending_lock:
            self._pending.discard(future)

    def wait_for_recognition(self, timeout: float | None = None) -> None:
        """等排队/在跑的识别结束。给测试与优雅退出用（正常请求不等）。"""
        with self._pending_lock:
            pending = list(self._pending)
        for future in pending:
            future.result(timeout=timeout)

    def _hotwords(self) -> list[str]:
        """这次转写带哪些热词。

        四段，顺序就是优先级：

        1. 设置里**手填的**（`ASR_HOTWORDS`）—— 兜底用：少见姓的人、没写进纪要
           的客户代号。程序抽不到的，这里补。
        2. **从素材里认出来的人名** —— 「参会：张伟、李娜」和「[00:12] 张伟：」。
           模型不认识这位同事，prompt 里出现过一次，后面每一句都会往对的方向偏。
        3. **产品名 / 型号 / 内部编号** —— 这一类不该手填：型号和编号一直在变，
           记漏一个就等于没做。出现两次以上的英数串才算数。
        4. **按素材词频排过的通用词**（`rank`）—— 冷启动兜底。

        学到的部分按 TTL 缓存：每段录音都扫一遍库，几 MB 的 IO 花得不值。
        """
        now = time.monotonic()
        stamp, cached = self._hotwords_cache
        if cached and now - stamp < _HOTWORD_TTL_SECONDS:
            return cached

        custom = asr_lexicon.custom_words(str(getattr(self.settings, "asr_hotwords", "") or ""))
        limit = max(0, int(getattr(self.settings, "asr_hotword_limit", 12) or 0))
        corpus = self._hotword_corpus()
        # 手填的先占位，剩下的名额依次分给人名、专名、通用词
        room = max(0, limit - len(custom))
        people = asr_lexicon.people(
            corpus, limit=min(max(0, int(getattr(self.settings, "asr_people", 4) or 0)), room)
        )
        room -= len(people)
        nouns = asr_lexicon.proper_nouns(
            corpus, limit=min(max(0, int(getattr(self.settings, "asr_proper_nouns", 6) or 0)), room)
        )
        learned = asr_lexicon.rank(corpus, limit=max(0, room - len(nouns)))
        words = asr_lexicon.merge_words(custom, [*people, *nouns, *learned], limit=limit)
        self._hotwords_cache = (now, words)
        return words

    def _proofread(self, result: RecognitionResult, hotwords: list[str]) -> RecognitionResult:
        """转写完再让大模型挑一遍同音字。

        只对中文、且只在设置打开时做；模型只能交回「错写法 → 正确写法」的配对，
        代码侧再过等长 / 原件存在 / 次数上限三道闸（见 `asr_proofread`）。
        任何意外都原样返回 —— 校对失败是「少改几个字」，不该变成「这段录音识别失败」。
        """
        try:
            if not getattr(self.settings, "asr_proofread", True):
                return result
            if not re.search(r"[\u4e00-\u9fff]", result.text):
                return result
            fixed, pairs = asr_proofread.proofread(result.text, hotwords, settings=self.settings)
            if not pairs:
                return result
            meta = dict(result.meta or {})
            meta["corrections"] = len(pairs)
            # 留前几条给用户看：改了什么要能查，不能只报个数字
            meta["corrected"] = [f"{wrong}→{right}" for wrong, right in pairs[:5]]
            return RecognitionResult(text=fixed, meta=meta)
        except Exception:  # pragma: no cover - 校对永远不该影响识别结果
            return result

    def _hotword_corpus(self) -> str:
        """把用户已有素材的文字拼起来（限量），作为「他平时怎么说」的样本。

        任何一步失败都返回空串：热词只是锦上添花，不能因为它读不到文件就让
        整段录音识别失败。
        """
        try:
            items = self.artifacts.list(limit=_HOTWORD_SOURCES)
        except Exception:  # pragma: no cover - 仓储异常不该阻断识别
            return ""
        parts: list[str] = []
        total = 0
        for artifact in items:
            path = str((artifact.extra or {}).get("text_path") or "")
            if not path:
                continue
            try:
                text = self.storage.read_text(path)
            except (OSError, ValueError):
                continue
            parts.append(text)
            total += len(text)
            if total >= _HOTWORD_CORPUS_CHARS:
                break
        return "\n".join(parts)

    def _recognize(self, artifact_id: str, stored_path: Path, ext: str, kind: str) -> None:
        """后台线程：识别 → 写 parsed.txt → 更新状态。失败也落状态，不吞异常。"""
        try:
            data = stored_path.read_bytes()
            # 图片只认字（OCR），音频/视频只认说话（转写）：会议视频不抽画面，
            # 否则 PPT 上的字会混进会议纪要
            if kind == KIND_IMAGE:
                result = self.media.ocr(data)
            else:
                # 热词交给解码器：它听得清「yen shou」，但「验收 / 厌收」选哪个
                # 得靠语言模型，先告诉它这人平时说哪些词
                hotwords = self._hotwords()
                result = self._proofread(self.media.transcribe(data, hotwords=hotwords), hotwords)
        except MediaError as exc:
            self._mark_media(
                artifact_id, status="failed", error=exc.message, retryable=exc.retryable
            )
            return
        except Exception as exc:  # 识别组件抛的意外异常：记下来，下次可重试
            self._mark_media(
                artifact_id,
                status="failed",
                error=f"识别失败：{type(exc).__name__}: {exc}",
                retryable=True,
            )
            return

        text = (result.text or "").strip()
        if not text:
            self._mark_media(artifact_id, status="failed", error="没有识别到文字")
            return
        try:
            text_path = self.storage.save_text(stored_path, text)
        except OSError as exc:
            self._mark_media(artifact_id, status="failed", error=f"识别结果写入失败：{exc}")
            return
        self._mark_media(
            artifact_id,
            status="ready",
            text=text,
            text_path=str(text_path),
            meta=result.meta,
        )

    def _mark_media(
        self,
        artifact_id: str,
        *,
        status: str,
        text: str = "",
        text_path: str = "",
        meta: dict[str, Any] | None = None,
        error: str = "",
        retryable: bool = True,
    ) -> None:
        """把识别结果写回产物记录（后台线程里只改 extra，不动别的字段）。"""
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:  # 用户在识别期间把素材删了
            return
        extra = dict(artifact.extra or {})
        media = dict(extra.get("media") or {})
        media["status"] = status
        if error:
            media["error"] = error
            media["retryable"] = retryable
        else:
            media.pop("error", None)
            media.pop("retryable", None)
        if meta:
            media["meta"] = meta
        extra["media"] = media
        if status == "ready":
            extra["chars"] = count_chars(text)
            extra["parsed"] = True
            extra["text_preview"] = text[:200]
            extra["text_path"] = text_path
        self.artifacts.update_extra(artifact_id, extra)

    def retry_recognition(self, artifact_id: str) -> dict[str, Any]:
        """重试识别：模型没下载下来、或识别被中断时，用户不必删了重传。"""
        artifact = self.get(artifact_id)
        extra = dict(artifact.extra or {})
        media = dict(extra.get("media") or {})
        kind = str(media.get("kind") or "")
        if not needs_recognition(kind):
            raise AppError(ErrorCode.BAD_REQUEST, "这个素材不需要识别")
        if media.get("status") == "processing":
            raise AppError(ErrorCode.BAD_REQUEST, "正在识别中，稍等一下")
        media["status"] = "processing"
        media.pop("error", None)
        # 已经重新排队了，「可重试」这个标记要收掉，否则界面在识别中又摆一个重试
        media.pop("retryable", None)
        extra["media"] = media
        extra["parsed"] = False
        self.artifacts.update_extra(artifact_id, extra)
        self._enqueue_recognition(
            artifact, Path(artifact.path), Path(artifact.filename).suffix.lower(), kind
        )
        return {"artifact_id": artifact_id, "status": "processing", "media": media}

    # ---------- 查询 ----------
    def list_files(self, thread_id: str) -> list[dict[str, Any]]:
        if self.threads.get(thread_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, f"会话不存在：{thread_id}")
        files: list[dict[str, Any]] = []
        for artifact in self.artifacts.list(thread_id=thread_id, type=ArtifactType.UPLOAD.value):
            extra = artifact.extra or {}
            media = dict(extra.get("media") or {})
            parsed = bool(extra.get("parsed", False))
            # 「收下了但读不出文字」不是失败：文件确实在素材里，只是没有正文。
            # 把它报成 failed 会让卡片在刷新后突然变红，用户以为传丢了。
            note = extra.get("note")
            files.append(
                {
                    "file_id": artifact.id,
                    "artifact_id": artifact.id,
                    "filename": artifact.filename,
                    "size": artifact.size,
                    "type": extra.get("ext", ""),
                    "ext": extra.get("ext", ""),
                    "chars": int(extra.get("chars", 0)),
                    "parsed": parsed,
                    # 状态是给界面的真话：识别中 / 可用 / 失败（失败带原因与能否重试）
                    "status": media.get("status") or ("ready" if parsed or note else "failed"),
                    "note": note,
                    "media": media or None,
                    "text_preview": extra.get("text_preview", ""),
                    "created_at": artifact.created_at,
                }
            )
        return files

    def get(self, artifact_id: str) -> Artifact:
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            raise AppError(ErrorCode.NOT_FOUND, f"产物不存在：{artifact_id}")
        return artifact

    def metadata(self, artifact: Artifact) -> dict[str, Any]:
        extra = dict(artifact.extra or {})
        preview_path = extra.pop("preview_path", None)
        text_path = extra.pop("text_path", None)
        extra.pop("text_preview", None)
        return {
            "artifact_id": artifact.id,
            "type": artifact.type,
            "filename": artifact.filename,
            "size": artifact.size,
            "sha256": artifact.sha256,
            "content_type": artifact.content_type,
            "created_at": artifact.created_at,
            "thread_id": artifact.thread_id,
            "run_id": artifact.run_id,
            "download_url": f"/api/v1/artifacts/{artifact.id}/download",
            "preview_url": f"/api/v1/artifacts/{artifact.id}/preview",
            "extra": extra,
            # 与会话详情一致：素材名单独给一份，方便列表/右栏说明产物从哪来
            "sources": [str(name) for name in (extra.get("sources") or [])],
            "has_preview_file": bool(preview_path and self.storage.exists(str(preview_path))),
            "has_text": bool(text_path and self.storage.exists(str(text_path))),
        }

    def list_artifacts(
        self,
        thread_id: str | None = None,
        run_id: str | None = None,
        type_filter: str | None = None,
        page: int = 1,
        page_size: int = 20,
        include_uploads: bool = False,
    ) -> dict[str, Any]:
        if thread_id:
            self._ensure_thread(thread_id)
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        # 产物中心是「Agent 生成的东西」，上传素材（type=upload）默认不掺进来：
        # 两者的文件名一模一样（比如 cet4成绩.pdf），混在一起用户分不清哪个是产物。
        # 明着筛 type=upload 时照旧能查，工作台取素材走的就是这条。
        exclude_type = None if include_uploads or type_filter == "upload" else "upload"
        # 分页下推到 SQL：COUNT 取总数，LIMIT/OFFSET 只取当前页
        total = self.artifacts.count(
            thread_id=thread_id, run_id=run_id, type=type_filter, exclude_type=exclude_type
        )
        selected = self.artifacts.list(
            thread_id=thread_id,
            run_id=run_id,
            type=type_filter,
            limit=page_size,
            offset=(page - 1) * page_size,
            exclude_type=exclude_type,
        )
        return {
            "artifacts": [self.metadata(artifact) for artifact in selected],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ---------- 下载 / 预览 / 删除 ----------
    def download_target(self, artifact_id: str) -> tuple[Path, str, str]:
        artifact = self.get(artifact_id)
        path = Path(artifact.path)
        if not path.exists():
            raise AppError(ErrorCode.NOT_FOUND, "产物文件不存在（可能已被删除）")
        return path, artifact.filename, _media_type(artifact.filename, artifact.content_type)

    def preview(self, artifact_id: str) -> str:
        artifact = self.get(artifact_id)
        extra = artifact.extra or {}
        if artifact.type == ArtifactType.DOCX.value:
            preview_path = extra.get("preview_path")
            if preview_path and self.storage.exists(str(preview_path)):
                return self.storage.read_text(str(preview_path))
            return self._render_docx_preview(artifact)
        if artifact.type == ArtifactType.XLSX.value:
            return self._render_xlsx_preview(artifact)
        if artifact.type == ArtifactType.PDF.value:
            return self._render_pdf_preview(artifact)
        text_path = extra.get("text_path")
        if text_path and self.storage.exists(str(text_path)):
            text = self.storage.read_text(str(text_path))
        elif Path(artifact.path).exists():
            text = self.storage.read_text(artifact.path)
        else:
            raise AppError(ErrorCode.NOT_FOUND, "产物预览不可用（文件缺失）")
        body = (
            self._render_markdown(text) if artifact.type == "md" else self._render_plain_text(text)
        )
        return f'<article style="{_PREVIEW_STYLE}">{self._preview_header(artifact)}{body}</article>'

    def _preview_header(self, artifact: Artifact) -> str:
        return (
            f'<header style="{_PREVIEW_HEADER_STYLE}">'
            f'<h1 style="{_PREVIEW_TITLE_STYLE}">{html.escape(artifact.filename)}</h1>'
            f'<p style="{_PREVIEW_META_STYLE}">{artifact.type.upper()} · '
            f"{html.escape(_format_size(artifact.size))}</p></header>"
        )

    def _render_plain_text(self, text: str) -> str:
        """纯文本：按段落排版，保留原始换行，比一整块 <pre> 好读。"""
        return f'<div style="{_PREVIEW_BODY_STYLE}">{html.escape(text[:200_000])}</div>'

    def _render_markdown(self, text: str) -> str:
        """轻量 Markdown 渲染：标题 / 无序列表 / 粗体 / 代码块，够读文档就行。"""
        lines = text[:200_000].splitlines()
        parts: list[str] = [f'<div style="{_PREVIEW_BODY_STYLE}">']
        in_code = False
        in_list = False
        for raw in lines:
            line = raw.rstrip()
            if line.startswith("```"):
                if in_list:
                    parts.append("</ul>")
                    in_list = False
                if in_code:
                    parts.append("</code></pre>")
                else:
                    parts.append(f'<pre style="{_CODE_STYLE}"><code>')
                in_code = not in_code
                continue
            if in_code:
                parts.append(html.escape(line) + "\n")
                continue
            stripped = line.strip()
            if not stripped:
                if in_list:
                    parts.append("</ul>")
                    in_list = False
                continue
            heading = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= heading <= 4 and stripped[heading : heading + 1] == " ":
                if in_list:
                    parts.append("</ul>")
                    in_list = False
                level = min(heading + 1, 5)
                parts.append(f"<h{level}>{html.escape(stripped[heading + 1 :])}</h{level}>")
                continue
            if stripped.startswith(("- ", "* ", "+ ")):
                if not in_list:
                    parts.append(f'<ul style="{_LIST_STYLE}">')
                    in_list = True
                parts.append(f"<li>{_inline_md(stripped[2:])}</li>")
                continue
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<p>{_inline_md(stripped)}</p>")
        if in_list:
            parts.append("</ul>")
        if in_code:
            parts.append("</code></pre>")
        parts.append("</div>")
        return "".join(parts)

    def _render_xlsx_preview(self, artifact: Artifact) -> str:
        """Excel 预览：用 openpyxl 读出前若干行，渲染成 HTML 表格（只读）。"""
        path = Path(artifact.path)
        if not path.exists():
            raise AppError(ErrorCode.NOT_FOUND, "产物预览不可用（文件缺失）")
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(str(path), read_only=True, data_only=True)
        except Exception as exc:
            raise AppError(ErrorCode.FILE_PARSE_ERROR, f"Excel 预览失败：{exc}") from exc
        blocks: list[str] = [f'<article style="{_PREVIEW_STYLE}">{self._preview_header(artifact)}']
        try:
            for sheet in workbook.worksheets[:5]:
                rows = list(sheet.iter_rows(min_row=1, max_row=120, max_col=20, values_only=True))
                if not rows:
                    continue
                blocks.append(
                    f'<h2 style="{_PREVIEW_SHEET_STYLE}">{html.escape(sheet.title)}</h2>'
                    f'<div style="overflow-x:auto"><table style="{_TABLE_STYLE}"><tbody>'
                )
                for index, row in enumerate(rows):
                    tag = "th" if index == 0 else "td"
                    cells = "".join(
                        f'<{tag} style="{_CELL_STYLE}">{html.escape("" if value is None else str(value))}</{tag}>'
                        for value in row
                    )
                    blocks.append(f"<tr>{cells}</tr>")
                blocks.append("</tbody></table></div>")
        finally:
            workbook.close()
        blocks.append("</article>")
        return "".join(blocks)

    def _render_pdf_preview(self, artifact: Artifact) -> str:
        """PDF 预览：交给浏览器内置阅读器（iframe 指向原文件流）。"""
        url = f"/api/v1/artifacts/{artifact.id}/download"
        return (
            f'<article style="{_PREVIEW_STYLE}">{self._preview_header(artifact)}'
            f'<iframe src="{url}" title="{html.escape(artifact.filename)}" '
            'style="width:100%;height:70vh;border:1px solid #e5e7eb;border-radius:8px;"></iframe>'
            "</article>"
        )

    def _render_docx_preview(self, artifact: Artifact) -> str:
        path = Path(artifact.path)
        if not path.exists():
            raise AppError(ErrorCode.NOT_FOUND, "产物预览不可用（文件缺失）")
        try:
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            document = Document(str(path))
        except Exception as exc:
            raise AppError(ErrorCode.FILE_PARSE_ERROR, f"DOCX 预览失败：{exc}") from exc
        parts = [f'<article style="{_PREVIEW_STYLE}">']
        for paragraph in document.paragraphs:
            text = (paragraph.text or "").strip()
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style is not None else ""
            style = (style_name or "").lower()
            # Title 才是「文档大标题」；Heading N 是正文里的小节标题。小节标题左起，
            # 只有文首标题块（大标题 / 副标题 / 信息行）居中。
            if style.startswith("title") or style == "heading 0":
                parts.append(f'<h1 class="doc-title">{html.escape(text)}</h1>')
                continue
            if style.startswith("heading"):
                depth = 1
                digits = re.sub(r"\D", "", style)
                if digits:
                    depth = max(1, min(int(digits), 4))
                level = min(depth + 1, 5)
                # 这条兜底路径不加载 tokens.css，只能用 inline style。
                # 文件里明确写了「左对齐」的是公文那套顶格排法，照它；其余按默认居中。
                # 居中时不能再给 margin-left：先缩 1em 再居中，整行会往右偏。
                left_aligned = paragraph.alignment == WD_ALIGN_PARAGRAPH.LEFT
                align = "left" if left_aligned else "center"
                indent = f"margin-left:{depth - 1}em;" if left_aligned and depth > 1 else ""
                parts.append(
                    f'<h{level} class="doc-h{depth}" style="text-align:{align};{indent}">'
                    f"{html.escape(text)}</h{level}>"
                )
                continue
            # 正文空两格、两端对齐；副标题、图注、列表项不空、顶格——和界面预览
            # （.prose-docx）同一套规则，也和 doc_render 的 Preset.body_align 一致。
            # 权威是文件里自己存的值：生成时就把「正文两端对齐、标题块居中」写进去了，
            # 这里照抄，别再自己猜一遍——猜两遍就会出现「预览一套、Word 一套」。
            flat = style.startswith(("subtitle", "caption", "list"))
            value = paragraph.alignment
            if value == WD_ALIGN_PARAGRAPH.CENTER:
                align, indent = "center", "0"
            elif value == WD_ALIGN_PARAGRAPH.RIGHT:
                align, indent = "right", "0"
            elif value == WD_ALIGN_PARAGRAPH.LEFT:
                align, indent = "left", "0" if flat else "2em"
            else:
                align, indent = ("left", "0") if flat else ("justify", "2em")
            parts.append(
                f'<p style="margin:0 0 10px;text-align:{align};text-indent:{indent};">'
                f"{html.escape(text)}</p>"
            )
        parts.append("</article>")
        return "\n".join(parts)

    def delete(self, artifact_id: str) -> dict[str, Any]:
        """软删：文件移入 data/trash/，下载/预览立即 404；原记录保留供审计。

        同时把「原路径 → 回收站路径」的对应关系写进 `extra["trash"]`，
        这样回收站里的「恢复」才能把文件挪回原位（只靠文件名猜是不可靠的）。
        """
        artifact = self.get(artifact_id)
        extra = dict(artifact.extra or {})
        moves: list[dict[str, str]] = []
        trashed: list[str] = []
        candidates: list[str] = [artifact.path]
        for key in ("text_path", "preview_path"):
            candidate = extra.get(key)
            if candidate:
                candidates.append(str(candidate))
        for candidate in candidates:
            moved = self.storage.trash(candidate)
            if moved:
                trashed.append(moved)
                moves.append({"from": str(candidate), "to": moved})
        if moves:
            extra["trash"] = moves
        self.artifacts.soft_delete(artifact_id, now_iso(), extra)
        return {"artifact_id": artifact_id, "deleted": True, "trashed": trashed}

    def list_trash(
        self, page: int = 1, page_size: int = 20, include_uploads: bool = False
    ) -> dict[str, Any]:
        """回收站列表：只列已软删的记录，按删除时间倒序。

        同样不列上传素材——回收站是「产物」的回收站，素材只在会话里管。
        """
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        exclude_type = None if include_uploads else "upload"
        total = self.artifacts.count(deleted_only=True, exclude_type=exclude_type)
        selected = self.artifacts.list(
            limit=page_size,
            offset=(page - 1) * page_size,
            deleted_only=True,
            exclude_type=exclude_type,
        )
        items = []
        for artifact in selected:
            meta = self.metadata(artifact)
            meta["deleted_at"] = artifact.deleted_at
            meta["restorable"] = bool((artifact.extra or {}).get("trash"))
            items.append(meta)
        return {"artifacts": items, "total": total, "page": page, "page_size": page_size}

    def restore(self, artifact_id: str) -> dict[str, Any]:
        """从回收站恢复：把文件挪回原路径，再清掉 deleted_at。"""
        artifact = self.artifacts.get(artifact_id, include_deleted=True)
        if artifact is None:
            raise AppError(ErrorCode.NOT_FOUND, f"产物不存在：{artifact_id}")
        extra = dict(artifact.extra or {})
        moves = extra.get("trash") or []
        restored: list[str] = []
        for move in moves:
            if self.storage.restore_file(move.get("to", ""), move.get("from", "")):
                restored.append(move.get("from", ""))
        extra.pop("trash", None)
        self.artifacts.restore(artifact_id, extra)
        return {"artifact_id": artifact_id, "restored": True, "files": restored}

    def purge(self, artifact_id: str) -> dict[str, Any]:
        """彻底删除：清掉回收站里的实体文件并删除记录（不可恢复）。"""
        artifact = self.artifacts.get(artifact_id, include_deleted=True)
        if artifact is None:
            raise AppError(ErrorCode.NOT_FOUND, f"产物不存在：{artifact_id}")
        extra = dict(artifact.extra or {})
        for move in extra.get("trash") or []:
            self.storage.delete_file(move.get("to", ""))
        self.artifacts.hard_delete(artifact_id)
        return {"artifact_id": artifact_id, "purged": True}

    def open_file(self, artifact_id: str) -> dict[str, Any]:
        """用系统默认程序打开产物（装了 WPS 就是 WPS，装了 Office 就是 Office）。

        Web 端没法直接把本地文件交给桌面软件，这里由服务端调用系统文件关联：
        Windows 用 os.startfile，macOS 用 open，Linux 用 xdg-open。
        """
        artifact = self.get(artifact_id)
        path = Path(artifact.path)
        if not path.exists():
            raise AppError(ErrorCode.NOT_FOUND, "产物文件不存在（可能已被删除）")
        opened, error = _open_with_system(path)
        return {
            "artifact_id": artifact_id,
            "path": str(path),
            "opened": opened,
            "error": error,
        }

    def delete_many(self, artifact_ids: list[str]) -> dict[str, Any]:
        """批量软删：逐条复用 delete()，单条失败不影响其余（部分成功语义）。

        去重保序：同一 ID 重复提交只删一次，避免前端重复点击导致计数虚高。
        """
        unique_ids: list[str] = []
        seen: set[str] = set()
        for artifact_id in artifact_ids:
            key = (artifact_id or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_ids.append(key)

        trashed: list[str] = []
        failed: list[dict[str, Any]] = []
        deleted = 0
        for artifact_id in unique_ids:
            try:
                result = self.delete(artifact_id)
            except AppError as error:
                failed.append(
                    {"artifact_id": artifact_id, "deleted": False, "message": error.message}
                )
            except Exception as error:  # 单条异常不阻断整批
                failed.append({"artifact_id": artifact_id, "deleted": False, "message": str(error)})
            else:
                deleted += 1
                trashed.extend(result.get("trashed", []))
        return {
            "requested": len(unique_ids),
            "deleted": deleted,
            "failed": failed,
            "trashed": trashed,
        }

    # ---------- 内部 ----------
    def _ensure_thread(self, thread_id: str) -> None:
        if self.threads.get(thread_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, f"会话不存在：{thread_id}")

    def _touch(self, thread_id: str) -> None:
        thread = self.threads.get(thread_id)
        if thread is not None:
            thread.updated_at = now_iso()
            self.threads.update(thread)


def _media_type(filename: str, content_type: str | None) -> str:
    """定 Content-Type：上传时浏览器给的通用类型（octet-stream）不足以让 PDF 内联打开，
    按扩展名兜底一次，否则「预览 PDF」会被浏览器当成未知二进制直接下载。"""
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or content_type or "application/octet-stream"
