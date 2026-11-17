"""运行服务：SSE 事件持久化、审批挂起、取消/重试、断线重放、审计导出。

架构：生产者任务（engine.run → 持久化 → 队列/广播）+ SSE 消费者生成器。
取消 = 取消生产者任务 → 生产者落库 run.cancelled 帧 → 队列收到该帧后结束流。
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

from ..agents.engine_protocol import EngineEvent, RunContext, normalize_approval_mode
from ..agents.runtime import AgentRuntime
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.events import (
    CONTEXT_COMPACTED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    TERMINAL_EVENTS,
    build_event,
)
from ..core.logging import bind_log_context, get_logger, reset_log_context
from ..core.utils import new_id, now_iso
from ..domain.entities import Artifact, Run, RunEventEntity, Thread, UploadInfo
from ..domain.enums import MessageRole, RunStatus
from ..domain.ports import (
    ApprovalRepository,
    ArtifactRepository,
    MessageRepository,
    RunEventRepository,
    RunRepository,
)
from .approval_service import ApprovalService
from .artifact_service import ArtifactService, UploadInput
from .conversation_service import ConversationService
from .project_service import MAX_STAGE_BYTES, ProjectService
from .prompt_packs import PromptPackService
from .settings_service import SettingsService
from .thread_service import ThreadService
from .title_suggester import suggest_title
from .usage_service import run_usage

logger = get_logger("app.services.run")


@dataclass(frozen=True)
class RetryTarget:
    """重试/重新生成要复原的现场：任务文本 + 当时带的附件（否则重试会多带一屋子旧素材）。"""

    thread_id: str
    message: str
    attachment_ids: list[str] = field(default_factory=list)


@dataclass
class RunChunk:
    seq: int | None
    event: str | None
    data: dict[str, Any] = field(default_factory=dict)
    comment: str | None = None


class RunService:
    def __init__(
        self,
        settings: Settings,
        runtime: AgentRuntime,
        threads: ThreadService,
        messages: MessageRepository,
        runs: RunRepository,
        events: RunEventRepository,
        artifacts: ArtifactRepository,
        approvals: ApprovalRepository,
        approval_service: ApprovalService,
        artifact_service: ArtifactService,
        settings_service: SettingsService,
        projects: ProjectService | None = None,
        prompt_packs: PromptPackService | None = None,
    ):
        self.settings = settings
        self.runtime = runtime
        self.threads = threads
        self.messages = messages
        self.runs = runs
        self.events = events
        self.artifacts = artifacts
        self.approvals = approvals
        self.approval_service = approval_service
        self.artifact_service = artifact_service
        self.settings_service = settings_service
        self.projects = projects
        self.prompt_packs = prompt_packs or PromptPackService()
        # 一轮请求的「规范化 → 附件归属 → 上下文计划」全在这一层，run 只负责编排
        self.conversation = ConversationService(settings, messages, artifacts)
        self._broker: dict[str, set[asyncio.Queue[RunChunk | None]]] = {}
        self._active: dict[str, asyncio.Task[None]] = {}
        # 标题还是自动生成、可以再优化的会话（用户手动改过名的不在此列）
        self._auto_title_threads: set[str] = set()

    # ---------- 发起运行（SSE） ----------
    async def start(
        self,
        thread_id: str,
        message: str,
        *,
        trace_id: str = "",
        mode_override: str | None = None,
        output_format: str | None = None,
        project_id: str | None = None,
        project_files: list[str] | None = None,
        approval_mode: str | None = None,
        attachment_ids: list[str] | None = None,
    ) -> AsyncIterator[RunChunk]:
        thread = self.threads.get(thread_id)
        approval_rules = self.settings_service.approval_rules()
        engine_pref = self.settings.engine_kind
        selection = await self.runtime.prepare_engine(
            force_mock=(mode_override == "mock") or engine_pref == "mock",
            approval_tools=self.runtime.tools.approval_tools(approval_rules),
        )
        # 项目素材先入会话（会成为本轮 uploads 的一部分），再做上下文装配
        project, staged_note = self._stage_project(thread_id, project_id, project_files)
        turn = self.conversation.prepare(thread_id, message, attachment_ids=attachment_ids)
        if not turn.message:
            raise AppError(ErrorCode.BAD_REQUEST, "message 不能为空")
        if self.threads.ensure_title(thread_id, turn.message):
            self._auto_title_threads.add(thread_id)
        uploads = turn.uploads
        effective_format = self._resolve_output_format(output_format, uploads)
        prompt_extra = self.prompt_packs.render(turn.message)
        if staged_note:
            prompt_extra = f"{prompt_extra}\n\n{staged_note}".strip()
        run_id = new_id("r")
        ctx_tokens = bind_log_context(trace_id=trace_id, run_id=run_id)
        run = Run(
            id=run_id,
            thread_id=thread_id,
            status=RunStatus.RUNNING.value,
            mode=selection.mode,
            engine=selection.engine.name,
            provider=selection.provider,
            model=selection.model,
            started_at=now_iso(),
        )
        self.runs.add(run)
        # 用户消息带上本轮附件快照：重试、审计、历史回放都靠它还原现场
        self.conversation.record_user(turn, run_id, attachment_ids=attachment_ids)
        self.threads.touch(thread_id)
        queue: asyncio.Queue[RunChunk | None] = asyncio.Queue()
        self._broker[run_id] = set()
        ctx = RunContext(
            thread_id=thread_id,
            run_id=run_id,
            trace_id=trace_id,
            message=turn.message,
            mode=selection.mode,
            model=selection.model,
            degraded=selection.degraded,
            settings=self.settings,
            messages=self.messages,
            artifacts=self.artifacts,
            approvals=self.approvals,
            storage=self.runtime.storage,
            approval_gate=self.approval_service,
            tools=self.runtime.tools,
            approval_tools=selection_approval_tools(selection, self.runtime),
            uploads=uploads,
            output_format=effective_format,
            prompt_extra=prompt_extra,
            project=project,
            approval_mode=normalize_approval_mode(approval_mode),
            history=turn.plan.messages,
            context_summary=turn.plan.summary,
            context_meta=turn.plan.meta(),
        )
        logger.info(
            "运行开始 mode=%s engine=%s thread=%s",
            selection.mode,
            selection.engine.name,
            thread_id,
            extra={"event": "run_started", "thread_id": thread_id, "run_id": run_id},
        )
        producer = asyncio.create_task(
            self._produce(run, ctx, selection, queue), name=f"run:{run_id}"
        )
        self._active[run_id] = producer
        _ = thread  # 仅用于存在性校验
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not producer.done():
                producer.cancel()
            self._active.pop(run_id, None)
            self._close_broker(run_id)
            reset_log_context(ctx_tokens)

    async def _produce(
        self,
        run: Run,
        ctx: RunContext,
        selection: Any,
        queue: asyncio.Queue[RunChunk | None],
    ) -> None:
        seq = 0
        terminal = False
        try:
            # 压缩过上下文就先报一声：前端可忽略，排障时要能看出「模型看到的历史被裁过」
            if ctx.context_meta.get("dropped_turns"):
                seq += 1
                compacted = EngineEvent(
                    CONTEXT_COMPACTED,
                    build_event(run.id, CONTEXT_COMPACTED, **ctx.context_meta),
                )
                self._persist_event(run.id, seq, compacted)
                chunk = RunChunk(seq, compacted.event, compacted.data)
                self._publish(run.id, chunk)
                queue.put_nowait(chunk)
            async for engine_event in selection.engine.run(ctx):
                if engine_event.comment:
                    chunk = RunChunk(None, None, comment=engine_event.comment)
                    queue.put_nowait(chunk)
                    continue
                seq += 1
                entity = RunEventEntity(
                    run_id=run.id,
                    seq=seq,
                    event=engine_event.event,
                    data=engine_event.data,
                    created_at=now_iso(),
                )
                self.events.append(entity)
                chunk = RunChunk(seq=seq, event=engine_event.event, data=engine_event.data)
                self._publish(run.id, chunk)
                queue.put_nowait(chunk)
                if engine_event.event in TERMINAL_EVENTS:
                    terminal = True
                    if engine_event.event == RUN_COMPLETED:
                        # 跑完再定标题：此时素材已解析、主题已明确，取出来的名字比截断首句贴题
                        await self._retitle_if_auto(ctx)
                    self._finish_run(run, engine_event, selection.mode)
            if not terminal:
                failed = self._internal_failure(run, "运行意外结束")
                seq += 1
                self._persist_event(run.id, seq, failed)
                chunk = RunChunk(seq, failed.event, failed.data)
                self._publish(run.id, chunk)
                queue.put_nowait(chunk)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            logger.info("运行被取消 run_id=%s", run.id, extra={"event": "run_cancelled"})
            usage = self._meter_snapshot(selection)
            seq = max(seq, self.events.max_seq(run.id)) + 1
            cancelled = EngineEvent(
                RUN_CANCELLED,
                build_event(
                    run.id,
                    RUN_CANCELLED,
                    reason="cancelled_by_user",
                    degraded=ctx.degraded,
                    # 中断前已经花掉的量：一并下发，前端收到就能把账补上
                    tokens=int(usage.get("total_tokens") or 0),
                    cost_cny=float(usage.get("cost_cny") or 0.0),
                    usage=usage,
                ),
            )
            self._persist_event(run.id, seq, cancelled)
            chunk = RunChunk(seq, cancelled.event, cancelled.data)
            self._publish(run.id, chunk)
            queue.put_nowait(chunk)
            self._finish_cancelled(run, selection)
            self._cancel_pending_approvals(run)
        except Exception as exc:
            logger.exception("运行异常 run_id=%s", run.id)
            failed = self._internal_failure(run, str(exc)[:300] or "服务内部错误")
            seq = max(seq, self.events.max_seq(run.id)) + 1
            self._persist_event(run.id, seq, failed)
            chunk = RunChunk(seq, failed.event, failed.data)
            self._publish(run.id, chunk)
            queue.put_nowait(chunk)
        finally:
            queue.put_nowait(None)
            self._close_broker(run.id)
            self._active.pop(run.id, None)

    async def _retitle_if_auto(self, ctx: RunContext) -> None:
        """首轮结束后用模型把自动标题换成更贴题的名字（失败就保留原样）。"""
        thread_id = ctx.thread_id
        if thread_id not in self._auto_title_threads:
            return
        self._auto_title_threads.discard(thread_id)
        try:
            title = await suggest_title(
                self.runtime.router, ctx.message, [upload.filename for upload in ctx.uploads]
            )
            if not title:
                return
            applied = self.threads.apply_auto_title(thread_id, title)
            if applied:
                logger.info(
                    "会话自动命名 thread=%s title=%s",
                    thread_id,
                    applied,
                    extra={"event": "thread_auto_renamed"},
                )
        except Exception:  # 命名失败不影响运行结果
            logger.warning("会话自动命名异常 thread=%s", thread_id, exc_info=True)

    # ---------- 取消 / 重试 ----------
    async def cancel(self, run_id: str, *, reason: str = "cancelled_by_user") -> dict[str, Any]:
        run = self.get_run(run_id)
        if run.status != RunStatus.RUNNING.value:
            return {
                "run_id": run_id,
                "cancelled": False,
                "status": run.status,
                "idempotent": True,
            }
        producer = self._active.get(run_id)
        if producer is not None:
            producer.cancel()
            await asyncio.wait({producer}, timeout=5.0)
        else:
            # 进程内没有活跃生产者（例如服务重启后）：补一条 run.cancelled 事件
            seq = self.events.max_seq(run_id) + 1
            cancelled = EngineEvent(
                RUN_CANCELLED,
                build_event(run_id, RUN_CANCELLED, reason=reason, degraded=False),
            )
            self._persist_event(run_id, seq, cancelled)
            self._finish_cancelled(run)
            self._cancel_pending_approvals(run)
        refreshed = self.runs.get(run_id)
        if refreshed is not None and refreshed.status == RunStatus.CANCELLED.value:
            self._cancel_pending_approvals(refreshed)
        return {
            "run_id": run_id,
            "cancelled": True,
            "status": refreshed.status if refreshed else RunStatus.CANCELLED.value,
            "idempotent": False,
        }

    def validate_attachments(self, thread_id: str, attachment_ids: list[str] | None) -> None:
        """发起前校验附件归属：拼错 id 直接 400，别让模型拿着空素材跑一整轮。"""
        missing = self.conversation.missing_attachments(thread_id, attachment_ids)
        if missing:
            raise AppError(
                ErrorCode.BAD_REQUEST,
                f"附件不属于该会话或已被删除：{'、'.join(missing[:3])}",
            )

    def retry_message(self, run_id: str) -> RetryTarget:
        """取原 run 的用户任务消息与当时附件，供 retry/regenerate 复原现场。"""
        run = self.get_run(run_id)
        messages = [
            message
            for message in self.messages.list_by_thread(run.thread_id)
            if message.run_id == run.id and message.role == MessageRole.USER.value
        ]
        if not messages:
            raise AppError(ErrorCode.BAD_REQUEST, "原始任务消息缺失，无法重试（请重新发起任务）")
        original = messages[-1]
        return RetryTarget(
            thread_id=run.thread_id,
            message=original.content,
            attachment_ids=self.conversation.attachments_of_run(run.id, run.thread_id),
        )

    def regenerate_source(self, artifact: Artifact) -> RetryTarget:
        if artifact.type == "upload":
            raise AppError(ErrorCode.BAD_REQUEST, "上传素材不支持重新生成")
        if not artifact.run_id:
            raise AppError(ErrorCode.BAD_REQUEST, "该产物没有关联运行，无法重新生成")
        return self.retry_message(artifact.run_id)

    # ---------- 查询 / 重放 ----------
    def get_run(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise AppError(ErrorCode.NOT_FOUND, f"运行不存在：{run_id}")
        return run

    def list_runs(
        self,
        thread_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size
        # 分页下推到 SQL（含 status 过滤），不再 list_recent(2000) 后在内存切片
        total = self.runs.count(thread_id=thread_id, status=status)
        runs = (
            self.runs.list_by_thread(thread_id, limit=page_size, offset=offset, status=status)
            if thread_id
            else self.runs.list_recent(limit=page_size, offset=offset, status=status)
        )
        return {
            "runs": [self.usage_public(run) for run in runs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def list_by_thread(self, thread_id: str) -> list[Run]:
        return self.runs.list_by_thread(thread_id)

    def events_json(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        self.get_run(run_id)
        return [
            {
                "seq": event.seq,
                "event": event.event,
                "data": event.data,
                "created_at": event.created_at,
            }
            for event in self.events.list_after(run_id, after_seq=max(0, after))
        ]

    async def resume(self, run_id: str, after: int = 0) -> AsyncIterator[RunChunk]:
        run = self.get_run(run_id)
        queue = self._subscribe(run_id) if run.status == RunStatus.RUNNING.value else None
        last_seq = max(0, after)
        try:
            for event in self.events.list_after(run_id, after_seq=last_seq):
                last_seq = event.seq
                yield RunChunk(event.seq, event.event, event.data)
            if queue is None:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield RunChunk(None, None, comment="ping")
                    continue
                if item is None:
                    return
                if item.seq is not None and item.seq <= last_seq:
                    continue
                if item.seq is not None:
                    last_seq = item.seq
                yield item
        finally:
            self._unsubscribe(run_id, queue)

    # ---------- 审计 / 导出 ----------
    def audit(self, thread_id: str) -> dict[str, Any]:
        thread = self.threads.get(thread_id)
        runs = self.runs.list_by_thread(thread_id)
        approvals = self.approval_service.list_by_thread(thread_id)
        artifacts = self.artifacts.list(thread_id=thread_id)
        runs_payload = [self._audit_run(run, approvals, artifacts) for run in runs]
        return {
            "thread_id": thread.id,
            "thread_title": thread.title,
            "runs": runs_payload,
            "approvals": [self.approval_service.public(item) for item in approvals],
            "artifacts": [self.artifact_service.metadata(item) for item in artifacts],
        }

    def _audit_run(
        self,
        run: Run,
        approvals: list[Any],
        artifacts: list[Artifact],
    ) -> dict[str, Any]:
        extra = run.extra or {}
        return {
            "run_id": run.id,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "status": run.status,
            "mode": run.mode,
            "engine": run.engine,
            "provider": run.provider,
            "model": run.model,
            "tokens": run.tokens,
            # 按现价重算：run 上存的是当时那版价格表算出来的钱，改价后会跟用量页对不上
            "cost_cny": run_usage(run)["cost_cny"],
            "elapsed_ms": int(extra.get("elapsed_ms", 0)),
            "error_code": run.error_code,
            "degraded": bool(extra.get("degraded", False)),
            # 调用回执：请求 id 是拿去向供应商控制台对账的凭据。
            # 只回传最近几条，审计列表不需要整份明细。
            "request_ids": _request_ids(extra),
            "calls": _usage_int(extra, "calls"),
            "verified_calls": _usage_int(extra, "verified_calls"),
            # 供应商实际跑的模型名。配置名（deepseek-chat）与官方回执
            # （deepseek-flash）可能不同，控制台按回执名归类账单，
            # 两边名字对不上常常被误读成「根本没调用」。
            "provider_model": _provider_model(extra),
            "approvals": [
                {
                    "approval_id": approval.id,
                    "tool": approval.tool,
                    "decision": approval.decision,
                    "decided_at": approval.decided_at,
                }
                for approval in approvals
                if approval.run_id == run.id
            ],
            "artifacts": [
                {
                    "artifact_id": artifact.id,
                    "type": artifact.type,
                    "filename": artifact.filename,
                }
                for artifact in artifacts
                if artifact.run_id == run.id
            ],
        }

    def export_audit(
        self, fmt: str = "json", thread_id: str | None = None
    ) -> tuple[bytes, str, str]:
        fmt = fmt.lower()
        if fmt not in ("json", "csv"):
            raise AppError(ErrorCode.BAD_REQUEST, "format 只能是 json 或 csv")
        records: list[dict[str, Any]] = []
        # 线程与 run 都分批取（每批 200），避免一次性把 1000×500 行读进内存
        for thread in self._iter_export_threads(thread_id):
            approvals = self.approval_service.list_by_thread(thread.id)
            artifacts = self.artifacts.list(thread_id=thread.id, limit=1000)
            for run in self._iter_thread_runs(thread.id):
                record = self._audit_run(run, approvals, artifacts)
                record["thread_id"] = thread.id
                record["thread_title"] = thread.title
                records.append(record)
        stamp = now_iso()[:19].replace(":", "").replace("-", "")
        if fmt == "json":
            payload = {
                "exported_at": now_iso(),
                "thread_id": thread_id,
                "runs": records,
            }
            content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            return content, f"audit_{stamp}.json", "application/json"
        buffer = io.StringIO()
        fields = [
            "run_id",
            "thread_id",
            "thread_title",
            "started_at",
            "finished_at",
            "status",
            "mode",
            "engine",
            "provider",
            "model",
            "provider_model",
            "tokens",
            "cost_cny",
            "elapsed_ms",
            "error_code",
            "approvals",
            "artifacts",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["approvals"] = "; ".join(
                f"{item['tool']}:{item['decision']}" for item in record["approvals"]
            )
            row["artifacts"] = "; ".join(item["filename"] for item in record["artifacts"])
            writer.writerow(row)
        return (
            buffer.getvalue().encode("utf-8-sig"),
            f"audit_{stamp}.csv",
            "text/csv",
        )

    def usage_public(self, run: Run) -> dict[str, Any]:
        return {
            "run_id": run.id,
            "thread_id": run.thread_id,
            "status": run.status,
            "mode": run.mode,
            "engine": run.engine,
            "provider": run.provider,
            "model": run.model,
            "tokens": run.tokens,
            "cost_cny": run.cost_cny,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_code": run.error_code,
            "extra": run.extra,
        }

    # ---------- 内部 ----------
    # 审计导出批次：线程与 run 都按页拉取，避免全量常驻内存
    _EXPORT_BATCH = 200

    def _iter_export_threads(self, thread_id: str | None) -> Iterator[Thread]:
        if thread_id:
            thread = self.threads.get(thread_id)
            if thread is not None:
                yield thread
            return
        offset = 0
        while True:
            batch = self.threads.threads.list(limit=self._EXPORT_BATCH, offset=offset)
            if not batch:
                return
            yield from batch
            if len(batch) < self._EXPORT_BATCH:
                return
            offset += len(batch)

    def _iter_thread_runs(self, thread_id: str) -> Iterator[Run]:
        offset = 0
        while True:
            batch = self.runs.list_by_thread(thread_id, limit=self._EXPORT_BATCH, offset=offset)
            if not batch:
                return
            yield from batch
            if len(batch) < self._EXPORT_BATCH:
                return
            offset += len(batch)

    def _persist_event(self, run_id: str, seq: int, event: EngineEvent) -> None:
        self.events.append(
            RunEventEntity(
                run_id=run_id,
                seq=seq,
                event=event.event,
                data=event.data,
                created_at=now_iso(),
            )
        )

    def _uploads(self, thread_id: str, attachment_ids: list[str] | None = None) -> list[UploadInfo]:
        """会话素材（保留了老签名：不传 attachment_ids 就是全量，行为与改造前一致）。"""
        return self.conversation.uploads_for(thread_id, attachment_ids)

    @staticmethod
    def _resolve_output_format(requested: str | None, uploads: list[UploadInfo]) -> str:
        """产物格式优先级：用户显式选择 > 首个上传素材格式 > docx。"""
        from ..tools.builtin.doc import DEFAULT_OUTPUT_FORMAT, OUTPUT_FORMATS

        if requested:
            normalized = requested.strip().lower()
            if normalized in OUTPUT_FORMATS:
                return normalized
        for upload in uploads:
            ext = (upload.ext or "").strip().lower().lstrip(".")
            if ext in OUTPUT_FORMATS:
                return ext
        return DEFAULT_OUTPUT_FORMAT

    def _stage_project(
        self, thread_id: str, project_id: str | None, project_files: list[str] | None
    ) -> tuple[dict[str, Any] | None, str]:
        """把选中项目的文档加进本次运行的素材，并给出一段提示词说明。

        为什么要暂存而不是让 Agent 直接读目录：file_read 只认会话素材（上传目录），
        直接放开任意路径读写等于把用户整块磁盘交给模型。这里由服务端做白名单搬运，
        Agent 仍然只看到「素材」，路径越界由 ProjectService 拦住。
        """
        if not project_id or self.projects is None:
            return None, ""
        project, paths = self.projects.staging_paths(project_id, project_files)
        existing = {item.filename for item in self._uploads(thread_id)}
        available: list[str] = []
        for path in paths:
            if path.name in existing:
                available.append(path.name)
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if len(data) > MAX_STAGE_BYTES:
                logger.warning("项目文件过大，跳过 file=%s", path.name)
                continue
            try:
                self.artifact_service.upload_many(
                    thread_id, [UploadInput(filename=path.name, content_type=None, data=data)]
                )
            except AppError as exc:
                # 单个文件解析失败（加密 PDF / 损坏 xlsx）不该拖垮整轮任务
                logger.warning("项目文件加入素材失败 file=%s err=%s", path.name, exc.message)
                continue
            available.append(path.name)
        if available:
            detail = f"本轮已加入 {len(available)} 个文件作为素材：" + "、".join(available[:12])
            if len(available) > 12:
                detail += f" 等 {len(available)} 个"
        else:
            detail = "项目里暂时没有可用的文档素材。"
        note = (
            f"【当前项目】{project['name']}（{project['path']}）。{detail}。"
            "需要项目里的其它文件时先告诉用户要读哪个，不要遍历项目目录以外的位置。"
        )
        return project, note

    def _finish_run(self, run: Run, engine_event: EngineEvent, mode: str = "") -> None:
        data = engine_event.data
        tokens, cost = self._usage_metrics(data)
        if engine_event.event == RUN_COMPLETED:
            run.status = str(data.get("status") or RunStatus.COMPLETED.value)
            run.tokens = tokens
            run.cost_cny = cost
            # fallback 后记录"实际主要供应商"（run.started 语义不变，仍用启动探测值）
            run.provider = self._actual_provider(data, run.provider, mode)
        elif engine_event.event == RUN_FAILED:
            run.status = RunStatus.FAILED.value
            run.tokens = tokens
            run.cost_cny = cost
            run.error_code = str((data.get("error") or {}).get("code") or "INTERNAL")
        else:  # run.cancelled（v1.1）
            run.status = RunStatus.CANCELLED.value
        run.finished_at = now_iso()
        run.extra = {
            **run.extra,
            "elapsed_ms": int(data.get("elapsed_ms", 0)),
            "degraded": bool(data.get("degraded", False)),
            "artifact_ids": list(data.get("artifact_ids", [])),
            "approvals": list(data.get("approvals", [])),
            "usage": data.get("usage", {}),
        }
        self.runs.update(run)
        logger.info(
            "运行结束 status=%s tokens=%s elapsed_ms=%s",
            run.status,
            run.tokens,
            run.extra.get("elapsed_ms"),
            extra={"event": "run_finished", "run_id": run.id, "thread_id": run.thread_id},
        )

    def _finish_cancelled(self, run: Run, selection: Any = None) -> None:
        run.status = RunStatus.CANCELLED.value
        run.finished_at = now_iso()
        # 取消不等于没花钱：被中断之前那些轮工具调用，供应商照样扣费。
        # 原来这里一个 token 都不记，于是「本地账本 10 次 / 官方账单 398 次」，
        # 越看越像数据丢了。取消那一刻把已消耗的量写进账，两边才谈得拢。
        usage = self._meter_snapshot(selection)
        if usage:
            run.tokens = int(usage.get("total_tokens") or 0)
            run.cost_cny = float(usage.get("cost_cny") or 0.0)
        run.extra = {
            **run.extra,
            "elapsed_ms": 0,
            "degraded": False,
            "reason": "cancelled_by_user",
            # 中途截断：这个用量只到取消那一刻，之后不再增长。
            # 用量页据此把它和「跑完整」的运行分开统计。
            "partial": True,
            **({"usage": usage} if usage else {}),
        }
        self.runs.update(run)
        logger.info(
            "运行取消 run_id=%s tokens=%s",
            run.id,
            run.tokens,
            extra={"event": "run_cancelled"},
        )

    @staticmethod
    def _meter_snapshot(selection: Any) -> dict[str, Any]:
        """向引擎要本次运行的用量快照；拿不到就返回空（不影响取消流程）。"""
        engine = getattr(selection, "engine", None)
        getter = getattr(engine, "usage_snapshot", None)
        if not callable(getter):
            return {}
        try:
            data = getter()
        except Exception:  # 快照失败不能让取消本身也失败
            logger.warning("取用量快照失败，本次取消记录将不含用量", exc_info=True)
            return {}
        return data if isinstance(data, dict) else {}

    def _cancel_pending_approvals(self, run: Run) -> None:
        for approval in self.approvals.list_by_thread(run.thread_id, run.id):
            if approval.decision is None:
                self.approvals.update_extra(approval.id, {"cancelled": True})

    @staticmethod
    def _usage_metrics(data: dict[str, Any]) -> tuple[int, float]:
        """tokens/cost 以 run 上下文 usage 为准，缺失时回退事件顶层字段。"""
        raw_usage = data.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        tokens = int(usage.get("total_tokens") or data.get("tokens") or 0)
        raw_cost = usage.get("cost_cny", data.get("cost_cny"))
        cost = float(raw_cost or 0.0)
        return tokens, cost

    @staticmethod
    def _actual_provider(data: dict[str, Any], fallback: str, mode: str) -> str:
        """实际主要供应商：事件 provider > usage.by_provider token 最多者 > fallback。"""
        explicit = str(data.get("provider") or "")
        raw_usage = data.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        groups = usage.get("by_provider") or []
        best_provider = ""
        best_tokens = -1
        for group in groups:
            if not isinstance(group, dict):
                continue
            total = int(group.get("input_tokens") or 0) + int(group.get("output_tokens") or 0)
            if total > best_tokens:
                best_tokens = total
                best_provider = str(group.get("provider") or "")
        if best_provider:
            return best_provider
        if explicit:
            return explicit
        if mode == "mock":
            return "mock"
        return fallback

    def _internal_failure(self, run: Run, message: str) -> EngineEvent:
        data = build_event(
            run.id,
            RUN_FAILED,
            error={"code": "INTERNAL", "message": message, "retryable": True},
            degraded=False,
        )
        self._finish_run(run, EngineEvent(RUN_FAILED, data))
        return EngineEvent(RUN_FAILED, data)

    def _publish(self, run_id: str, chunk: RunChunk) -> None:
        for queue in self._broker.get(run_id, set()):
            with contextlib.suppress(asyncio.QueueFull):  # pragma: no cover
                queue.put_nowait(chunk)

    def _subscribe(self, run_id: str) -> asyncio.Queue[RunChunk | None] | None:
        subscribers = self._broker.get(run_id)
        if subscribers is None:
            return None
        queue: asyncio.Queue[RunChunk | None] = asyncio.Queue()
        subscribers.add(queue)
        return queue

    def _unsubscribe(self, run_id: str, queue: asyncio.Queue[RunChunk | None] | None) -> None:
        if queue is None:
            return
        subscribers = self._broker.get(run_id)
        if subscribers is not None:
            subscribers.discard(queue)

    def _close_broker(self, run_id: str) -> None:
        subscribers = self._broker.pop(run_id, set())
        for queue in subscribers:
            with contextlib.suppress(asyncio.QueueFull):  # pragma: no cover
                queue.put_nowait(None)


def selection_approval_tools(selection: Any, runtime: AgentRuntime) -> list[str]:
    """当前选择的引擎使用的审批工具集合（与引擎构造时保持一致）。"""
    engine = selection.engine
    configured = getattr(engine, "approval_tools", None)
    if isinstance(configured, list):
        return list(configured)
    return list(runtime.approval_tools)


def _usage_of(extra: dict[str, Any]) -> dict[str, Any]:
    usage = extra.get("usage")
    return usage if isinstance(usage, dict) else {}


def _usage_int(extra: dict[str, Any], key: str) -> int:
    try:
        return int(_usage_of(extra).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _provider_model(extra: dict[str, Any]) -> str | None:
    """供应商回执里的真实模型名；没有回执就没有这个名字。"""
    by_provider = _usage_of(extra).get("by_provider")
    if isinstance(by_provider, list):
        for item in by_provider:
            if isinstance(item, dict) and item.get("model"):
                return str(item["model"])
    return None


def _request_ids(extra: dict[str, Any], limit: int = 3) -> list[str]:
    """最近几条外部调用的请求 id（新的在后）。没有回执的老数据返回空列表。"""
    detail = _usage_of(extra).get("calls_detail")
    if not isinstance(detail, list):
        return []
    ids = [
        str(item.get("request_id"))
        for item in detail
        if isinstance(item, dict) and item.get("request_id")
    ]
    return ids[-limit:]
