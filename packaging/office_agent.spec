# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出一个 Windows 单文件 exe。

用法（在仓库根）：

    ./.venv/Scripts/python.exe -m PyInstaller packaging/office_agent.spec --noconfirm

产物：dist/Office Agent.exe（一个文件，双击即用，不需要装 Python / Node）。

设计要点：

1. 入口是 scripts/app_entry.py（不是 scripts/launch.py）：exe 里没有 venv、
   没有 Node、没有仓库根，launch.py 那套「准备环境」的逻辑在打包版里全是错分支。
2. 只有「非 .py 资源」需要手工列进 datas：前端 dist、提示词、技能库、数据库迁移脚本、
   价格表、.env 示例。.py 模块由 PyInstaller 沿 import 链自动收集。
3. 用户数据（SQLite、上传、产物、.env）不在这里——它们运行时落在数据目录，
   源码态是仓库根，打包态是 %LOCALAPPDATA%\\Office Agent（见 backend/app/core/paths.py）。
   这是打包最重要的一条纪律：写进 exe 解压目录的数据，关掉程序就没了。
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent


def _git_sha() -> str:
    """打包时的 commit：写进 build_info.json，供界面「设置 → 关于」显示。

    打包版里没有 .git，运行期读不到 sha；没有它就没法判断「这个 exe 是哪一版」，
    也就没法解释「本地看到的界面和代码不一致」。
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _write_build_info() -> Path:
    import json
    from datetime import datetime

    target = ROOT / "build" / "build_info.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "git_sha": _git_sha(),
        "built_at": datetime.now().isoformat(timespec="minutes"),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


BUILD_INFO = _write_build_info()

datas = [
    # 前端构建产物（SERVE_FRONTEND=1 时由 FastAPI 直接托管）
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    # 打包时的 commit / 构建时间：/api/v1/health 与界面「关于」都读它
    (str(BUILD_INFO), "."),
    # 提示词与提示词包
    (str(ROOT / "backend" / "app" / "prompts"), "backend/app/prompts"),
    # 内置技能与技能库
    (str(ROOT / "backend" / "app" / "skills"), "backend/app/skills"),
    (str(ROOT / "backend" / "app" / "skills_catalog"), "backend/app/skills_catalog"),
    # Alembic 迁移脚本（启动时 upgrade head 要用；版本文件是动态加载的，必须按 data 带）
    (
        str(ROOT / "backend" / "app" / "infra" / "db" / "migrations"),
        "backend/app/infra/db/migrations",
    ),
    # 模型价格表（backend/config/model_prices.yaml）
    (str(ROOT / "backend" / "config"), "backend/config"),
    # 冒烟评测用例
    (str(ROOT / "backend" / "app" / "evals" / "smoke_cases.json"), "backend/app/evals"),
    # 首次运行时复制成数据目录里的 .env
    (str(ROOT / ".env.example"), "."),
]

# 动态导入 / 字符串导入的模块，静态分析扫不到，必须显式登记
hiddenimports = [
    "launch",  # scripts/launch.py：入口复用了它的端口探测与健康检查
    "backend.app.main",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "alembic",
    "docx",
    "pypdf",
    "openpyxl",
    "reportlab",
    "multipart",
    "yaml",
    "httpx",
]

# 测试/开发工具不会在运行时被 import，带上只会白白撑大体积
excludes = [
    "pytest",
    "pytest_asyncio",
    "pytest_mock",
    "pytest_cov",
    "coverage",
    "hypothesis",
    "IPython",
    "tkinter",
    "sphinx",
    "mypy",
    "ruff",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "scripts" / "app_entry.py")],
    pathex=[str(ROOT), str(ROOT / "scripts")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Office Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 不加壳：UPX 压缩省不了多少体积，反而常见杀软误报
    runtime_tmpdir=None,
    console=True,  # 保留窗口：地址写在这儿，用户关窗口 = 退出程序
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "icon.ico"),
)
