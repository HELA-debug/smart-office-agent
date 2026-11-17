# 录音与视频识别：代码汇编

> 两个模块共用**同一条链路**：视频只取音轨、按音频转写，画面不处理。
> 所以下面没有「视频识别」和「录音识别」两套代码，只有一条 `transcribe()`，
> 差异出现在两个地方：**格式表**把后缀判成 `audio` 还是 `video`，
> 以及结果里的 `meta.source` 记成 `audio` 还是 `video`。

## 调用链

```
上传 会议录音.wav / 会议视频.mp4
      │
      ▼
domain.media.media_kind(ext)  →  "audio" / "video"
      │   （NEEDS_RECOGNITION 为真 → 进后台识别队列）
      ▼
ArtifactService._recognize()           后台线程，不挡住对话
      │
      ├─ image → media.ocr()          图片走 OCR，另一条链路
      │
      └─ audio / video
            ├─ _hotwords()            人名 / 产品型号 / 高频词
            ├─ MediaRecognizer.transcribe(data, hotwords=…)
            │     ├─ _probe_audio()   有没有音轨、编码、时长
            │     ├─ _asr_model()     faster-whisper（CPU / int8）
            │     ├─ initial_prompt   短提示语 + 热词
            │     ├─ 逐段收：超时截断、丢弃「提示语复读」
            │     ├─ 相邻重复句去重
            │     ├─ 碎片合并（「嗯」「对」并进下一句）
            │     ├─ 繁转简（OpenCC，可选依赖）
            │     └─ 打时间戳 → "mm:ss 文本"
            └─ _proofread()           大模型按上下文挑同音字（只许等长换词）
      │
      ▼
写 parsed.txt → 状态 ready → 可以被当成对话素材引用
```

## 1. 格式表：哪些后缀算录音、哪些算视频

`backend/app/domain/media.py`

kind 只决定「怎么取字」，不决定前端长什么样。

````python
KIND_IMAGE = "image"
KIND_TRANSCRIPT = "transcript"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"

#: 上传后的类别徽标（「识别中 / 已可用」旁边那一小块）。
KIND_LABELS: dict[str, str] = {
    KIND_IMAGE: "图片",
    KIND_TRANSCRIPT: "会议记录",
    KIND_AUDIO: "会议录音",
    KIND_VIDEO: "会议视频",
}
````

````python
MEDIA_SPECS: tuple[MediaSpec, ...] = (
    # ---- 图片：OCR ----
    MediaSpec(".png", KIND_IMAGE, ("image/png",)),
    MediaSpec(".jpg", KIND_IMAGE, ("image/jpeg", "image/jpg", "image/pjpeg")),
    MediaSpec(".jpeg", KIND_IMAGE, ("image/jpeg", "image/jpg", "image/pjpeg")),
    MediaSpec(".webp", KIND_IMAGE, ("image/webp",)),
    MediaSpec(".bmp", KIND_IMAGE, ("image/bmp", "image/x-bmp", "image/x-ms-bmp")),
    MediaSpec(".tif", KIND_IMAGE, ("image/tiff", "image/tif")),
    MediaSpec(".tiff", KIND_IMAGE, ("image/tiff", "image/tif")),
    # ---- 会议记录：本身就是文字，只是多了转写稿的格式 ----
    MediaSpec(".srt", KIND_TRANSCRIPT, ("application/x-subrip", "text/plain", "text/srt")),
    MediaSpec(".vtt", KIND_TRANSCRIPT, ("text/vtt", "text/plain")),
    # ---- 会议录音 ----
    MediaSpec(".mp3", KIND_AUDIO, ("audio/mpeg", "audio/mp3", "audio/x-mp3", "audio/mpeg3")),
    MediaSpec(".m4a", KIND_AUDIO, ("audio/mp4", "audio/x-m4a", "audio/m4a")),
    MediaSpec(".wav", KIND_AUDIO, ("audio/wav", "audio/x-wav", "audio/wave")),
    MediaSpec(".amr", KIND_AUDIO, ("audio/amr", "audio/amr-nb", "audio/x-amr")),
    MediaSpec(".aac", KIND_AUDIO, ("audio/aac", "audio/x-aac", "audio/aacp")),
    MediaSpec(".ogg", KIND_AUDIO, ("audio/ogg", "application/ogg")),
    MediaSpec(".flac", KIND_AUDIO, ("audio/flac", "audio/x-flac")),
    # ---- 会议视频 ----
    MediaSpec(".mp4", KIND_VIDEO, ("video/mp4", "application/mp4")),
    MediaSpec(".mov", KIND_VIDEO, ("video/quicktime",)),
    MediaSpec(".m4v", KIND_VIDEO, ("video/x-m4v", "video/mp4")),
    MediaSpec(".avi", KIND_VIDEO, ("video/x-msvideo", "video/avi", "video/msvideo")),
    MediaSpec(".mkv", KIND_VIDEO, ("video/x-matroska", "video/mkv")),
    MediaSpec(".3gp", KIND_VIDEO, ("video/3gpp", "audio/3gpp")),
)

