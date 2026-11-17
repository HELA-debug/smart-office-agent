"""单测：单端口运行时前端的缓存策略。

这一块出错的症状很隐蔽——不是报错，而是「本地重建后页面还是旧界面」：
入口 HTML / sw.js 被浏览器缓存住，就会一直加载上一次的 bundle。
所以把三条规则钉死：
1. `/assets/*`（文件名带内容哈希）长缓存 + immutable；
2. `index.html`、`sw.js`、manifest 必须每次回源（no-cache）；
3. 未匹配的 SPA 路由回 index.html，`/api/*` 仍然 404（不能吐 HTML）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.core.static_site import mount_spa


def _client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body><div id=root></div></body></html>", "utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", "utf-8")
    (dist / "sw.js").write_text("const VERSION = 'x';", "utf-8")
    (dist / "manifest.webmanifest").write_text("{}", "utf-8")
    app = FastAPI()
    mount_spa(app, dist)
    return TestClient(app)


def test_assets_are_immutable(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_entry_html_must_revalidate(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_service_worker_must_revalidate(tmp_path: Path) -> None:
    """sw.js 被缓存住 = 装成桌面端的窗口永远停在旧外壳。"""
    response = _client(tmp_path).get("/sw.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_spa_route_falls_back_to_index(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/settings")
    assert response.status_code == 200
    assert "<div id=root>" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_unknown_api_path_stays_404(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/v1/nope")
    assert response.status_code == 404
    assert "text/html" not in response.headers["content-type"]
