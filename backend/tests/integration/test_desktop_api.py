"""桌面端安装包接口：存到本机、记住位置、位置失效要说清楚。

这些用例故意都指定 target_dir（或覆盖 OA_DOWNLOAD_DIR），绝不往真实「下载」目录写东西；
open / reveal 会拉起资源管理器，全部用 monkeypatch 换成记录调用，跑测试不弹窗口。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.api.v1 import desktop as desktop_api


@pytest.fixture()
def fake_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    package = tmp_path / "Office Agent.exe"
    package.write_bytes(b"MZ" + b"\x00" * 2048)
    monkeypatch.setenv(desktop_api.PACKAGE_ENV, str(package))
    return package


@pytest.fixture()
def state_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """每个用例一份独立记录文件：会话级 settings 共用同一个数据目录，不能互相串。"""
    state = tmp_path / desktop_api.STATE_NAME
    monkeypatch.setattr(desktop_api, "state_file", lambda _settings: state)
    return state


def test_没下载过时状态干净且可交付(client: httpx.Client, fake_package: Path, state_clean):
    body = client.get("/api/v1/desktop/package").json()

    assert body["available"] is True
    assert body["filename"] == "Office Agent.exe"
    assert body["size"] == fake_package.stat().st_size
    assert body["saved"] is None
    assert body["default_dir"]


def test_保存到指定目录后返回真实路径并落盘记录(
    client: httpx.Client, fake_package: Path, tmp_path: Path, state_clean
):
    target = tmp_path / "自定义目录"
    response = client.post("/api/v1/desktop/package/download", json={"target_dir": str(target)})
    assert response.status_code == 200, response.text
    body = response.json()

    saved_path = Path(body["path"])
    assert body["ok"] is True
    assert saved_path.is_absolute()
    assert saved_path == target / "Office Agent.exe"
    assert saved_path.read_bytes() == fake_package.read_bytes()
    assert body["saved"]["exists"] is True
    assert body["saved"]["size"] == fake_package.stat().st_size
    # 记录真的写到了数据目录（刷新页面还能读到）
    assert state_clean.is_file()

    again = client.get("/api/v1/desktop/package").json()
    assert again["saved"]["path"] == str(saved_path)
    assert again["saved"]["exists"] is True


def test_文件被删掉后状态明确提示失效(
    client: httpx.Client, fake_package: Path, tmp_path: Path, state_clean
):
    target = tmp_path / "下载"
    body = client.post("/api/v1/desktop/package/download", json={"target_dir": str(target)}).json()
    Path(body["path"]).unlink()

    status = client.get("/api/v1/desktop/package").json()
    saved = status["saved"]
    assert saved is not None  # 记录还在，界面才能告诉人「原来在哪」
    assert saved["exists"] is False
    assert saved["dir_exists"] is True
    assert "不在这个位置" in (saved["error"] or "")

    # 打开安装包：明确失败 + 让人重新下载，而不是静默什么都不发生
    opened = client.post("/api/v1/desktop/package/open").json()
    assert opened["ok"] is False
    assert opened["exists"] is False
    assert "重新下载" in (opened["error"] or "")


def test_目录连根被删后提示目录也不在(
    client: httpx.Client, fake_package: Path, tmp_path: Path, state_clean
):
    target = tmp_path / "临时目录"
    client.post("/api/v1/desktop/package/download", json={"target_dir": str(target)})
    for item in target.iterdir():
        item.unlink()
    target.rmdir()

    saved = client.get("/api/v1/desktop/package").json()["saved"]
    assert saved["exists"] is False
    assert saved["dir_exists"] is False
    assert "文件夹" in (saved["error"] or "")


def test_目录不可用时不留旧记录(
    client: httpx.Client, fake_package: Path, tmp_path: Path, state_clean
):
    ok = client.post(
        "/api/v1/desktop/package/download", json={"target_dir": str(tmp_path / "下载")}
    ).json()
    assert ok["ok"] is True

    not_a_dir = tmp_path / "这是个文件.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    failed = client.post(
        "/api/v1/desktop/package/download", json={"target_dir": str(not_a_dir)}
    ).json()
    assert failed["ok"] is False
    assert failed["saved"] is None
    assert failed["error"]

    after = client.get("/api/v1/desktop/package").json()
    assert after["saved"] is None


def test_相对路径被拒绝(client: httpx.Client, fake_package: Path, state_clean):
    body = client.post("/api/v1/desktop/package/download", json={"target_dir": "相对/目录"}).json()
    assert body["ok"] is False
    assert "绝对路径" in (body["error"] or "")


def test_没有安装包时明确拒绝且前端可退回下载链接(
    client: httpx.Client, monkeypatch: pytest.MonkeyPatch, state_clean
):
    # 把源文件指向不存在的路径 = 这台机器上没有可交付的安装包
    monkeypatch.setenv(desktop_api.PACKAGE_ENV, "/definitely/not/here.exe")
    monkeypatch.setattr(desktop_api, "local_package", lambda: None)

    status = client.get("/api/v1/desktop/package").json()
    assert status["available"] is False

    body = client.post("/api/v1/desktop/package/download", json={"target_dir": None}).json()
    assert body["ok"] is False
    assert body["error"]


def test_在文件管理器中定位会调用系统命令(
    client: httpx.Client, fake_package: Path, tmp_path: Path, state_clean, monkeypatch
):
    body = client.post(
        "/api/v1/desktop/package/download", json={"target_dir": str(tmp_path / "下载")}
    ).json()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        desktop_api.subprocess, "Popen", lambda args, *a, **kw: calls.append(list(args))
    )

    result = client.post("/api/v1/desktop/package/reveal").json()
    assert result["ok"] is True
    assert result["path"] == body["path"]
    assert result["exists"] is True
    # Windows 是 explorer /select,<path>，Linux/macOS 打开的是所在目录
    assert calls
    joined = " ".join(calls[0])
    assert body["path"] in joined or str(Path(body["path"]).parent) in joined


def test_重新打开安装包会拉起程序(
    client: httpx.Client, fake_package: Path, tmp_path: Path, state_clean, monkeypatch
):
    body = client.post(
        "/api/v1/desktop/package/download", json={"target_dir": str(tmp_path / "下载")}
    ).json()
    started: list[str] = []
    monkeypatch.setattr(
        desktop_api, "launch", lambda path: started.append(str(path)) or (True, None)
    )

    result = client.post("/api/v1/desktop/package/open").json()
    assert result["ok"] is True
    assert started == [body["path"]]


def test_没记录时定位与打开都给明确提示(client: httpx.Client, state_clean):
    for endpoint in ("/api/v1/desktop/package/reveal", "/api/v1/desktop/package/open"):
        body = client.post(endpoint).json()
        assert body["ok"] is False
        assert "还没有保存过" in (body["error"] or "")


def test_重复下载不会重复写同样大小的一份(
    client: httpx.Client, fake_package: Path, tmp_path: Path, state_clean, monkeypatch
):
    client.post("/api/v1/desktop/package/download", json={"target_dir": str(tmp_path / "下载")})

    def boom(*_args, **_kwargs):
        raise AssertionError("同样大小的一份已经在，不该再复制一次")

    monkeypatch.setattr(desktop_api.shutil, "copy2", boom)
    again = client.post(
        "/api/v1/desktop/package/download", json={"target_dir": str(tmp_path / "下载")}
    ).json()
    assert again["ok"] is True
