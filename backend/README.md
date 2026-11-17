# office-agent-backend（V2.1 分层版）

FastAPI + 进程内 Agent 的后端。V2.1 起代码在 `app/` 下分层，旧 `backend.main:app` 启动路径保留兼容。

## 启动（在仓库根执行）

```bash
# Windows
./.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# macOS / Linux
./.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

- 接口：`/api/v1/*` 为主路径；旧 `/api/*` 保留兼容别名（响应头 `Deprecation: true`）
- 文档：<http://127.0.0.1:8000/docs>
- 健康检查：`GET /api/v1/health`
- 默认 mock 模式，断网可跑；`.env` 配置真实模型后自动探测，失败自动降级

## 目录

```text
backend/
├── pyproject.toml            # 依赖 / ruff / mypy / pytest / coverage / import-linter
├── alembic.ini               # Alembic CLI 入口
├── app/
│   ├── main.py               # 组合根：装配 infra/services/agents，挂载路由
│   ├── api/                  # HTTP 层：deps.py + v1/* 路由 + schemas
│   ├── core/                 # config/logging/errors/events/security/utils（无框架业务逻辑）
│   ├── domain/               # entities/enums/ports（Protocol，不依赖框架）
│   ├── services/             # thread/run/approval/artifact/settings/usage 编排
│   ├── agents/               # runtime + engine_protocol + mock/real engine + model_router
│   ├── tools/                # spec.py 扩展点 + builtin/{file,doc,todo,xlsx}
│   ├── connectors/           # 连接器抽象 + mock 邮件 + IMAP 只读骨架 + registry
│   ├── subagents/            # 1 实现（doc_agent）+ 2 占位（sheet/research）
│   ├── infra/                # db（SQLAlchemy/Alembic/仓储）、storage、parsing、http
│   ├── prompts/system.md     # 版本化系统提示词
│   ├── skills/               # 已安装技能：SKILL.md（frontmatter 声明触发词/开关/分类/图标）
│   ├── skills_catalog/       # 技能库：可一键添加的内置技能，未添加不进提示词
│   └── evals/smoke_cases.json
└── tests/                    # unit / integration / contract / e2e
```


## B3 基础功能接口（/api/v1）

| 能力 | 接口 |
|------|------|
| 设置中心 | `GET /settings`（生效值 + 来源 db/env/default + 密钥引用）、`PUT /settings`（保存即热生效） |
| 模型管理 | `GET /models`、`POST /models`（`api_key_ref` 仅 `env:NAME`）、`POST /models/{id}/test`（脱敏探测） |
| 会话管理 | `GET /threads?q=&page=&page_size=`、`PATCH /threads/{id}`、`DELETE /threads/{id}` |
| 运行管理 | `POST /threads/{id}/runs/stream`、`POST /runs/{id}/cancel`、`POST /runs/{id}/retry`、`GET /runs?thread_id=&status=`、`GET /runs/{id}/events?after=`、`GET /runs/{id}/events/stream` |
| 产物中心 | `GET /artifacts?thread_id=&type=&page=`、`DELETE /artifacts/{id}`（移入 data/trash）、`POST /artifacts/{id}/regenerate` |
| 上传增强 | `POST /threads/{id}/files`（`file` 单文件 / `files` 多文件，扩展名+MIME+magic bytes，xlsx/csv 解析）、`GET /threads/{id}/files`、`DELETE /files/{id}` |
| 模板与技能 | `GET/POST/DELETE /templates`、`POST /templates/{id}/render`、`GET /skills`、`PATCH /skills/{id}`、`GET /skills/catalog`、`POST /skills/catalog/{id}/install` |
| 用量与审计 | `GET /usage/summary?range=7d\|30d&thread_id=`、`GET /threads/{id}/audit`、`GET /audit/export?format=json\|csv` |

错误码目录见 `app/core/errors.py`（`ERROR_CODE_CATALOG`），错误体统一为
`{"trace_id": "...", "error": {"code": "...", "message": "...", "details": ...}}`。
旧 `/api/*` 全部保留为兼容别名（响应头 `Deprecation: true`）。

## 数据库

- 8 张表：`threads/messages/runs/run_events/approvals/artifacts/settings/model_configs`
- 启动时自动执行 `alembic upgrade head`（可用 `AUTO_MIGRATE=false` 关闭）
- 迁移链：`0001` 对齐 v0.1 四表 → `0002` 新增四表与列；对空库与现有 `data/app.db` 均幂等
- 手动迁移：

```bash
cd backend
../.venv/Scripts/python.exe -m alembic upgrade head
```

## 事件与重放

- SSE 帧：`id: <seq>` / `event` / `data`，`seq` 与 `run_events.seq` 一致
- 运行中每帧落库 `run_events`；断线后用 `GET /api/v1/runs/{run_id}/events/stream`
  携带 `Last-Event-ID`（或 `?after=`）续传；`GET /api/v1/runs/{run_id}/events?after=` 返回 JSON 事件列表
- 审批期间连接保持打开，等待期每 15s 一条 `: ping` 注释帧

## 质量门禁

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q
../.venv/Scripts/python.exe -m ruff check app tests
../.venv/Scripts/python.exe -m ruff format --check app tests
../.venv/Scripts/python.exe -m mypy
../.venv/Scripts/python.exe -m lint-imports      # 分层契约
```

## 配置

唯一来源 `app/core/config.py`（pydantic-settings，读取仓库根 `.env`）。
密钥只从环境读取，API 只返回"是否配置"，日志与响应一律脱敏。
模型 HTTP 调用统一走 `app/infra/http.py`（`trust_env=False` + 显式 HTTPS_PROXY），
规避 Windows `NO_PROXY=[::1]` 导致的 httpx `InvalidURL`。
