# 贡献指南（CONTRIBUTING）

> 适用版本：V2.1（标准化版本）。V2.0 毛胚版的行为基线见 `CHANGELOG.md` 与 `docs/acceptance.md`。
> 目标：让「规范可执行、契约可校验、扩展可证明」落到每一次提交，而不是靠口头约定。

## 1. 环境准备

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.13+ | 后端；工程根为 `backend/pyproject.toml`（uv 管理） |
| Node.js | 20+ | 前端；`frontend/package-lock.json` 锁定 |
| Docker | 可选 | 镜像与 compose 验证；无 Docker 时 `make verify` 跳过并提示 |

```bash
# 一条命令装齐（Linux/macOS/Git Bash）
make setup

# 无 make（Windows 默认不带）时，按 README「开发命令」逐条执行
```

**镜像源**：本机实测官方 PyPI / 清华源不可达，统一用阿里云镜像
`https://mirrors.aliyun.com/pypi/simple`；npm 使用默认 registry（或团队内网镜像）。

**Windows 代理变量**：本机 `NO_PROXY` 含 `[::1]` 会让 httpx 抛
`InvalidURL: Invalid port: ':1]'`。测试进程与 CI 已统一设为
`NO_PROXY=localhost,127.0.0.1`；业务代码统一走 HTTP 客户端工厂（`trust_env=False`），
不要在业务里直接 `httpx.Client()` 读环境代理。

## 2. 分支与提交

- `main` 受保护；功能分支 `feat/<scope>`、修复 `fix/<scope>`、重构 `refactor/<scope>`、
  文档 `docs/<scope>`、工程 `chore/<scope>`。
- PR 目标分支 `main`，**≤400 行**、**一人 review**、**当日合并**；冲突当场解决，不积压。
- 提交信息用 Conventional Commits：
  `feat(backend): add run replay`、`fix(frontend): approval card focus`、`docs: update ADR`。
- 提交前必须跑：
  ```bash
  pre-commit run --all-files   # 或至少 ruff check / ruff format --check / mypy
  make test
  ```
- 禁止 `--no-verify` 跳过钩子；确有例外需在 PR 描述说明并获 review 同意。

## 3. 代码规范

### 后端（`backend/app/`）

- 分层依赖：`api → services → domain ← infra`。
  **禁止** `api` 直接 import `infra`；`domain` 不得依赖 FastAPI/SQLAlchemy 等框架。
- 配置唯一来源 `core/config.py`（pydantic-settings）；禁止散落 `os.getenv`。
- 路由函数必须声明 `response_model=` 与 `status_code=`；错误统一 `AppError(code, message, status)`。
- 日志结构化 JSON：`trace_id / run_id / thread_id / event / duration_ms`；
  **禁止**记录密钥、完整邮箱等敏感信息。
- 异步优先；`python-docx` 等阻塞调用放线程池。
- 类型：`mypy --strict` 覆盖 `domain/services/agents`；其余至少 `disallow_untyped_defs`。
- 工具实现只依赖 `domain` 与注入上下文；禁止直接建 `sqlite3` / `httpx` 连接。
- 数据层：SQLAlchemy 2.0 + Alembic；SQLite 与 PostgreSQL 同一条迁移链。

### 前端（`frontend/src/`）

- `strict: true` + `noUncheckedIndexedAccess`；**禁止 `any`**（ESLint error）。
- feature 之间禁止互相 import 内部文件，只能走 `features/<name>/index.ts`。
- 类型生成链路：`contracts/openapi.v1.json` → `npm run gen:api`；
  `features/../generated/` 只读，**禁止手改**。
- 数据请求只在 hooks/feature api 层；组件只接收 props。
- 表单 label、按钮 aria、焦点管理必须可用；对比度符合 WCAG AA。

## 4. 测试要求