_BY_EXT: dict[str, MediaSpec] = {spec.ext: spec for spec in MEDIA_SPECS}

#: 媒体素材的扩展名集合（与文档白名单一起构成上传白名单）。
MEDIA_EXTS: frozenset[str] = frozenset(_BY_EXT)

#: 需要调识别引擎（OCR / 语音）的类别：这三类上传后是异步出文字。
NEEDS_RECOGNITION: frozenset[str] = frozenset({KIND_IMAGE, KIND_AUDIO, KIND_VIDEO})


def media_spec(ext: str) -> MediaSpec | None:
    """按后缀取媒体规格；不是媒体就返回 None（上游据此走文档解析）。"""
    key = (ext or "").strip().lower()
    if key and not key.startswith("."):
        key = f".{key}"
    return _BY_EXT.get(key)


def media_kind(ext: str) -> str | None:
    spec = media_spec(ext)
    return spec.kind if spec else None


def media_label(kind: str | None) -> str:
    return KIND_LABELS.get(kind or "", "")


def needs_recognition(kind: str | None) -> bool:
    return (kind or "") in NEEDS_RECOGNITION
````


## 2. 分流：图片走 OCR，音频视频走转写

`backend/app/services/artifact_service.py`（`_recognize`，后台线程）

注意这里的顺序：先算热词，再转写，最后校对。热词算不出来（读素材失败）只是少几个词，
不会让整段录音识别失败。

````python
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
````


## 3. 音轨探测：区分「没声音」和「模型坏了」

`backend/app/services/media_service.py`

视频没音轨是会议场景里最常见的一种「坏文件」（录屏时没开麦）。直接丢给 whisper，
它只会报一句 `Invalid data found`，用户分不清是文件的问题还是环境的问题。
所以先用 `av` 读容器头，没有音轨就直接给出人话，且**不加载模型**（省掉几百 MB 的内存与十几秒）。

````python
def _probe_audio(data: bytes) -> dict[str, Any]:
    """读容器头，看有没有音轨、是什么编码。

    视频「没声音」在会议场景里很常见（录屏只录了画面）。直接丢给 whisper，
    它只会报一句 `Invalid data found`，用户看不出是文件没音轨还是模型坏了。
    """
    try:
        import av
    except ImportError:  # pragma: no cover - 没装识别组件时不做探测
        return {}
    try:
        with av.open(io.BytesIO(data), metadata_errors="ignore") as container:
            audio = next((s for s in container.streams if s.type == "audio"), None)
            video = next((s for s in container.streams if s.type == "video"), None)
            if audio is None:
                return {"has_audio": False, "has_video": video is not None}
            context = audio.codec_context
            duration = float(container.duration / 1_000_000) if container.duration else 0.0
            return {
                "has_audio": True,
                "has_video": video is not None,
                "codec": str(getattr(context, "name", "") or ""),
                "sample_rate": int(getattr(context, "sample_rate", 0) or 0),
                "duration": duration,
            }
    except Exception:
        # 探测失败不阻断：让 whisper 自己去试，它的报错更具体
        return {}


#: 中文转写的前置提示。只留最短一句：whisper 的 prompt 是当「前文」续写的，
#: 提示语越长，第一段把它整句复读出来的概率越高（真发生过：正文第一行变成
#: 「以下是简体中文的会议记录，请使用简体中文转写」）。简体化交给 OpenCC 兜底，
#: 不让 prompt 兼任翻译指令。
_ZH_PROMPT = "以下是普通话会议录音。"

#: 提示语去掉标点后的样子，用来识别「模型把提示语当正文吐出来」
_PROMPT_COMPACT = re.sub(r"[^\w]", "", _ZH_PROMPT)

#: 少于这么多字的段先攒着跟下一段合并。whisper 常把「嗯」「对」「这个」单独切成
#: 一段，一段一行带时间戳，30 分钟的会议会变成几百行碎片，纪要根本没法读。
_MERGE_MAX_CHARS = 2

#: 攒着的短段最多等这么多秒，超过就不等了 —— 相隔很远的两句不该拼在一起。
_MERGE_MAX_GAP = 2.0
````


## 4. 转写主流程

`backend/app/services/media_service.py`

### 4.1 模型加载

