"""API 矩阵测试的基础设施：进程内 TestClient + 一份可复用的种子数据。

为什么不用 tests/conftest.py 里的真 uvicorn：矩阵有上千条用例，每条都过一次网络栈
没必要。TestClient 走的是同一个 ASGI app（含中间件、异常处理器、双前缀路由），
语义一致，单条 3–5ms。

代价是这里要自己起一份 Settings：显式传参优先级高于 .env，所以开发者本地的
APPROVAL_RULES / Key 不会渗进来。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# Windows 本机 TEMP ACL 异常：临时根放仓库内，按 PID 隔离
_SESSION_TMP = Path(__file__).resolve().parents[2] / ".pytest-tmp" / f"matrix{os.getpid()}"
_SESSION_TMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_SESSION_TMP)

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MATRIX_PREFIX = "/api/v1"


@dataclass
class Seed:
    """一份基线数据：只读用例拿它当合法 id，写用例自己另建资源。"""

    ids: dict[str, str] = field(default_factory=dict)
    spare_threads: list[str] = field(default_factory=list)
    spare_artifacts: list[str] = field(default_factory=list)
    project_dir: Path | None = None

    def take_thread(self) -> str:
        return self.spare_threads.pop() if self.spare_threads else ""

    def take_artifact(self) -> str:
        return self.spare_artifacts.pop() if self.spare_artifacts else ""


@pytest.fixture(scope="session")
def matrix_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("matrix-data")
    return Settings(
        engine="mock",
        model_provider="mock",
        model_name="mock-scripted",
        model_fallback_chain="mock",
        mock_mode=True,
        mock_model_speed=0,
        deepseek_api_key="",
        qwen_api_key="",
        dashscope_api_key="",
        glm_api_key="",
        openai_api_key="test-openai-key",
        approval_rules="doc.generate_report,file.delete,code.run_python",
        approval_timeout_seconds=5,
        # 测试不读仓库里的 frontend/dist：有没有构建过不该影响接口断言。
        serve_frontend=False,
        database_url=f"sqlite:///{root / 'matrix.db'}",
        env_path=str(root / ".env"),
        upload_dir=str(root / "uploads"),
        artifact_dir=str(root / "artifacts"),
        trash_dir=str(root / "trash"),
        templates_file=str(root / "templates.json"),
        auto_migrate=True,
        log_level="ERROR",
        log_format="text",
    )


@pytest.fixture(scope="session")
def api_client(matrix_settings: Settings) -> Iterator[TestClient]:
    settings = matrix_settings
    settings.ensure_dirs()
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _iter_sse(client: TestClient, thread_id: str, message: str) -> dict[str, object]:
    """跑一轮运行，中途自动批准，返回 {run_id, events, approval_id}。"""
    run_id = ""
    approval_id = ""
    events: list[str] = []
    with client.stream(
        "POST",
        f"{MATRIX_PREFIX}/threads/{thread_id}/runs/stream",
        # 种子里要留一条「已经批过」的审批记录（409 用例用），所以显式要逐步审批：
        # 默认档已经不为写盘弹卡了。
        json={"message": message, "mode": "mock", "approval_mode": "always_ask"},
    ) as response:
        assert response.status_code == 200, response.text
        current = ""
        body = ""
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current = line[len("event:") :].strip()
                events.append(current)
            elif line.startswith("data:"):
                body = line[len("data:") :].strip()
            elif line == "" and current:
                payload = json.loads(body) if body else {}
                if current == "run.started":
                    run_id = str(payload.get("run_id") or run_id)
                if current == "approval.required":
                    approval_id = str(payload.get("approval_id") or "")
                    decision = client.post(
                        f"{MATRIX_PREFIX}/threads/{thread_id}/approvals/{approval_id}",
                        json={"decision": "approved", "comment": "矩阵自动批准"},
                    )
                    assert decision.status_code == 200, decision.text
                    if not decision.json().get("resumed"):
                        break
                current, body = "", ""
    return {"run_id": run_id, "events": events, "approval_id": approval_id}


@pytest.fixture(scope="session", autouse=True)
def sandbox_skill_dirs(api_client: TestClient, tmp_path_factory: pytest.TempPathFactory):
    """把技能目录搬到临时区：导入/删除技能是真实文件操作，不能拿仓库里的 app/skills 练手。

    服务把目录当作可替换属性（self.skills_dir），复制一份再指过去即可；
    复制而不是清空，是为了让「内置技能存在」这类断言仍然成立。
    """
    import shutil

    container = api_client.app.state.container
    real_dir = Path(container.skills.skills_dir)
    before = {item.name for item in real_dir.iterdir()} if real_dir.exists() else set()
    root = tmp_path_factory.mktemp("skill-sandbox")
    skills_dir = root / "skills"
    catalog_dir = root / "catalog"
    shutil.copytree(container.skills.skills_dir, skills_dir)
    shutil.copytree(container.skills.catalog_dir, catalog_dir)
    container.skills.skills_dir = skills_dir
    container.skills.catalog_dir = catalog_dir
    container.skills._reload()  # 目录换了，内存里的技能清单要重建一次
    yield
    # 收尾校验：万一将来有人绕过 sandbox 直接写回 skills_dir，这条断言会当场叫出来
    after = {item.name for item in real_dir.iterdir()} if real_dir.exists() else set()
    assert after == before, (
        f"测试改动了仓库里的技能目录：多出 {after - before}，少了 {before - after}"
    )


@pytest.fixture(scope="session")
def seed(api_client: TestClient, tmp_path_factory: pytest.TempPathFactory) -> Seed:
    client = api_client
    data = Seed()

    main_thread = client.post(f"{MATRIX_PREFIX}/threads", json={"title": "矩阵基线会话"})
    assert main_thread.status_code == 201, main_thread.text
    data.ids["thread_id"] = main_thread.json()["thread_id"]

    upload = client.post(
        f"{MATRIX_PREFIX}/threads/{data.ids['thread_id']}/files",
        files={"file": ("矩阵素材.txt", "第一行\n第二行\n".encode(), "text/plain")},
    )
    assert upload.status_code in (200, 201), upload.text
    files = client.get(f"{MATRIX_PREFIX}/threads/{data.ids['thread_id']}/files").json()["files"]
    data.ids["file_id"] = files[0]["file_id"]

    runs: list[str] = []
    artifacts: list[str] = []
    approval_id = ""
    for message in (f"整理第 {i} 份材料" for i in range(1, 9)):
        result = _iter_sse(client, data.ids["thread_id"], message)
        runs.append(str(result["run_id"]))
        if result["approval_id"]:
            approval_id = str(result["approval_id"])
        listed = client.get(f"{MATRIX_PREFIX}/artifacts?thread_id={data.ids['thread_id']}").json()
        found = [item["artifact_id"] for item in listed["artifacts"]]
        for artifact_id in found:
            if artifact_id not in artifacts:
                artifacts.append(artifact_id)

    assert runs and artifacts, "种子数据没跑出运行或产物"
    data.ids["run_id"] = runs[-1]
    data.ids["artifact_id"] = artifacts[0]
    data.spare_artifacts = artifacts[1:]
    data.ids["approval_id"] = approval_id or "apr_nope"

    # 额外两条会话给「删除 / 批量删除」用，避免删掉只读基线
    for _ in range(2):
        created = client.post(f"{MATRIX_PREFIX}/threads", json={"title": "矩阵备用会话"})
        data.spare_threads.append(created.json()["thread_id"])

    template = client.post(
        f"{MATRIX_PREFIX}/templates",
        json={"name": "矩阵模板", "sections": [{"heading": "本周进展", "source": "progress"}]},
    )
    assert template.status_code in (200, 201), template.text
    data.ids["template_id"] = template.json()["id"]

    project_dir = tmp_path_factory.mktemp("matrix-project")
    (project_dir / "笔记.md").write_text("# 笔记\n内容\n", encoding="utf-8")
    project = client.post(f"{MATRIX_PREFIX}/projects", json={"path": str(project_dir)})
    assert project.status_code in (200, 201), project.text
    data.ids["project_id"] = project.json()["project"]["id"]
    data.project_dir = project_dir

    skills = client.get(f"{MATRIX_PREFIX}/skills").json()["skills"]
    # 技能的对外标识就是目录名（SkillOut.name），没有单独的 skill_id
    data.ids["skill_id"] = skills[0]["name"] if skills else "weekly-report"
    models = client.get(f"{MATRIX_PREFIX}/models").json()["models"]
    data.ids["model_id"] = models[0]["id"] if models else "deepseek"
    return data


@pytest.fixture()
def ids(seed: Seed) -> dict[str, str]:
    """只读用例用的合法 id 集合。"""
    return dict(seed.ids)


@pytest.fixture()
def fresh_thread(api_client: TestClient) -> str:
    created = api_client.post(f"{MATRIX_PREFIX}/threads", json={"title": "一次性会话"})
    assert created.status_code == 201, created.text
    return created.json()["thread_id"]
