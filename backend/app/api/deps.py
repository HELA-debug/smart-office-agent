"""依赖注入：从 app.state.container 取服务；api 层不直接 import infra。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import Depends, Request

from ..agents.runtime import AgentRuntime
from ..core.config import Settings
from ..services.approval_service import ApprovalService
from ..services.artifact_service import ArtifactService
from ..services.feedback_service import FeedbackService
from ..services.model_service import ModelService
from ..services.project_service import ProjectService
from ..services.prompt_packs import PromptPackService
from ..services.run_service import RunService
from ..services.settings_service import SettingsService
from ..services.skill_service import SkillService
from ..services.template_service import TemplateService
from ..services.thread_service import ThreadService
from ..services.usage_service import UsageService


@dataclass
class AppContainer:
    settings: Settings
    runtime: AgentRuntime
    threads: ThreadService
    artifacts: ArtifactService
    approvals: ApprovalService
    runs: RunService
    settings_service: SettingsService
    usage: UsageService
    models: ModelService
    templates: TemplateService
    skills: SkillService
    projects: ProjectService
    prompt_packs: PromptPackService
    feedback: FeedbackService
    database: Any


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - 启动失败时才会发生
        raise RuntimeError("应用容器未初始化")
    return cast(AppContainer, container)


ContainerDep = Annotated[AppContainer, Depends(get_container)]
