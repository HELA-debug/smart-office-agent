from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import Artifact
from ..models import ArtifactModel
from ..session import session_scope


def _to_entity(row: ArtifactModel) -> Artifact:
    return Artifact(
        id=row.id,
        thread_id=row.thread_id,
        run_id=row.run_id,
        type=row.type,
        filename=row.filename,
        path=row.path,
        size=row.size,
        sha256=row.sha256,
        content_type=row.content_type,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
        extra=dict(row.extra or {}),
    )


class SqlArtifactRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def add(self, artifact: Artifact) -> Artifact:
        with session_scope(self._sf) as session:
            session.add(
                ArtifactModel(
                    id=artifact.id,
                    thread_id=artifact.thread_id,
                    run_id=artifact.run_id,
                    type=artifact.type,
                    filename=artifact.filename,
                    path=artifact.path,
                    size=artifact.size,
                    sha256=artifact.sha256,
                    content_type=artifact.content_type,
                    deleted_at=artifact.deleted_at,
                    created_at=artifact.created_at,
                    extra=dict(artifact.extra),
                )
            )
        return artifact

    def get(self, artifact_id: str, include_deleted: bool = False) -> Artifact | None:
        with session_scope(self._sf) as session:
            row = session.get(ArtifactModel, artifact_id)
            if row is None or (row.deleted_at and not include_deleted):
                return None
            return _to_entity(row)

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
    ) -> list[Artifact]:
        stmt = self._filtered(thread_id, run_id, type, include_deleted, deleted_only, exclude_type)
        # 回收站按「删除时间倒序」更有意义（最近删的在最上面），普通列表仍按创建升序
        order = (
            (ArtifactModel.deleted_at.desc(), ArtifactModel.id.desc())
            if deleted_only
            else (ArtifactModel.created_at.asc(), ArtifactModel.id.asc())
        )
        stmt = stmt.order_by(*order)
        stmt = stmt.limit(limit).offset(max(0, offset))
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def count(
        self,
        thread_id: str | None = None,
        run_id: str | None = None,
        type: str | None = None,
        include_deleted: bool = False,
        deleted_only: bool = False,
        exclude_type: str | None = None,
    ) -> int:
        """分页总数用 SQL COUNT，避免把整表读进内存再切片。"""
        stmt = self._filtered(thread_id, run_id, type, include_deleted, deleted_only, exclude_type)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        with session_scope(self._sf) as session:
            return int(session.scalar(count_stmt) or 0)

    def _filtered(
        self,
        thread_id: str | None,
        run_id: str | None,
        type: str | None,
        include_deleted: bool,
        deleted_only: bool = False,
        exclude_type: str | None = None,
    ) -> Select[Any]:
        stmt = select(ArtifactModel)
        if thread_id:
            stmt = stmt.where(ArtifactModel.thread_id == thread_id)
        if run_id:
            stmt = stmt.where(ArtifactModel.run_id == run_id)
        if type:
            stmt = stmt.where(ArtifactModel.type == type)
        # 产物中心只列 Agent 生成的东西：上传素材（type=upload）默认被这条排除
        if exclude_type:
            stmt = stmt.where(ArtifactModel.type != exclude_type)
        if deleted_only:
            stmt = stmt.where(ArtifactModel.deleted_at.is_not(None))
        elif not include_deleted:
            stmt = stmt.where(ArtifactModel.deleted_at.is_(None))
        return stmt

    def count_by_thread(self, thread_id: str) -> int:
        """会话里「产出了几份文件」。

        只数 Agent 生成的产物，不算上传素材（type=upload）：左栏那个「N 产物」
        要和产物中心看到的一致，而产物中心本来就不列上传素材——把素材也算进去，
        用户把产物中心清空后这里还会剩下「2 产物」，看起来像没删掉。
        """
        stmt = (
            select(func.count())
            .select_from(ArtifactModel)
            .where(ArtifactModel.thread_id == thread_id)
            .where(ArtifactModel.deleted_at.is_(None))
            .where(ArtifactModel.type != "upload")
        )
        with session_scope(self._sf) as session:
            return int(session.scalar(stmt) or 0)

    def update_extra(self, artifact_id: str, extra: dict[str, Any]) -> None:
        """只改 extra：识别结果、转写时长这类「后到的元数据」都走这里。

        不另写 UPDATE 语句，是因为 extra 本来就是整块 JSON；整块替换比「读-改-写
        某几个键」更难写出半更新状态（识别线程和请求线程会同时碰同一条记录）。
        """
        with session_scope(self._sf) as session:
            row = session.get(ArtifactModel, artifact_id)
            if row is not None:
                row.extra = dict(extra)

    def replace_file(self, artifact_id: str, *, size: int, sha256: str, created_at: str) -> None:
        """同一份文件被重写：只更新内容相关字段，id 不动。

        为什么必须复用 id：界面拿的是这条记录的 id。以前「同名重写」是新建一条再把旧的
        软删，前端那张卡还指着旧 id，点预览就是 404（`get()` 默认不含已删）。
        顺带清了 `deleted_at`——被别的路径软删过又重写的，应当是活的。
        """
        with session_scope(self._sf) as session:
            row = session.get(ArtifactModel, artifact_id)
            if row is None:
                return
            row.size = size
            row.sha256 = sha256
            row.created_at = created_at
            row.deleted_at = None

    def soft_delete(
        self, artifact_id: str, deleted_at: str, extra: dict[str, Any] | None = None
    ) -> None:
        """软删：置 deleted_at；extra 传入时一并写回（回收站要记「文件被挪到哪」）。"""
        with session_scope(self._sf) as session:
            row = session.get(ArtifactModel, artifact_id)
            if row is not None:
                row.deleted_at = deleted_at
                if extra is not None:
                    row.extra = dict(extra)

    def restore(self, artifact_id: str, extra: dict[str, Any] | None = None) -> None:
        """从回收站恢复：清空 deleted_at。"""
        with session_scope(self._sf) as session:
            row = session.get(ArtifactModel, artifact_id)
            if row is not None:
                row.deleted_at = None
                if extra is not None:
                    row.extra = dict(extra)

    def hard_delete(self, artifact_id: str) -> None:
        """彻底删除：连记录一起删掉（回收站里的「永久删除」）。"""
        with session_scope(self._sf) as session:
            row = session.get(ArtifactModel, artifact_id)
            if row is not None:
                session.delete(row)