首次使用要下载模型（约 145 MB），走镜像地址；失败给出可重试的错误，不静默。

````python
    # ---------- 音视频 ----------
````


### 4.2 transcribe：从字节流到带时间戳的正文

这条链路里每一处取舍都写在注释里了，重点看四段后处理：
**提示语复读丢弃 → 相邻重复去重 → 碎片合并 → 最后统一繁转简**。
顺序不能换：先合并再转简会把多音字拆散，先转简再合并会让「同形判断」失效。

````python
    def transcribe(
        self, data: bytes, *, hotwords: Sequence[str] | None = None
    ) -> RecognitionResult:
        probe = _probe_audio(data)
        if probe.get("has_audio") is False:
            if probe.get("has_video"):
                raise MediaError("这个视频里没有音轨（录屏时可能没开麦），听不到说话内容")
            raise MediaError("这个文件里没有音频流，可能已损坏")
        model = self._asr_model()
        raw_language = str(getattr(self.settings, "asr_language", "zh") or "").strip()
        # "auto" / 留空 = 让模型自己判语种；固定 zh 时遇到英文会议会整段硬翻成中文
        language = None if raw_language.lower() in ("", "auto") else raw_language
        zh = bool(language) and language.lower().startswith("zh")
        max_minutes = max(1, int(getattr(self.settings, "asr_max_minutes", 60)))
        # 热词只对中文有用：英文会议的术语偏置靠的是模型自己的词表，塞中文词只会带偏
        used_hotwords = [word for word in (hotwords or ()) if word] if zh else []
        prompt = asr_lexicon.build_prompt(_ZH_PROMPT, used_hotwords)
        started = time.monotonic()
        try:
            segments, info = model.transcribe(
                io.BytesIO(data),
                language=language,
                beam_size=5,
                # 会议录音里大量「嗯、啊、停顿」：VAD 先掐掉静音，既快又不让模型
                # 在静音处幻想出句子。静音阈值不能太短 —— 中文句间三四百毫秒的
                # 停顿很常见，500ms 会把一句话切成好几段，跨句上下文断了，人名和
                # 术语就开始飘（「客户验收」认成「客户厌收」多半是这么来的）。
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 800},
                condition_on_previous_text=False,
                # 只给中文加提示：英文会议用不上，还会把英文带偏
                **({"initial_prompt": prompt} if zh else {}),
            )
        except Exception as exc:
            raise MediaError(f"音视频转写失败：{_short_error(exc, 120)}", retryable=True) from exc

        limit = max_minutes * 60
        pieces: list[tuple[float, float, str]] = []
        truncated = False
        try:
            for segment in segments:
                start = float(getattr(segment, "start", 0) or 0)
                end = float(getattr(segment, "end", 0) or 0)
                if end and end > limit:
                    truncated = True
                    break
                text = str(getattr(segment, "text", "") or "").strip()
                if not text:
                    continue
                # 首段偶尔是模型把 initial_prompt 当正文续写出来的，不是真说话
                if not pieces and zh and _looks_like_prompt_echo(text):
                    continue
                pieces.append((start, end, text))
        except Exception as exc:
            raise MediaError(f"音视频转写中断：{_short_error(exc, 120)}") from exc
        finally:
            _close_quietly(segments)

        repeats = 0
        deduped: list[tuple[float, float, str]] = []
        for start, end, text in pieces:
            # 静音、掌声、空调声处模型会「补」一句话，而且同一句连着吐好几遍；
            # 连续两次完全相同且时间挨着，只留第一条
            if deduped and text == deduped[-1][2] and start - deduped[-1][0] < 3.0:
                repeats += 1
                continue
            deduped.append((start, end, text))

        # 碎片合并放在去重之后：先把「嗯」「对」攒到下一句身上，再决定输出
        merged: list[tuple[float, float, str]] = []
        for start, end, text in deduped:
            if merged:
                prev_start, _prev_end, prev_text = merged[-1]
                if len(prev_text) <= _MERGE_MAX_CHARS and start - _prev_end <= _MERGE_MAX_GAP:
                    merged[-1] = (prev_start, end, prev_text + text)
                    continue
            merged.append((start, end, text))

        lines = [f"[{_timestamp(start)}] {text}" for start, _end, text in merged]
        count = len(merged)
        if not lines:
            raise MediaError("没有识别到说话内容（静音、纯音乐或音量过低）")
        text = "\n".join(lines)
        if zh:
            # 繁转简放在最后统一做：逐段转会把「乾／干」这类多音字拆散，整段更准
            text = _to_simplified(text)
        if truncated:
            text += f"\n\n（录音超过 {max_minutes} 分钟，只转写了前 {max_minutes} 分钟）"
        duration = float(probe.get("duration") or getattr(info, "duration", 0) or 0)
        meta: dict[str, Any] = {
            "engine": "faster-whisper",
            "model": str(getattr(self.settings, "asr_model", "base")),
            "duration": round(duration, 1),
            "segments": count,
            "language": str(getattr(info, "language", "") or language or ""),
            "truncated": truncated,
            "source": "video" if probe.get("has_video") else "audio",
            "elapsed": round(time.monotonic() - started, 1),
        }
        if probe.get("codec"):
            meta["audio_codec"] = probe["codec"]
        if repeats:
            meta["repeats"] = repeats
        if used_hotwords:
            # 记下来是为了可诊断：识别不准时第一件事就是看「当时给了哪些词」
            meta["hotwords"] = used_hotwords
        return RecognitionResult(text=text, meta=meta)
