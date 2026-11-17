"""单测：打包态也能报出「这是哪一版」。

打包版里没有 .git，`detect_git_sha()` 原来直接返回空串，于是「设置 → 关于」只剩
`0.2.0 ·`，出了「本地界面和代码不一致」的问题时没法自证是哪一版。
现在打包时写一份 build_info.json 带进 exe，这里锁住读取逻辑与容错。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backend.app.core import utils


@pytest.fixture()
def frozen_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(utils, "RESOURCE_ROOT", tmp_path)
    return tmp_path


def test_frozen_reads_sha_from_build_info(frozen_bundle: Path) -> None:
    (frozen_bundle / "build_info.json").write_text(
        json.dumps({"git_sha": "5bc46b8", "built_at": "2026-10-29T22:32"}),
        encoding="utf-8",
    )
    assert utils.detect_git_sha() == "5bc46b8"


def test_missing_build_info_degrades_to_empty(frozen_bundle: Path) -> None:
    """没有这个文件（老 exe / 手工拷贝）不能报错，只是版本号少一段。"""
    assert utils.detect_git_sha() == ""


def test_broken_build_info_degrades_to_empty(frozen_bundle: Path) -> None:
    (frozen_bundle / "build_info.json").write_text("{ not json", encoding="utf-8")
    assert utils.detect_git_sha() == ""


def test_non_dict_payload_degrades_to_empty(frozen_bundle: Path) -> None:
    (frozen_bundle / "build_info.json").write_text("[]", encoding="utf-8")
    assert utils.read_build_info() == {}


def test_source_mode_still_shells_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """源码态保持原行为：读 git，不去碰 build_info.json。"""
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        lambda *args, **kwargs: type("R", (), {"returncode": 0, "stdout": "abc1234\n"})(),
    )
    assert utils.detect_git_sha() == "abc1234"
