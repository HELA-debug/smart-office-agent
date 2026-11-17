#!/usr/bin/env python
"""commit-msg 校验：Conventional Commits（轻量版 commitlint）。

用法（由 pre-commit 的 commit-msg 阶段自动调用）：
    python scripts/check_commit_msg.py .git/COMMIT_EDITMSG

规则：
    <type>(<scope>): <subject>
    type ∈ feat|fix|refactor|test|docs|chore|perf|build|ci|style|revert
    - 支持 merge/revert 提交与 `fixup!`/`squash!` 前缀直接放行
    - subject 非空，长度 ≤ 100
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TYPES = {
    "feat",
    "fix",
    "refactor",
    "test",
    "docs",
    "chore",
    "perf",
    "build",
    "ci",
    "style",
    "revert",
}
PATTERN = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[\w./-]+)\))?!?: (?P<subject>.+)$")
ALLOW_PREFIX = ("Merge ", "Revert ", "fixup! ", "squash! ")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python scripts/check_commit_msg.py <commit-msg-file>", file=sys.stderr)
        return 2
    raw = Path(argv[1]).read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        print("✗ 提交信息为空", file=sys.stderr)
        return 1
    subject_line = raw.splitlines()[0].strip()
    if subject_line.startswith(ALLOW_PREFIX):
        return 0
    match = PATTERN.match(subject_line)
    if not match:
        print(
            "✗ 提交信息不符合 Conventional Commits：\n"
            f"  {subject_line}\n"
            "  格式：<type>(<scope>): <subject>\n"
            f"  type ∈ {'/'.join(sorted(TYPES))}\n"
            "  示例：feat(backend): add event replay",
            file=sys.stderr,
        )
        return 1
    if match.group("type") not in TYPES:
        print(
            f"✗ 未知 type={match.group('type')!r}；允许：{', '.join(sorted(TYPES))}",
            file=sys.stderr,
        )
        return 1
    if len(match.group("subject").strip()) > 100:
        print("✗ subject 超过 100 字符", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
