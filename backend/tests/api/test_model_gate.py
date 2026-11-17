"""发送门禁：真实引擎下一个能用的模型都没有时，健康检查要说明、运行要拒绝。

守护两头的口径一致：前端靠 /health 的 model_ready 拦发送，后端 RunService
再兜一道——只拦一边，就会出现「按钮亮着发不出去」或「界面拦了 API 还能直发」。
演示模式不受影响（它不依赖 Key，也不产生费用）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.paths import DATA_ROOT
from app.main import create_app
from fastapi.testclient import TestClient

PREFIX = "/api/v1"


@pytest.fixture()
def gated_client(tmp_path: Path) -> Iterator[TestClient]:
    """真实引擎、但一家 Key 都没配（用户刚装好 / 刚断开全部 Key 的状态）。"""
    settings = Settings(
        engine="real",
        mock_mode=False,
        model_provider="deepseek",
        model_name="deepseek-chat",
        model_fallback_chain="deepseek",
        deepseek_api_key="",
        qwen_api_key="",
        dashscope_api_key="",
        glm_api_key="",
        serve_frontend=False,
        database_url=f"sqlite:///{tmp_path / 'gate.db'}",
        # 门禁翻转要真的落盘一次 Key：必须落在 tmp，否则会覆盖仓库 .env 里的真 Key
        env_path=str(tmp_path / ".env"),
        upload_dir=str(tmp_path / "uploads"),
        artifact_dir=str(tmp_path / "artifacts"),
        trash_dir=str(tmp_path / "trash"),
        templates_file=str(tmp_path / "templates.json"),
        auto_migrate=True,
        log_level="ERROR",
        log_format="text",
    )
    settings.ensure_dirs()
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_health_reports_model_not_ready(gated_client: TestClient) -> None:
    body = gated_client.get(f"{PREFIX}/health").json()
    assert body["model_ready"] is False
    assert "模型" in body["model_hint"]
    # 引擎还写着 real：这是「想用真实模型但没配上」，不是「用户选了演示」
    assert body["engine"] == "real"
    assert body["engine_effective"] == "mock"


def test_run_without_model_is_rejected(gated_client: TestClient) -> None:
    thread = gated_client.post(f"{PREFIX}/threads", json={"title": "门禁"}).json()
    response = gated_client.post(
        f"{PREFIX}/threads/{thread['thread_id']}/runs/stream",
        json={"message": "整理成周报"},
    )
    assert response.status_code == 400
    assert "模型" in response.json()["error"]["message"]


def test_mock_mode_still_sends_without_key(gated_client: TestClient) -> None:
    """演示模式不依赖 Key：显式 mode=mock 照常能跑（想试界面的人不该被拦死）。"""
    thread = gated_client.post(f"{PREFIX}/threads", json={"title": "演示"}).json()
    with gated_client.stream(
        "POST",
        f"{PREFIX}/threads/{thread['thread_id']}/runs/stream",
        json={"message": "整理成周报", "mode": "mock"},
    ) as response:
        assert response.status_code == 200


def test_model_ready_flips_after_key_saved(gated_client: TestClient) -> None:
    """配上一把 Key，门禁立刻解除——这一步只验证状态翻转，不真发外网请求。"""
    saved = gated_client.put(
        f"{PREFIX}/models/env:deepseek/key",
        json={"api_key": "sk-gate-test-1234567890"},
    )
    assert saved.status_code == 200, saved.text
    body = gated_client.get(f"{PREFIX}/health").json()
    assert body["model_ready"] is True
    assert body["model_hint"] == ""


def test_saving_key_writes_the_test_env_not_the_real_one(
    gated_client: TestClient, tmp_path: Path
) -> None:
    """保存 Key 只能写测试自己的 .env，绝不许碰仓库里那份。

    这是 2026-11-10 的真实事故：门禁用例把数据库 / 上传 / 产物全指到 tmp，
    唯独 `env_file_path` 还硬绑 DATA_ROOT，于是跑一遍 `pytest backend/tests`，
    夹具里的假 Key（`sk-gate-test-…`）就被写进仓库 .env，把用户的真 Key 覆盖掉。
    表现是之后每次运行都降级演示模式、顶栏写着「API Key 无效或已失效」，
    而用户根本没动过那把 Key——最伤信任的一类自伤，必须有个用例钉住。
    """
    real_env = DATA_ROOT / ".env"
    before = real_env.read_bytes() if real_env.exists() else None

    saved = gated_client.put(
        f"{PREFIX}/models/env:deepseek/key",
        json={"api_key": "sk-gate-test-1234567890"},
    )
    assert saved.status_code == 200, saved.text

    # 假 Key 落在 tmp 的 .env 里
    assert "sk-gate-test-1234567890" in (tmp_path / ".env").read_text(encoding="utf-8")
    # 真实配置一个字节都没变（包括「本来就没有这个文件」的情况）
    after = real_env.read_bytes() if real_env.exists() else None
    assert after == before
