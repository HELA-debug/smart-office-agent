"""媒体素材格式表：图片 / 会议记录 / 录音 / 视频。

## 职责边界（改这里之前先读这一段）

**这一层只管「后缀和 MIME」。** 它回答三个问题，也只回答这三个：

1. 这个后缀算不算媒体素材 —— `media_spec(ext)`；
2. 属于哪一类 —— `media_kind(ext)` → image / transcript / audio / video；
3. 这个 MIME 是不是这一类能接受的值 —— `media_specs_for_mime(mime)`。

它**不判断**下面这些，它们各有各的归属：

- 文件内容真不真：图片能不能解码、容器有没有流 → `core.security._validate_media`；
- 文件多大：单文件体积上限 → `Settings.max_media_mb`；
- 录音多长：转写时长上限 → `Settings.asr_max_minutes`；
- 识别用什么模型、多久出结果 → `services.media_service`。

把这些混进格式表，这张表就会变成第二个配置中心：改一个上传上限也要动它。
本层唯一允许的判断是「这个后缀该怎么取字」，别的都别往这里塞。

## 为什么单开一张表

不往 `formats.py` 里加行，是因为那张表回答的是「一种**文档**格式怎么产出、
用哪个库处理」，它的每一行都会进 `OUTPUT_FORMATS` / `ARTIFACT_TYPE_HINT`
这些对外契约。图片和录音不是产物、也没有生成器，混进去会让「产物格式下拉」
多出 PNG、MP3 这种点不出来的项。

但「用户能不能传」这件事必须只有一处说得清，所以这里的 `MEDIA_SPECS` 与
`formats.FORMATS` 一起构成上传白名单：`security.validate_upload` 两边都查。

## 四种 kind 的区别

区别只在**怎么取出文字**，不在前端长什么样：

- image：OCR（RapidOCR，PP-OCR 中文模型，离线）；
- transcript：本身就是文字（会议纪要、srt / vtt 转写稿），按文本解析；
- audio：语音转写（faster-whisper）；
- video：抽出音轨后按音频转写，画面不处理。

kind 同时决定上传后的徽标文案（「图片 / 会议记录 / 会议录音 / 会议视频」）。
前端不按 kind 分设上传入口：系统文件对话框永远开在同一个位置，分了类也定位
不到具体文件夹，反而多一次点击。
"""

from __future__ import annotations

from dataclasses import dataclass

KIND_IMAGE = "image"
KIND_TRANSCRIPT = "transcript"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"

#: 上传后的类别徽标（「识别中 / 已可用」旁边那一小块）。
#: 同时是本层认可的 kind 全集：新增 kind 必须同时补这里，否则导入自检会报错。
KIND_LABELS: dict[str, str] = {
    KIND_IMAGE: "图片",
    KIND_TRANSCRIPT: "会议记录",
    KIND_AUDIO: "会议录音",
    KIND_VIDEO: "会议视频",
}


@dataclass(frozen=True)
class MediaSpec:
    """一种媒体素材：扩展名 + 类别 + 浏览器可能上报的 MIME + 要不要识别。

    字段语义：

    - ``ext``：带点的小写后缀（``".m4a"``）。**必须小写且带点**，导入时自检；
    - ``kind``：``image`` / ``transcript`` / ``audio`` / ``video``，决定怎么取字；
    - ``mimes``：浏览器可能上报的 MIME 值，全部小写、不带参数（``;codecs=…``
      要在比较前切掉，见 `core.security.validate_upload`）。写在每条规格旁边的
      注释里说明了它是「谁报上来的」，方便判断某个值能不能删；
    - ``needs_recognition``：上传后是否进后台识别队列。默认 ``True`` —— 图片、
      录音、视频都要异步出字；只有**本身就是文字**的转写稿（srt / vtt）需要显式
      关掉。同一个 kind 的所有规格必须一致，导入自检会拦住写歪的那一条。

    ``frozen=True`` 是刻意的：这张表在导入时构建一次，运行期被多处并发读
    （上传校验、解析分流、健康检查），可变对象一旦被谁顺手改了，问题会以
    「某个格式时好时坏」的形式出现，极难定位。
    """

    ext: str
    kind: str
    mimes: tuple[str, ...] = ()
    needs_recognition: bool = True


