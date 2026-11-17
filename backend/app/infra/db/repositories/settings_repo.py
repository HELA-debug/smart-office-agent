from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ....domain.entities import SettingItem
from ..models import SettingModel
from ..session import session_scope


def _to_entity(row: SettingModel) -> SettingItem:
    return SettingItem(
        key=row.key,
        scope=row.scope,
        value=row.value_json,
        is_secret=bool(row.is_secret),
        updated_at=row.updated_at,
    )


class SqlSettingsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    def list_all(self) -> list[SettingItem]:
        stmt = select(SettingModel).order_by(SettingModel.key.asc())
        with session_scope(self._sf) as session:
            return [_to_entity(row) for row in session.scalars(stmt)]

    def get(self, key: str) -> SettingItem | None:
        with session_scope(self._sf) as session:
            row = session.get(SettingModel, key)
            return _to_entity(row) if row is not None else None

    def upsert(self, item: SettingItem) -> SettingItem:
        with session_scope(self._sf) as session:
            row = session.get(SettingModel, item.key)
            if row is None:
                session.add(
                    SettingModel(
                        key=item.key,
                        scope=item.scope,
                        value_json=item.value,
                        is_secret=item.is_secret,
                        updated_at=item.updated_at,
                    )
                )
            else:
                row.scope = item.scope
                row.value_json = item.value
                row.is_secret = item.is_secret
                row.updated_at = item.updated_at
        return item

    def as_dict(self) -> dict[str, Any]:
        return {item.key: item.value for item in self.list_all()}
