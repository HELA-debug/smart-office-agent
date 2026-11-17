"""单端口运行：后端把构建好的前端一起端出来（「启动 Office Agent」双击走的就是这条路）。

不依赖真前端产物：临时目录里放一个最小的 dist 就够验证规则——
子路由回 index.html、静态文件按内容返回、/api 不被兜底吞掉、目录穿越拿不到仓库文件。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def _fake_dist(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "index-abc123.js").write_text("console.log('hi')", encoding="utf-8")
    (root / "sw.js").write_text("self.addEventListener('fetch', () => {})", encoding="utf-8")
    (root / "index.html").write_text("<!doctype html><title>Office Agent</title>", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def spa_client(tmp_path_factory: pytest.TempPathFactory):
    root = _fake_dist(tmp_path_factory.mktemp("frontend-dist"))
    settings = Settings(
        engine="mock",
        model_provider="mock",
        mock_mode=True,
        serve_frontend=True,
        frontend_dist=str(root),
        database_url="sqlite://",
    )
    # 不进 lifespan：静态托管不依赖容器，DB / 迁移在这里只会拖慢测试
    return TestClient(create_app(settings))


def test_根路径返回界面而不是JSON(spa_client: TestClient):
    response = spa_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Office Agent</title>" in response.text


def test_子路由刷新不会404(spa_client: TestClient):
    """前端是 BrowserRouter：在 /settings 按 F5 必须还是界面，不是 404。"""
    response = spa_client.get("/settings")
    assert response.status_code == 200
    assert "<title>Office Agent</title>" in response.text
    # 入口 HTML 必须回源，否则用户更新后看到的是缓存里的旧版本
    assert response.headers["cache-control"] == "no-cache"


def test_静态文件按真内容返回(spa_client: TestClient):
    script = spa_client.get("/assets/index-abc123.js")
    assert script.status_code == 200
    assert script.text == "console.log('hi')"
    # 静态资源走 StaticFiles：带 ETag，第二次请求可以 304，不用重下
    assert script.headers["etag"]

    # Service Worker 这类固定名字的文件也要能拿到（装成桌面端靠它）
    assert spa_client.get("/sw.js").status_code == 200


def test_接口不受静态托管影响(spa_client: TestClient):
    """写错的接口必须回 JSON 404：吐一坨 HTML 会让「哪里坏了」变成猜谜。"""
    missing = spa_client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404
    assert "application/json" in missing.headers["content-type"]

    assert spa_client.get("/api/v1/openapi.json").status_code == 200


def test_目录穿越拿不到仓库文件(spa_client: TestClient):
    response = spa_client.get("/%2e%2e/%2e%2e/.env")
    assert response.status_code == 200
    assert "<title>Office Agent</title>" in response.text


def test_不开启静态托管时根路径仍是JSON():
    """显式关掉托管的纯接口模式（SERVE_FRONTEND=0），行为不能变。"""
    client = TestClient(
        create_app(
            Settings(
                engine="mock", model_provider="mock", serve_frontend=False, database_url="sqlite://"
            )
        )
    )
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["version"]


def test_默认就托管界面(tmp_path: Path):
    """不传 serve_frontend 也要出界面。

    手动 `uvicorn ... --port 8080` 不会带任何环境变量，默认关掉托管的话根路径只有
    一行 JSON，用户看到的就是「页面渲染不出来」（这个坑踩过两次）。
    """
    root = _fake_dist(tmp_path)
    client = TestClient(
        create_app(
            Settings(
                engine="mock",
                model_provider="mock",
                mock_mode=True,
                frontend_dist=str(root),
                database_url="sqlite://",
            )
        )
    )
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Office Agent</title>" in response.text


def test_dist没构建时给说明页而不是JSON(tmp_path: Path):
    """想托管但没 build：回一张写明命令的说明页，别回 {"name": ...} 让人以为界面坏了。"""
    empty = tmp_path / "empty-dist"
    empty.mkdir()
    client = TestClient(
        create_app(
            Settings(
                engine="mock",
                model_provider="mock",
                mock_mode=True,
                frontend_dist=str(empty),
                database_url="sqlite://",
            )
        )
    )
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "npm.cmd run build" in response.text
