"""启动脚本的几条硬约束。

这些不是「锦上添花」的测试，是把已经踩过的坑钉死：

1. `.cmd` 必须只含 ASCII。cmd.exe 按字节读批处理，行里混进中文时它会从字符中间
   接着读，下一行就报「不是内部或外部命令」。中文提示统一放 scripts/messages/*.txt。
2. `.cmd` 必须 CRLF，`.command` 必须 LF（macOS 靠 shebang 执行）。
3. 找 Python 的顺序：先项目自带 .venv，最后才轮到 PATH 里的 python。很多电脑的
   PATH 里只有 Microsoft Store 那个转发存根，它一声不吭返回 9009——用户看到的就是
   「双击了没反应」。
4. 出错时不能一闪就没：die() 要等用户看完，并且用退出码 2 告诉批处理「已经等过了」。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
CMD = ROOT / "启动 Office Agent.cmd"
COMMAND = ROOT / "启动 Office Agent.command"
MESSAGES = ROOT / "scripts" / "messages"


def _load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_launcher", ROOT / "scripts" / "launch.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_launcher"] = module
    spec.loader.exec_module(module)
    return module


def test_批处理只能有_ascii字符():
    raw = CMD.read_bytes()
    offenders = [(index, byte) for index, byte in enumerate(raw) if byte > 0x7F]
    assert offenders == [], f"第 {offenders[:3]} 个字节不是 ASCII，cmd.exe 会读错行"


def test_批处理是_crlf_换行():
    raw = CMD.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n"), "存在只有 LF 的换行，cmd.exe 可能跳错行"


def test_mac_脚本是_lf_且有_shebang():
    raw = COMMAND.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n")
    assert b"\r\n" not in raw


def test_找_python_先试项目自带环境再试_path():
    text = CMD.read_text(encoding="ascii")
    venv = text.find(".venv\\Scripts\\python.exe")
    path_lookup = text.find("where python")
    assert venv > 0 and path_lookup > 0
    assert venv < path_lookup, "PATH 里的 python 可能是商店存根，必须先试 .venv"


def test_跳过微软商店的转发存根():
    text = CMD.read_text(encoding="ascii")
    assert 'find /i "WindowsApps"' in text


def test_所有_pause_都不打印英文提示():
    text = CMD.read_text(encoding="ascii")
    bare = [
        line.strip()
        for line in text.splitlines()
        if line.strip().lower() == "pause"  # 只有 pause 没有 >nul：会打英文
    ]
    assert bare == []


@pytest.mark.parametrize("name", ["no-python.txt", "crashed.txt", "no-launcher.txt"])
def test_提示文件是_utf8_无_bom_且带按键提示(name: str):
    raw = (MESSAGES / name).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM 会在控制台里多打一个怪字符"
    text = raw.decode("utf-8")  # 解不出 UTF-8 就直接失败
    assert "按任意键" in text


def test_启动失败会等用户看完再退出(monkeypatch: pytest.MonkeyPatch, capsys):
    launcher = _load_launcher()
    waited: list[str] = []
    monkeypatch.setattr(launcher, "wait_for_key", lambda *a, **k: waited.append("waited"))

    with pytest.raises(SystemExit) as excinfo:
        launcher.die("依赖没装上", "检查网络后重试")

    # 2 = 「已经提示并等过按键了」，批处理据此不再多停一次
    assert excinfo.value.code == 2
    assert waited == ["waited"]
    out = capsys.readouterr().out
    assert "没能启动" in out
    assert "检查网络后重试" in out


def test_非终端环境不等待(monkeypatch: pytest.MonkeyPatch):
    """pytest / CI 里 stdin 不是 tty，等下去会卡死整条流水线。"""
    launcher = _load_launcher()

    class _NotATty:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(launcher.sys, "stdin", _NotATty())
    launcher.wait_for_key()  # 不抛异常、不读 stdin 就算通过


class _FakeResponse:
    """只够 urlopen 的 with 用法：status + Content-Type 头。"""

    def __init__(self, status: int, content_type: str) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def test_只跑接口的端口不算已经启动(monkeypatch: pytest.MonkeyPatch):
    """8000 上只有 API、根路径吐 JSON 时，不能再「复用它」。

    真实事故：开发时手动起的 `python -m uvicorn backend.app.main:app` 没有设
    SERVE_FRONTEND=1，只提供 /api，根路径是一行 JSON。启动器只看 /health 通就
    复用它 → 浏览器打开的是一行 JSON，用户看到的是「页面没渲染出来」，
    而服务明明是通的，怎么查都查不到原因。
    """
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "port_free", lambda port: False)

    def _fake_urlopen(url: str, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(200, "application/json")

    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_urlopen)

    assert launcher.already_running_on(8000) is None


def test_带界面的实例照旧复用(monkeypatch: pytest.MonkeyPatch):
    """真正在托管界面的实例（根路径是 HTML）不该被误伤成「没在跑」。"""
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "port_free", lambda port: port != 8000)

    def _fake_urlopen(url: str, timeout: float | None = None) -> _FakeResponse:
        if ":8000/" in url:
            return _FakeResponse(200, "text/html; charset=utf-8")
        return _FakeResponse(200, "application/json")

    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_urlopen)

    assert launcher.already_running_on(8000) == 8000


def test_根路径不是_html_就不算托管界面(monkeypatch: pytest.MonkeyPatch):
    launcher = _load_launcher()

    def _fake_urlopen(url: str, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(200, "application/json")

    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_urlopen)

    assert launcher.serves_frontend(8000) is False