#: 全部媒体素材规格。**唯一的真相源**：上传白名单、解析分流、识别队列都从这里派生。
#:
#: 每条都显式写 ``needs_recognition``（而不是靠 kind 推断），因为「要不要识别」
#: 是产品决策，不是分类的必然结果 —— 同一个 transcript 类别将来若加入 CSV 转写稿，
#: 也得单独判断一次，而不是被 kind 顺手带进识别队列。
MEDIA_SPECS: tuple[MediaSpec, ...] = (
    # ---- 图片：OCR ----
    # MIME 来源：PNG/WebP 只有标准值；JPEG 的 image/jpg 是老 IE，
    # image/pjpeg 是更早的渐进式 JPEG 标记，Windows 资源管理器至今仍偶发上报。
    MediaSpec(".png", KIND_IMAGE, ("image/png",)),
    MediaSpec(".jpg", KIND_IMAGE, ("image/jpeg", "image/jpg", "image/pjpeg")),
    MediaSpec(".jpeg", KIND_IMAGE, ("image/jpeg", "image/jpg", "image/pjpeg")),
    MediaSpec(".webp", KIND_IMAGE, ("image/webp",)),
    # image/x-bmp / image/x-ms-bmp：Windows 老版本与部分 OEM 看图工具上报的别名
    MediaSpec(".bmp", KIND_IMAGE, ("image/bmp", "image/x-bmp", "image/x-ms-bmp")),
    # image/tif：扫描仪驱动与部分 macOS 版本把 .tiff 报成 .tif
    MediaSpec(".tif", KIND_IMAGE, ("image/tiff", "image/tif")),
    MediaSpec(".tiff", KIND_IMAGE, ("image/tiff", "image/tif")),
    # ---- 会议记录：本身就是文字，只是多了转写稿的格式 ----
    # MIME 来源：SubRip 没有官方注册类型，各系统报得很散 —— 播放器多是
    # text/plain，VLC 与部分文件管理器报 application/x-subrip。
    MediaSpec(
        ".srt",
        KIND_TRANSCRIPT,
        ("application/x-subrip", "text/plain", "text/srt"),
        needs_recognition=False,
    ),
    # text/vtt 是 W3C 规范值；仍有浏览器按 text/plain 处理
    MediaSpec(".vtt", KIND_TRANSCRIPT, ("text/vtt", "text/plain"), needs_recognition=False),
    # ---- 会议录音 ----
    # audio/mp3 / audio/x-mp3 / audio/mpeg3：老播放器与部分采集卡的别名
    MediaSpec(".mp3", KIND_AUDIO, ("audio/mpeg", "audio/mp3", "audio/x-mp3", "audio/mpeg3")),
    # MIME 来源：iPhone 录音报 audio/x-m4a，安卓与部分浏览器报 audio/mp4，
    # 桌面端偶见 audio/m4a
    MediaSpec(".m4a", KIND_AUDIO, ("audio/mp4", "audio/x-m4a", "audio/m4a")),
    # audio/x-wav / audio/wave：老浏览器与录音笔软件的上报值
    MediaSpec(".wav", KIND_AUDIO, ("audio/wav", "audio/x-wav", "audio/wave")),
    # MIME 来源：功能机录音、微信语音导出多为 audio/amr，窄带版本报 audio/amr-nb
    MediaSpec(".amr", KIND_AUDIO, ("audio/amr", "audio/amr-nb", "audio/x-amr")),
    # audio/aacp：流媒体（HLS 切片）导出时的上报值
    MediaSpec(".aac", KIND_AUDIO, ("audio/aac", "audio/x-aac", "audio/aacp")),
    # application/ogg 是容器级类型，Linux 桌面与部分下载器会这么报
    MediaSpec(".ogg", KIND_AUDIO, ("audio/ogg", "application/ogg")),
    MediaSpec(".flac", KIND_AUDIO, ("audio/flac", "audio/x-flac")),
    # ---- 会议视频 ----
    # application/mp4：部分系统（含部分安卓浏览器）把 mp4 报成应用类型
    MediaSpec(".mp4", KIND_VIDEO, ("video/mp4", "application/mp4")),
    # quicktime 是 .mov 唯一被广泛接受的值，没有别名
    MediaSpec(".mov", KIND_VIDEO, ("video/quicktime",)),
    # MIME 来源：苹果体系报 video/x-m4v，非苹果播放器常统一按 video/mp4 上报
    MediaSpec(".m4v", KIND_VIDEO, ("video/x-m4v", "video/mp4")),
    # video/avi、video/msvideo：老播放器与部分 Windows 采集软件
    MediaSpec(".avi", KIND_VIDEO, ("video/x-msvideo", "video/avi", "video/msvideo")),
    # video/mkv：部分国产播放器与下载工具的上报值
    MediaSpec(".mkv", KIND_VIDEO, ("video/x-matroska", "video/mkv")),
    # MIME 来源：旧手机录制的视频是 video/3gpp；只有音轨的 3gp（语音彩信）
    # 会被报成 audio/3gpp，两者都要接
    MediaSpec(".3gp", KIND_VIDEO, ("video/3gpp", "audio/3gpp")),
)


