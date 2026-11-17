"""FastAPI 组合根：装配 infra 实现 + services + agents runtime，挂载 /api/v1 与旧 /api 别名。

启动：在仓库根执行
    ./.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agents.runtime import build_runtime
from .api.auth import ApiTokenMiddleware
from .api.deps import AppContainer
from .api.v1.router import api_router
from .core.config import Settings, get_settings
from .core.errors import register_exception_handlers
from .core.logging import (
    bind_log_context,
    get_logger,
    reset_log_context,
    setup_logging,
)
from .core.static_site import mount_spa
from .core.utils import new_id
from .infra.db.repositories import (
    SqlApprovalRepository,
    SqlArtifactRepository,
    SqlMessageRepository,
    SqlModelConfigRepository,
    SqlRunEventRepository,
    SqlRunRepository,
    SqlSettingsRepository,
    SqlThreadRepository,
)
from .infra.db.session import Database, run_migrations
from .infra.http import sanitize_no_proxy_env
from .infra.parsing import LocalFileParser
from .infra.storage import LocalFileStorage
from .plugins import load_plugins
from .services.approval_service import ApprovalService
from .services.artifact_service import ArtifactService
from .services.feedback_service import FeedbackService
from .services.model_service import ModelService
from .services.project_service import ProjectService
from .services.prompt_packs import PromptPackService
from .services.provider_usage_service import ProviderUsageService
from .services.run_service import RunService
from .services.settings_service import SettingsService
from .services.skill_service import SkillService
from .services.template_service import TemplateService
from .services.thread_service import ThreadService
from .services.usage_service import UsageService

logger = get_logger("app.main")


def build_container(settings: Settings, database: Database) -> AppContainer:
    session_factory = database.session_factory
    thread_repo = SqlThreadRepository(session_factory)
    message_repo = SqlMessageRepository(session_factory)
    run_repo = SqlRunRepository(session_factory)
    run_event_repo = SqlRunEventRepository(session_factory)
    approval_repo = SqlApprovalRepository(session_factory)
    artifact_repo = SqlArtifactRepository(session_factory)
    settings_repo = SqlSettingsRepository(session_factory)
    model_config_repo = SqlModelConfigRepository(session_factory)

    storage = LocalFileStorage(settings)
    parser = LocalFileParser(settings)
    runtime = build_runtime(settings, storage)
    threads = ThreadService(thread_repo, message_repo, artifact_repo)
    artifacts = ArtifactService(artifact_repo, thread_repo, storage, parser, settings)
    approvals = ApprovalService(approval_repo, settings)
    settings_service = SettingsService(settings_repo, settings, model_config_repo)
    models = ModelService(model_config_repo, settings, settings_service)
    skills = SkillService(settings_repo, settings)
    projects = ProjectService(settings_repo)
    prompt_packs = PromptPackService()
    feedback = FeedbackService(settings)
    templates = TemplateService(
        settings_repo,
        settings,
        thread_repo,
        message_repo,
        run_repo,
        run_event_repo,
        artifact_repo,
        storage,
    )
    usage = UsageService(run_repo)
    provider_usage = ProviderUsageService(settings)
    runs = RunService(
        settings=settings,
        runtime=runtime,
        threads=threads,
        messages=message_repo,
        runs=run_repo,
        events=run_event_repo,
        artifacts=artifact_repo,
        approvals=approval_repo,
        approval_service=approvals,
        artifact_service=artifacts,
        settings_service=settings_service,
        projects=projects,
        prompt_packs=prompt_packs,
    )
    container = AppContainer(
        settings=settings,
        runtime=runtime,
        threads=threads,
        artifacts=artifacts,
        approvals=approvals,
        runs=runs,
        settings_service=settings_service,
        usage=usage,
        provider_usage=provider_usage,
        models=models,
        templates=templates,
        skills=skills,
        projects=projects,
        prompt_packs=prompt_packs,
        feedback=feedback,
        database=database,
    )
    # 启动时应用 DB 覆盖（设置中心/模型 base_url/技能开关），并绑定提示词
    settings_service.bind_runtime(runtime)
    skills.bind_runtime(runtime)
    templates.bind_runtime(runtime)
    return container


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_format)
    sanitize_no_proxy_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        database = Database(settings)
        if settings.auto_migrate:
            await asyncio.to_thread(run_migrations, settings)
        container = build_container(settings, database)
        app.state.container = container
        plugins = load_plugins(container.runtime.tools)
        container.runtime.extra["plugins"] = plugins
        logger.info(
            "服务启动完成 mode=%s provider=%s tools=%d subagents=%d skills=%s",
            "real" if settings.real_model_configured else "mock",
            settings.configured_provider,
            len(container.runtime.tools.names()),
            len(container.runtime.subagents.all()),
            sorted(container.runtime.skills),
            extra={"event": "app_started"},
        )
        try:
            yield
        finally:
            database.dispose()
            logger.info("服务已停止", extra={"event": "app_stopped"})

    app = FastAPI(
        title="office-agent-mvp",
        version=settings.version,
        description="""办公助理 MVP（V2.1 分层版）：SSE 事件 + 审批 + DOCX 产物 + 审计。

