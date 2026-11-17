"""file.delete 工具：软删入回收站 + 审批归属 + 作用域限制。

补 P1「file.delete 配置漂移」：审批规则默认含 file.delete，但工具此前从未实现，
设置页却展示为「可审批工具」，属误导。本文件守护实现不再退化。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.domain.entities import Artifact
from app.domain.enums import ArtifactType, Risk
from app.tools.builtin import file as file_tools
from app.tools.registry import REGISTRY
from app.tools.spec import ToolContext


class FakeArtifactRepo:
    def __init__(self, items: list[Artifact] | None = None) -> None:
        self.items = {item.id: item for item in (items or [])}
        self.deleted: list[str] = []

    def add(self, artifact: Artifact) -> Artifact:
        self.items[artifact.id] = artifact
        return artifact

    def get(self, artifact_id: str, include_deleted: bool = False) -> Artifact | None:
        item = self.items.get(artifact_id)
        if item is None or (item.deleted_at and not include_deleted):
            return None
        return item

    def list(
        self,
        thread_id: str | None = None,
        run_id: str | None = None,
        type: str | None = None,
        include_deleted: bool = False,
        limit: int = 200,
    ) -> list[Artifact]:
        items = [
            item
            for item in self.items.values()
            if (thread_id is None or item.thread_id == thread_id)
            and (run_id is None or item.run_id == run_id)
            and (include_deleted or not item.deleted_at)
        ]
        return items[:limit]

    def count_by_thread(self, thread_id: str) -> int:
        return len([item for item in self.items.values() if item.thread_id == thread_id])

    def soft_delete(self, artifact_id: str, deleted_at: str) -> None:
        self.items[artifact_id].deleted_at = deleted_at
        self.deleted.append(artifact_id)


class FakeStorage:
    def __init__(self) -> None:
        self.trashed: list[str] = []

    def exists(self, path: str) -> bool:
        return True

    def trash(self, path: str) -> str:
        self.trashed.append(path)
        return f"trash/{Path(path).name}"

    def delete(self, path: str) -> None:
        self.trashed.append(path)


def _artifact(
    artifact_id: str, filename: str, *, thread_id: str = "th_1", run_id: str = "run_1"
) -> Artifact:
    return Artifact(
        id=artifact_id,
        thread_id=thread_id,
        run_id=run_id,
        type=ArtifactType.DOCX,
        filename=filename,
        path=f"/data/artifacts/{artifact_id}.docx",
        size=1024,
        sha256="a" * 64,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        created_at="2026-10-24T00:00:00Z",
        extra={"text_path": f"/data/artifacts/{artifact_id}.txt"},
    )


def _context(repo: FakeArtifactRepo, storage: FakeStorage, **kwargs: Any) -> ToolContext:
    return ToolContext(
        thread_id="th_1",
        run_id="run_1",
        trace_id="tr_1",
        settings=Settings(),
        artifacts=repo,  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        **kwargs,
    )


def test_file_delete_registered_as_high_risk() -> None:
    """审批规则默认含 file.delete：工具必须存在且为 high（触发审批门控）。"""
    spec = REGISTRY.get("file.delete")
    assert spec is not None, "file.delete 未注册到工具注册表"
    assert spec.risk == Risk.HIGH, "file.delete 必须是高风险工具，否则审批规则永不触发"
    assert "file.delete" in REGISTRY.names()


def test_default_approval_rules_reference_real_tools() -> None:
    """默认审批规则引用的工具必须真实存在（防配置漂移回归）。"""
    settings = Settings(approval_rules="doc.generate_report,file.delete")
    registered = set(REGISTRY.names())
    for name in settings.approval_tools:
        assert name in registered, f"审批规则引用了未实现的工具：{name}"


def test_delete_by_filename_soft_deletes_and_trashes() -> None:
    repo = FakeArtifactRepo([_artifact("ar_1", "报告.docx"), _artifact("ar_2", "摘要.docx")])
    storage = FakeStorage()
    result = file_tools.delete_files(_context(repo, storage), files=["报告.docx"])

    assert result["count"] == 1
    assert result["deleted"][0]["artifact_id"] == "ar_1"
    assert repo.deleted == ["ar_1"]
    # 主产物与正文文本文件都要移入回收站
    assert len(storage.trashed) == 2
    assert result["_summary"].startswith("已删除 1 个产物")


def test_delete_without_names_only_targets_current_run() -> None:
    """未指定文件名时只删本次运行产物，避免误删会话历史产物。"""
    repo = FakeArtifactRepo(
        [
            _artifact("ar_1", "本次.docx", run_id="run_1"),
            _artifact("ar_2", "历史.docx", run_id="run_old"),
        ]
    )
    storage = FakeStorage()
    result = file_tools.delete_files(_context(repo, storage), files=None)

    assert result["count"] == 1
    assert result["deleted"][0]["filename"] == "本次.docx"
    assert "ar_2" not in repo.deleted


def test_delete_scoped_to_current_thread() -> None:
    """不能删除其它会话的产物。"""
    repo = FakeArtifactRepo([_artifact("ar_other", "别人的.docx", thread_id="th_2")])
    storage = FakeStorage()
    result = file_tools.delete_files(_context(repo, storage), files=["别人的.docx"])

    assert result["count"] == 0
    assert result["missing"] == ["别人的.docx"]
    assert storage.trashed == []


def test_delete_missing_file_reports_and_keeps_others() -> None:
    repo = FakeArtifactRepo([_artifact("ar_1", "报告.docx")])
    storage = FakeStorage()
    result = file_tools.delete_files(_context(repo, storage), files=["报告.docx", "不存在.docx"])

    assert result["count"] == 1
    assert result["missing"] == ["不存在.docx"]


def test_delete_removes_id_from_run_artifacts() -> None:
    repo = FakeArtifactRepo([_artifact("ar_1", "报告.docx")])
    storage = FakeStorage()
    ctx = _context(repo, storage, artifact_ids=["ar_1", "ar_keep"])
    file_tools.delete_files(ctx, files=["报告.docx"])
    assert ctx.artifact_ids == ["ar_keep"]


def test_delete_no_match_is_noop() -> None:
    repo = FakeArtifactRepo([])
    storage = FakeStorage()
    result = file_tools.delete_files(_context(repo, storage), files=[])
    assert result["count"] == 0
    assert result["deleted"] == []
    assert storage.trashed == []
