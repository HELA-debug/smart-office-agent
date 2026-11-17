"""校验依赖清单一致性（pyproject / requirements.api / requirements.lock）。

背景（代码审查 P1-6）：
- 依赖唯一真源是 `backend/pyproject.toml`；
- CI 的 pip-audit 曾只审 `deploy/requirements.api.txt`（另一份手抄清单），
  真源新增依赖而清单未同步时，漏洞扫描会漏检；
- 且 clean 环境无法完全复现构建。

本脚本做三件事（CI 直接调用，退出码非 0 即失败）：
1. requirements.api.txt 的包集合与 pyproject 的 dependencies 完全一致；
2. requirements.lock.txt 覆盖 pyproject 的全部直接依赖（且锁定到 `==`）；
3. requirements.lock.txt 全部为精确固定版本（不含 `>=`/`~=`），保证可复现。

用法：
    python scripts/check_requirements_sync.py
    python scripts/check_requirements_sync.py --quiet
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "backend" / "pyproject.toml"
API_REQS = ROOT / "deploy" / "requirements.api.txt"
LOCK = ROOT / "deploy" / "requirements.lock.txt"

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$")


def normalize(name: str) -> str:
    """包名归一化：PEP 503（大小写不敏感，-/_/. 等价）。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_requirement(line: str) -> tuple[str, str] | None:
    """解析一行依赖，返回 (归一化包名, 版本约束)。跳过注释/空行/选项行。"""
    text = line.split("#", 1)[0].strip()
    if not text or text.startswith("-"):
        return None
    match = _REQ_RE.match(text)
    if not match:
        return None
    name, _extras, specifier = match.groups()
    return normalize(name), (specifier or "").strip()


def read_requirements(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"✗ 缺少依赖清单：{path}")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_requirement(line)
        if parsed:
            result[parsed[0]] = parsed[1]
    return result


def pyproject_dependencies() -> dict[str, str]:
    payload = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = payload.get("project", {}).get("dependencies", [])
    result: dict[str, str] = {}
    for item in deps:
        parsed = parse_requirement(item)
        if parsed:
            result[parsed[0]] = parsed[1]
    return result


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验依赖清单一致性")
    parser.add_argument("--quiet", action="store_true", help="仅输出结论")
    args = parser.parse_args()

    problems: list[str] = []
    truth = pyproject_dependencies()
    if not truth:
        raise SystemExit(f"✗ {rel(PYPROJECT)} 中没有解析到 dependencies")

    api = read_requirements(API_REQS)
    lock = read_requirements(LOCK)

    # 1) requirements.api.txt 与 pyproject 包集合一致
    missing_api = sorted(set(truth) - set(api))
    extra_api = sorted(set(api) - set(truth))
    if missing_api:
        problems.append(
            f"{rel(API_REQS)} 缺少 pyproject 中的依赖：{', '.join(missing_api)}"
        )
    if extra_api:
        problems.append(
            f"{rel(API_REQS)} 含有 pyproject 中没有的依赖：{', '.join(extra_api)}"
        )

    # 2) 锁文件覆盖全部直接依赖
    missing_lock = sorted(set(truth) - set(lock))
    if missing_lock:
        problems.append(
            f"{rel(LOCK)} 未锁定以下直接依赖：{', '.join(missing_lock)}"
        )

    # 3) 锁文件必须全部是 == 精确版本
    unpinned = sorted(name for name, spec in lock.items() if not spec.startswith("=="))
    if unpinned:
        problems.append(
            f"{rel(LOCK)} 存在未精确固定的依赖（应为 ==）：{', '.join(unpinned)}"
        )

    # 4) 版本约束本身一致（避免 api 清单写成 >= 而 pyproject 已是 ~= 等）
    for name in sorted(set(truth) & set(api)):
        if truth[name].replace(" ", "") != api[name].replace(" ", ""):
            problems.append(
                f"{name} 版本约束不一致：pyproject={truth[name] or '(空)'} "
                f"{rel(API_REQS)}={api[name] or '(空)'}"
            )

    if problems:
        print("✗ 依赖清单不一致：", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        print(
            "\n修复方式：\n"
            "  1) 编辑 backend/pyproject.toml（唯一真源）\n"
            "  2) 同步 deploy/requirements.api.txt\n"
            "  3) 重新生成锁文件：make lock（或 pip-compile 命令见 deploy/requirements.lock.txt 头部）",
            file=sys.stderr,
        )
        return 1

    if not args.quiet:
        print(
            f"✓ 依赖清单一致：pyproject {len(truth)} 项 / "
            f"api {len(api)} 项 / lock {len(lock)} 项（全部精确定版）"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