````


### 4.3 这条链路用到的小工具

````python
def _timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _short_error(exc: BaseException, limit: int = 160) -> str:
    """异常摘要：类型 + 一行消息。

    原始消息里常带几十行堆栈或多行 ffmpeg 日志，塞进界面的红色小字里既读不完
    也看不出重点；截断后至少能让人判断「是文件坏了还是模型没装」。
    """
    message = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ").strip()
    return message[:limit] + ("…" if len(message) > limit else "")


def _close_quietly(iterator: Any) -> None:
    """尽早释放解码器。

    转写到一半因为超时/截断 break 出来时，whisper 的生成器还握着音频解码上下文；
    不 close 就等 GC，30 分钟的录音会白占着内存和文件句柄。
    """
    closer = getattr(iterator, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:  # pragma: no cover - 关闭失败不影响结果
            return
````

````python
#: 中文转写的前置提示。只留最短一句：whisper 的 prompt 是当「前文」续写的，
#: 提示语越长，第一段把它整句复读出来的概率越高（真发生过：正文第一行变成
#: 「以下是简体中文的会议记录，请使用简体中文转写」）。简体化交给 OpenCC 兜底，
#: 不让 prompt 兼任翻译指令。
_ZH_PROMPT = "以下是普通话会议录音。"

#: 提示语去掉标点后的样子，用来识别「模型把提示语当正文吐出来」
_PROMPT_COMPACT = re.sub(r"[^\w]", "", _ZH_PROMPT)

#: 少于这么多字的段先攒着跟下一段合并。whisper 常把「嗯」「对」「这个」单独切成
#: 一段，一段一行带时间戳，30 分钟的会议会变成几百行碎片，纪要根本没法读。
_MERGE_MAX_CHARS = 2

#: 攒着的短段最多等这么多秒，超过就不等了 —— 相隔很远的两句不该拼在一起。
_MERGE_MAX_GAP = 2.0


def _looks_like_prompt_echo(text: str) -> bool:
    """模型复读 initial_prompt 的判定。

    只对**首段**用，且要求去掉标点后仍是提示语的子串 —— 宁可漏判（多一行提示语），
    也不能误删真实台词。
    """
    compact = re.sub(r"[^\w]", "", text)
    return len(compact) >= 4 and compact in _PROMPT_COMPACT

#: 繁转简。whisper 的 simplified 偏好只是「倾向」，仍会混出繁体字，
#: 所以出字后再统一过一遍。opencc 是**可选**依赖：没装就原样返回，
#: 不能因为少一个包让整个转写报错。
_SIMPLIFIER: Any = None
_SIMPLIFIER_LOCK = threading.Lock()


def _to_simplified(text: str) -> str:
    global _SIMPLIFIER
    with _SIMPLIFIER_LOCK:
        if _SIMPLIFIER is None:
            try:
                from opencc import OpenCC
            except Exception:
                _SIMPLIFIER = False
            else:
                try:
                    _SIMPLIFIER = OpenCC("t2s")
                except Exception:  # pragma: no cover - 词典缺失
                    _SIMPLIFIER = False
    if not _SIMPLIFIER:
        return text
    try:
        return str(_SIMPLIFIER.convert(text))
    except Exception:  # pragma: no cover - 转换失败不该毁掉整段结果
        return text
````


## 5. 热词：让解码器在选字时就往对的方向偏

`backend/app/services/asr_lexicon.py`

热词不是「错字替换表」，是喂给解码器的上下文。真正按语境判断同音字的地方在这里，
判断由模型在解码时完成，不是事后拿规则硬改。

优先级：**手填（`ASR_HOTWORDS`）→ 人名 → 产品型号 / 内部编号 → 素材词频通用词**。

````python
def custom_words(raw: str) -> list[str]:
    """解析设置里的自定义热词（英文逗号 / 中文逗号 / 顿号 / 空白都当分隔符）。"""
    for separator in ("，", "、", "；", ";", "\n", "\t", " "):
        raw = raw.replace(separator, ",")
    words: list[str] = []
    for item in raw.split(","):
        word = item.strip()
        if word and word not in words:
            words.append(word)
    return words
````


### 5.1 人名：只认明确写法

````python
#: 会议纪要里明确列名字的字段。这类字段的格式在同一个人的文档里很稳定，
#: 是「这场会谁在场」最可靠的来源 —— 比统计「XX：」靠谱得多（后者会把
#: 「来源：」「说明：」也算进去）。
_ATTENDEE_LABELS = (
    "参会人员", "参会人", "参会", "参加人员", "参加人",
    "出席人员", "出席人", "出席", "与会人员", "与会",
    "列席人员", "列席", "记录人", "主持人", "汇报人",
)
#: 长词优先，否则 `参会` 会先把 `参会人员` 吃掉一半
_LABEL_PATTERN = "|".join(sorted(_ATTENDEE_LABELS, key=len, reverse=True))
_ATTENDEE_FIELD = re.compile(
    # 捕获到「下一个字段名 + 冒号」为止：纪要常写成
    # `记录人：王芳参会：张伟、李娜`，中间连空格都没有
    rf"(?:{_LABEL_PATTERN})[：:]\s*([^\n]*?)(?=\s*(?:{_LABEL_PATTERN})[：:]|$)",
    re.MULTILINE,
)

#: 转写稿里的说话人：`[00:12] 张伟：……`。有时间戳这个上下文，误判很少。
_SPEAKER_LINE = re.compile(r"(?m)^\[\d{1,2}:\d{2}(?::\d{2})?\]\s*([\u4e00-\u9fff]{2,4})[：:]")

#: 字段里的多个名字：顿号、逗号、分号、空格、残留的冒号都可能用。
_NAME_SPLIT = re.compile(r"[、,，;；/|\s：:]+")

#: 常见中文姓氏。**这一条是必须的**：不按姓氏筛，「参会：销售部、财务部」会把
#: 部门名当成人名塞进 prompt。宁可漏（少见姓），也不要错到把「研发」当人。
_SURNAMES = frozenset(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董"
    "袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟"
    "熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤常温康施文"
    "牛樊葛邢安齐易乔伍庞颜倪庄聂章鲁岳翟殷詹申欧耿关兰焦俞左柳甘祝包宁尚符"
    "舒阮柯纪梅童凌毕单季裴霍涂成苗谷盛曲翁冉骆蓝路游辛靳管柴蒙鲍华喻祁蒲房"
    "滕屈饶解牟艾尤阳时穆农司卓古吉缪简车项连芦麦褚娄窦戚岑景党宫费卜冷晏席"
    "卫米柏宗瞿桂全佟应臧闵苟邬边卞姬师和仇栾隋商刁沙荣巫寇桑郎甄丛仲虞敖巩"
    "明佘池查麻苑迟邝"
)

#: 姓氏对得上、但显然不是人的词（「时间」「地点」这类字段名最容易撞车）。
_NOT_NAMES = frozenset(
    {
        "时间", "地点", "议题", "主题", "会议", "部门", "全体", "全员", "各位",
        "人员", "同事", "大家", "客户", "领导", "高层", "团队", "项目", "费用",
        "金额", "问题", "结果", "内容", "备注", "附件", "纪要", "议程", "名单",
        "单位", "组织", "集团", "公司", "中心", "方案", "计划", "进度", "风险",
        "需求", "质量", "流程", "制度", "规则", "标准", "数据", "报表", "指标",
        "目标", "任务", "上午", "下午", "晚上", "今天", "明天", "本周", "下周",
        "上月", "本月", "季度", "年度",
    }
)
````

````python
def _looks_like_name(word: str) -> bool:
    """两到四个汉字、以常见姓氏开头、又不是字段名 —— 才当成人名。"""
    if not 2 <= len(word) <= 4:
        return False
    if word in _NOT_NAMES:
        return False
    if word[0] not in _SURNAMES:
        return False
    return all("\u4e00" <= char <= "\u9fff" for char in word)
````

````python
def people(corpus: str, limit: int = 4) -> list[str]:
    """从用户素材里认出「这场会都有谁」。

    人名的正确率最要紧：叫错一次，整篇纪要里每一次出现都是错的。所以只认两种
    **明确**的写法，不做任何猜测式抽取：

    1. 纪要里的名单字段 —— `参会：张伟、李娜`、`记录人：王芳`。字段本身就是声明，
       出现一次就算数。
    2. 转写稿的说话人行 —— `[00:12] 张伟：……`。带时间戳才算，且要出现两次以上。

    两条都要过「姓氏表 + 非字段名」两道筛子。宁可漏掉少见姓的人（他还能靠
    `ASR_HOTWORDS` 手填补上），也不要把「销售部」当成人名写进 prompt。
    """
    if limit <= 0 or not corpus:
        return []

    score: dict[str, int] = {}
    order: list[str] = []
````


### 5.2 产品名 / 型号 / 内部编号：从素材里现取

````python
#: 专名（产品名 / 型号 / 内部编号）的识别式。
#:
#: 只认「英数混排」：`DHT22`、`SSD1306`、`ESP32-DevKit`、`OPS-20261109-0731`。
#: 中文专名认不出来 —— 没有分词就分不清「温湿度采集」和「项目进度」哪个是名字，
#: 硬猜只会把普通词塞进 prompt 挤掉预算，所以中文的留给 `ASR_HOTWORDS` 手填。
_PROPER_NOUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-+.][A-Za-z0-9]+)*")

