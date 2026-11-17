"""v1 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    approvals,
    artifacts,
    desktop,
    extensions,
    feedback,
    files,
    health,
    knowledge,
    models,
    projects,
    prompts,
    runs,
    settings,
    skills,
    storage,
    templates,
    threads,
    usage,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(threads.router)
api_router.include_router(files.router)
api_router.include_router(runs.router)
api_router.include_router(approvals.router)
api_router.include_router(artifacts.router)
api_router.include_router(settings.router)
api_router.include_router(models.router)
api_router.include_router(templates.router)
api_router.include_router(skills.router)
api_router.include_router(knowledge.router)
api_router.include_router(projects.router)
api_router.include_router(storage.router)
api_router.include_router(desktop.router)
api_router.include_router(extensions.router)
api_router.include_router(usage.router)
api_router.include_router(feedback.router)
api_router.include_router(prompts.router)

__all__ = ["api_router"]
