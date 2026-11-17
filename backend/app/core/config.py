"""配置唯一来源（pydantic-settings）。禁止在业务代码里散落 os.getenv。

环境变量来源优先级：进程环境 > 仓库根 .env > 字段默认值。
密钥字段只从环境读取，不做日志/回显。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 显式重导出（`as` 形式）：其它模块从 config 读这两个根是设计意图，不是顺手蹭到的
from .paths import DATA_ROOT as DATA_ROOT
from .paths import RESOURCE_ROOT as RESOURCE_ROOT

# 两个根：RESOURCE_ROOT 放只读资源（前端 dist 等），DATA_ROOT 放用户数据（库/上传/产物/.env）。
# 源码运行两者都是仓库根；打包成 exe 后必须分开，详见 core/paths.py。
# 注意：重导出是各自的模块级绑定，且导入时定死。测试里要换数据根得 monkeypatch
# 这里的 DATA_ROOT（改 paths.DATA_ROOT 不会跟着变），运行中改环境变量也不会重算。
# PROJECT_ROOT 保留为 RESOURCE_ROOT 的旧名，避免一次性改动所有引用点。
PROJECT_ROOT = RESOURCE_ROOT

# 各供应商的 OpenAI 兼容默认 Base URL（可用环境变量覆盖）
#
# workbuddy 故意留空：WorkBuddy 的接口地址按账号/部署而变，写死一个猜测的域名只会让
# 「测试连接」永远失败。留空 → 模型列表里显示「待填接口」，由用户在「设置接口」里填真地址。
PROVIDER_DEFAULTS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "openai": "https://api.openai.com/v1",
    "workbuddy": "",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # .env 属于用户数据：打包版放在数据目录里，用户改完 Key 重启仍然生效
        env_file=str(DATA_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    app_name: str = "office-agent-backend"
    version: str = "0.2.0"
    # 环境标识：兼容 APP_ENV（compose/.env.example 用法）与 ENVIRONMENT 两种写法。
    # 此前只有 environment 字段，导致 compose 里的 APP_ENV=prod 被静默忽略，
    # 「生产环境关闭 /docs」等按环境分支的逻辑永远不生效。
    environment: str = Field(default="dev", validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"))
    log_level: str = "INFO"
    log_format: str = "json"  # json | text
    git_sha: str = ""  # 未显式提供时由 core.utils.detect_git_sha() 填充

    # ---- 模型 ----
    engine: str = "real"  # mock | real | deepagents
    model_provider: str = "mock"
    model_name: str = "mock-scripted"
    model_fallback_chain: str = "mock"
    mock_mode: bool = True
    mock_model_speed: float = 0.05
    model_timeout_seconds: float = 30.0
    # 一次运行的全局步数上限：**只防死循环，不是「做到第几步就交差」**。
    # 8 → 24 → 60：一次交付里「读 N 份材料 → 检索核对 → 写 → 自查 → 改一版」，
    # 十几二十步是常态；卡在 24 会在收尾前把任务掐断，用户看到的是「做了一半的文件」。
    # 到点不会给用户发任何提示，只写 stop_reason 和日志——步数是我们的工程参数，
    # 不该变成他要关心的东西。真实模式下想更省，在 .env 里把 MODEL_MAX_STEPS 调小即可。
    model_max_steps: int = 60
    # 单次调用的输出上限。**0 = 不限制**（默认）：请求里不带 `max_tokens` 字段，
    # 由供应商按模型自身的上限决定，思考用多少是多少。
    #
    # 为什么不再卡：`max_tokens` 是**上限**不是花费，按实际输出计费，卡紧几乎不省钱，
    # 却会实实在在毁掉答案。实测过两次：2000 时 thinking 先把额度花在推理上、正文变空
    # （`finish_reason=length`），provider 再放大到 6000 重试——白等 30 秒还多付一次调用；
    # 写长一点的判断会在半句上截断。留一个正整数仍可当硬顶用（多租户限流等场景）。
    model_max_tokens: int = 0
    # 采样温度与单次运行的 token 预算（此前硬编码在 real_engine/model_router 里）
    model_temperature: float = 0.3
    # 整轮预算：**只用来防跑飞**，不参与「该想多久」。设成 100 万是因为
    # deepseek-flash 的上下文就是 1M —— 它永远先于上下文溢出触发，正常任务碰不到；
    # 真触发了说明这轮在空转，停下来比继续烧钱合理。
    model_token_budget: int = 1_000_000
    # ---- 对话上下文（agents/context_window.py）----
    # 每轮最多回溯多少轮历史、最多占多少字符；超出的折叠成摘要（context.compacted）。
    # 0 表示不限制（不建议：长会话会把预算烧光）。
    context_max_turns: int = 8
    context_max_chars: int = 6000
    # 单条历史消息的截断长度：一条万字回复不该挤掉整段对话
    context_max_turn_chars: int = 1200
    # 折叠摘要的总长度上限
    context_summary_chars: int = 800
    # 各家 Key（只从环境读取）
    deepseek_api_key: str = ""
    # 通义千问：qwen_api_key（QWEN_API_KEY）兼顾 DASHSCOPE_API_KEY（旧名）
    qwen_api_key: str = ""
    dashscope_api_key: str = ""
    glm_api_key: str = ""
    openai_api_key: str = ""
    # WorkBuddy：接口地址与 Key 都由用户提供（不自带默认端点）
    workbuddy_api_key: str = ""
    # OpenAI 兼容 Base URL 覆盖（.env 里已有 OPENAI_BASE_URL）
    openai_base_url: str = ""
    # 各供应商 Base URL 覆盖（设置中心/模型管理可热更新）
    deepseek_base_url: str = ""
    qwen_base_url: str = ""
    glm_base_url: str = ""
    workbuddy_base_url: str = ""

    # ---- 代理（统一 HTTP 客户端使用；解决 Windows NO_PROXY=[::1] 问题） ----
    https_proxy: str = ""
    http_proxy: str = ""

    # ---- 存储 ----
    database_url: str = "sqlite:///data/app.db"
    # Key 落盘用的 .env 路径。留空 = 数据目录下的 .env（正式运行就该留空）；
    # 测试一律指到 tmp，否则保存 Key 的用例会把假 Key 写进真实配置。
    env_path: str = ""
    auto_migrate: bool = True
    upload_dir: str = "./data/uploads"
    artifact_dir: str = "./data/artifacts"
    trash_dir: str = "./data/trash"
    templates_file: str = "./data/templates.json"
    # 意见反馈：本机存档目录 + 开发者收件邮箱。
    # 邮箱留空 = 不拼 mailto，界面退化成「复制内容自己发」（还没配邮箱时的默认状态）。
    feedback_dir: str = "./data/feedback"
    feedback_email: str = ""

    # ---- 单端口运行（给「不装开发环境」的人）----
    # 打开后由 FastAPI 直接托管 frontend/dist，只起一个进程、只开一个地址。
    # 默认打开：手动 `uvicorn ... --port 8080` 时浏览器打开根路径看到的应该是界面。
    # 以前默认关，8080 的根路径只有一行 {"name": ...}，被当成「页面渲染不出来」报了两次。
    # dist 还没构建时不会挂空白页，而是回一张写明怎么构建的说明页。
    # 纯接口场景（只调 API、不想读静态文件）显式设 SERVE_FRONTEND=0；pytest 由夹具关掉。
    serve_frontend: bool = True
    frontend_dist: str = ""  # 留空 = 仓库里的 frontend/dist

    # ---- 审批 / 业务 ----
    # 只有「不可逆 / 会动到用户文件」的动作才拦下来等确认：
    # 生成文档写的是产物目录（可覆盖、可重跑），没必要每次都让人点一下。
    approval_rules: str = "code.run_python,file.delete"
    approval_timeout_seconds: int = 180

    # ---- HTTP ----
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_mb: int = 20
    # 录音 / 视频天然比文档大：20MB 的 mp3 只有二十来分钟，一段两小时的全员会
    # 上传直接被拒。这两类单独给一个上限，文档仍按 20MB 卡。
    max_media_mb: int = 200
    # ---- 媒体识别（图片 OCR / 会议音视频转写）----
    # 图片用哪家：auto（默认，装了 PaddleOCR 就用它，否则退回 RapidOCR）
    # | paddle（强制，缺组件时报错并给出安装命令）| rapid（强制，离线兜底）。
    ocr_engine: str = "auto"
    # 识别模型语种：ch 中文（中英混排也走它）、en 纯英文、japan/korean 等按需。
    ocr_lang: str = "ch"
    # PP-OCR 模型代次，如 PP-OCRv5；留空 = 用当前 PaddleOCR 的默认版本
    # （不写死：上游换默认模型时不该被迫改代码）。
    ocr_version: str = ""
    # 整页方向分类（横向 / 倒置的扫描件）。要多下一个模型，默认关：
    # 送进识别前已按 EXIF 摆正，真躺倒的图由「旋转 90°/270° 重试」兜住。
    ocr_doc_orientation: bool = False
    # 单行方向分类：表格里偶尔有倒着盖的章、竖排标注，开着更稳，代价很小。
    ocr_textline_orientation: bool = True
    # 送进识别前会把最长边缩到这个值：手机原图 4000px 宽对识别没有帮助，
    # 只会让检测阶段多跑几倍时间。
    ocr_max_side: int = 2200
    # 置信度下限：反光、遮挡处模型会吐乱码，低于这个分数的块不进正文
    ocr_min_score: float = 0.5
    # oneDNN（MKL-DNN）CPU 加速：能快一到两倍，但 Paddle 3.3 在部分 Windows CPU 上
    # 与 PIR 执行器不兼容，一开就在推理时抛
    # `ConvertPirAttribute2RuntimeAttribute not support`，整张图直接认不出来。
    # 默认关。确认自己机器跑得动再打开（真崩了也会自动降级重试一次）。
    ocr_mkldnn: bool = False
    # 音视频：faster-whisper，模型首次使用时从 asr_endpoint 下载到 asr_model_dir。
    # base 约 145MB、中文速度约 4 倍实时；要更准可换 small（约 484MB、1.7 倍实时）。
    asr_model: str = "base"
    # 留空或 auto = 自动判语种；固定 zh 时英文会议会被硬翻成中文
    asr_language: str = "zh"
    # huggingface.co 在国内常被墙/502，默认走镜像；改成空串则直连官方
    asr_endpoint: str = "https://hf-mirror.com"
    # 单次转写的时间上限：一小时会议已足够，再长就分文件传，免得一个任务占满 CPU
    asr_max_minutes: int = 60
    # 自定义热词（逗号分隔）：写进来的词永远排在最前面，比「按素材统计」更硬。
    # 这里放**中文**的人名、内部简称 —— 中文没有词边界，程序抽不出来。
    asr_hotwords: str = ""
    # 从素材里自动认的人名取几个，0 = 关闭。只认「参会：A、B、C」和转写稿的
    # 「[00:12] 张伟：」两种写法，并过姓氏表，宁可漏也不把部门名当人名。
    asr_people: int = 4
    # 从素材里自动抽的英数专名（产品名 / 型号 / 内部编号）取几个，0 = 关闭。
    # 这类词会变（型号换代、项目换编号），所以不写死在配置里，每次从素材现取。
    asr_proper_nouns: int = 6
    # 自动学到的热词取多少个（不含自定义的）。prompt 预算只有 224 token，
    # 十几个词就到顶了，再多会把提示语挤掉。
    asr_hotword_limit: int = 12
    # 转写完再用大模型挑一遍同音字（只允许等长换词，不会改写内容）。
    # 这一步会把**转写文本**发给当前配置的模型供应商；要全程离线就关掉它。
    asr_proofread: bool = True
    # 单用户兜底鉴权：配置后所有业务接口需带 X-API-Token；留空 = 关闭（本地开发默认）
    api_token: str = ""
    # ---- 解析防护（压缩炸弹 / 超大文档）----
    max_uncompressed_mb: int = 256
    max_archive_entries: int = 2000
    max_pdf_pages: int = 500
    max_parsed_chars: int = 1_000_000
    # ---- 模型请求防护 ----
    # 允许模型 base_url 指向的域名白名单（留空 = 只做内网地址段黑名单）
    model_base_url_allowlist: str = ""

    def model_post_init(self, _context: Any) -> None:
        # DASHSCOPE_API_KEY 旧名兼容：合并到 qwen_api_key（providers/base 只读该字段）
        if not self.qwen_api_key and self.dashscope_api_key:
            self.qwen_api_key = self.dashscope_api_key

    # ---------- 派生属性 ----------
    @property
    def asr_model_dir(self) -> str:
        """语音模型缓存目录：跟上传/产物一样放在数据目录，删库不会连模型一起删。"""
        return str(DATA_ROOT / "models" / "asr")

    @property
    def approval_tools(self) -> set[str]:
        return {t.strip() for t in self.approval_rules.split(",") if t.strip()}

    @property
    def cors_origins(self) -> list[str]:
        origins = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def fallback_chain(self) -> list[str]:
        chain = [p.strip().lower() for p in self.model_fallback_chain.split(",") if p.strip()]
        return chain or ["mock"]

    def resolve_path(self, value: str) -> Path:
        """相对路径按「资源根」解析（前端 dist 这类只读产物）。"""
        path = Path(value)
        return path if path.is_absolute() else RESOURCE_ROOT / path

    def resolve_data_path(self, value: str) -> Path:
        """相对路径按「数据根」解析（库 / 上传 / 产物 / 模板 / 反馈）。

        打包成 exe 后这两者不是同一个目录：写错地方，用户的数据会在关掉程序时一起消失。
        """
        path = Path(value)
        return path if path.is_absolute() else DATA_ROOT / path

    @property
    def storage_overrides_path(self) -> Path:
        """用户改过的存储目录：存这里，避免为了改一个路径去动 .env。"""
        return self.resolve_data_path("./data/storage-overrides.json")

    def storage_overrides(self) -> dict[str, str]:
        path = self.storage_overrides_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): str(value) for key, value in data.items() if value}

    def set_storage_dir(self, kind: str, value: str | None) -> Path:
        """设置/清除 uploads | artifacts 目录覆盖；返回最终生效的绝对路径。"""
        overrides = self.storage_overrides()
        if value:
            target = self.resolve_data_path(value).expanduser()
            if not target.is_absolute():
                target = (DATA_ROOT / target).resolve()
            target.mkdir(parents=True, exist_ok=True)
            overrides[kind] = str(target)
            final = target
        else:
            overrides.pop(kind, None)
            final = self.resolve_data_path(
                self.upload_dir if kind == "uploads" else self.artifact_dir
            )
        path = self.storage_overrides_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
        return final

    @property
    def uploads_path(self) -> Path:
        override = self.storage_overrides().get("uploads")
        return Path(override) if override else self.resolve_data_path(self.upload_dir)

    @property
    def artifacts_path(self) -> Path:
        override = self.storage_overrides().get("artifacts")
        return Path(override) if override else self.resolve_data_path(self.artifact_dir)

    @property
    def trash_path(self) -> Path:
        return self.resolve_data_path(self.trash_dir)

    @property
    def templates_path(self) -> Path:
        """自定义模板注册表：DB 为准，同时镜像成 JSON 供 doc 工具读取。"""
        return self.resolve_data_path(self.templates_file)

    @property
    def feedback_path(self) -> Path:
        """意见反馈存档目录（本机留底，方便用户导出后自己发邮件）。"""
        return self.resolve_data_path(self.feedback_dir)

    @property
    def frontend_dist_path(self) -> Path | None:
        """构建好的前端目录；没构建过返回 None（由启动脚本负责提示去构建）。"""
        candidate = (
            self.resolve_path(self.frontend_dist)
            if self.frontend_dist
            else RESOURCE_ROOT / "frontend" / "dist"
        )
        return candidate if (candidate / "index.html").is_file() else None

    @property
    def sqlite_path(self) -> Path | None:
        url = self.database_url
        if not url.startswith("sqlite"):
            return None
        if url in ("sqlite://", "sqlite:///:memory:"):
            return Path(":memory:")
        raw = url.split("sqlite:///", 1)[-1]
        path = Path(raw)
        return path if path.is_absolute() else DATA_ROOT / path

    def provider_base_url(self, provider: str) -> str:
        overrides = {
            "deepseek": self.deepseek_base_url,
            "qwen": self.qwen_base_url,
            "glm": self.glm_base_url,
            "openai": self.openai_base_url,
            "workbuddy": self.workbuddy_base_url,
        }
        if overrides.get(provider):
            return overrides[provider].rstrip("/")
        if self.openai_base_url and provider not in PROVIDER_DEFAULTS:
            return self.openai_base_url.rstrip("/")
        return PROVIDER_DEFAULTS.get(provider, self.openai_base_url or "").rstrip("/")

    def provider_api_key(self, provider: str) -> str:
        """与 app/providers/base.py resolve_api_key 保持一致（唯一真源在该模块）。"""
        if provider == "deepseek":
            return self.deepseek_api_key or self.openai_api_key
        if provider == "qwen":
            return self.qwen_api_key
        if provider == "glm":
            return self.glm_api_key
        if provider == "openai":
            return self.openai_api_key
        if provider == "workbuddy":
            return self.workbuddy_api_key
        return ""

    def model_for_provider(self, provider: str) -> str:
        return self.model_name

    @property
    def engine_kind(self) -> str:
        """引擎配置归一化：mock | real | deepagents（非法值按 real 处理）。"""
        value = self.engine.strip().lower()
        return value if value in ("mock", "real", "deepagents") else "real"

    @property
    def configured_provider(self) -> str:
        provider = self.model_provider.strip().lower() or "mock"
        return provider

    @property
    def real_model_configured(self) -> bool:
        provider = self.configured_provider
        return (
            not self.mock_mode
            and provider != "mock"
            and bool(self.provider_api_key(provider))
            and bool(self.provider_base_url(provider))
        )

    @property
    def model_ready(self) -> bool:
        """发送门禁：现在有没有能用的模型。

        演示模式（engine=mock 或 MOCK_MODE=true）不依赖 Key，恒为 True；
        真实引擎则要求当前供应商 Key 与接口地址齐备。界面和 RunService 都用它，
        两边口径必须一致——否则「按钮亮着却发不出去」或「拦住了 API 还能直发」。
        """
        return self.engine_kind == "mock" or self.mock_mode or self.real_model_configured

    @property
    def mode(self) -> str:
        return "real" if self.real_model_configured else "mock"

    @property
    def is_prod(self) -> bool:
        return self.environment.strip().lower() in ("prod", "production")

    @property
    def is_auth_enabled(self) -> bool:
        return bool(self.api_token)

    @property
    def model_base_url_allowlist_hosts(self) -> set[str]:
        return {
            host.strip().lower()
            for host in self.model_base_url_allowlist.split(",")
            if host.strip()
        }

    def ensure_dirs(self) -> None:
        for path in (
            self.uploads_path,
            self.artifacts_path,
            self.trash_path,
        ):
            path.mkdir(parents=True, exist_ok=True)
        db = self.sqlite_path
        if db and db.name != ":memory:":
            db.parent.mkdir(parents=True, exist_ok=True)

    # ---------- 密钥写入（本地单用户「添加 Key」） ----------
    # env 变量名 -> Settings 字段名。写入后既改进程环境变量，也改当前 Settings
    # 实例，使下一次运行立即生效（无需重启）。
    _SECRET_FIELDS: ClassVar[dict[str, str]] = {
        "DEEPSEEK_API_KEY": "deepseek_api_key",
        "QWEN_API_KEY": "qwen_api_key",
        "DASHSCOPE_API_KEY": "dashscope_api_key",
        "GLM_API_KEY": "glm_api_key",
        "OPENAI_API_KEY": "openai_api_key",
        "WORKBUDDY_API_KEY": "workbuddy_api_key",
    }

    def apply_secret(self, env_name: str, value: str) -> None:
        """把 Key 写入当前进程与 Settings 实例（只作用于本机运行期）。"""
        env_name = env_name.strip()
        if not env_name:
            raise ValueError("环境变量名不能为空")
        os.environ[env_name] = value
        field = self._SECRET_FIELDS.get(env_name)
        if field:
            object.__setattr__(self, field, value)
            if field == "dashscope_api_key":
                object.__setattr__(self, "qwen_api_key", value)
        # get_settings() 的缓存指向同一实例，无需 cache_clear

    def clear_secret(self, env_name: str) -> bool:
        """断开 Key：从进程环境、Settings 实例与本地 .env 三处一并抹掉。

        这是「项目要分享/部署给别人」前的止损动作——只清进程内存不够，
        .env 里的那行会随数据目录一起被拷走，Key 就继续能用。所以必须
        三处同清，任何一处残留都算没断开。

        返回 True 表示 .env 也清掉了；返回 False 说明 .env 写入失败
        （只读文件系统等），调用方要提示用户手动删那一行。
        """
        env_name = env_name.strip()
        if not env_name:
            raise ValueError("环境变量名不能为空")
        os.environ.pop(env_name, None)
        field = self._SECRET_FIELDS.get(env_name)
        if field:
            object.__setattr__(self, field, "")
            if field == "dashscope_api_key":
                object.__setattr__(self, "qwen_api_key", "")
        return self._remove_env_line(env_name)

    def _remove_env_line(self, env_name: str) -> bool:
        """从 .env 里删掉 `NAME=...` 那一行（文件或该行不存在视为成功）。"""
        path = self.env_file_path
        try:
            if not path.exists():
                return True
            existing = path.read_text(encoding="utf-8")
            pattern = re.compile(rf"^\s*{re.escape(env_name)}\s*=")
            lines = [item for item in existing.splitlines() if not pattern.match(item)]
            if len(lines) == len(existing.splitlines()):
                return True  # 本来就没有这行
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with contextlib.suppress(OSError):
                path.chmod(0o600)
            return True
        except OSError:
            return False

    @property
    def env_file_path(self) -> Path:
        """Key 落盘位置：默认数据目录下的 .env，可由 `env_path` 指到别处。

        为什么要能改：这条路径写的是**用户真正的 Key**，而它以前硬绑 DATA_ROOT。
        测试把所有存储都指到 tmp，唯独漏了它，于是跑一遍 `pytest backend/tests`
        就会把夹具里的假 Key（`sk-gate-test-…`）写进仓库 .env，用户的真 Key 被覆盖，
        之后每次运行都降级成演示模式——界面写着「API Key 无效或已失效」，
        而用户从没动过那把 Key。这是最伤信任的一类自伤，所以不能靠「记得别写」，
        得让测试天然写不到真实文件。
        """
        override = (self.env_path or "").strip()
        return Path(override).expanduser() if override else DATA_ROOT / ".env"

    def persist_secret(self, env_name: str, value: str) -> bool:
        """把 Key 落盘到仓库 .env（已 gitignore），重启后仍生效。

        返回 True 表示已写入；写失败（只读文件系统/权限）返回 False，
        由调用方提示「需手动配置环境变量」。
        """
        path = self.env_file_path
        line = f"{env_name}={value}"
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            lines = existing.splitlines()
            pattern = re.compile(rf"^\s*{re.escape(env_name)}\s*=")
            replaced = False
            for index, item in enumerate(lines):
                if pattern.match(item):
                    lines[index] = line
                    replaced = True
                    break
            if not replaced:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(line)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with contextlib.suppress(OSError):
                path.chmod(0o600)
            return True
        except OSError:
            return False

    def redacted(self) -> dict[str, Any]:
        """用于日志/健康检查的脱敏配置快照（不含任何 Key）。"""
        return {
            "environment": self.environment,
            "model_provider": self.configured_provider,
            "model_name": self.model_name,
            "mock_mode": self.mock_mode,
            "database_url": self.database_url.split("@")[-1],
            "approval_rules": sorted(self.approval_tools),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
