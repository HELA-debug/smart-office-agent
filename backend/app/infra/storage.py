"""本地文件存储：上传目录 / 产物目录，统一做路径逃逸防护与文件名清洗。"""

from __future__ import annotations

import contextlib
from pathlib import Path

from ..core.config import Settings
from ..core.security import ensure_within, safe_filename
from ..core.utils import new_id


class LocalFileStorage:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._ensure(self.uploads_root)
        self._ensure(self.artifacts_root)
        self._ensure(self.trash_root)

    @staticmethod
    def _ensure(path: Path) -> Path:
        with contextlib.suppress(OSError):
            path.mkdir(parents=True, exist_ok=True)
        return path

    # 三个根目录都按 settings 实时解析（不是构造时烤死）：
    # 用户在设置里改了产物目录后，后续新产物会直接落到新目录，无需重启。
    @property
    def uploads_root(self) -> Path:
        return self._settings.uploads_path

    @property
    def artifacts_root(self) -> Path:
        return self._ensure(self._settings.artifacts_path)

    @property
    def trash_root(self) -> Path:
        return self._ensure(self._settings.trash_path)

    def save_upload(self, thread_id: str, filename: str, data: bytes) -> tuple[Path, str]:
        ext = Path(safe_filename(filename)).suffix.lower()
        stored = self.uploads_root / f"{new_id('f')}{ext}"
        stored.write_bytes(data)
        return ensure_within(stored, self.uploads_root), ext

    def save_text(self, stored_path: Path, text: str) -> Path:
        # 注意不能与原文件同名（txt/md 上传时 with_suffix 会覆盖原文件）
        text_path = stored_path.with_suffix(".parsed.txt")
        text_path.write_text(text, encoding="utf-8", newline="\n")
        return text_path

    def new_artifact_path(self, filename: str) -> Path:
        target = ensure_within(self.artifacts_root / safe_filename(filename), self.artifacts_root)
        if not target.exists():
            return target
        # 同名再生成（例如同一天出第二份摘要）：按 (2)(3) 往后排，别塞随机串——
        # 用户在下载目录里要能一眼看出先后，随机四位看起来像乱码
        index = 2
        while True:
            candidate = target.with_name(f"{target.stem}({index}){target.suffix}")
            if not candidate.exists():
                return ensure_within(candidate, self.artifacts_root)
            index += 1

    def preview_path(self, artifact_path: Path) -> Path:
        return artifact_path.with_suffix(".preview.html")

    def write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")

    def exists(self, path: str) -> bool:
        return bool(path) and Path(path).exists()

    def trash(self, path: str) -> str:
        """软删配套：把文件移入 data/trash/（保留原文件名 + 短 ID，避免重名）。"""
        source = Path(path)
        if not source.exists():
            return ""
        target = self.trash_root / f"{new_id('t')}_{safe_filename(source.name)}"
        with contextlib.suppress(OSError):
            source.replace(target)
            return str(target)
        return ""

    def restore_file(self, from_path: str, to_path: str) -> bool:
        """回收站恢复：把文件从 trash 挪回原路径（原目录不存在时自动创建）。"""
        source = Path(from_path)
        if not source.exists():
            return False
        target = Path(to_path)
        with contextlib.suppress(OSError):
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            return True
        return False

    def delete_file(self, path: str) -> None:
        """彻底删除单个文件（回收站「永久删除」用，只接受 trash 内的路径）。"""
        with contextlib.suppress(OSError):
            Path(path).unlink(missing_ok=True)

    def delete(self, path: str) -> None:
        with contextlib.suppress(OSError):
            Path(path).unlink(missing_ok=True)
