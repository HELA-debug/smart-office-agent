"""技能服务：启停 / 删除 / 导入，并重建运行时提示词（都即时生效，不用重启）。"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..agents.runtime import CATALOG_DIR, SKILLS_DIR, load_catalog, load_skills
from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.utils import now_iso
from ..domain.entities import SettingItem
from ..domain.ports import SettingsRepository

_SETTINGS_KEY = "skills.disabled"
MAX_SKILL_BYTES = 200 * 1024
# 目录名既要能放中文（用户的技能常叫「周报」），又不能带路径分隔符/点号
_SKILL_SLUG_RE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]")


class SkillService:
    def __init__(self, repo: SettingsRepository, settings: Settings):
        self.repo = repo
        self.settings = settings
        self.runtime: Any = None
        self._base_prompt = ""
        # 技能根目录：默认仓库内的 app/skills，测试可替换成临时目录
        self.skills_dir: Path = SKILLS_DIR
        # 技能库（可以添加但还没装的内置技能）：测试同样可替换
        self.catalog_dir: Path = CATALOG_DIR

    # ---------- 装配 ----------
    def bind_runtime(self, runtime: Any) -> None:
        self.runtime = runtime
        self._base_prompt = runtime.prompt
        self.apply_persisted()

    # ---------- 读取 ----------
    def _disabled(self) -> set[str]:
        item = self.repo.get(_SETTINGS_KEY)
        if item is None or not isinstance(item.value, list):
            return set()
        return {str(name) for name in item.value}

    def list_skills(self) -> list[dict[str, Any]]:
        if self.runtime is None:
            return []
        disabled = self._disabled()
        skills: list[dict[str, Any]] = []
        for name, info in sorted(self.runtime.skills.items()):
            enabled = bool(info.enabled) and name not in disabled
            skills.append(
                {
                    **info.to_dict(),
                    "enabled": enabled,
                    "content_chars": len(info.content),
                }
            )
        return skills

    def list_catalog(self) -> list[dict[str, Any]]:
        """技能库：可以一键添加的内置技能（还没进 app/skills 的不占提示词）。"""
        installed = {entry["name"] for entry in self.list_skills()}
        return [
            {**entry, "installed": entry["name"] in installed}
            for entry in load_catalog(self.catalog_dir)
        ]

    def install_from_catalog(self, skill_id: str) -> dict[str, Any]:
        """把技能库里的一份技能复制到 app/skills，装完即为启用状态。"""
        entry = next(
            (
                item
                for item in load_catalog(self.catalog_dir)
                if skill_id in (item["name"], item["slug"])
            ),
            None,
        )
        if entry is None:
            raise AppError(ErrorCode.NOT_FOUND, f"技能库里没有这个技能：{skill_id}")
        if any(item["name"] == entry["name"] for item in self.list_skills()):
            raise AppError(ErrorCode.CONFLICT, f"已经添加过「{entry['title']}」了")
        slug = str(entry["slug"])
        target = self.skills_dir / slug
        if target.exists():
            raise AppError(ErrorCode.CONFLICT, f"技能目录已存在：{slug}")
        shutil.copytree(self.catalog_dir / slug, target)
        self._reload()
        # 装完默认启用：用户点「添加」就是要它开始工作
        disabled = self._disabled()
        if entry["name"] in disabled:
            disabled.discard(entry["name"])
            self.repo.upsert(
                SettingItem(
                    key=_SETTINGS_KEY,
                    value=sorted(disabled),
                    updated_at=now_iso(),
                    scope="global",
                    is_secret=False,
                )
            )
            self.apply_persisted()
        item = next(
            (skill for skill in self.list_skills() if skill["name"] == entry["name"]),
            None,
        )
        return {"name": entry["name"], "slug": slug, "skill": item}

    def prompt_chars(self) -> int:
        return len(self.runtime.prompt) if self.runtime is not None else 0

    # ---------- 启停 ----------
    def set_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any]:
        if self.runtime is None:
            raise AppError(ErrorCode.INTERNAL, "运行时未装配")
        info = self.runtime.skills.get(skill_id)
        if info is None:
            raise AppError(ErrorCode.NOT_FOUND, f"技能不存在：{skill_id}")
        disabled = self._disabled()
        if enabled:
            disabled.discard(skill_id)
        else:
            disabled.add(skill_id)
        self.repo.upsert(
            SettingItem(
                key=_SETTINGS_KEY,
                value=sorted(disabled),
                updated_at=now_iso(),
                scope="global",
                is_secret=False,
            )
        )
        info.enabled = enabled
        self._rebuild_prompt()
        return {
            "name": skill_id,
            "enabled": enabled,
            "prompt_chars": self.prompt_chars(),
        }

    # ---------- 应用 ----------
    def apply_persisted(self) -> None:
        if self.runtime is None:
            return
        disabled = self._disabled()
        for name, info in self.runtime.skills.items():
            info.enabled = name not in disabled
        self._rebuild_prompt()

    # ---------- 删除 / 导入 ----------
    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        """删除技能目录（挪进 app/skills/.trash 而不是直接删，误删还能捞回来）。"""
        info = self._require(skill_id)
        folder = Path(info.path).resolve().parent
        root = self.skills_dir.resolve()
        if folder.parent != root:
            # 只允许删技能根目录下的直接子目录，防止 path 参数被拼歪
            raise AppError(ErrorCode.BAD_REQUEST, f"拒绝删除该路径：{folder}")
        target = root / ".trash" / f"{folder.name}-{time.strftime('%Y%m%d%H%M%S')}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder), str(target))
        self._reload()
        return {"name": skill_id, "deleted": True, "recovered_at": str(target)}

    def import_skill(self, filename: str, data: bytes) -> dict[str, Any]:
        """导入一个 SKILL.md（带 name/description/triggers frontmatter）。"""
        if not data:
            raise AppError(ErrorCode.BAD_REQUEST, "文件是空的")
        if len(data) > MAX_SKILL_BYTES:
            raise AppError(ErrorCode.BAD_REQUEST, f"技能文件超过 {MAX_SKILL_BYTES // 1024}KB 上限")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppError(ErrorCode.BAD_REQUEST, "技能文件必须是 UTF-8 文本") from exc
        if not text.strip():
            raise AppError(ErrorCode.BAD_REQUEST, "技能文件里没有内容")

        name = _frontmatter_name(text) or Path(filename or "skill").stem
        slug = _SKILL_SLUG_RE.sub("-", name).strip("-") or "skill"
        folder = self.skills_dir / slug
        if folder.exists():
            raise AppError(ErrorCode.CONFLICT, f"已经有同名技能：{name}")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(text, encoding="utf-8")
        self._reload()
        item = next((entry for entry in self.list_skills() if entry["name"] in (name, slug)), None)
        return {"skill": item, "name": name, "slug": slug}

    def _require(self, skill_id: str) -> Any:
        if self.runtime is None:
            raise AppError(ErrorCode.INTERNAL, "运行时未装配")
        info = self.runtime.skills.get(skill_id)
        if info is None:
            raise AppError(ErrorCode.NOT_FOUND, f"技能不存在：{skill_id}")
        return info

    def _reload(self) -> None:
        """重新扫磁盘：导入/删除后调用，技能列表与提示词立刻跟着变。"""
        if self.runtime is None:
            return
        self.runtime.skills = load_skills(self.skills_dir)
        # 删掉的技能可能还躺在禁用名单里，顺手清掉，避免以后同名技能一导入就是关着的
        known = set(self.runtime.skills)
        disabled = {name for name in self._disabled() if name in known}
        self.repo.upsert(
            SettingItem(
                key=_SETTINGS_KEY,
                value=sorted(disabled),
                updated_at=now_iso(),
                scope="global",
                is_secret=False,
            )
        )
        self.apply_persisted()

    def _rebuild_prompt(self) -> None:
        if self.runtime is None:
            return
        parts = [self._base_prompt]
        enabled_skills = [info for info in self.runtime.skills.values() if info.enabled]
        if enabled_skills:
            parts.append("# 可用技能（按需参考）")
            for info in enabled_skills:
                parts.append(f"## {info.name}\n{info.content}")
        self.runtime.prompt = "\n\n".join(part for part in parts if part)


def _frontmatter_name(text: str) -> str:
    """从 SKILL.md 的 frontmatter 里取 name（没有就返回空串，由调用方退回文件名）。"""
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    for line in parts[1].splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "name":
            return value.strip().strip('"').strip("'")
    return ""