#: 抓到这些后缀说明匹配的是文件名（`W45.txt`），不是产品名。
_FILE_SUFFIXES = frozenset(
    {
        "txt", "md", "doc", "docx", "pdf", "xls", "xlsx", "ppt", "pptx",
        "csv", "json", "html", "png", "jpg", "jpeg", "wav", "mp3", "mp4", "mov",
    }
)

#: 英文里的功能词。它们也「含大写」（句首）或反复出现，但对选字毫无帮助。
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "this", "that", "these", "those",
        "you", "your", "are", "was", "were", "will", "would", "shall", "should",
        "have", "has", "had", "not", "but", "all", "any", "can", "could", "may",
        "might", "must", "our", "their", "its", "it", "is", "be", "been", "being",
        "of", "to", "in", "on", "at", "as", "by", "or", "if", "then", "than",
        "so", "we", "they", "he", "she", "use", "used", "using", "make", "made",
        "get", "got", "new", "old", "see", "also", "more", "most", "other",
        "some", "such",
    }
)

#: 专名里单个词的长度上限。再长基本是路径或一长串编号，念都念不出来。
_MAX_PROPER_LEN = 20
````

````python
def proper_nouns(corpus: str, limit: int = 6, *, max_chars: int = 40) -> list[str]:
    """从用户素材里捞出产品名 / 型号 / 内部编号。

    这一类词是转写错得最离谱的：`DHT22` 会被写成「DHT 二二」「D H T 二十二」，
    `OPS-20261109-0731` 干脆变成一串中文。它们**不能靠手填维护**——型号和编号
    一直在变，靠人记一定会漏。所以从素材里统计：出现过两次以上的英数串才算数，
    一次的多半是笔误或路径碎片。

    **为什么只认英数。** 中文没有词边界，「温湿度采集」和「项目进度」在字面上
    是同一种东西，抽出来就是普通词，塞进 prompt 只会挤掉真正有用的预算。
    中文人名、内部简称留给设置里的手填词。

    返回按出现次数降序；同一写法的大小写变体（`Dht22` / `DHT22`）合并，取出现
    最多的那个写法 —— whisper 会照着 prompt 里的样子输出，写对一次能省掉一整篇
    的错字。
    """
    if limit <= 0 or not corpus:
        return []

    spelled: Counter[str] = Counter()
    for match in _PROPER_NOUN_RE.finditer(corpus):
        word = match.group(0).rstrip(".")
        # 长度门槛顺带滤掉 `MB`、`NC`、`V3` 这类两字母缩写：会议里没人念，占位置
        if len(word) < 3 or len(word) > _MAX_PROPER_LEN:
            continue
        if word.rsplit(".", 1)[-1].lower() in _FILE_SUFFIXES:
            continue  # `W45.txt` 是文件名
        if word.lower() in _STOPWORDS:
            continue
        # 纯数字开头的不可能（正则要求字母开头）；剩下要求「有大写或数字」，
        # 否则 hello / project 这种人人在用的英文词也会进来
        if not any(char.isdigit() or char.isupper() for char in word):
            continue
        spelled[word] += 1

    # 大小写归一：`Esp32` 5 次 + `ESP32` 3 次 → `Esp32` 记 8 次（取出现最多的写法）
    merged: dict[str, tuple[int, str]] = {}
    for word, count in spelled.items():
        key = word.casefold()
        total, best = merged.get(key, (0, word))
        total += count
        if count > spelled.get(best, 0):
            best = word
        merged[key] = (total, best)

    picked: list[str] = []
    used = 0
    ranked = [(count, word) for count, word in merged.values() if count >= 2]
    # 全大写、纯字母、五个字母以上的（`NORMAL`、`ALARM`、`OKAY`）多半是代码里的
    # 状态值或常量，不是产品名 —— 它们在素材里出现得很频繁，光按次数排会被顶到
    # 前面，把真正的型号挤掉。降权而不是删除：万一真是个缩写（`REDIS`），还有机会。
    ranked.sort(
        key=lambda pair: (
            bool(len(pair[1]) >= 5 and pair[1].isalpha() and pair[1].isupper()),
            -pair[0],
            len(pair[1]),
        )
    )
    for _count, word in ranked:
        cost = len(word) + (1 if picked else 0)
        if used + cost > max_chars:
            continue  # 太长的编号跳过，别把预算吃光，后面还有通用词要放
        picked.append(word)
        used += cost
        if len(picked) >= limit:
            break
    return picked
