"""兼容 v0.1 启动路径：`uvicorn backend.main:app`。

V2.1 起后端实现位于 `backend.app`，新启动命令：
    ./.venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8000
"""

from .app.main import app, create_app

__all__ = ["app", "create_app"]