def _check_specs() -> None:
    """导入时自检格式表。表写歪了要**当场**炸，而不是等用户传到某个后缀才发现。

    校验项，每一条都对应一种真实会发生的「静默错」：

    - ext 必须小写、带点、至少两个字符 —— 大写会让 `Path(..).suffix.lower()`
      查不到，表现是「同一类文件有的能传有的不能传」；
    - ext 不能重复 —— `_BY_EXT` 是 dict，重复时后一条会**静默覆盖**前一条，
      被覆盖的那条从此永远取不到；
    - kind 必须在 `KIND_LABELS` 里 —— 否则界面上那块徽标是空白；
    - mimes 不能为空，且必须小写、不带参数 —— 带 `;codecs=` 的值永远匹配不上；
    - 同一个 kind 的 `needs_recognition` 必须一致 —— 否则「图片有的识别有的不识别」，
      前端只能靠猜。

    失败抛 `RuntimeError` 而不是 `assert`：`python -O` 会去掉 assert，
    而这张表写错是必须在任何模式下都拦下来的。
    """
    problems: list[str] = []
    seen_ext: dict[str, MediaSpec] = {}
    kind_flag: dict[str, bool] = {}

    if not MEDIA_SPECS:
        # 空表会让上传白名单里一个媒体都没有，而且下面的反查索引无从构建
        problems.append("格式表为空，至少要有一条媒体规格")

    for spec in MEDIA_SPECS:
        if not spec.ext.startswith("."):
            problems.append(f"{spec.ext!r} 缺少前导点号")
        if spec.ext != spec.ext.lower():
            problems.append(f"{spec.ext!r} 必须全小写")
        if len(spec.ext) < 2:
            problems.append(f"{spec.ext!r} 只有点号、没有后缀名")
        if spec.ext in seen_ext:
            problems.append(f"{spec.ext!r} 重复定义（前一条的 kind={seen_ext[spec.ext].kind}）")
        else:
            seen_ext[spec.ext] = spec

        if spec.kind not in KIND_LABELS:
            problems.append(f"{spec.ext!r} 的 kind={spec.kind!r} 不在 KIND_LABELS 里")
        if not spec.mimes:
            problems.append(f"{spec.ext!r} 没有声明任何 MIME")
        for mime in spec.mimes:
            if mime != mime.lower():
                problems.append(f"{spec.ext!r} 的 MIME {mime!r} 必须全小写")
            if not mime or ";" in mime:
                problems.append(f"{spec.ext!r} 的 MIME {mime!r} 不能带参数或为空")
            if "/" not in mime:
                problems.append(f"{spec.ext!r} 的 MIME {mime!r} 不是 type/subtype 形式")

        previous = kind_flag.get(spec.kind)
        if previous is not None and previous is not spec.needs_recognition:
            problems.append(
                f"{spec.ext!r} 的 needs_recognition={spec.needs_recognition} "
                f"与同类 kind={spec.kind!r} 的其他规格（{previous}）不一致"
            )
        kind_flag[spec.kind] = spec.needs_recognition

    if problems:
        raise RuntimeError("媒体格式表自检失败：\n- " + "\n- ".join(problems))


_check_specs()


#: 后缀 → 规格。导入时一次构建，上传校验与解析分流都走这里，运行期 O(1)。
_BY_EXT: dict[str, MediaSpec] = {spec.ext: spec for spec in MEDIA_SPECS}


