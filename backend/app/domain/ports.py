"""领域端口（Protocol）：服务层只依赖这些接口，infra 提供实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .entities import (
    Approval,
    Artifact,
    Message,
    ModelConfigEntity,
    Run,
    RunEventEntity,
    SettingItem,
    Thread,
)
from .enums import Decision


@runtime_checkable
class ThreadRepository(Protocol):
    def add(self, thread: Thread) -> Thread: ...

    def get(self, thread_id: str, include_deleted: bool = False) -> Thread | None: ...

    def list(
        self,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
        q: str | None = None,
    ) -> list[Thread]: ...

    def count(self, include_deleted: bool = False, q: str | None = None) -> int: ...

    def update(self, thread: Thread) -> Thread: ...

    def soft_delete(self, thread_id: str, deleted_at: str) -> None: ...

    def soft_delete_many(self, thread_ids: list[str], deleted_at: str) -> int: ...

    def reorder(self, thread_ids: list[str]) -> int: ...

    def min_sort_index(self) -> float | None: ...


@runtime_checkable
class MessageRepository(Protocol):
    def add(self, message: Message) -> Message: ...

    def list_by_thread(self, thread_id: str, include_run_summary: bool = True) -> list[Message]: ...

    def count_by_thread(self, thread_id: str) -> int: ...


@runtime_checkable
class RunRepository(Protocol):
    def add(self, run: Run) -> Run: ...

    def get(self, run_id: str) -> Run | None: ...

    def update(self, run: Run) -> Run: ...

    def list_by_thread(
        self, thread_id: str, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[Run]: ...

    def list_recent(
        self, limit: int = 100, offset: int = 0, status: str | None = None
    ) -> list[Run]: ...

    def count(self, thread_id: str | None = None, status: str | None = None) -> int: ...


@runtime_checkable
class RunEventRepository(Protocol):
    def append(self, event: RunEventEntity) -> RunEventEntity: ...

    def list_after(
        self, run_id: str, after_seq: int = 0, limit: int = 1000
    ) -> list[RunEventEntity]: ...

    def max_seq(self, run_id: str) -> int: ...


@runtime_checkable
class ApprovalRepository(Protocol):
    def add(self, approval: Approval) -> Approval: ...

    def get(self, approval_id: str) -> Approval | None: ...

    def decide(
        self, approval_id: str, decision: str, comment: str | None, decided_at: str
    ) -> bool: ...

    def update_extra(self, approval_id: str, patch: dict[str, Any]) -> None: ...

    def list_by_thread(self, thread_id: str, run_id: str | None = None) -> list[Approval]: ...


@runtime_checkable
class ArtifactRepository(Protocol):
    def add(self, artifact: Artifact) -> Artifact: ...

    def get(self, artifact_id: str, include_deleted: bool = False) -> Artifact | None: ...

    def list(
        self,
        thread_id: str | None = None,
        run_id: str | None = None,
        type: str | None = None,
        include_deleted: bool = False,
        limit: int = 200,
        offset: int = 0,
        deleted_only: bool = False,
        exclude_type: str | None = None,
    ) -> list[Artifact]: ...

    def count(
        self,
        thread_id: str | None = None,
        run_id: str | None = None,
        type: str | None = None,
        include_deleted: bool = False,
        deleted_only: bool = False,
        exclude_type: str | None = None,
    ) -> int: ...

    def count_by_thread(self, thread_id: str) -> int: ...

    def update_extra(self, artifact_id: str, extra: dict[str, Any]) -> None: ...

    def replace_file(
        self, artifact_id: str, *, size: int, sha256: str, created_at: str
    ) -> None: ...

    def soft_delete(
        self, artifact_id: str, deleted_at: str, extra: dict[str, Any] | None = None
    ) -> None: ...

    def restore(self, artifact_id: str, extra: dict[str, Any] | None = None) -> None: ...

    def hard_delete(self, artifact_id: str) -> None: ...


@runtime_checkable
class SettingsRepository(Protocol):
    def list_all(self) -> list[SettingItem]: ...

    def get(self, key: str) -> SettingItem | None: ...

    def upsert(self, item: SettingItem) -> SettingItem: ...


@runtime_checkable
class ModelConfigRepository(Protocol):
    def list_all(self) -> list[ModelConfigEntity]: ...

    def add(self, config: ModelConfigEntity) -> ModelConfigEntity: ...

    def update(self, config: ModelConfigEntity) -> ModelConfigEntity: ...

    def delete(self, config_id: str) -> None: ...

    def get(self, config_id: str) -> ModelConfigEntity | None: ...


@runtime_checkable
class FileStorage(Protocol):
    def save_upload(self, thread_id: str, filename: str, data: bytes) -> tuple[Path, str]: ...

    def save_text(self, stored_path: Path, text: str) -> Path: ...

    def new_artifact_path(self, filename: str) -> Path: ...

    def preview_path(self, artifact_path: Path) -> Path: ...

    def write_text(self, path: Path, text: str) -> None: ...

    def read_text(self, path: str) -> str: ...

    def exists(self, path: str) -> bool: ...

    def trash(self, path: str) -> str: ...

    def restore_file(self, from_path: str, to_path: str) -> bool: ...

    def delete_file(self, path: str) -> None: ...

    def delete(self, path: str) -> None: ...


@runtime_checkable
class FileParser(Protocol):
    @property
    def supported_exts(self) -> set[str]: ...

    def parse(self, data: bytes, ext: str) -> str: ...


@runtime_checkable
class ApprovalGate(Protocol):
    """引擎与审批服务之间的端口：创建审批记录并等待决议。"""

    async def create(
        self,
        thread_id: str,
        run_id: str,
        tool: str,
        payload: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> Approval: ...

    async def wait(self, approval_id: str, timeout_seconds: float) -> Decision | None: ...
