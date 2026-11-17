#!/usr/bin/env python3
"""一键启动：双击「启动 Office Agent.cmd」（macOS 是 `启动 Office Agent.command`）跑的就是这里。

为什么不是一条 .bat：Windows 和 macOS 共用一套逻辑，而且每一步失败都能说清
「卡在哪、为什么、怎么办」——黑框一闪就没了是最劝退的。判断标准是：完全不懂命令行的人
也能一路回车到浏览器打开。

依次做四件事：
1. 确认这台电脑的 Python 版本够用（不够就给出下载地址，不往下走）
2. 准备 .venv（第一次启动要几分钟）
3. 装后端依赖（已经装过就跳过，第二次启动几秒钟）
4. 确认前端已经构建（没构建就构建一次），起服务，等它真能访问了再自动开浏览器

参数：
    --port 8000     换端口（被占用时会自动往后找；实际用的会打印出来）
    --no-browser    只启动，不开浏览器
    --rebuild       强制重新构建前端
    --check         只做环境检查，不启动（给排错和自动化用）

退出码：0 正常结束（含 Ctrl+C）；2 已经打印过原因并等过按键（启动脚本据此不再停一次）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = REPO_ROOT / ".venv"
FRONTEND_DIR = REPO_ROOT / "frontend"
DIST_INDEX = FRONTEND_DIR / "dist" / "index.html"
REQUIREMENTS = REPO_ROOT / "deploy" / "requirements.api.txt"
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# 后端运行所需的模块（与 deploy/requirements.api.txt 对齐）；用来判断「装过没」
REQUIRED_MODULES = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "pydantic_settings",
    "docx",
    "pypdf",
    "openpyxl",
    "reportlab",
    "httpx",
    "yaml",
    "multipart",
)

PYPI_MIRROR = "https://mirrors.aliyun.com/pypi/simple"
DEFAULT_PORT = 8000
HEALTH_PATH = "/api/v1/health"

_step_no = 0


# --------------------------------------------------------------------- 输出
def say(message: str = "") -> None:
    print(message, flush=True)


def step(title: str, total: int = 4) -> None:
    global _step_no
    _step_no += 1
    say()
    say(f"[{_step_no}/{total}] {title}")


def detail(message: str) -> None:
    say(f"      {message}")


def wait_for_key(text: str = "  按任意键关闭这个窗口...") -> None:
    """窗口别一闪就没：双击启动的人看不到已经滚过去的报错。

    只在真终端里等（管道、CI、pytest 里 stdin 不是 tty，等下去会卡死）。
    """
    if not sys.stdin or not sys.stdin.isatty():
        return
    say()
    try:
        input(text)
    except (EOFError, KeyboardInterrupt):  # pragma: no cover - 用户直接关窗口
        pass


def die(message: str, hint: str | None = None) -> None:
    """打印「卡在哪 + 为什么 + 怎么办」，等用户看完再退出。

    退出码用 2：启动脚本据此判断「已经提示过也等过按键了」，不再多停一次。
    """
    say()
    say("  × 没能启动，原因：")
    say(f"    {message}")
    if hint:
        say()
        for line in hint.splitlines():
            say(f"    {line}")
    wait_for_key()
    sys.exit(2)


def _setup_console() -> None:
    """Windows 控制台默认 GBK，中文提示会变问号或直接抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - 老终端不支持就算了
                pass


