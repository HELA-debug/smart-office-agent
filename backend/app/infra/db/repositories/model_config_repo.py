from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import ModelConfigEntity
from ..models import ModelConfigModel
from ..session import session_scope


def _to_entity(row: ModelConfigModel) -> ModelConfigEntity:
    return ModelConfigEntity(
        id=row.id,
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        api_key_ref=row.api_key_ref,
        priority=row.priority,
        enabled=bool(row.enabled),
        extra=dict(row.extra or {}),
    )


class SqlModelConfigRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def list_all(self) -> list[ModelConfigEntity]:
        stmt = select(ModelConfigModel).order_by(ModelConfigModel.priority.asc())
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def add(self, config: ModelConfigEntity) -> ModelConfigEntity:
        with session_scope(self._sf) as session:
            session.add(
                ModelConfigModel(
                    id=config.id,
                    provider=config.provider,
                    base_url=config.base_url,
                    model=config.model,
                    api_key_ref=config.api_key_ref,
                    priority=config.priority,
                    enabled=config.enabled,
                    extra=dict(config.extra),
                )
            )
        return config

    def update(self, config: ModelConfigEntity) -> ModelConfigEntity:
        with session_scope(self._sf) as session:
            row = session.get(ModelConfigModel, config.id)
            if row is None:
                raise ValueError(f"model config not found: {config.id}")
            row.provider = config.provider
            row.base_url = config.base_url
            row.model = config.model
            row.api_key_ref = config.api_key_ref
            row.priority = config.priority
            row.enabled = config.enabled
            row.extra = dict(config.extra)
        return config

    def delete(self, config_id: str) -> None:
        with session_scope(self._sf) as session:
            row = session.get(ModelConfigModel, config_id)
            if row is not None:
                session.delete(row)

    def get(self, config_id: str) -> ModelConfigEntity | None:
        with session_scope(self._sf) as session:
            row = session.get(ModelConfigModel, config_id)
            return _to_entity(row) if row is not None else None
