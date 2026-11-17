#!/usr/bin/env python3
"""打包版入口：双击 Office Agent.exe 跑的就是这里。

和 scripts/launch.py 分工不同：
    launch.py   给「拿到源码的人」——建 venv、装依赖、构建前端；
    本文件      给「只拿到一个 exe 的人」——不做任何环境准备，只做三件事：
      1. 找到数据目录（没有就建；没有 .env 就从内置的 .env.example 补一份）
      2. 挑一个空闲端口，在后台等服务真的能访问了再说话
      3. 起服务、开浏览器

为什么单独一个入口：exe 里没有 venv、没有 Node，也没有仓库根目录，
launch.py 里那套「准备环境」的逻辑在这里全是错的分支，硬塞进去只会互相拖累。

参数：
    --port 8000         换端口（被占用会自动往后找）
    --no-browser        只启动，不开浏览器
    --data-dir DIR      指定数据目录（默认 %LOCALAPPDATA%\\Office Agent）
    --show-data-dir     打印数据目录后退出（找自己的库/产物/Key 用）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import webbrowser
from pathlib import Path

# scripts/ 在源码态就是 sys.path[0]，打包时由 spec 的 pathex 带上，两边都能 import
import launch as launcher

DEFAULT_PORT = 8000


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="Office Agent", add_help=True)
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("OA_PORT", DEFAULT_PORT))
    )
    parser.add_argument("--no-browser", action="store_true", help="只启动，不开浏览器")
    parser.add_argument(
        "--data-dir",
        default="",
        help="指定数据目录（数据库/上传/产物/.env 都在这里）",
    )
    parser.add_argument(
        "--show-data-dir", action="store_true", help="打印数据目录后退出"
    )
    return parser.parse_args(argv)


def prepare_data_dir(data_root: Path, resource_root: Path) -> bool:
    """保证数据目录和 .env 存在；返回 .env 是否是这次新建的。"""
    data_root.mkdir(parents=True, exist_ok=True)
    env_file = data_root / ".env"
    if env_file.is_file():
        return False
    example = resource_root / ".env.example"
    if example.is_file():
        shutil.copyfile(example, env_file)
        return True
    return False


def serve(port: int) -> None:
    """起单端口服务：后端 API + 前端 dist 由 FastAPI 一并托管。"""
    os.environ.setdefault("SERVE_FRONTEND", "1")
    # 控制台只留必要信息：给不懂命令行的人看满屏 JSON 日志等于没信息
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    import uvicorn

    from backend.app.main import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    launcher._setup_console()

    if args.data_dir:
        os.environ["OA_DATA_DIR"] = str(Path(args.data_dir).expanduser())

    # 必须在 OA_DATA_DIR 落定之后再导入：数据根在 import 时求值
    from backend.app.core.paths import DATA_ROOT, RESOURCE_ROOT

    if args.show_data_dir:
        launcher.say(str(DATA_ROOT))
        return 0

    launcher.say()
    launcher.say("  Office Agent")
    launcher.say()
    launcher.say(f"   数据目录：{DATA_ROOT}")
    created_env = prepare_data_dir(DATA_ROOT, RESOURCE_ROOT)
    if created_env:
        launcher.say("   （已生成配置文件 .env，在设置页填模型 Key 后就能用真实模型）")
    launcher.say()

    # 已经在跑：直接开浏览器，不重复起第二个进程（第二个必然抢不到端口）
    running = launcher.already_running_on(args.port)
    if running is not None:
        url = f"http://127.0.0.1:{running}"
        launcher.say("  已经在运行，不用再开一个。")
        launcher.say()
        launcher.say(f"   浏览器地址：{url}")
        if not args.no_browser:
            webbrowser.open(url)
        launcher.set_console_title(f"Office Agent —— 浏览器打开 {url}")
        launcher.wait_for_key("  按回车关闭这个窗口...")
        return 0

    port = launcher.pick_port(args.port)
    launcher.set_console_title(f"Office Agent —— 启动中 http://127.0.0.1:{port}")
    launcher.say("  启动中，就绪后浏览器会自动打开（第一次十几秒，这个窗口别关）...")
    launcher.announce_when_ready(port, not args.no_browser)

    try:
        serve(port)
    except KeyboardInterrupt:
        launcher.say()
        launcher.say("  已停止。下次用的时候再双击一次 Office Agent 即可。")
        return 0
    except OSError as error:  # 端口在探测和真正 bind 之间被抢
        launcher.die(
            f"启动失败：{error}",
            f"端口 {port} 刚被别的程序占用了，重新双击会自动换一个。",
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:  # pragma: no cover - Ctrl+C 不算错误
        launcher.say()
        launcher.say("  已停止。")
        sys.exit(0)
    except Exception:  # noqa: BLE001 - 兜底：别让窗口在用户看到原因前就关掉
        import traceback

        launcher._setup_console()
        launcher.say()
        launcher.say("  × 启动器遇到意外错误：")
        traceback.print_exc()
        launcher.wait_for_key()
        sys.exit(2)
