"""资源根 / 数据根的拆分（打包成 exe 的生命线）。

打包后只有一个不变量真正要命：用户数据不能写进 exe 的解压目录
（--onefile 每次启动解压、退出即删）。写错了的表现是「今天用得好好的，
明天打开全没了」，而且没有任何报错——所以这里把它钉死成测试：

    打包态：resource_root() == 解压目录，data_root() == 用户数据目录，两者不相等

源码态两者都是仓库根，保持与历史行为一致（不改开发体验和现有测试）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from app.core import paths
from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """模拟 PyInstaller 打包态：sys.frozen=True + sys._MEIPASS 指向临时目录。"""
    bundle = tmp_path / "_MEI123456"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    return bundle


def test_source_mode_both_roots_are_repo_root():
    assert paths.IS_FROZEN is False
    assert paths.resource_root() == REPO_ROOT
    assert paths.data_root() == REPO_ROOT


def test_is_frozen_is_the_single_live_check(monkeypatch: pytest.MonkeyPatch):
    """形态要动态切换时以 is_frozen() 为准；IS_FROZEN 只是导入时快照，别拿它判路径。"""
    assert paths.is_frozen() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.is_frozen() is True
    assert paths.IS_FROZEN is False
    assert paths.data_root() != REPO_ROOT


def test_data_dir_env_overrides_in_source_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = tmp_path / "somewhere-else"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(target))
    assert paths.data_root() == target
    assert paths.resource_root() == REPO_ROOT


def test_frozen_resource_root_is_bundle_dir(frozen: Path):
    assert paths.resource_root() == frozen


def test_frozen_data_root_is_user_dir_not_bundle(frozen: Path):
    """核心不变量：数据根目录绝不能落在解压目录里。"""
    data = paths.data_root()
    assert data != frozen
    assert frozen not in data.parents

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        expected = Path(base) / paths.APP_NAME
    elif sys.platform == "darwin":
        expected = Path.home() / "Library" / "Application Support" / paths.APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        expected = Path(base) / paths.APP_NAME.lower().replace(" ", "-")
    assert data == expected


def test_frozen_data_dir_env_wins(frozen: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """U 盘 / 多实例场景：OA_DATA_DIR 显式指定时优先。"""
    target = tmp_path / "portable-data"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(target))
    assert paths.data_root() == target


def test_settings_data_paths_follow_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """数据库/上传/产物/模板都按数据根解析，与前端 dist（资源根）互不影响。"""
    monkeypatch.setattr("app.core.config.DATA_ROOT", tmp_path)
    settings = Settings(_env_file=None, database_url="sqlite:///data/app.db")

    assert settings.resolve_data_path("./data/app.db") == tmp_path / "data" / "app.db"
    assert settings.uploads_path == tmp_path / "data" / "uploads"
    assert settings.artifacts_path == tmp_path / "data" / "artifacts"
    assert settings.uploads_path != settings.frontend_dist_path


def test_settings_frontend_dist_uses_resource_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """前端 dist 是只读资源：打包后从解压目录读，不能跟着数据目录跑。"""
    bundle = tmp_path / "bundle"
    (bundle / "frontend" / "dist").mkdir(parents=True)
    (bundle / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.core.config.RESOURCE_ROOT", bundle)
    monkeypatch.setattr("app.core.config.PROJECT_ROOT", bundle)

    settings = Settings(_env_file=None)
    assert settings.frontend_dist_path == bundle / "frontend" / "dist"


def test_packaged_entry_prepares_env_file(tmp_path: Path):
    """打包入口：首次运行要把内置的 .env.example 复制成数据目录里的 .env。"""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import app_entry
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))

    data_dir = tmp_path / "data-home"
    created = app_entry.prepare_data_dir(data_dir, REPO_ROOT)
    assert data_dir.is_dir()
    assert created is True
    assert (data_dir / ".env").is_file()

    # 第二次不该覆盖用户已经改过的配置
    (data_dir / ".env").write_text("MOCK_MODE=false\n", encoding="utf-8")
    assert app_entry.prepare_data_dir(data_dir, REPO_ROOT) is False
    assert (data_dir / ".env").read_text(encoding="utf-8") == "MOCK_MODE=false\n"
