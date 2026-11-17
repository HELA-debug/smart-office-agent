# 13 · 测试与质量门禁

> 事实来源：`.github/workflows/ci.yml`、`backend/tests/`、`frontend/`（vitest + playwright）、根 `tests/`、`.pre-commit-config.yaml`

## 13.1 四层测试

| 层 | 位置 | 规模 | 跑法 |
|---|---|---|---|
| 后端单测/集成 | `backend/tests/{unit,integration,api,contract,e2e}` | 1454 passed / 42 skipped（当前基线） | `cd backend && pytest -q` |
| 根级黑盒 smoke | `tests/` | 30 passed + 1 skipped（真实模型） | `make smoke` |
| 前端单测 | `frontend/src/**/*.test.{ts,tsx}` | 60 文件 / 约 808 用例 | `cd frontend && npm run test` |
| E2E | `frontend/e2e/smoke.spec.ts` | 39 用例 | `make e2e` |

## 13.2 后端测试组织

| 目录 | 特点 |
|---|---|
| `unit/` | 34 个文件，覆盖核心算法：pricing、context_window、tool、docx/pdf/xlsx/text utils、engine_switch、runtime_degrade、provider_adapters、model_router |
| `integration/` | 走真实 API 栈：approval_mode、artifact 回收站/批量删、events 重放、migrations、pipeline、thread 分页、desktop |
| `api/` | 契约矩阵 + 语义测试 + fuzz 矩阵（对同一组端点跑参数组合，验证状态码与错误码一致） |
| `contract/` | 事件契约校验 |
| `e2e/` | 真实 DeepSeek 调用（默认跳过） |

统一约定：`MOCK_MODE=true`、`DATABASE_URL=sqlite:///:memory:`；**测试结束仓库根必须干净**（CI 里 `git status --porcelain` 必须为空）。

### 根级 smoke 设计

| 文件 | 内容 |
|---|---|
| `conftest.py` | `--base-url`（默认 `http://127.0.0.1:8004`）；`require_mock_backend` 自动守卫（非 mock 模式直接 `pytest.exit`）；辅助 `consume_sse()`（可自动提交审批）、`SseReader`、`run_flow()`、`assert_error()` |
| `test_smoke_core.py` | 10 条：health 字段、旧 `/api` Deprecation 头、会话 CRUD、搜索分页、设置来源、保存即生效、校验错误、模型/工具/技能 |
| `test_smoke_files.py` | 5 条：6 格式上传、多文件字段、非法类型、伪造 magic bytes、素材删除 |
| `test_smoke_flow.py` | 15 条：SSE 全链路、拒绝流、重复审批 409、审批超时、取消/重试、事件重放、产物、审计 |
| `test_real_smoke.py` | 1 条，需 `RUN_REAL_MODEL_TEST=1` |

**黑盒**：不 import 任何后端代码，只走 HTTP。

## 13.3 前端测试

| 项 | 配置 |
|---|---|
| 环境 | jsdom |
| 并行 | **`fileParallelism: false`**（20+ 文件并行会触发 V8 OOM，导致部分文件静默不执行、覆盖率虚低到 22%） |
| 覆盖率 | v8 provider；阈值 statements/branches/functions/lines 各 **60** |
| 排除 | 入口、app 层、generated、桶文件、测试文件 |
| E2E | `workers: 1`、`channel: 'msedge'`；`?mock=1`；后端不可用时 `test.skip` |

覆盖重点：

| 文件 | 用例数 | 覆盖点 |
|---|---|---|
| `useWorkbench.test.ts` | 72 | 健康检查、会话恢复、上传、审批、停止/重试、队列出队、后台任务、产物补拉 |
| `sse.test.ts` | 36 | 帧解析、终态关流、续传去重、错误体解析 |
| `StreamComponents.test.tsx` | 38 | ChatStream / MessageBubble / ThinkingBlock / ExecutionTrace |
| `Composer.test.tsx` | 29 | 输入、排队、附件、格式、审批策略 |
| `ArtifactCard.test.tsx` | 35 | 产物卡片交互 |

## 13.4 CI 六门禁

`CI (V2.1 六门禁)`，触发：push main / PR / 手动 / **nightly（cron 0 18 * * *）**。

| # | Job | 内容 |
|---|---|---|
| 1 | `backend-lint` | `ruff check` + `ruff format --check` + `mypy app` |
| 2 | `backend-test` | `pytest --cov=app --cov-fail-under=70` + 起 8004 mock 服务跑 30 条 smoke + **工作区洁净断言** `git status --porcelain` |
| 3 | `frontend-quality` | `npm run lint` → `format:check` → `typecheck` → `test:coverage` |
| 4 | `contract` | `export_openapi.py` + `git diff --exit-code contracts/` + 快照自检 + 前端类型 diff |
| 5 | `build` | `npm ci && npm run build`；Docker 可用则 `docker compose build && up -d` 并探活 8080（不可用则 warning 跳过） |
| 6 | `security` | `.env` 不得入库 + secret 扫描 + PII 扫描 + `check_requirements_sync.py` + `pip_audit` + `npm audit --omit=dev --audit-level=high` + `bandit -r backend/app -ll` |

外加 **E2E（nightly，不阻塞 PR）**：起 mock 后端 + vite dev → `playwright test`。

流水线习惯：

| 项 | 做法 |
|---|---|
| 前置守卫 | 每个 job 先检查关键文件存在（缺就 `::error` 快速失败），避免环境配置问题伪装成代码问题 |
| 并发 | `concurrency` 按 workflow+ref 分组，`cancel-in-progress: true` |
| 定位 | 每个 job 开头打印 `::group::`，失败时上传 coverage / playwright-report |
| 网络 | 全局设 `NO_PROXY=localhost,127.0.0.1`、`PIP_INDEX_URL` 阿里云 |

## 13.5 覆盖率现状

| 侧 | 门槛 | 备注 |
|---|---|---|
| 后端 | `--cov-fail-under=70` | core 层约 88% |
| 前端 | 60 / 60 / 60 / 60（vitest 配置） | CI 注释里写"40% 起"是旧值，**实际生效的是 vitest 配置里的 60** |

## 13.6 本地钩子

.pre-commit-config.yaml：

| 阶段 | 内容 |
|---|---|
| pre-commit | 尾随空格、文件末尾换行、yaml/json/toml 校验、合并冲突、大文件 >2048KB、私钥检测、换行符 |
| pre-commit（backend） | ruff（v0.8.4）、mypy（v1.13.0） |
| manual | 前端 eslint / prettier / typecheck |
| commit-msg | `scripts/check_commit_msg.py`（Conventional Commits） |

## 13.7 写测试时的几条硬规矩

1. **测试不能把仓库弄脏**：只写 `tmp_path`，CI 会检查 `git status --porcelain`。
2. **黑盒 smoke 不 import 后端代码**，保证它测的是真实部署形态。
3. **前端测试关并行**，否则覆盖率虚低、部分文件静默不执行。
4. **改契约必须同 PR 更新快照**，否则 job 4 红。
5. **真实模型测试默认跳过**（`RUN_REAL_MODEL_TEST=1` 才跑），避免 CI 花用户的钱。
