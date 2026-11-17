# 12 · 开发工作流

> 事实来源：`Makefile`、`CONTRIBUTING.md`、`.pre-commit-config.yaml`、`.github/workflows/ci.yml`

## 12.1 首次上手

```bash
make setup          # 建 .venv + 装后端依赖 + npm ci
make api            # 终端 A：uvicorn --reload
make web            # 终端 B：vite dev
make verify         # 改完后：lint + test + contract + smoke + build + security
```

不想开两个终端：`make start`（走 `scripts/launch.py`，自动装依赖、构建前端、起服务、开浏览器）。

## 12.2 高频命令

| 场景 | 命令 |
|---|---|
| 后端单测 | `cd backend && pytest -q` |
| 后端覆盖率 | `cd backend && pytest --cov=app --cov-report=term-missing --cov-fail-under=70` |
| 前端单测 | `cd frontend && npm run test` |
| 前端类型 | `cd frontend && npm run typecheck` |
| 只跑某个用例 | `pytest -k "test_pricing"` / `npm run test -- -t "frames"` |
| 契约快照 | `python scripts/export_openapi.py`（`--check` 只校验） |
| 前端类型生成 | `cd frontend && npm run gen:api` |
| 黑盒 smoke | `make smoke`（自动起停 8004 mock 服务） |
| E2E | `make e2e`（需要本机 Edge/Chrome） |
| 造演示素材 | `make sample`（生成 `data/samples/meeting_notes.docx`） |

## 12.3 改代码常见落点

| 需求 | 落点 |
|---|---|
| 加 HTTP 接口 | `api/v1/<module>.py` → `router.py` → 契约快照 → 前端 `api.ts` |
| 加工具 | `tools/builtin/<name>.py`，`@tool(...)` 注册 |
| 加供应商 | `providers/registry.py` + `core/config.py` 的 Key/URL 字段 + `model_prices.yaml` |
| 加产物格式 | `tools/builtin/doc.py` 的 `OUTPUT_FORMATS` + 对应 `*_utils.py` |
| 改成本 | `backend/config/model_prices.yaml`（改完不用重启） |
| 改提示词 | `backend/app/prompts/system.md`（改完需重启；技能是热更新的） |
| 加事件 | 见 [08 篇 8.7](08-events-sse.md) |
| 加表 | 改 `infra/db/models.py` → `alembic revision --autogenerate` → 检查迁移幂等性 |
| 加页面 | `frontend/src/features/<x>/` + `app/router.tsx` + `shared/config/feature-flags.ts` 导航项 |

## 12.4 契约更新流程（改接口必须走）

```bash
# 1. 改代码
# 2. 导出快照
python scripts/export_openapi.py
# 3. 生成前端类型
cd frontend && npm run gen:api
# 4. 更新文档（只追加）
# 5. 提交时 contracts/ 与 generated/schema.d.ts 一起进
```

CI 会做两件事：

1. `export_openapi.py` + `git diff --exit-code contracts/` → 快照必须与代码一致。
2. 用快照生成的类型 vs 仓库里 `generated/schema.d.ts` → 必须完全一致（先去掉 CLI 的 4 行 banner）。

规则（`contracts/README.md`）：**禁止手改快照，只允许追加**；破坏性变更升 `/api/v2` 或 `events version=2` 并补 ADR。

## 12.5 代码风格

### 后端

| 工具 | 配置 |
|---|---|
| ruff | `backend/pyproject.toml`；`ruff check .` + `ruff format --check .` |
| mypy | `mypy app`（工作目录 `backend`） |
| 行宽 | 与 ruff 默认一致 |

### 前端

| 项 | 规则 |
|---|---|
| 格式化 | Prettier：`semi`、`singleQuote`、`printWidth 100`、`trailingComma all` |
| 导入顺序 | `import/order` 强制：builtin → external → internal → parent → sibling → index → object → type，字母序升序，组间不空行 |
| 类型导入 | `consistent-type-imports`（`prefer: type-imports`） |
| any | `no-explicit-any: error` |
| console | 只允许 `warn` / `error` |
| 架构边界 | `eslint-plugin-boundaries`（见 [09 篇 9.3](09-frontend.md)） |
| 命名 | 未使用变量以 `_` 前缀豁免 |

## 12.6 分支与提交

| 项 | 规则 |
|---|---|
| 分支 | `feat/xxx` / `fix/xxx` |
| PR | ≤400 行，一人 review，当日合并 |
| 提交信息 | Conventional Commits，由 `scripts/check_commit_msg.py` 在 commit-msg 阶段校验 |
| 允许的 type | `feat` `fix` `refactor` `test` `docs` `chore` `perf` `build` `ci` `style` `revert` |
| subject | 非空且 ≤100 字符 |
| 放行前缀 | `Merge ` / `Revert ` / `fixup! ` / `squash! ` |

本地钩子（`.pre-commit-config.yaml`）：

| 阶段 | 内容 |
|---|---|
| pre-commit | 尾随空格、文件末尾换行、yaml/json/toml 校验、合并冲突标记、大文件（>2048KB）、私钥检测、换行符 |
| pre-commit（仅 backend） | ruff、mypy |
| manual | 前端 eslint / prettier / typecheck |
| commit-msg | Conventional Commits |

安装：`pre-commit install && pre-commit install --hook-type commit-msg`

## 12.7 调试技巧

| 想看什么 | 怎么做 |
|---|---|
| 某次请求的日志 | 取响应头 `X-Trace-ID`，在日志里搜它 |
| 某次运行 | 搜 `run_id`；模型调用会打 `event="model_call"` |
| 后端进程是否比代码旧 | `GET /api/v1/health` 比对 `git_sha` 与 `git_sha_live` |
| 前端是否比后端旧 | 界面上有 StaleBuildBanner；`shared/lib/build-info.ts` 三方 sha 比对 |
| 成本算得对不对 | 看 `run.extra["usage"]` 的 `cache_hit`/`cache_miss`，再对照 `model_prices.yaml` |
| 到底用的哪个引擎 | `GET /api/v1/health` 的 `engine_effective` + `engine_reason` + `degraded_reason` |
| 模型调用是否真实 | 审计里的 `request_ids` / `verified_calls`；没有 id 会打 `model_call_unverified` 警告 |
| 只想看演示数据 | 前端加 `?mock=1`（或 `VITE_MOCK=1`），不依赖后端 |