def set_console_title(text: str) -> None:
    """把地址写进窗口标题：提示滚上去了也还能看到「该访问哪个地址」。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(text[:200])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - 非控制台（IDE/管道）里没有窗口标题
        pass


# --------------------------------------------------------------------- 环境
def _run(command: list[str], cwd: Path | None = None) -> int:
    """跑外部命令；Windows 上 .cmd/.bat 必须经 cmd /c 才起得来。"""
    resolved = list(command)
    if os.name == "nt" and resolved[0].lower().endswith((".cmd", ".bat")):
        resolved = ["cmd", "/c", *resolved]
    try:
        return subprocess.call(resolved, cwd=str(cwd or REPO_ROOT))
    except FileNotFoundError:
        return 127


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def python_version(python: Path) -> tuple[int, int] | None:
    try:
        out = subprocess.check_output(
            [str(python), "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        major, minor = out.strip().split(".")
        return int(major), int(minor)
    except ValueError:
        return None


def deps_installed(python: Path) -> bool:
    code = "import " + ", ".join(REQUIRED_MODULES)
    return _run_with(python, ["-c", code]) == 0


def _run_with(python: Path, args: list[str]) -> int:
    try:
        return subprocess.call(
            [str(python), *args],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return 127


def ensure_venv() -> Path:
    """返回「该用哪个 python 装依赖、起服务」。已经在 venv 里就直接用。"""
    if Path(sys.prefix).resolve() == VENV_DIR.resolve() and venv_python().is_file():
        detail("使用当前虚拟环境（已在 .venv 里运行）")
        return venv_python()

    python = venv_python()
    if python.is_file():
        existing = python_version(python)
        if existing is not None:
            detail(f"复用已有的 .venv（{existing[0]}.{existing[1]}）")
            return python

    version = python_version(Path(sys.executable))
    if version is None or version < (3, 10):
        die(
            "这台电脑的 Python 太旧了（需要 3.10 或更新的版本）",
            "去 https://www.python.org/downloads/ 下载安装最新版，\n"
            "安装第一步记得勾选「Add python.exe to PATH」，装完再双击一次启动。",
        )

    detail("第一次启动，正在创建运行环境（大约 1 分钟，别关窗口）...")
    code = _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if code != 0 or not python.is_file():
        die(
            "创建运行环境失败",
            "可能原因：系统缺少 Python 自带的 venv 组件。\n"
            "重装 Python 时勾选「pip」和「venv」再试一次。",
        )
    return python


def install_deps(python: Path) -> None:
    detail("正在安装依赖（第一次大约 2-5 分钟，有下载进度在走就说明正常）...")
    base = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-r",
        str(REQUIREMENTS),
    ]
    with_mirror = [*base[:4], "-i", PYPI_MIRROR, *base[4:]]
    if _run(with_mirror) == 0:
        return
    detail("镜像源没连上，改用官方源重试...")
    if _run(base) != 0:
        die(
            "依赖没装上（网络问题最常见）",
            "请确认这台电脑能上网，然后重新双击启动。\n如果公司网络要走代理，先关掉代理再试。",
        )


def ensure_env_file() -> None:
    """没有 .env 就用示例补一份：不然第一次启动连日志级别都没有默认值。"""
    if ENV_FILE.is_file() or not ENV_EXAMPLE.is_file():
        return
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    detail("已生成本机配置 .env（没有填模型 Key 也能先用演示模式）")


def npm_command() -> str | None:
    for name in ("npm.cmd", "npm") if os.name == "nt" else ("npm",):
        found = shutil.which(name)
        if found:
            return found
    return None


def _frontend_sources_newer_than_dist() -> bool:
    """源码里有没有比 `dist/index.html` 更新的文件——有就说明改了代码没重新构建。

    这不是洁癖：`frontend/dist` 不进版本库，`git pull` 之后直接启动会跑上一版界面，
    用户看到的是「样式变差了/少了个改动」，排查半天才发现跑的是旧产物。
    """
    if not DIST_INDEX.is_file():
        return True
    dist_mtime = DIST_INDEX.stat().st_mtime
    roots = [FRONTEND_DIR / "src", FRONTEND_DIR / "public"]
    for directory in roots:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.stat().st_mtime > dist_mtime:
                return True
    for name in ("index.html", "vite.config.ts", "package.json", "package-lock.json"):
        target = FRONTEND_DIR / name
        if target.is_file() and target.stat().st_mtime > dist_mtime:
            return True
    return False


def ensure_frontend(rebuild: bool) -> None:
    """界面是构建产物；没构建过、或源码比产物新，就用 npm 构建一次（只有这一步需要 Node）。"""
    stale = _frontend_sources_newer_than_dist()
    if DIST_INDEX.is_file() and not rebuild and not stale:
        detail("界面已就绪（frontend/dist，且不比源码旧）")
        return
    if DIST_INDEX.is_file() and stale:
        detail("界面产物比源码旧（改过代码没重新构建），先重新生成一次...")

    npm = npm_command()
    if npm is None:
        die(
            "找不到 Node.js，没法生成界面文件",
            "两条路选一条：\n"
            "  1. 装 Node.js（https://nodejs.org/ 选 LTS），装完重新双击启动；\n"
            "  2. 用带「已构建界面」的发布包解压，里面应该已经有 frontend/dist 这个文件夹。",
        )

    if not (FRONTEND_DIR / "node_modules").is_dir():
        detail("正在下载界面依赖（几分钟，只做这一次）...")
        install = (
            [npm, "ci"] if (FRONTEND_DIR / "package-lock.json").is_file() else [npm, "install"]
        )
        if _run(install, cwd=FRONTEND_DIR) != 0:
            die("界面依赖下载失败", "检查网络后重新双击启动。")

    detail("正在生成界面文件...")
    if _run([npm, "run", "build"], cwd=FRONTEND_DIR) != 0 or not DIST_INDEX.is_file():
        die(
            "界面文件生成失败",
            "把窗口里最后几行报错截个图，反馈给开发者即可。",
        )


# --------------------------------------------------------------------- 端口
def port_free(port: int) -> bool:
    # 先主动连一下：Windows 上 SO_REUSEADDR 允许「绑到别人正在监听的端口」，
    # 只靠 bind 判断会把占用误判成空闲，然后起服务时才炸
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def health_ok(port: int, timeout: float = 1.5) -> bool:
    url = f"http://127.0.0.1:{port}{HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def pick_port(preferred: int) -> int:
    """被占用时往后找：用户不该为了端口冲突去改配置。"""
    for port in range(preferred, preferred + 20):
        if port_free(port):
            return port
    die(f"{preferred} 起的 20 个端口都被占用了", "关掉其他程序后重新双击启动。")


def serves_frontend(port: int, timeout: float = 2.0) -> bool:
    """根路径吐 HTML 才算「带着界面在跑」。

    开发时手动起的 uvicorn（没设 SERVE_FRONTEND=1）只提供 /api，根路径是一行
    JSON。只凭 /health 通就复用它，浏览器打开只有那行 JSON —— 用户看到的是
    「页面没渲染出来」，却完全猜不到原因（服务明明是通的）。
    """
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return False
            return "text/html" in (response.headers.get("Content-Type") or "").lower()
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def already_running_on(preferred: int) -> int | None:
    """只复用「已经能直接看」的实例；只跑 API 的那种另起一个带界面的。"""
    for port in range(preferred, preferred + 20):
        if not port_free(port) and health_ok(port) and serves_frontend(port):
            return port
    return None


# --------------------------------------------------------------------- 启动
def announce_when_ready(port: int, open_browser: bool, total_wait: float = 120.0) -> None:
    """等服务真能访问了再喊「已启动」+ 开浏览器：开早了只会看到「无法访问此网站」。"""

    def worker() -> None:
        deadline = time.monotonic() + total_wait
        while time.monotonic() < deadline:
            if health_ok(port):
                banner(port, open_browser)
                if open_browser:
                    webbrowser.open(f"http://127.0.0.1:{port}")
                return
            time.sleep(0.4)
        say()
        say("  ! 服务超过两分钟还没就绪，窗口里应该有报错信息，截图反馈给开发者即可。")

    threading.Thread(target=worker, daemon=True).start()


def serve(port: int) -> None:
    os.environ.setdefault("SERVE_FRONTEND", "1")
    # 控制台只留必要信息：给不懂命令行的人看满屏 JSON 日志等于没信息
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    import uvicorn

    config = uvicorn.Config(
        "backend.app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()


def banner(port: int, opened: bool) -> None:
    url = f"http://127.0.0.1:{port}"
    set_console_title(f"Office Agent —— 浏览器打开 {url}")
    say()
    say("  ────────────────────────────────────────────────")
    say("   启动完成，可以用了")
    say()
    say(f"   浏览器地址：{url}")
    say("   （窗口标题栏里也一直写着这个地址）")
    say()
    if opened:
        say("   已经自动帮你打开浏览器。没弹出来的话，把上面")
        say("   那行地址复制到浏览器地址栏，回车就行。")
    else:
        say("   把上面那行地址复制到浏览器地址栏，回车就行。")
    say()
    say("   用完关掉这个黑窗口 = 退出程序（别在用的中途关）")
    say("  ────────────────────────────────────────────────")
    say()


# --------------------------------------------------------------------- 主流程
def check_report(python: Path, port: int) -> bool:
    say("环境检查：")
    version = python_version(python)
    version_text = f"{version[0]}.{version[1]}" if version else ""
    say(f"  Python      {'OK ' + version_text if version else '缺失'}")
    say(f"  运行环境    {'OK' if python.is_file() else '未创建'} {python}")
    say(f"  依赖        {'OK' if deps_installed(python) else '未安装'}")
    if not DIST_INDEX.is_file():
        spa_state = "未构建"
    elif _frontend_sources_newer_than_dist():
        spa_state = "比源码旧（启动时会自动重建）"
    else:
        spa_state = "OK"
    say(f"  界面产物    {spa_state} {DIST_INDEX}")
    say(f"  Node.js     {npm_command() or '未安装（只在需要构建界面时才需要）'}")
    say(f"  端口 {port}    {'空闲' if port_free(port) else '被占用'}")
    return (
        version is not None and python.is_file() and deps_installed(python) and DIST_INDEX.is_file()
    )


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--port", type=int, default=int(os.environ.get("OA_PORT", DEFAULT_PORT)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="强制重新构建前端")
    parser.add_argument("--check", action="store_true", help="只检查环境，不启动")
    args = parser.parse_args(argv)

    say()
    say("  Office Agent · 本机启动器")

    if args.check:
        python = venv_python() if venv_python().is_file() else Path(sys.executable)
        ready = check_report(python, args.port)
        say()
        say("结论：" + ("可以直接启动" if ready else "还差上面标「未安装 / 未构建」的步骤"))
        return 0 if ready else 1

    # 已经在跑：直接开浏览器，不重复起第二个进程（第二个必然抢不到端口）
    running = already_running_on(args.port)
    if running is not None:
        url = f"http://127.0.0.1:{running}"
        say()
        say("  Office Agent 已经在运行，不用再开一个。")
        say()
        say(f"   浏览器地址：{url}")
        say()
        if not args.no_browser:
            webbrowser.open(url)
            say("   已经帮你打开浏览器（没弹出来就把上面的地址复制过去）。")
        set_console_title(f"Office Agent —— 浏览器打开 {url}")
        wait_for_key()
        return 2

    step("检查这台电脑的运行环境")
    python = ensure_venv()

    step("确认依赖齐全")
    if deps_installed(python):
        detail("依赖已齐全，跳过安装")
    else:
        install_deps(python)
        if not deps_installed(python):
            die("依赖装完仍然 import 失败", "删掉 .venv 文件夹后重新双击启动试试。")

    step("准备界面文件")
    ensure_env_file()
    ensure_frontend(args.rebuild)

    step("启动服务")
    if not port_free(args.port) and health_ok(args.port):
        # 能走到这里说明那个端口上的后端没托管界面（否则上面就复用了）。
        # 不说这一句，用户只会看到端口莫名换成了 8001。
        say(f"  ! {args.port} 上有个只跑接口的后端（没有界面），另外起一个带界面的。")
    port = pick_port(args.port)
    say(f"      端口：{port}（默认 8000，被占用会自动往后换，这里显示的就是实际用的）")
    detail(f"地址：http://127.0.0.1:{port}")
    set_console_title(f"Office Agent —— 启动中 http://127.0.0.1:{port}")
    say()
    if args.no_browser:
        say("  启动中，就绪后按上面的地址用浏览器打开（这个窗口别关）...")
    else:
        say("  启动中，就绪后浏览器会自动打开（第一次要十几秒，这个窗口别关）...")
    announce_when_ready(port, not args.no_browser)

    try:
        serve(port)
    except KeyboardInterrupt:
        say()
        say("  已停止。下次用的时候再双击一次「启动 Office Agent」即可。")
        return 0
    except OSError as error:  # 端口在探测和真正 bind 之间被抢
        die(f"启动失败：{error}", f"端口 {port} 刚被别的程序占用了，重新双击启动会自动换一个。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:  # pragma: no cover - Ctrl+C 不算错误
        say()
        say("  已停止。")
        sys.exit(0)
    except Exception:  # noqa: BLE001 - 兜底：别让窗口在用户看到原因前就关掉
        import traceback

        _setup_console()
        say()
        say("  × 启动器遇到意外错误：")
        traceback.print_exc()
        wait_for_key()
        sys.exit(2)
