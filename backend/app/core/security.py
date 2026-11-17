"""安全工具：脱敏、文件名校验、目录逃逸防护、上传类型校验。"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 上传白名单由 `domain/formats.py` 定义，这里只做转发。
# 以前这份集合和 doc.py 的产物格式各写一份，结果是「能产出的格式」与
# 「能上传的格式」慢慢分叉——同一个 .pptx，产物菜单里没有、上传又被拒。
from ..domain.formats import (
    FORMATS,
    OOXML_ROOTS,
)
from ..domain.formats import UPLOAD_EXTS as DOC_UPLOAD_EXTS
from ..domain.media import (
    KIND_AUDIO,
    KIND_IMAGE,
    KIND_TRANSCRIPT,
    KIND_VIDEO,
    MEDIA_EXTS,
    media_spec,
    media_specs_for_mime,
)

#: 上传白名单 = 文档格式 + 媒体素材。两个来源各自是事实源，这里只做并集，
#: 避免「加了一种图片格式，忘了改另一处」。
SUPPORTED_UPLOAD_EXTS: set[str] = set(DOC_UPLOAD_EXTS) | set(MEDIA_EXTS)

#: 明确拒收的扩展名：可执行文件与脚本。
#:
#: 「什么都拖得进来」不等于「什么都收」——这些文件既读不出文字，也不该被一个
#: 办公助手收进素材库。没有扩展名的文件同理：无从判断是什么，只能请用户补后缀。
#: 除这两种情况外，其余扩展名一律收下（读不读得出字由解析层如实回答）。
BLOCKED_UPLOAD_EXTS: frozenset[str] = frozenset(
    {
        ".exe",
        ".msi",
        ".com",
        ".scr",
        ".dll",
        ".so",
        ".dylib",
        ".bat",
        ".cmd",
        ".ps1",
        ".vbs",
        ".vbe",
        ".js",
        ".mjs",
        ".jse",
        ".wsf",
        ".hta",
        ".sh",
        ".bash",
        ".zsh",
        ".command",
        ".jar",
        ".apk",
        ".ipa",
        ".app",
        ".lnk",
        ".reg",
    }
)

#: 浏览器对 OOXML / 文本的「随手一标」：这些值与扩展名同时出现时不该报错。
_BROWSER_MIME = {"application/zip", "application/octet-stream", ""}

#: 各家客户端实际会上报的别名（Excel 存的老格式、WPS、部分邮件网关）。
_MIME_ALIASES: dict[str, set[str]] = {
    ".docx": {"application/msword"},
    ".xlsx": {"application/vnd.ms-excel"},
    ".pptx": {"application/vnd.ms-powerpoint"},
    ".csv": {"application/vnd.ms-excel", "text/plain"},
    ".md": {"text/plain"},
}

#: 扩展名 -> 允许的 MIME。基础值直接取格式表的 content_type
#: （容器类型 + 浏览器通用值 + 别名），不再手抄一份容易漏的清单。
ALLOWED_MIME: dict[str, set[str]] = {
    spec.ext: {spec.mime} | _BROWSER_MIME | _MIME_ALIASES.get(spec.ext, set())
    for spec in FORMATS
    if spec.can_upload
}

#: 文本格式的扩展名集合（按 content_type 反推，加新文本格式不用改这里）。
TEXT_EXTS: set[str] = {
    spec.ext for spec in FORMATS if spec.can_upload and spec.mime.startswith("text/")
}


class UploadValidationError(ValueError):
    """上传校验失败：扩展名/MIME/magic bytes/大小。"""

    def __init__(self, message: str, *, reason: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.reason = reason


def validate_upload(
    filename: str,
    content_type: str | None,
    data: bytes,
    *,
    limits: UploadLimits | None = None,
) -> None:
    """扩展名 + MIME + magic bytes 三重校验（OOXML 用 zip 内的目录区分）。

    白名单之外的扩展名**不再拒收**：用户拖进来的东西五花八门（旧版 .doc、
    .zip、.json、相机导出的 .heic…），拒收只会让人卡在「到底能传什么」上。
    未知类型走 `_validate_generic`：只查「非空」和「别是压缩炸弹」，
    能不能读出字交给 `parsing.parse_bytes` 如实回答。
    唯二例外是可执行文件/脚本与没有扩展名的文件，见 `BLOCKED_UPLOAD_EXTS`。
    """
    ext = Path(filename).suffix.lower()
    if not ext:
        raise UploadValidationError(
            "文件没有扩展名，认不出是什么；改名补上后缀（如 .docx）再上传",
            reason="unsupported_type",
        )
    if ext in BLOCKED_UPLOAD_EXTS:
        raise UploadValidationError(
            f"{ext} 是可执行文件或脚本，素材库不收这类文件", reason="unsupported_type"
        )
    if ext not in SUPPORTED_UPLOAD_EXTS:
        _validate_generic(data, limits)
        return
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    media = media_spec(ext)
    if media is not None:
        # 媒体素材的 MIME 各家差异大（audio/x-m4a、video/quicktime…），按类别放宽，
        # 真正的把关交给下面的 magic 校验（图片解码、音视频容器探测）。
        if not _mime_matches_media(mime, media):
            raise UploadValidationError(
                f"文件 MIME 与扩展名不符：{mime or '（空）'}（{ext}）", reason="mime_mismatch"
            )
        if not data:
            raise UploadValidationError("文件内容为空", reason="empty")
        _validate_media(data, ext, media.kind, limits)
        return
    if mime not in ALLOWED_MIME.get(ext, set()):
        raise UploadValidationError(
            f"文件 MIME 与扩展名不符：{mime or '（空）'}（{ext}）", reason="mime_mismatch"
        )
    if not data:
        raise UploadValidationError("文件内容为空", reason="empty")
    if ext in OOXML_ROOTS:
        _validate_ooxml(data, ext, limits)
    elif ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise UploadValidationError("PDF magic bytes 校验失败", reason="magic_mismatch")
        _validate_pdf(data, limits)
    else:
        _validate_text(data, ext, limits)


# --------------------------------------------------------------------------
# 解压炸弹 / 超大文档防护
#
# OOXML（docx/xlsx）本质是 zip，PDF 可嵌套大量对象流：
# 20MB 的恶意文件能解压出数 GB 内容，直接拖垮内存与 CPU。
# 上传与解析两处都要拦：上传时拒收，解析时再兜底。
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class UploadLimits:
    """解析防护阈值（来自 Settings，缺省时用下面的保守默认值）。"""

    max_uncompressed_bytes: int = 256 * 1024 * 1024  # 解压后总量上限
    max_archive_entries: int = 2000  # 压缩包条目数上限
    max_pdf_pages: int = 500  # PDF 页数上限
    max_parsed_chars: int = 1_000_000  # 解析文本字符上限
    max_compression_ratio: int = 200  # 单条目压缩比上限（防高度冗余炸弹）

    @classmethod
    def from_settings(cls, settings: Any) -> UploadLimits:
        return cls(
            max_uncompressed_bytes=settings.max_uncompressed_mb * 1024 * 1024,
            max_archive_entries=settings.max_archive_entries,
            max_pdf_pages=settings.max_pdf_pages,
            max_parsed_chars=settings.max_parsed_chars,
        )


def check_zip_bomb(data: bytes, *, limits: UploadLimits | None = None) -> None:
    """校验 OOXML/zip 的解压规模：总大小、条目数、单条目压缩比。"""
    limits = limits or UploadLimits()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("不是合法的 zip/OOXML 文件", reason="magic_mismatch") from exc
    except (zipfile.LargeZipFile, EOFError, ValueError) as exc:
        raise UploadValidationError(f"压缩包结构异常：{type(exc).__name__}") from exc

    if len(entries) > limits.max_archive_entries:
        raise UploadValidationError(
            f"压缩包条目数 {len(entries)} 超过上限 {limits.max_archive_entries}",
            reason="too_many_entries",
        )
    total = 0
    for entry in entries:
        size = entry.file_size
        if size < 0:
            raise UploadValidationError("压缩包条目大小异常", reason="bad_entry")
        total += size
        if total > limits.max_uncompressed_bytes:
            raise UploadValidationError(
                f"解压后体积超过 {limits.max_uncompressed_bytes // (1024 * 1024)}MB 上限，"
                "文件可能是压缩炸弹",
                reason="zip_bomb",
            )
        # 压缩比异常（小文件撑出巨量内容）单独拦一道
        compressed = max(entry.compress_size, 1)
        if size // compressed > limits.max_compression_ratio and size > 1024 * 1024:
            raise UploadValidationError(
                f"条目 {entry.filename[:40]} 压缩比异常（{size // compressed}:1），疑似压缩炸弹",
                reason="zip_bomb",
            )


def _validate_ooxml(data: bytes, ext: str, limits: UploadLimits | None = None) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise UploadValidationError(
            f"{ext} magic bytes 校验失败（不是合法 zip/OOXML）", reason="magic_mismatch"
        ) from exc
    expected = OOXML_ROOTS[ext]
    if not any(name.startswith(expected) for name in names):
        raise UploadValidationError(
            f"文件内容与扩展名不符：{ext} 但缺少 {expected} 目录", reason="magic_mismatch"
        )
    # 目录名合法后再查规模，避免对非 OOXML 的 zip 做无意义计算
    check_zip_bomb(data, limits=limits)


def _validate_pdf(data: bytes, limits: UploadLimits | None = None) -> None:
    """PDF 页数上限（页数在解析阶段统计，这里只做体积的粗校验防超大对象流）。"""
    limits = limits or UploadLimits()
    if limits.max_pdf_pages <= 0:
        return
    # PDF 的对象流高度冗余也会形成「解压炸弹」，按原始体积与页数比粗估：
    # 单页平均体积低于 200 字节时，说明存在大量重复/嵌套对象
    estimated_pages = _estimate_pdf_pages(data)
    if estimated_pages > limits.max_pdf_pages * 4:
        raise UploadValidationError(
            f"PDF 结构异常（估算页数 {estimated_pages} 远超上限 {limits.max_pdf_pages}）",
            reason="too_many_pages",
        )


def _estimate_pdf_pages(data: bytes) -> int:
    """用 /Type /Page 出现次数粗估页数（不解码，纯字节扫描，代价可控）。"""
    head = data[: 8 * 1024 * 1024]
    return head.count(b"/Type /Page") + head.count(b"/Type/Page")


def _validate_text(data: bytes, ext: str, limits: UploadLimits | None = None) -> None:
    if ext in TEXT_EXTS and b"\x00" in data[:4096]:
        raise UploadValidationError("文本文件包含二进制内容", reason="magic_mismatch")
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            data.decode(encoding)
            return
        except UnicodeDecodeError:
            continue
    raise UploadValidationError("文本编码无法识别（支持 UTF-8/GB18030）", reason="magic_mismatch")


def _validate_generic(data: bytes, limits: UploadLimits | None = None) -> None:
    """白名单之外的文件只做「兜底安全」校验：非空 + 别是压缩炸弹。

    刻意**不**校验 MIME 与扩展名是否匹配：用户从微信、网盘、相机导出的文件
    上报的 MIME 常常是 application/octet-stream 甚至空的，拿它当判据只会误伤。
    真正危险的是「小文件解出几个 G」，所以 zip 容器单独查一遍规模；
    其余一律收下——文件本身不会被打开执行，只是存起来、尽量取字。
    """
    if not data:
        raise UploadValidationError("文件内容为空", reason="empty")
    if data[:4] == b"PK\x03\x04":
        check_zip_bomb(data, limits=limits)
        return
    if data[:5] == b"%PDF":
        _validate_pdf(data, limits)


def _mime_matches_media(mime: str, spec: Any) -> bool:
    """媒体 MIME 的宽松匹配：精确值 / 同类别前缀 / 浏览器兜底值。

    只认精确值会逼着用户「同样的 mp4，从微信拖进来能传、从 OBS 导出的不能传」；
    只认前缀又会让把 .exe 改成 .mp4 的文件混过第一道。所以：MIME 放宽，
    内容用 magic 严格验（见 `_validate_media`）。

    精确命中走 `media_specs_for_mime` 的 dict 反查（O(1)），不再拿
    `mime in spec.mimes` 线性扫元组；只有前缀这一类兜底才需要比较字符串。
    """
    if mime in _BROWSER_MIME:
        return True
    if spec in media_specs_for_mime(mime):
        return True
    prefix = "text/" if spec.kind == KIND_TRANSCRIPT else f"{spec.kind}/"
    return mime.startswith(prefix)


def _validate_media(data: bytes, ext: str, kind: str, limits: UploadLimits | None = None) -> None:
    """媒体素材的内容校验：图片真能解码、音视频真能读出流、转写稿真是文本。"""
    if kind == KIND_IMAGE:
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - Pillow 是基础依赖
            return
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except Exception as exc:
            raise UploadValidationError(
                f"图片内容与扩展名不符（无法解码）：{type(exc).__name__}", reason="magic_mismatch"
            ) from exc
        return
    if kind in (KIND_AUDIO, KIND_VIDEO):
        try:
            import av
        except ImportError:  # pragma: no cover - 没装识别组件时跳过容器探测
            return
        try:
            with av.open(io.BytesIO(data), metadata_errors="ignore") as container:
                if not container.streams:
                    raise ValueError("没有可读的媒体流")
        except Exception as exc:
            raise UploadValidationError(
                f"音视频内容与扩展名不符（无法解析容器）：{type(exc).__name__}",
                reason="magic_mismatch",
            ) from exc
        return
    # 会议记录里的 srt / vtt：就是文本，按文本校验（含编码识别）
    try:
        _validate_text(data, ".txt", limits)
    except UploadValidationError as exc:
        raise UploadValidationError(
            f"{ext} 内容不是可识别的文本：{exc}", reason="magic_mismatch"
        ) from exc


_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "token",
    "credential",
    "authorization",
)


def sanitize(value: Any) -> Any:
    """按字段名递归脱敏；邮箱允许展示（契约要求），但日志里用 mask_email。"""
    if isinstance(value, dict):
        return {
            key: "***" if any(s in str(key).lower() for s in _SENSITIVE_KEYS) else sanitize(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return value if len(value) <= 2000 else value[:2000] + "…(截断)"
    return value


def mask_email(value: str) -> str:
    """日志脱敏：a***@example.com。"""
    match = re.match(r"^([^@\s]{1,2})[^@\s]*(@[^@\s]+)$", value or "")
    return f"{match.group(1)}***{match.group(2)}" if match else value


def safe_filename(name: str) -> str:
    """保留中文，去掉路径与 Windows 非法字符，限制长度。"""
    base = Path(name or "artifact").name
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", base).strip(" .")
    return base[:120] or "artifact"


def ensure_within(path: Path, root: Path) -> Path:
    """防止路径穿越：解析后的文件必须位于 root 内。"""
    resolved = path.resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise ValueError(f"路径越界：{path}")
    return resolved


def is_supported_upload(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_UPLOAD_EXTS


def masked_secret(value: str) -> str:
    """密钥脱敏展示：sk-****abcd。"""
    if not value:
        return ""
    return f"{value[:3]}****{value[-4:]}" if len(value) > 8 else "****"
