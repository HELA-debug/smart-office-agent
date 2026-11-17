"""模板服务：内置模板（weekly/meeting/summary）+ 自定义模板（存储于 settings 表）。

自定义模板同时镜像到 data/templates.json，供 doc.generate_report 工具读取并渲染 DOCX。
模板可按需生成产物（POST /templates/{id}/render），并复用现有工具链（file.read + doc.generate_report）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.utils import new_id, now_iso
from ..domain.entities import Artifact, Message, Run, RunEventEntity, SettingItem, UploadInfo
from ..domain.enums import MessageRole, RunStatus
from ..domain.ports import (
    ArtifactRepository,
    FileStorage,
    MessageRepository,
    RunEventRepository,
    RunRepository,
    SettingsRepository,
    ThreadRepository,
)
from ..tools.registry import REGISTRY, ToolContext

_SETTINGS_KEY = "templates.custom"
_VALID_SOURCES = {"summary", "progress", "data", "risk", "plan"}

BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "weekly": {
        "id": "weekly",
        "name": "周报",
        "description": "本周进展 / 关键数据 / 风险与问题 / 下周计划",
        "builtin": True,
        "skill": "weekly-report",
        "sections": [
            {"heading": "摘要", "source": "summary"},
            {"heading": "本周进展", "source": "progress"},
            {"heading": "关键数据", "source": "data"},
            {"heading": "风险与问题", "source": "risk"},
            {"heading": "下周计划", "source": "plan"},
        ],
    },
    "meeting": {
        "id": "meeting",
        "name": "会议纪要",
        "description": "摘要 / 议题与讨论 / 结论与待办",
        "builtin": True,
        "skill": None,
        "sections": [
            {"heading": "摘要", "source": "summary"},
            {"heading": "议题与讨论", "source": "progress"},
            {"heading": "结论与待办", "source": "plan"},
        ],
    },
    "summary": {
        "id": "summary",
        "name": "文件摘要",
        "description": "摘要 / 要点",
        "builtin": True,
        "skill": None,
        "sections": [
            {"heading": "摘要", "source": "summary"},
            {"heading": "要点", "source": "progress"},
        ],
    },
}


class TemplateService:
    def __init__(
        self,
        settings_repo: SettingsRepository,
        settings: Settings,
        threads: ThreadRepository,
        messages: MessageRepository,
        runs: RunRepository,
        events: RunEventRepository,
        artifacts: ArtifactRepository,
        storage: FileStorage,
    ):
        self.settings_repo = settings_repo
        self.settings = settings
        self.threads = threads
        self.messages = messages
        self.runs = runs
        self.events = events
        self.artifacts = artifacts
        self.storage = storage
        self.runtime: Any = None

    def bind_runtime(self, runtime: Any) -> None:
        self.runtime = runtime
        self.sync_file()

    # ---------- CRUD ----------
    def _custom(self) -> list[dict[str, Any]]:
        item = self.settings_repo.get(_SETTINGS_KEY)
        if item is None or not isinstance(item.value, list):
            return []
        return [entry for entry in item.value if isinstance(entry, dict)]

    def _save_custom(self, items: list[dict[str, Any]]) -> None:
        self.settings_repo.upsert(
            SettingItem(
                key=_SETTINGS_KEY,
                value=items,
                updated_at=now_iso(),
                scope="global",
                is_secret=False,
            )
        )
        self.sync_file()

    def list_templates(self) -> list[dict[str, Any]]:
        templates: list[dict[str, Any]] = []
        for builtin in BUILTIN_TEMPLATES.values():
            item = dict(builtin)
            skill = builtin.get("skill")
            enabled = True
            if self.runtime is not None and skill:
                info = self.runtime.skills.get(str(skill))
                enabled = bool(info.enabled) if info is not None else True
            item["enabled"] = enabled
            templates.append(item)
        templates.extend(self._custom())
        return templates

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise AppError(ErrorCode.BAD_REQUEST, "模板 name 不能为空")
        template_id = str(payload.get("id") or "").strip().lower()
        if not template_id:
            template_id = re.sub(r"[^a-z0-9_-]+", "-", name.lower())[:40] or new_id("tpl")
        if template_id in BUILTIN_TEMPLATES:
            raise AppError(ErrorCode.CONFLICT, f"模板 ID 与内置模板冲突：{template_id}")
        sections = payload.get("sections") or []
        if not isinstance(sections, list) or not sections:
            raise AppError(ErrorCode.BAD_REQUEST, "sections 必须是非空数组")
        normalized_sections: list[dict[str, str]] = []
        for entry in sections:
            if not isinstance(entry, dict):
                raise AppError(ErrorCode.BAD_REQUEST, "sections 元素必须是对象")
            heading = str(entry.get("heading", "")).strip()
            source = str(entry.get("source", "")).strip()
            if not heading or source not in _VALID_SOURCES:
                raise AppError(
                    ErrorCode.BAD_REQUEST,
                    f"section 需要 heading 与 source（source ∈ {sorted(_VALID_SOURCES)}）",
                )
            normalized_sections.append({"heading": heading, "source": source})
        custom = [item for item in self._custom() if item.get("id") != template_id]
        template = {
            "id": template_id,
            "name": name,
            "description": str(payload.get("description", "")),
            "builtin": False,
            "enabled": True,
            "sections": normalized_sections,
            "created_at": now_iso(),
        }
        custom.append(template)
        self._save_custom(custom)
        return template

    def delete_template(self, template_id: str) -> None:
        if template_id in BUILTIN_TEMPLATES:
            raise AppError(ErrorCode.BAD_REQUEST, "内置模板不可删除")
        custom = self._custom()
        remaining = [item for item in custom if item.get("id") != template_id]
        if len(remaining) == len(custom):
            raise AppError(ErrorCode.NOT_FOUND, f"模板不存在：{template_id}")
        self._save_custom(remaining)

    def get_template(self, template_id: str) -> dict[str, Any]:
        for item in self.list_templates():
            if item.get("id") == template_id:
                return item
        raise AppError(ErrorCode.NOT_FOUND, f"模板不存在：{template_id}")

    def sync_file(self) -> None:
        """镜像自定义模板到 data/templates.json，供 doc 工具无 DB 依赖读取。"""
        path = self.settings.templates_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            item["id"]: {
                "name": item.get("name", item["id"]),
                "sections": item.get("sections", []),
            }
            for item in self._custom()
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 生成产物 ----------
    def render(self, template_id: str, thread_id: str) -> dict[str, Any]:
        template = self.get_template(template_id)
        if self.runtime is None:
            raise AppError(ErrorCode.INTERNAL, "运行时未装配，无法生成模板产物")
        if self.threads.get(thread_id) is None:
            raise AppError(ErrorCode.NOT_FOUND, f"会话不存在：{thread_id}")
        run_id = new_id("r")
        run = Run(
            id=run_id,
            thread_id=thread_id,
            status=RunStatus.RUNNING.value,
            mode="mock",
            engine="template",
            provider="mock",
            model="template-render",
            started_at=now_iso(),
        )
        self.runs.add(run)
        uploads = [
            {
                "artifact_id": artifact.id,
                "filename": artifact.filename,
                "path": artifact.path,
                "ext": (artifact.extra or {}).get("ext", ""),
                "chars": int((artifact.extra or {}).get("chars", 0)),
                "text_path": (artifact.extra or {}).get("text_path", ""),
                "parsed": bool((artifact.extra or {}).get("parsed", False)),
            }
            for artifact in self.artifacts.list(thread_id=thread_id, type="upload")
        ]
        ctx = ToolContext(
            thread_id=thread_id,
            run_id=run_id,
            trace_id="",
            settings=self.settings,
            artifacts=self.artifacts,
            storage=self.storage,
            mode="mock",
            uploads=[
                UploadInfo(
                    artifact_id=item["artifact_id"],
                    filename=item["filename"],
                    path=item["path"],
                    ext=item["ext"],
                    chars=item["chars"],
                    text_path=item["text_path"],
                    parsed=item["parsed"],
                )
                for item in uploads
            ],
        )
        read_tool = REGISTRY.get("file.read")
        doc_tool = REGISTRY.get("doc.generate_report")
        if read_tool is None or doc_tool is None:
            raise AppError(ErrorCode.INTERNAL, "生成工具未注册")
        read_tool.handler(ctx)
        result = doc_tool.handler(ctx, title=str(template.get("name", "")), template=template_id)
        artifact = self.artifacts.get(str(result["artifact_id"]), include_deleted=True)
        finished = now_iso()
        run.status = RunStatus.COMPLETED.value
        run.finished_at = finished
        run.extra = {
            "elapsed_ms": 0,
            "degraded": False,
            "artifact_ids": [artifact.id] if artifact else [],
            "approvals": [],
        }
        self.runs.update(run)
        self.events.append(
            RunEventEntity(
                run_id=run_id,
                seq=1,
                event="artifact.ready",
                data={
                    "version": 1,
                    "run_id": run_id,
                    "artifact_id": result["artifact_id"],
                    "type": "docx",
                    "filename": result.get("filename", ""),
                    "size": result.get("size", 0),
                    "download_url": f"/api/v1/artifacts/{result['artifact_id']}/download",
                    "preview_url": f"/api/v1/artifacts/{result['artifact_id']}/preview",
                },
                created_at=finished,
            )
        )
        self.messages.add(
            Message(
                id=new_id("m"),
                thread_id=thread_id,
                role=MessageRole.ASSISTANT.value,
                content=f"已按模板「{template.get('name', template_id)}」生成 DOCX。",
                run_id=run_id,
                created_at=finished,
            )
        )
        if artifact is None:  # pragma: no cover - 工具失败会抛错
            raise AppError(ErrorCode.INTERNAL, "模板产物登记失败")
        return {
            "run_id": run_id,
            "artifact_id": artifact.id,
            "artifact": self._artifact_public(artifact),
            "template": template_id,
        }

    def _artifact_public(self, artifact: Artifact) -> dict[str, Any]:
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
            "extra": {},
            "download_url": f"/api/v1/artifacts/{artifact.id}/download",
            "preview_url": f"/api/v1/artifacts/{artifact.id}/preview",
        }