````


### 5.3 通用词排序 + prompt 拼装

````python
def rank(corpus: str, limit: int = 12) -> list[str]:
    """按用户语料里的出现次数排序，取前 `limit` 个。

    - **没有语料**（刚装好、一篇素材都没有）：退回默认顺序，让第一次转写就有词表可用；
    - **有语料**：只保留在本人的材料里出现过的词。一个词从来没在他的文档里出现过，
      说明不是他的常用词，塞进 prompt 只会给解码器添噪。
    """
    if limit <= 0:
        return []
    if not corpus:
        return list(HOTWORDS[:limit])

    counts = {word: corpus.count(word) for word in HOTWORDS}
    hit = [word for word in HOTWORDS if counts[word]]
    if not hit:
        # 语料里一个都对不上（纯英文材料 / 刚换领域）：别硬塞通用词，交给模型自己判断
        return []
    hit.sort(key=lambda word: (-counts[word], _ORDER[word]))
    return hit[:limit]
````

````python
def build_prompt(base: str, hotwords: Iterable[str] = (), *, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """把热词接在短提示后面，超预算就截断（宁可少几个词，也不要挤掉提示语）。"""
    budget = max_chars - len(base) - len("常用词：") - 1
    picked: list[str] = []
    used = 0
    for word in hotwords:
        cost = len(word) + (1 if picked else 0)
        if used + cost > budget:
            break
        picked.append(word)
        used += cost
    if not picked:
        return base
    return f"{base}常用词：{'、'.join(picked)}。"
````

````python
def merge_words(custom: Sequence[str], learned: Sequence[str], limit: int = 12) -> list[str]:
    """用户手填的词排最前（那是他明确说「我叫这个」的），其余按学到的顺序补。"""
    merged: list[str] = []
    for word in list(custom) + list(learned):
        if word and word not in merged:
            merged.append(word)
        if len(merged) >= limit:
            break
    return merged
````


> `HOTWORDS` 本身是一张约 110 个词的数据表，在 `asr_lexicon.py` 第 34–156 行，
> 按「项目交付 / 财务合同 / 客户销售 / 数据指标 / 组织协作 / 技术运维 / 会议本身」分组，
> 顺序即冷启动优先级。


## 6. 事后再校一遍：只许换词，不许改稿

`backend/app/services/asr_proofread.py`

`base` 档的中文语言模型太浅，热词只能把概率往对的方向拨，硬伤仍会漏。
这一步把转写稿连同热词交给大一点的模型，让它指出「这里应该是哪个词」，
然后由代码过四道闸。**任何一步失败都原样返回**——宁可一个字不改，
也不能把用户的录音改出他没说过的话。

````python
#: 一次交给模型的字数。太长（几万字）既贵又容易让模型「开始总结」；
#: 按行切块、逐块校对，块与块之间不重叠（替换只发生在块内）。
_CHUNK_CHARS = 6000

#: 单块请求的超时。转写本身要跑几分钟，这里多等十几秒不算什么；
#: 但卡住就得放弃，否则一个坏网关能把整个识别队列堵死。
_CHUNK_TIMEOUT = 15.0

#: 一次校对最多接受多少处替换
_MAX_PAIRS = 40

#: 同一个「错写法」在原文出现超过这么多次就跳过（多半是正常词）
_MAX_SAME_FORM = 3

_SYSTEM = """你是会议录音转写稿的校对员。下面这段是语音识别的结果，可能有个别同音字写错
（例如把「验收」写成「厌收」，把「排期」写成「排齐」）。

你只做一件事：把写错的词换成正确的写法。

硬性规则：
1. 只能替换**字数相同**的词。
2. 不许改写句子、不许调整语序、不许增删内容、不许动标点和时间戳。
3. 没有把握就不要改；宁可漏改，不可改错。
4. 只输出 JSON 数组，每个元素是 ["错写法","正确写法"]；没有错误就输出 []。
   除了这个数组，不要输出任何别的内容。"""


def _strip_fence(text: str) -> str:
    """模型偶尔会套 ```json 围栏，去掉再解析。"""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def parse_pairs(raw: str) -> list[tuple[str, str]]:
    """从模型回复里取出配对；格式不对就当没改。"""
    text = _strip_fence(raw)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    pairs: list[tuple[str, str]] = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            wrong, right = str(item[0]).strip(), str(item[1]).strip()
            if wrong and right and wrong != right and (wrong, right) not in pairs:
                pairs.append((wrong, right))
    return pairs


def apply_pairs(text: str, pairs: Sequence[tuple[str, str]]) -> tuple[str, list[tuple[str, str]]]:
    """把配对照到正文上，逐条过四道闸。"""
    applied: list[tuple[str, str]] = []
    for wrong, right in pairs:
        if len(applied) >= _MAX_PAIRS:
            break
        if len(wrong) != len(right):  # 等长：杜绝增删内容
            continue
        if wrong not in text:  # 原文里没有这个写法
            continue
        if text.count(wrong) > _MAX_SAME_FORM:  # 出现太多次 → 多半是正常词
            continue
        text = text.replace(wrong, right)
        applied.append((wrong, right))
    return text, applied


def _chunks(text: str) -> list[str]:
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > _CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


async def _ask(provider, chunk: str, hotwords: Sequence[str]) -> str:
    words = "、".join(hotwords) if hotwords else "（无）"
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"参考词表：{words}\n\n转写稿：\n{chunk}"},
    ]
    result = await asyncio.wait_for(provider.chat(messages, temperature=0.0), timeout=_CHUNK_TIMEOUT)
    return str(getattr(result, "text", "") or "")