错误码目录（core/errors.py）：BAD_REQUEST / NOT_FOUND / CONFLICT /
APPROVAL_ALREADY_DECIDED / UNSUPPORTED_FILE_TYPE / FILE_PARSE_ERROR /
PAYLOAD_TOO_LARGE / MODEL_TIMEOUT / MODEL_RATE_LIMIT / TOOL_ERROR /
APPROVAL_TIMEOUT / UNAUTHORIZED / INTERNAL。
错误体固定为 {"trace_id": str, "error": {"code": str, "message": str, "details": any}}。
服务端配置 API_TOKEN 后，业务接口需带请求头 X-API-Token（未配置时无需携带）。

旧 /api/* 为 v1 兼容别名（响应头 Deprecation: true）。""",
        lifespan=lifespan,
        # 生产环境关闭交互文档与 OpenAPI JSON（版本化快照由 contracts/ 提供）
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None if settings.is_prod else "/redoc",
        openapi_url=None if settings.is_prod else "/openapi.json",
    )
    # 鉴权先于 CORS/observability 注册 → 位于调用链内层，可复用 observability 的 trace_id。
    # 用纯 ASGI 实现，避免 BaseHTTPMiddleware 缓冲 SSE 流。
    app.add_middleware(ApiTokenMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-ID"],
    )

    @app.middleware("http")
    async def observability(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get("X-Trace-ID") or new_id("tr")
        request.state.trace_id = trace_id
        tokens = bind_log_context(trace_id=trace_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            reset_log_context(tokens)
        response.headers["X-Trace-ID"] = trace_id
        path = request.url.path
        # 旧 /api/* 兼容别名：标记 Deprecation（/api/v1/* 不受影响）
        if path.startswith("/api/") and not path.startswith("/api/v1/"):
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = '</api/v1>; rel="successor-version"'
        logger.info(
            "HTTP %s %s -> %s",
            request.method,
            path,
            response.status_code,
            extra={
                "event": "http_request",
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "trace_id": trace_id,
            },
        )
        return response

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    # 兼容 v0.1 与前端 B2/B3 联调期间的旧路径；响应头带 Deprecation
    app.include_router(api_router, prefix="/api", include_in_schema=False)

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    async def openapi_v1_alias() -> JSONResponse:
        """前端 gen:api 使用的版本化 OpenAPI 快照（仅含 /api/v1 路由）。"""
        return JSONResponse(app.openapi())

    # 单端口运行（启动脚本用）：把构建好的前端一起托管，用户只需要开一个地址。
    # 默认关闭，开发态仍是 uvicorn + vite 双进程，pytest 也不受静态文件影响。
    # 必须放在所有 /api 路由之后：兜底路由会吞掉后注册的路径。
    frontend_dist = settings.frontend_dist_path if settings.serve_frontend else None
    if frontend_dist is not None:
        mount_spa(app, frontend_dist)
        logger.info("前端静态资源已挂载：%s", frontend_dist, extra={"event": "spa_mounted"})
    else:

        @app.get("/", include_in_schema=False)
        async def index() -> JSONResponse:
            return JSONResponse({"name": settings.app_name, "version": settings.version})

    return app


app = create_app()
