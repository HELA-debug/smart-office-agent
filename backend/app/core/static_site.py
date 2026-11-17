"""单端口运行：把构建好的前端（frontend/dist）挂在 FastAPI 上。

给「只在电脑上双击一下就要用」的人：不开两个终端、不装 Node、不记端口，
浏览器打开 http://127.0.0.1:8000 就是完整界面。

三条规则：

1. `/assets/*` 交给 StaticFiles——vite 产物带内容哈希，可以长缓存。
2. 其它 GET 先看 dist 里有没有同名文件（`sw.js`、`manifest.webmanifest`、`icons/*`），
   没有就回 `index.html`。前端是 BrowserRouter，刷新 `/settings`、`/artifacts` 不能 404。
3. `/api/*` 一律不接管：不存在的接口仍然返回 JSON 404，不能吐一坨 HTML 让排错变成猜谜。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 这些前缀属于后端自己（接口、交互文档），SPA 兜底必须绕开
_BACKEND_OWNED = ("api", "docs", "redoc", "openapi.json")

# 每次都得回源的文件：入口 HTML 变了要立刻换掉；sw.js 变了要立刻触发 SW 更新检查。
# 浏览器对 .js 默认会给一段启发式缓存，sw.js 被缓存住就等于「装成桌面端后永远停在旧版本」。
_ALWAYS_REVALIDATE = {".html", ".webmanifest"}


class ImmutableStaticFiles(StaticFiles):
    """`/assets/*` 专用：vite 产物文件名带内容哈希，可以放心长缓存 + immutable。

    默认的 StaticFiles 只回 `etag` / `last-modified`，浏览器每次仍要发一次条件请求；
    带上 immutable 后连条件请求都省了，首屏和二次进入都快一截。因为文件名随内容变，
    不存在「改了代码还拿到旧文件」的风险——旧文件本来也不会再被引用。
    """

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _is_backend_path(relative: str) -> bool:
    head = relative.split("/", 1)[0]
    return head in _BACKEND_OWNED


def _cache_control(target: Path) -> str:
    """带哈希的构建产物可以长缓存；入口 HTML / SW / manifest 必须每次回源，否则更新后还是旧界面。"""
    if target.suffix in _ALWAYS_REVALIDATE:
        return "no-cache"
    if "assets" in target.parts:
        return "public, max-age=31536000, immutable"
    return "no-cache"


def mount_spa(app: FastAPI, dist: Path) -> None:
    """把 dist 挂到 app 上（必须在所有 /api 路由注册之后调用）。"""
    root = dist.resolve()
    index = root / "index.html"
    assets = root / "assets"
    if assets.is_dir():
        app.mount(
            "/assets",
            ImmutableStaticFiles(directory=str(assets)),
            name="spa-assets",
        )

    @app.get("/{spa_path:path}", include_in_schema=False)
    async def spa_fallback(spa_path: str) -> FileResponse:
        relative = spa_path.strip("/")
        # 后端路径没匹配到路由 = 真的不存在，直接 404；
        # 落到这里说明 API 路径写错了，返回 index.html 只会让人以为「部署坏了」
        if _is_backend_path(relative):
            raise HTTPException(status_code=404, detail="Not Found")
        if relative:
            target = (root / relative).resolve()
            # 防目录穿越：解析后必须仍在 dist 里（`/../.env` 这类请求只会拿到首页）
            if root in target.parents and target.is_file():
                return FileResponse(target, headers={"Cache-Control": _cache_control(target)})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


__all__ = ["ImmutableStaticFiles", "mount_spa"]