| 层 | 位置 | 门槛 |
|---|---|---|
| 单元 | `backend/tests/unit`、前端 `*.test.ts(x)` | 后端行覆盖 ≥70%（core ≥85%），前端 ≥60% |
| 集成 | `backend/tests/integration` | 主链路全覆盖 |
| 契约 | `backend/tests/contract` | OpenAPI/事件 Schema 快照 100% 通过 |
| E2E | `backend/tests/e2e`、`frontend/e2e` | smoke ≥28/30；Playwright 6 条（nightly/release） |

**测试卫生硬要求**：

- 所有临时文件用 `tmp_path` / `tmp_path_factory` / `tmp_path` 等价物，禁止写入仓库根。
- 测试结束仓库根必须干净：
  ```bash
  pytest ... && test -z "$(git status --porcelain)"
  ```
  CI 的 `backend-test` job 已加该断言。
- 禁止联网测试；外部依赖一律 mock（模型、邮件、IMAP）。

## 5. 契约规则（重要）

- `docs/events.md`、`docs/api.md` 是前后端合同：**只允许追加**事件/字段，不得修改已有语义。
- 契约快照 `contracts/openapi.v1.json`、`contracts/events.v1.schema.json` 入库；
  改接口必须同步快照，CI 的 `contract` 门禁要求 `git diff --exit-code contracts/` 为空。
- 破坏性变更必须：升版本（`/api/v2`、`events version=2`）+ ADR + 保留旧版一个迭代。
- 新增 ADR：`docs/adr/NNNN-<title>.md`，结构：背景 / 决策 / 替代方案 / 影响。

## 6. CI 六道门禁

| # | Job | 内容 | 阻塞 |
|---|---|---|---|
| 1 | `backend-lint` | `ruff check` + `ruff format --check` + `mypy app` | 是 |
| 2 | `backend-test` | `pytest --cov=app --cov-fail-under=70` + 工作区洁净断言 | 是 |
| 3 | `frontend-quality` | eslint + prettier + `tsc -b` + vitest | 是 |
| 4 | `contract` | 导出 OpenAPI/事件 Schema 后 `git diff --exit-code contracts/` | 是 |
| 5 | `build` | `vite build`；Docker 可用时 `docker compose build` | 是（Docker 不可用则告警跳过） |
| 6 | `security` | secret/PII 扫描（**排除 `.env`**）+ pip-audit + npm audit + bandit | 是 |

> B0 阶段门禁为骨架：相关文件（`backend/pyproject.toml`、`scripts/export_openapi.py`、
> 前端 lint 脚本）未就绪时 job 会**明确报错**而不是空跑成功；B1/B2 落地后由 QA 校准。

## 7. 安全与合规

- 密钥只允许环境变量或设置中心「引用」（如 `env:DEEPSEEK_API_KEY`），**DB 不存明文**；
  日志与 API 回显一律脱敏，设置页不回显完整 Key。
- `.env` 已 gitignore；禁止提交、打印、上传任何真实 Key。CI secret scan 不扫描 `.env`。
- 上传：扩展名 + MIME + magic bytes 三重校验；文件名 sanitize；禁止路径穿越；限额。
- 模型 Base URL 仅允许 http(s)，可选私网地址阻断（SSRF）。
- 依赖：锁文件入库；每月 `pip-audit` / `npm audit` 巡检。

## 8. 发布与文档

- 版本 semver；首个标准版本 `v0.2.0`。
- 每个面向用户的 PR 更新 `CHANGELOG.md` 的 `[Unreleased]`。
- 文档：README（启动/架构/命令）、`docs/demo.md`、`docs/acceptance.md`、
  `docs/adr/`；接口与事件文档随契约快照更新。
- 已知问题记录到 `KNOWN_ISSUES.md`，每条包含「影响 + 绕过方式」。

## 9. Issue / PR

- Bug 用 `.github/ISSUE_TEMPLATE/bug.md`（含复现步骤、期望/实际、环境）。
- 需求用 `.github/ISSUE_TEMPLATE/feature.md`（含验收判定）。
- PR 用 `.github/pull_request_template.md`，勾选检查项；契约变更需附 ADR/快照 diff。