def proofread(
    text: str,
    hotwords: Sequence[str] = (),
    *,
    settings: Settings,
) -> tuple[str, list[tuple[str, str]]]:
    """返回 (校对后的文本, 实际替换的配对)。没有可用的模型就原样返回。"""
    if not text.strip():
        return text, []
    try:
        providers = build_configured_providers(settings)
    except Exception:  # pragma: no cover - 配置异常不该影响识别结果
        return text, []
    if not providers:
        return text, []
    provider = next(iter(providers.values()))

    corrected: list[str] = []
    applied_all: list[tuple[str, str]] = []
    for chunk in _chunks(text):
        try:
            reply = asyncio.run(_ask(provider, chunk, hotwords))
        except Exception:
            # 超时 / 网络错 / 供应商报错：这一块保持原样，后面的块也不用再试
            corrected.append(chunk)
            continue
        fixed, applied = apply_pairs(chunk, parse_pairs(reply))
        corrected.append(fixed)
        applied_all.extend(applied)
        if len(applied_all) >= _MAX_PAIRS:
            break
    return "\n".join(corrected), applied_all[:_MAX_PAIRS]
````


## 7. 可调参数

| 配置项 | 默认 | 作用 |
|---|---|---|
| `ASR_MODEL` | `base` | 模型档位：`base` 145MB / `small` 460MB（更准）/ `medium` 1.5GB |
| `ASR_LANGUAGE` | `zh` | `zh` 时加中文提示并繁转简；`auto` 交给模型判语种 |
| `ASR_ENDPOINT` | hf-mirror | 模型下载源，国内直连 huggingface.co 常 502 |
| `ASR_MAX_MINUTES` | `60` | 单次转写上限，超出部分截断并在正文注明 |
| `ASR_HOTWORDS` | 空 | 手填兜底：少见姓的人、还没进过文档的客户代号 |
| `ASR_PEOPLE` | `4` | 自动认几个人名（0 = 关） |
| `ASR_PROPER_NOUNS` | `6` | 自动抽几个型号（0 = 关） |
| `ASR_HOTWORD_LIMIT` | `12` | 热词总数上限（prompt 预算有限） |
| `ASR_PROOFREAD` | `true` | 是否做第 6 步；开启会把转写文本发给当前模型供应商 |

## 8. 已知边界

- **视频只取音轨**：画面上的字（PPT、白板）不识别。会议视频如果把关键信息放在画面里，
  需要截图后按图片走 OCR。
- **`base` 档的同音字仍会错**：第 5、6 步是「降低概率」不是「消灭」，改名换姓级别的
  关键场合建议换 `small` 并把手填词配齐。
- **单文件体积**：受 `MAX_MEDIA_MB` 限制（默认 200MB），更长的会议要分段落盘。
- **第二层是否外发**：`ASR_PROOFREAD=true` 会把转写文本发给当前配置的模型供应商；
  要全程离线就设 `false`，那时只剩本地两层。
