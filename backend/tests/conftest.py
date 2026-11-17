"""pytest 配置：真起 uvicorn（随机端口）+ tmp_path 隔离数据目录。

- 每个测试会话使用独立临时目录（DATABASE_URL / UPLOAD_DIR / ARTIFACT_DIR / OUTBOX_DIR）；
- --basetemp=.pytest-tmp 保证临时文件不落到仓库根，session 结束整体删除；
- httpx 统一 trust_env=False，规避 Windows NO_PROXY=[::1] 的 InvalidURL 问题。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from app.core.config import Settings
from app.main import create_app

# Windows 本机 TEMP ACL 异常，且多人可能并发跑 pytest：统一用仓库内按 PID 隔离的临时根。
_SESSION_TMP = Path(__file__).resolve().parents[1] / ".pytest-tmp" / f"pid{os.getpid()}"
_SESSION_TMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_SESSION_TMP)


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("oam-data")
    return Settings(
        engine="mock",
        model_provider="mock",
        model_name="mock-scripted",
        model_fallback_chain="mock",
        mock_mode=True,
        mock_model_speed=0,
        # 固定 Key 规则，避免依赖本机 .env：deepseek 走 OPENAI_API_KEY 兼容，
        # qwen/glm 无 Key（用于断言 configured 一致性）
        deepseek_api_key="",
        qwen_api_key="",
        dashscope_api_key="",
        glm_api_key="",
        openai_api_key="test-openai-key",
        approval_rules="doc.generate_report,file.delete,code.run_python",
        approval_timeout_seconds=3,
        # 测试不读仓库里的 frontend/dist：有没有构建过不该影响接口断言。
        serve_frontend=False,
        database_url=f"sqlite:///{root / 'app.db'}",
        env_path=str(root / ".env"),
        upload_dir=str(root / "uploads"),
        artifact_dir=str(root / "artifacts"),
        trash_dir=str(root / "trash"),
        templates_file=str(root / "templates.json"),
        feedback_dir=str(root / "feedback"),
        auto_migrate=True,
        log_level="WARNING",
        log_format="text",
    )


@pytest.fixture(scope="session")
def data_dir(settings: Settings) -> Path:
    settings.ensure_dirs()
    return Path(settings.upload_dir).resolve().parent


@pytest.fixture(scope="session")
def app(settings: Settings):
    # 兜底断言：测试绝不能连仓库里的生产库。
    # 那里存着用户真实的 engine / mock_mode / 模型 Key 引用，一次
    # `PUT /settings` 就会把「现在用哪个模型」改掉，而跑测试的人毫无察觉——
    # 表现就是「我明明切成 mock 了，跑完测试又开始烧钱」。
    assert "data/app.db" not in settings.database_url.replace("\\", "/"), (
        f"测试连到了生产库：{settings.database_url}"
    )
    return create_app(settings)


@pytest.fixture(scope="session")
def base_url(app) -> Iterator[str]:
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(300):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn 未能启动"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=60, trust_env=False) as instance:
        yield instance


@pytest.fixture()
def thread(client: httpx.Client) -> dict:
    response = client.post("/api/v1/threads", json={"title": "测试会话"})
    assert response.status_code == 201, response.text
    return response.json()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """清理 pytest basetemp，保证仓库根/后端目录无残留。"""
    shutil.rmtree(_SESSION_TMP, ignore_errors=True)
