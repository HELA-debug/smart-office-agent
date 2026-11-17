"""技能管理（导入 / 删除 / 启停）单测：全部落在临时目录，不碰仓库里的真实技能。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.errors import AppError, ErrorCode
from app.services.skill_service import SkillService


class FakeRepo:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self.items.get(key)

    def upsert(self, item: object) -> object:
        self.items[item.key] = item
        return item


def make_service(root: Path) -> SkillService:
    service = SkillService(repo=FakeRepo(), settings=SimpleNamespace())  # type: ignore[arg-type]
    service.runtime = SimpleNamespace(skills={}, prompt="基础提示词")
    service._base_prompt = "基础提示词"
    service.skills_dir = root
    # 技能库也指到临时目录：别让单测读到仓库里真实的 app/skills_catalog
    service.catalog_dir = root / "_catalog"
    return service


SKILL_MD = """---
name: 周报助手
description: 按周报骨架整理材料
triggers: [周报, 周总结]
---

# 周报助手
按摘要/进展/数据/风险/计划组织内容。
"""


def test_import_creates_folder_and_enables_prompt(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    result = service.import_skill("SKILL.md", SKILL_MD.encode("utf-8"))

    assert result["name"] == "周报助手"
    folder = tmp_path / str(result["slug"])
    assert (folder / "SKILL.md").is_file()
    names = [item["name"] for item in service.list_skills()]
    assert names == ["周报助手"]
    # 导入后提示词立刻带上技能内容（不用重启）
    assert "周报助手" in service.runtime.prompt
    assert "按摘要/进展/数据/风险/计划" in service.runtime.prompt


def test_import_duplicate_conflicts(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.import_skill("SKILL.md", SKILL_MD.encode("utf-8"))
    with pytest.raises(AppError) as exc:
        service.import_skill("SKILL.md", SKILL_MD.encode("utf-8"))
    assert exc.value.code == ErrorCode.CONFLICT


def test_import_rejects_bad_payload(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(AppError):
        service.import_skill("SKILL.md", b"")
    with pytest.raises(AppError):
        service.import_skill("SKILL.md", b"\xff\xfe\x00bad")
    with pytest.raises(AppError):
        service.import_skill("big.md", b"x" * (200 * 1024 + 1))


def test_slug_cannot_escape_root(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    payload = "---\nname: ../../逃逸\n---\n正文"
    result = service.import_skill("SKILL.md", payload.encode("utf-8"))
    slug = str(result["slug"])
    assert "/" not in slug and "\\" not in slug and ".." not in slug
    assert (tmp_path / slug / "SKILL.md").is_file()
    assert not (tmp_path.parent / "逃逸").exists()


def test_delete_moves_to_trash_and_clears_prompt(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.import_skill("SKILL.md", SKILL_MD.encode("utf-8"))
    name = service.list_skills()[0]["name"]

    result = service.delete_skill(str(name))
    assert result["deleted"] is True
    assert Path(result["recovered_at"]).exists()  # 挪进 .trash，可人工恢复
    assert service.list_skills() == []
    assert "周报助手" not in service.runtime.prompt


def test_delete_refuses_path_outside_root(tmp_path: Path) -> None:
    service = make_service(tmp_path / "skills")
    (tmp_path / "skills").mkdir()
    outside = tmp_path / "outside" / "SKILL.md"
    outside.parent.mkdir()
    outside.write_text(SKILL_MD, encoding="utf-8")
    service.runtime.skills = {
        "外挂": SimpleNamespace(name="外挂", path=str(outside), content="x", enabled=True)
    }

    with pytest.raises(AppError) as exc:
        service.delete_skill("外挂")
    assert exc.value.code == ErrorCode.BAD_REQUEST
    assert outside.exists()


def test_set_enabled_persists_and_rebuilds_prompt(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.import_skill("SKILL.md", SKILL_MD.encode("utf-8"))
    name = str(service.list_skills()[0]["name"])

    result = service.set_enabled(name, False)
    assert result["enabled"] is False
    assert "周报助手" not in service.runtime.prompt
    assert [item["enabled"] for item in service.list_skills()] == [False]

    service.set_enabled(name, True)
    assert "周报助手" in service.runtime.prompt


# ---------- 技能库（可添加的内置技能） ----------

CATALOG_MD = """---
name: 会议纪要
title: 会议纪要
description: 把速记压成决议与待办
triggers: [纪要, 会议记录]
category: 会议协作
icon: minutes
badge: 必备精选
---

# 会议纪要
按决议/待办/遗留问题组织内容。
"""


def seed_catalog(service: SkillService) -> Path:
    folder = service.catalog_dir / "meeting-minutes"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(CATALOG_MD, encoding="utf-8")
    return folder


def test_catalog_lists_metadata_and_installed_flag(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_catalog(service)

    items = service.list_catalog()
    assert len(items) == 1
    item = items[0]
    assert item["name"] == "会议纪要"
    assert item["title"] == "会议纪要"
    assert item["category"] == "会议协作"
    assert item["icon"] == "minutes"
    assert item["badge"] == "必备精选"
    assert item["slug"] == "meeting-minutes"
    assert item["installed"] is False
    assert item["content_chars"] > 0
    # 只是「能添加」，没装之前不进提示词
    assert "会议纪要" not in service.runtime.prompt


def test_install_copies_skill_and_enables_it(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_catalog(service)

    result = service.install_from_catalog("meeting-minutes")
    assert result["name"] == "会议纪要"
    assert result["slug"] == "meeting-minutes"
    assert (tmp_path / "meeting-minutes" / "SKILL.md").is_file()
    assert [item["name"] for item in service.list_skills()] == ["会议纪要"]
    assert service.list_skills()[0]["enabled"] is True
    assert "按决议/待办/遗留问题组织内容" in service.runtime.prompt
    # 装完技能库里标记为已添加，不能再点一次「添加」
    assert service.list_catalog()[0]["installed"] is True


def test_install_rejects_unknown_and_duplicate(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_catalog(service)

    with pytest.raises(AppError) as missing:
        service.install_from_catalog("不存在的技能")
    assert missing.value.code == ErrorCode.NOT_FOUND

    service.install_from_catalog("会议纪要")
    with pytest.raises(AppError) as duplicated:
        service.install_from_catalog("会议纪要")
    assert duplicated.value.code == ErrorCode.CONFLICT
