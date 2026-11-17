"""API 请求/响应模型（Pydantic）。

约定：所有 JSON 响应顶层带 trace_id；字段尽量给 description，便于前端 gen:api 生成类型与文档。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...domain.formats import ARTIFACT_TYPE_HINT, OUTPUT_FORMAT_HINT


class ErrorDetail(BaseModel):
    code: str = Field(description="错误码，见 core/errors.py ErrorCode 枚举")
    message: str = Field(description="人类可读错误信息")
    details: Any | None = Field(default=None, description="结构化补充信息（可选）")


class ErrorResponse(BaseModel):
    trace_id: str = Field(description="请求追踪 ID")
    error: ErrorDetail


# ---------- health ----------
class HealthOut(BaseModel):
    trace_id: str
    status: str = Field(description="服务状态，固定 ok")
    version: str = Field(description="后端版本")
    git_sha: str = Field(description="当前提交 SHA（进程启动时载入的版本）")
    git_sha_live: str = Field(
        default="",
        description="仓库当前 HEAD；与 git_sha 不同说明后端进程比代码旧，需要重启",
    )
    mode: str = Field(description="mock | real")
    provider: str = Field(description="当前模型供应商")
    model: str = Field(description="当前模型名")
    degraded: bool = Field(description="真实模型探测失败后是否已降级")
    degraded_reason: str = Field(
        default="", description="降级原因（人话，便于判断是 Key、网络还是模型名的问题）"
    )
    mock: bool
    tools: int = Field(description="已注册工具数量")
    subagents: int = Field(description="子智能体数量")
    skills: list[str] = Field(description="已加载技能名")
    prompt_version: str
    engine: str = Field(default="real", description="配置的引擎：mock | real | deepagents")
    engine_effective: str = Field(
        default="mock", description="实际生效引擎（无 Key/引擎未实现时自动降级）"
    )
    engine_supported: bool = Field(
        default=True, description="配置的引擎是否已有实现（deepagents 为 planned）"
    )
    engine_reason: str = Field(
        default="",
        description="实际生效引擎与配置不一致时的人话原因（开关/缺 Key/探测失败）",
    )
    model_ready: bool = Field(
        default=True,
        description="真实引擎下是否有可用模型（演示模式恒为 true）；false 时界面应拦住发送",
    )
    model_hint: str = Field(
        default="", description="model_ready=false 时的引导文案（怎么把模型配上）"
    )
    engines: list[str] = Field(default_factory=list)
    approval_tools: list[str] = Field(default_factory=list)
    media: dict[str, Any] = Field(
        default_factory=dict,
        description="媒体识别能力：ocr / asr 是否可用、转写模型名、单次上限（分钟）",
    )


# ---------- threads ----------
class ThreadCreateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = Field(default=None, description="会话标题，缺省为『新会话』")


class ThreadUpdateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = Field(default=None, description="重命名（非空）")
    pinned: bool | None = Field(default=None, description="是否置顶")


class ThreadBulkDeleteIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    thread_ids: list[str] = Field(
        min_length=1,
        max_length=200,
        description="要软删的会话 ID（1–200 个；不存在的 ID 忽略，不报错）",
    )


class ThreadReorderOut(BaseModel):
    trace_id: str
    reordered: int = Field(default=0, description="真正写进库的会话条数")


class ThreadReorderIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    thread_ids: list[str] = Field(
        min_length=1,
        max_length=500,
        description="按新顺序排好的会话 ID（从前往后）；顺序写入 threads.sort_index",
    )


class ThreadBulkDeleteOut(BaseModel):
    trace_id: str = Field(description="请求追踪 ID")
    deleted: int = Field(description="真正被软删的会话数（已删/不存在的 ID 不计）")


class ThreadOut(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    pinned: bool = False
    message_count: int = 0
    artifact_count: int = 0


class ThreadListOut(BaseModel):
    trace_id: str
    threads: list[ThreadOut]
    total: int = Field(default=0, description="过滤后总数")
    page: int = Field(default=1)
    page_size: int = Field(default=20)


class MessageOut(BaseModel):
    message_id: str
    thread_id: str
    role: str
    content: str
    run_id: str | None = None
    created_at: str
    extra: dict[str, Any] = Field(default_factory=dict)


class ArtifactOut(BaseModel):
    artifact_id: str
    type: str = Field(description=ARTIFACT_TYPE_HINT)
    filename: str
    size: int
    sha256: str = ""
    content_type: str = ""
    created_at: str
    thread_id: str
    run_id: str | None = None
    download_url: str
    preview_url: str
    extra: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(
        default_factory=list,
        description="生成该产物的素材文件名；同一天多份产物靠它区分是哪一份",
    )
    has_preview_file: bool = False
    has_text: bool = False


class MediaStatusOut(BaseModel):
    """媒体素材的识别状态（图片 OCR / 音视频转写）。"""

    kind: str = Field(description="image / transcript / audio / video")
    label: str = Field(default="", description="中文类别：图片 / 会议记录 / 会议录音 / 会议视频")
    status: str = Field(default="ready", description="processing 识别中 / ready 可用 / failed 失败")
    error: str = Field(default="", description="失败原因（给人看的）")
    # 只有「失败了」才谈得上重试：识别中/已可用的素材给 true，界面会白摆一个重试按钮
    retryable: bool = Field(default=False, description="失败是否值得重试（缺组件也可以装完再试）")
    meta: dict[str, Any] = Field(default_factory=dict, description="时长、句数、引擎等")


class FileOut(BaseModel):
    file_id: str
    artifact_id: str
    filename: str
    size: int
    type: str
    ext: str
    chars: int
    parsed: bool
    status: str = Field(default="ready", description="processing / ready / failed")
    note: str | None = Field(default=None, description="收下了但读不出文字时的说明")
    media: MediaStatusOut | None = None
    text_preview: str = ""
    created_at: str


class ThreadDetailOut(ThreadOut):
    messages: list[MessageOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    uploads: list[UploadItemOut] = Field(default_factory=list, description="本会话的素材文件")


class ThreadDetailEnvelope(ThreadDetailOut):
    trace_id: str


class ThreadCreateOut(ThreadOut):
    trace_id: str


# ---------- files ----------
class UploadItemOut(BaseModel):
    file_id: str
    artifact_id: str
    filename: str
    size: int
    type: str = Field(description="扩展名（不含点）")
    ext: str
    chars: int = Field(description="解析后字数")
    parsed: bool
    status: str = Field(default="ready", description="processing 识别中 / ready 可用 / failed 失败")
    note: str | None = Field(
        default=None,
        description="收下了但读不出文字时的说明（旧版 .doc、压缩包等），parsed 会是 false",
    )
    media: MediaStatusOut | None = Field(default=None, description="媒体素材类别与识别状态")
    text_preview: str = Field(default="", description="解析文本前 200 字预览")
    created_at: str | None = Field(default=None, description="上传时间（会话详情的素材列表会带）")


class UploadResultOut(UploadItemOut):
    """兼容 v0.1 单文件响应（顶层为第一个文件字段），并追加 files 列表。"""

    trace_id: str
    files: list[UploadItemOut] = Field(description="本次上传的全部文件")


# ThreadDetailEnvelope 声明在 UploadItemOut 之前，`from __future__ import annotations`
# 会把 uploads 的类型留成 ForwardRef（缺它生成 OpenAPI 时直接报 not fully defined）。
ThreadDetailEnvelope.model_rebuild()


class FileListOut(BaseModel):
    trace_id: str
    thread_id: str
    files: list[FileOut]


class FileRecognizeOut(BaseModel):
    """重试识别的回执：立刻返回 processing，结果由文件列表轮询拿到。"""

    trace_id: str
    artifact_id: str
    status: str
    media: MediaStatusOut | None = None


class DeleteOut(BaseModel):
    trace_id: str
    deleted: bool = True
    artifact_id: str
    trashed: list[str] = Field(default_factory=list, description="移入回收站的文件路径")


class ArtifactBatchDeleteIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artifact_ids: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="待软删的产物 ID 列表（单次上限 200，重复 ID 自动去重）",
    )


class ArtifactBatchDeleteItem(BaseModel):
    artifact_id: str
    deleted: bool
    message: str = Field(default="", description="失败原因（成功时为空）")


class ArtifactBatchDeleteOut(BaseModel):
    trace_id: str
    requested: int = Field(description="去重后的请求数量")
    deleted: int = Field(description="实际软删成功数量")
    failed: list[ArtifactBatchDeleteItem] = Field(default_factory=list)
    trashed: list[str] = Field(default_factory=list, description="移入回收站的文件路径")


class ArtifactTrashItem(ArtifactOut):
    """回收站条目：多一个删除时间与「文件是否可挪回」标记。"""

    deleted_at: str | None = Field(default=None, description="软删时间")
    restorable: bool = Field(default=True, description="文件仍在回收站目录，可恢复")


class ArtifactTrashListOut(BaseModel):
    trace_id: str
    artifacts: list[ArtifactTrashItem]
    total: int
    page: int
    page_size: int


# ---------- runs ----------
class RunRequestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str = ""
    mode: str | None = Field(default=None, description="mock | real；缺省按配置")
    output_format: str | None = Field(
        default=None,
        description=(f"产物格式：{OUTPUT_FORMAT_HINT}；缺省时与首个上传素材同格式，无素材时 docx"),
    )
    run_id: str | None = Field(
        default=None, description="断线续传：配合 Last-Event-ID / after 回放该运行事件"
    )
    project_id: str | None = Field(
        default=None, description="左栏选中的项目 ID：本轮把项目里的文档作为素材一起交给 Agent"
    )
    project_files: list[str] | None = Field(
        default=None, description="只带项目里的这些文件（相对路径）；缺省带最近修改的若干文档"
    )
    approval_mode: str | None = Field(
        default=None,
        description=(
            "审批策略：always_ask（高风险一律问）| risky（按设置的规则，默认）| "
            "all_allow（全权交给 Agent，不再打断）"
        ),
    )
    attachment_ids: list[str] | None = Field(
        default=None,
        description=(
            "本轮使用的附件 ID（会话内上传的素材）；缺省表示沿用该会话全部素材（兼容旧客户端）"
        ),
    )
    doc_style: dict[str, Any] | None = Field(
        default=None,
        description=(
            "本轮文档格式（用户在输入区「文档格式」里点的那几项）："
            "font（中文字体）/ font_en / size（字号，如 12 或「小四」）/ "
            "bold / italic / underline / line（行距，如 1.5 或「固定值28磅」）/ "
            "indent_chars（首行缩进字符数）/ align（justify/left/center/right）。"
            "缺省表示不干预，由 Agent 按版式预设决定"
        ),
    )


class RunOut(BaseModel):
    run_id: str
    thread_id: str
    status: str = Field(description="running | completed | rejected | failed | cancelled")
    mode: str
    engine: str
    provider: str
    model: str
    tokens: int
    cost_cny: float
    started_at: str
    finished_at: str | None = None
    error_code: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RunListOut(BaseModel):
    trace_id: str
    runs: list[RunOut]
    total: int = 0
    page: int = 1
    page_size: int = 20


class RunEnvelope(RunOut):
    trace_id: str


class RunCancelOut(BaseModel):
    trace_id: str
    run_id: str
    cancelled: bool = Field(description="本次是否真正中断了运行")
    status: str = Field(description="取消后（或原本）的运行状态")
    idempotent: bool = Field(description="重复取消时为 true")


class RunEventOut(BaseModel):
    seq: int
    event: str
    data: dict[str, Any]
    created_at: str


class RunEventsOut(BaseModel):
    trace_id: str
    run_id: str
    events: list[RunEventOut]


# ---------- approvals ----------
class ApprovalRequestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decision: str = Field(description="approved | rejected")
    comment: str | None = None


class ApprovalDecisionOut(BaseModel):
    trace_id: str
    approval_id: str
    decision: str
    decided_at: str
    resumed: bool


class ApprovalOut(BaseModel):
    approval_id: str
    thread_id: str
    run_id: str | None
    tool: str
    risk: str
    payload: dict[str, Any] = Field(default_factory=dict)
    decision: str | None = None
    comment: str | None = None
    created_at: str
    decided_at: str | None = None
    policy_version: str = "v1"
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------- audit / usage ----------
class AuditRunOut(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None = None
    status: str
    mode: str
    engine: str
    provider: str
    model: str
    tokens: int
    cost_cny: float
    elapsed_ms: int
    error_code: str | None = None
    degraded: bool = False
    request_ids: list[str] = Field(
        default_factory=list,
        description="最近几次模型调用的供应商请求 id（用于与供应商控制台对账）",
    )
    calls: int = Field(default=0, description="本轮外部模型调用次数")
    verified_calls: int = Field(
        default=0, description="带回执 id 的调用次数；小于 calls 说明有调用没拿到回执"
    )
    provider_model: str | None = Field(
        default=None,
        description="供应商回执里的实际模型名，可能与配置的 model 不同（官方侧会做重路由）",
    )
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class AuditOut(BaseModel):
    trace_id: str
    thread_id: str
    thread_title: str = ""
    runs: list[AuditRunOut]
    approvals: list[ApprovalOut]
    artifacts: list[ArtifactOut]


class UsageDayOut(BaseModel):
    date: str
    runs: int
    tokens: int
    cost_cny: float
    elapsed_ms: int
    calls: int = Field(default=0, description="当天发生的大模型计费请求次数")
    mock_runs: int = Field(default=0, description="当天本地 mock 运行数（不计费）")


class UsageProviderOut(BaseModel):
    provider: str
    runs: int
    tokens: int
    cost_cny: float


class UsageModelOut(BaseModel):
    model: str
    runs: int
    tokens: int
    cost_cny: float


class LedgerBucketOut(BaseModel):
    """账本按维度分组的一行（用途 / 供应商 / 日期）。"""

    calls: int = Field(description="发出去的请求数，含失败")
    failed_calls: int = Field(default=0, description="其中失败或被截断重试的请求")
    tokens: int = 0
    cost_cny: float = 0.0


class LedgerPurposeOut(LedgerBucketOut):
    purpose: str = Field(
        description="engine 主循环 | reading 理解层 | probe 探测 | title 标题 | enhance 增强 | skill 技能"
    )


class LedgerProviderOut(LedgerBucketOut):
    provider: str


class LedgerDayOut(LedgerBucketOut):
    date: str


class UsageLedgerOut(BaseModel):
    """全量调用账本：**这一栏才接近供应商控制台的口径**。

    差异来源是设计使然而非缺陷：`runs` 口径只统计运行内成功的调用；
    账本还包括探测 / 标题 / 提示词增强 / 技能起草这些不属于任何 run 的请求，
    以及失败与重试（失败的请求对面也收，只是没给 usage）。
    """

    calls: int = Field(description="账本里的请求总数（含失败）")
    failed_calls: int = Field(default=0, description="失败或重试的请求数")
    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    cost_cny: float = Field(default=0.0, description="按现价重算的估算金额")
    since: str | None = Field(
        default=None,
        description="账本最早一条记录的时间；此前的历史请求没有账可查，对不回来",
    )
    by_purpose: list[LedgerPurposeOut] = Field(default_factory=list)
    by_provider: list[LedgerProviderOut] = Field(default_factory=list)
    by_day: list[LedgerDayOut] = Field(default_factory=list)


class UsageOut(BaseModel):
    trace_id: str
    thread_id: str | None = None
    range: str = Field(default="7d", description="7d | 30d | today | all")
    since: str | None = None
    runs: int
    real_runs: int = Field(default=0, description="真实模型调用运行数（会产生费用）")
    mock_runs: int = Field(default=0, description="本地 mock 运行数（不计费）")
    calls: int = Field(
        default=0,
        description="运行内已记账的真实请求数（一次运行可含多次调用）；不含运行外请求与失败重试",
    )
    tokens: int = Field(description="只统计真实调用的 tokens")
    cost_cny: float = Field(description="只统计真实调用的成本；按当前价目表重算，mock 不计费")
    cache_hit_tokens: int = Field(default=0, description="输入里命中上下文缓存的 tokens")
    cache_miss_tokens: int = Field(default=0, description="输入里未命中缓存的 tokens（按全价计）")
    ledger: UsageLedgerOut | None = Field(
        default=None,
        description="全量调用账本（含 run 外调用与失败重试）；None = 账本不可用",
    )
    price_note: str = Field(default="", description="成本口径说明：单价、高峰/闲时")
    elapsed_ms: int
    avg_elapsed_ms: int
    by_status: dict[str, int]
    by_provider: list[UsageProviderOut] = Field(default_factory=list)
    by_model: list[UsageModelOut] = Field(default_factory=list)
    by_day: list[UsageDayOut]


# ---------- settings / models ----------
class SettingSecretOut(BaseModel):
    configured: bool
    ref: str = Field(description="密钥环境变量引用，如 env:DASHSCOPE_API_KEY")
    via: str | None = Field(default=None, description="兼容回退来源，如 env:OPENAI_API_KEY")


class SettingsOut(BaseModel):
    trace_id: str
    engine: str = Field(description="引擎：mock | real | deepagents")
    approval_rules: list[str] = Field(description="需审批工具列表")
    mock_mode: bool
    model_provider: str
    model_name: str
    fallback_chain: list[str]
    max_upload_mb: int
    model_timeout_seconds: float
    approval_timeout_seconds: int
    feature_flags: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, str] = Field(
        description="每个可配置项的来源：db | env | default",
        examples=[{"model_provider": "env", "approval_rules": "db"}],
    )
    env_hints: dict[str, str] = Field(
        description="对应环境变量名", examples=[{"model_provider": "MODEL_PROVIDER"}]
    )
    secrets: dict[str, SettingSecretOut] = Field(description="模型 Key 只返回引用，不返回明文")
    database_url: str
    upload_dir: str
    artifact_dir: str
    log_level: str
    environment: str


class SettingsUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str | None = Field(default=None, description="mock | real | deepagents")
    approval_rules: str | list[str] | None = None
    mock_mode: bool | None = None
    model_provider: str | None = None
    model_name: str | None = None
    fallback_chain: str | list[str] | None = None
    max_upload_mb: int | None = Field(default=None, ge=1, le=200)
    model_timeout_seconds: float | None = None
    approval_timeout_seconds: int | None = None
    feature_flags: dict[str, Any] | None = None


class ModelOut(BaseModel):
    id: str
    provider: str
    base_url: str
    model: str
    api_key_ref: str = Field(description="Key 引用，如 env:DEEPSEEK_API_KEY（不返回明文）")
    configured: bool = Field(description="对应环境变量中的 Key 是否存在")
    enabled: bool
    priority: int
    builtin: bool = Field(default=False, description="是否来自环境变量内置配置")
    last_probe: dict[str, Any] | None = Field(default=None, description="最近一次探测结果")
    extra: dict[str, Any] = Field(default_factory=dict)


class ModelListOut(BaseModel):
    trace_id: str
    models: list[ModelOut]


class ModelEnvelope(ModelOut):
    trace_id: str


class ModelCreateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = Field(default=None, description="更新已有登记时传入")
    provider: str = Field(description="deepseek | qwen | glm | openai | 自定义")
    base_url: str | None = None
    model: str | None = None
    api_key_ref: str | None = Field(default=None, description="只允许 env:NAME 形式；禁止明文 Key")
    priority: int = 100
    enabled: bool = True


class ModelKeyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    api_key: str = Field(description="供应商开放平台获取的 Key 明文；只落本地 .env，不回显")
    env_name: str | None = Field(
        default=None, description="可选：环境变量名（缺省按供应商约定，如 DEEPSEEK_API_KEY）"
    )


class ModelKeyOut(BaseModel):
    trace_id: str
    provider: str
    api_key_ref: str
    configured: bool
    masked: str = Field(description="掩码展示，如 sk-****abcd")
    persisted: bool = Field(description="是否已写入本地 .env（只读文件系统时为 false）")


class ModelKeyDisconnectOut(BaseModel):
    """断开 Key 的回执：configured 恒为 false，persisted=false 说明 .env 删行失败。"""

    trace_id: str
    provider: str
    api_key_ref: str
    configured: bool
    disconnected: bool
    persisted: bool = Field(
        description="是否已从本地 .env 删掉该行（false 时用户需手动删除，Key 仍会随文件分发）"
    )


class ModelBalanceOut(BaseModel):
    trace_id: str
    supported: bool = Field(description="该供应商是否提供余额查询接口（DeepSeek 支持）")
    provider: str
    currency: str = "CNY"
    total_balance: float | None = Field(default=None, description="账户总余额")
    granted_balance: float | None = Field(default=None, description="赠送余额")
    topped_up_balance: float | None = Field(default=None, description="充值余额")
    checked_at: str
    reason: str | None = Field(default=None, description="不支持/查询失败的原因（脱敏）")


class ModelTestOut(BaseModel):
    trace_id: str
    ok: bool
    provider: str
    model: str
    api_key_ref: str
    latency_ms: int
    returned_model: str | None = None
    reason: str | None = Field(default=None, description="失败原因（脱敏，不含 Key）")


# ---------- templates / skills ----------
class TemplateSectionOut(BaseModel):
    heading: str
    source: str = Field(description="summary | progress | data | risk | plan")


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str = ""
    builtin: bool = False
    enabled: bool = True
    sections: list[TemplateSectionOut] = Field(default_factory=list)


class TemplateListOut(BaseModel):
    trace_id: str
    templates: list[TemplateOut]


class TemplateEnvelope(TemplateOut):
    trace_id: str


class TemplateCreateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    name: str
    description: str = ""
    sections: list[TemplateSectionOut] = Field(
        description="小节顺序与数据来源映射",
        examples=[[{"heading": "本周进展", "source": "progress"}]],
    )


class TemplateRenderOut(BaseModel):
    trace_id: str
    run_id: str
    template: str
    artifact: ArtifactOut


class SkillOut(BaseModel):
    name: str
    title: str = Field(default="", description="展示名（frontmatter 的 title，缺省回落 name）")
    description: str
    triggers: list[str] = Field(default_factory=list)
    enabled: bool
    category: str = Field(default="", description="技能分类，技能页的分类筛选用它")
    icon: str = Field(
        default="", description="图标键（doc/sheet/minutes/retro/shield/book），前端映射成图标"
    )
    badge: str = Field(default="", description="角标文案（必备精选 / 新功能推荐），空串表示没有")
    content_chars: int = 0


class SkillListOut(BaseModel):
    trace_id: str
    skills: list[SkillOut]
    prompt_chars: int = Field(description="当前运行时提示词长度，启停技能后立即变化")


class CatalogSkillOut(SkillOut):
    slug: str = Field(description="技能目录名，安装时按它复制目录")
    installed: bool = Field(description="是否已添加到 app/skills（已添加的不再重复安装）")


class SkillCatalogOut(BaseModel):
    trace_id: str
    skills: list[CatalogSkillOut]
    categories: list[str] = Field(description="技能库里出现过的分类，按首见顺序去重")


class SkillInstallOut(BaseModel):
    trace_id: str
    name: str
    slug: str
    skill: SkillOut | None = None


class SkillPatchIn(BaseModel):
    enabled: bool


class SkillDraftIn(BaseModel):
    """「让模型帮你写」的输入：一句话说清这张便签要干什么。"""

    model_config = ConfigDict(extra="ignore")

    idea: str = Field(
        min_length=1,
        max_length=300,
        description="用一句大白话说想要的效果，例如「把录音转成会议纪要，只留结论和待办」",
    )


class SkillDraftOut(BaseModel):
    trace_id: str
    markdown: str = Field(description="完整的 SKILL.md 文本，可直接拿去导入")
    name: str = Field(description="技能内部标识（同名会自动加数字后缀）")
    title: str
    description: str
    triggers: list[str]
    model: str = Field(default="", description="生成用的模型；本地骨架时为空串")
    source: str = Field(description="model = 模型写的；local = 没模型时的本地骨架")
    note: str = Field(default="", description="给用户看的一句说明（要不要改、怎么改）")


class SkillPatchOut(BaseModel):
    trace_id: str
    name: str
    enabled: bool
    prompt_chars: int


# ---------- extensions / artifacts lists ----------
class ToolOut(BaseModel):
    name: str
    description: str
    risk: str
    schema_: dict[str, Any] = Field(alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class ToolListOut(BaseModel):
    trace_id: str
    tools: list[ToolOut]


class SubagentOut(BaseModel):
    name: str
    description: str
    tools: list[str] = Field(default_factory=list)
    status: str
    step_limit: int


class SubagentListOut(BaseModel):
    trace_id: str
    subagents: list[SubagentOut]


class ArtifactListOut(BaseModel):
    trace_id: str
    artifacts: list[ArtifactOut]
    total: int = 0
    page: int = 1
    page_size: int = 20


class ArtifactEnvelope(ArtifactOut):
    trace_id: str


# ---------- feedback ----------
class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = Field(default="idea", description="反馈类型：bug | idea | other")
    message: str = Field(
        min_length=1,
        max_length=1500,
        description="反馈内容（上限 1500 字，超出的部分会被截断）",
    )
    contact: str = Field(default="", max_length=120, description="可选：邮箱或微信，便于回访")
    include_diagnostics: bool = Field(
        default=True, description="是否附带版本/引擎/窗口形态等环境信息（便于定位问题）"
    )
    client: dict[str, str] = Field(
        default_factory=dict,
        description="前端上报的窗口形态/系统/屏幕等展示信息，只用于邮件正文",
    )


class FeedbackOut(BaseModel):
    trace_id: str
    id: str = Field(description="反馈编号（本机存档的文件里也有）")
    kind: str
    saved: bool = Field(description="是否已写入本机存档")
    saved_path: str = Field(description="本机存档文件路径")
    target: str = Field(description="开发者收件邮箱；空串表示还没配置")
    subject: str = Field(description="邮件标题")
    body: str = Field(description="邮件正文（可直接复制粘贴）")
    mailto: str = Field(description="mailto 链接；target 为空时也是空串")
    truncated: bool = Field(default=False, description="正文是否因过长被截断")


# ---------- prompts ----------
class PromptEnhanceIn(BaseModel):
    """输入框右侧「增强提示词」的入参：就取当前输入框里的原文。"""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(
        min_length=1,
        max_length=4000,
        description="当前输入框里的需求原文（上限 4000 字）",
    )
    output_format: str | None = Field(
        default=None,
        max_length=16,
        description=f"期望的产物格式（{OUTPUT_FORMAT_HINT}），只作为改写提示，不改变产物",
    )


class PromptEnhanceOut(BaseModel):
    trace_id: str
    text: str = Field(description="增强后的提示词（直接替换输入框内容）")
    source: str = Field(description="来源：model（模型改写）| rules（本地规则补全）")
    model: str = Field(default="", description="实际使用的模型名；rules 时为空串")
    note: str = Field(default="", description="给用户的一句说明（本地补全时解释为什么）")