#: MIME → 声明了该 MIME 的规格集合。
#:
#: 一个 MIME 可能对应多个后缀（`image/jpeg` → .jpg / .jpeg；`video/mp4` →
#: .mp4 / .m4v），所以值必须是集合而不是单条。用它在上传校验里做**精确命中**
#: 的 O(1) 反查，不必每次拿 `mime in spec.mimes` 线性扫一遍元组。
def _index_by_mime(specs: tuple[MediaSpec, ...]) -> dict[str, frozenset[MediaSpec]]:
    """MIME → 规格集合。用函数而不是模块级循环，避免留下 `_spec` / `_mime`
    这种临时变量（空表时 `del` 会直接 NameError）。"""
    index: dict[str, set[MediaSpec]] = {}
    for spec in specs:
        for mime in spec.mimes:
            index.setdefault(mime, set()).add(spec)
    return {mime: frozenset(group) for mime, group in index.items()}


_BY_MIME: dict[str, frozenset[MediaSpec]] = _index_by_mime(MEDIA_SPECS)

#: 媒体素材的扩展名集合（与文档白名单一起构成上传白名单）。
MEDIA_EXTS: frozenset[str] = frozenset(_BY_EXT)

#: 需要调识别引擎的 kind 集合 —— **从规格表派生**，不再手写第二份。
#: 手写集合曾经和 `MEDIA_SPECS` 分过叉：加了新格式却没加进集合，表现是
#: 上传后一直停在「识别中」。
_NEEDS_RECOGNITION_KINDS: frozenset[str] = frozenset(
    spec.kind for spec in MEDIA_SPECS if spec.needs_recognition
)


def _normalise_ext(ext: str) -> str:
    """后缀归一化：去空白、补前导点、转小写。

    调用方传来的形式很杂 —— `".PNG"`（资源管理器）、`"png"`（`extra["ext"]` 里
    存的就是不带点的值）、`" .png "`（拼出来的）。统一在这里收一次，调用处
    就不用各写一遍。
    """
    key = (ext or "").strip().lower()
    if key and not key.startswith("."):
        key = f".{key}"
    return key


def media_spec(ext: str) -> MediaSpec | None:
    """后缀 → 媒体规格；不是媒体素材时返回 ``None``（调用方据此回落文档解析）。

    输入 ``ext`` 允许三种写法（见 `_normalise_ext`）：``".PNG"`` / ``"png"`` /
    ``" .png "``，全部等价。空串、只有点号、不认识的后缀 → ``None``。

    返回的是**表里那一个共享对象**（frozen），不要试图修改它。
    """
    return _BY_EXT.get(_normalise_ext(ext))


def media_specs_for_mime(mime: str) -> frozenset[MediaSpec]:
    """MIME → 声明了它的规格集合，用于上传校验的精确反查。

    输入 ``mime`` 会先小写、去空白、切掉 ``;codecs=…`` 之类参数（浏览器对
    ``<video>`/``<audio>`` 元素常常带参数上报）。

    返回空集合表示「格式表里没有任何规格声明过这个 MIME」—— 调用方通常还要
    再看类别前缀（``audio/`` / ``video/``）做宽松匹配，见
    `core.security._mime_matches_media`。
    """
    key = (mime or "").split(";", 1)[0].strip().lower()
    if not key:
        return frozenset()
    return _BY_MIME.get(key, frozenset())


def media_kind(ext: str) -> str | None:
    """后缀 → kind（``image`` / ``transcript`` / ``audio`` / ``video``）。

    参数归一化同 `media_spec`。不是媒体素材时返回 ``None``，与
    ``media_spec(ext) is None`` 完全等价。
    """
    spec = media_spec(ext)
    return spec.kind if spec else None


def media_label(kind: str | None) -> str:
    """kind → 界面徽标文案（「会议录音」）；未知 kind 返回空串。

    给 ``None`` 也返回空串而不是 ``"None"`` —— 调用处常直接拼进界面。
    """
    return KIND_LABELS.get(kind or "", "")


def needs_recognition(kind: str | None) -> bool:
    """这个类别上传后要不要进后台识别队列。

    只看 kind，不碰文件内容与大小。``None`` / 未知 kind → ``False``
    （不认识的东西不进队列，避免把一个空 kind 塞给识别器）。

    依据是 `MEDIA_SPECS` 里各规格的 ``needs_recognition`` 字段**派生**出来的
    集合，不是另一份手写清单。
    """
    return (kind or "") in _NEEDS_RECOGNITION_KINDS
