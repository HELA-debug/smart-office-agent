# office-agent-mvp 项目解析报告

> 解析范围：源码 / 配置 / 文档（已自动跳过 node_modules、.git、dist、build、__pycache__ 等依赖目录与编译产物）
> 版本：v0.2.0（V2.1 标准骨架） · 许可：MIT

## 一、项目概览

### 项目定位与核心功能

**单用户、桌面优先的办公 Agent 工作台（MVP）**。核心是一条完整可演示的办公自动化链路：

```
上传素材 → 任务计划 → 工具调用 → 高风险审批 → DOCX 产物 → 审计用量
```

- 默认 mock 模式：无 API Key、断网也能完整演示（内置确定性引擎，事件时序与真实模式一致）
- 配置 Key 后走真实大模型：DeepSeek 默认（`deepseek-chat`），千问 / GLM / OpenAI 可切换，fallback 链 + 失败自动降级 mock 并标记 `degraded`
- mock 邮件只写本地 `data/outbox/*.eml`，**绝不真实外发**；审批拒绝时零写入

### 架构模式与完整技术栈清单

**架构：前后端分离 + 后端清晰分层（近似 DDD / 六边形），单体部署。**

- 前端 SPA（React 19 + Vite），开发经 Vite 代理、生产经 Nginx 反代访问 `/api`
- 后端 FastAPI 单体：分层依赖方向 `api → services → domain ← infra`，由 import-linter 在 CI 强制
- Agent 引擎与 API 同进程（ADR 0001 主动决策）；运行事件 SSE 推送并全量落库，支持断线重放

| 层 | 技术 | 版本 / 说明 |
|---|---|---|
| 后端语言 | Python | >= 3.13 |
| Web 框架 | FastAPI + uvicorn | >= 0.115 / >= 0.30 |
| 数据验证 | pydantic / pydantic-settings | >= 2.8 / >= 2.4 |
| ORM / 迁移 | SQLAlchemy 2.0 + Alembic | >= 2.0 / >= 1.13 |
| 文档处理 | python-docx / pypdf / openpyxl | DOCX 生成；PDF / XLSX / CSV 解析 |
| HTTP 客户端 | httpx | >= 0.27，统一工厂 `trust_env=False` |
| 其他后端库 | pyyaml / python-multipart | 价格表 / 上传 |
| 前端框架 | React 19 + react-router-dom 7 | SPA，features 目录组织 |
| 构建 | Vite 7 + TypeScript 5.9 + Tailwind CSS 4 | |
| 前端测试 | Vitest 5 + Testing Library + Playwright | 单测 / E2E（6 条） |
| 数据库 | SQLite（默认 `sqlite:///data/app.db`）/ PostgreSQL 可切换 | 同一 Alembic 迁移链 |
| 质量工具 | ruff / mypy（domain·services·agents strict）/ import-linter / bandit / pytest+cov / eslint / prettier | CI 六门禁 |
| 部署 | Docker + docker-compose（api:8000 + web:8080 Nginx，SSE buffering off） | |
| 大模型 | DeepSeek（默认）/ 通义千问 DashScope / 智谱 GLM / OpenAI，均走 OpenAI 兼容协议 | fallback 链 `deepseek,qwen,glm,mock` |

### 运行环境与依赖安装要求

- **前置**：Python 3.13+、Node.js 20+（Windows 无 GNU make，README 提供了所有原始命令）
- **安装**：`pip install -e backend`（README 建议阿里云镜像）+ `cd frontend && npm ci`
- **配置**：`cp .env.example .env`（默认 `MOCK_MODE=true`，Key 只放 .env，已 gitignore）
- **启动**：`uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` + `cd frontend && npm run dev`（5173）
- **或 Docker**：`docker compose up --build -d`（工作台 8080，api 8000）
- 注意：Windows 若 `NO_PROXY` 含 `[::1]` 会导致 httpx `InvalidURL`，需设为 `localhost,127.0.0.1`（代码/CI 已统一处理）

## 二、目录结构说明

```text
office-agent-mvp/
├── backend/                        # FastAPI 后端（Python 3.13）
│   ├── pyproject.toml              # 依赖 + ruff/mypy/pytest/coverage/import-linter/bandit 配置
│   ├── alembic.ini                 # 数据库迁移 CLI 入口
│   ├── config/model_prices.yaml    # 供应商价格表（元/百万 tokens，成本估算）
│   ├── main.py                     # 旧启动路径兼容（backend.main:app）
│   └── app/
│       ├── main.py                 # 【组合根】create_app()：装配 infra+services+agents，挂载路由
│       ├── api/                    # HTTP 层：deps.py（AppContainer 依赖注入）+ v1/ 路由 + schemas
│       ├── core/                   # config/logging/errors/events/security/utils（无业务框架逻辑）
│       ├── domain/                 # entities/enums/ports（纯 dataclass + Protocol，零框架依赖）
│       ├── services/               # 业务编排：thread/run/approval/artifact/settings/model/template/skill/usage
│       ├── agents/                 # runtime（装配）+ engine_protocol + mock/real engine + model_router
│       ├── tools/                  # spec.py（扩展点）+ registry + builtin/{file,doc,mail,todo,xlsx}
│       ├── connectors/             # 连接器抽象 + mail_mock + mail_imap（只读骨架）+ registry
│       ├── subagents/              # 子智能体：spec/registry + 1 实现（doc_agent）+ 2 占位
│       ├── skills/weekly-report/   # SKILL.md（frontmatter 声明触发词/启停）
│       ├── prompts/system.md       # 版本化系统提示词（含 version frontmatter）
│       ├── plugins.py              # entry points 插件加载
│       └── infra/                  # db（SQLAlchemy+Alembic+仓储）/ storage / parsing / http / mail
├── frontend/                       # React SPA
│   ├── package.json                # 依赖与脚本（dev/build/test/lint/gen:api/e2e）
│   ├── vite.config.ts / vitest.config.ts / playwright.config.ts
│   └── src/
│       ├── app/                    # App / router / providers / error-boundary
│       ├── features/               # workbench / sessions / runs / settings / audit（api+state+components）
│       ├── shared/                 # ui / lib（sse,api,format,markdown,redact）/ types / config / api/generated
│       └── test/                   # Vitest setup
├── contracts/                      # openapi.v1.json（32 paths/40 ops）+ events.v1.schema.json（入库，CI diff 锁版本）
├── deploy/                         # nginx.conf.template + snippets / requirements.api.txt + lock / migrations
├── docs/                           # api.md / events.md / demo.md / acceptance.md / adr/0001–0005
├── scripts/                        # export_openapi.py / export.py / make_sample.py / check_commit_msg.py
├── tests/                          # 根目录 30 条黑盒 smoke（pytest + httpx，mock 服务 8004）
├── data/                            # 运行时数据：app.db / uploads / artifacts / outbox / trash（gitignore）
├── .github/workflows/ci.yml        # 六道门禁 + nightly Playwright
├── Dockerfile.api / Dockerfile.web / docker-compose.yml
├── Makefile / .env.example / .editorconfig / .pre-commit-config.yaml
└── README.md / CHANGELOG.md / CONTRIBUTING.md / KNOWN_ISSUES.md / CODEOWNERS / LICENSE
```

## 三、核心业务流程

### 主功能链路的数据流向与调用关系

```
浏览器工作台
  │ POST /api/v1/threads/{id}/runs/stream（SSE，fetch + ReadableStream）
  ▼
FastAPI（main.py 组合根装配的 AppContainer）
  ▼ RunService.start()
AgentRuntime.prepare_engine() ── 探测供应商（60s 缓存）→ 选 mock / real 引擎
  ▼ 创建 Run(running) + user Message，启动生产者 asyncio.Task
Engine.run(ctx) ── 每个 EngineEvent：
  ├─ 落库 run_events（seq 自增，run_id+seq 唯一）
  ├─ 内存 broker 广播（多订阅者）
  └─ asyncio.Queue → RunChunk → SSE 帧（id=seq / event / data）
  ▼
前端 shared/lib/sse.ts 解析帧 → features/workbench/state/workbench.ts reducer → UI
```

**MockEngine 确定性链路**（与 v0.1 事件顺序一致）：
`run.started → message.delta* → message.completed → plan.updated(4 项逐步推进) → tool.finished(file.list) → tool.finished(file.read) → tool.finished(doc.generate_report) → artifact.ready → approval.required（挂起）→ 批准则 tool.finished(mail.send) / 拒绝则跳过 → plan.updated → message.* → run.completed`

**RealEngine ReAct 循环**（事件协议与 mock 完全一致，只追加字段）：
1. system prompt（`prompts/system.md` + 工具调用约定）+ 工具 JSON Schema（由函数签名反射生成）+ 会话素材清单 + 用户邮箱
2. `router.chat_with_tools()` 调模型 → 文本流式输出（message.delta 12 字/片）+ tool_calls
3. 内核执行工具（`asyncio.to_thread` 防阻塞 + sanitize 脱敏 + 内核计划推进）→ 观察结果回填 messages → 再决策
4. 保护：最大 12 步 / 单 run 200k tokens 预算 / 工具失败不中断转结构化观察 / 模型"说完就停"时按任务意图兜底（补生成 DOCX、补发邮件走审批，记 `fallback_actions`）
5. 供应商全不可用 → 整条运行降级 MockEngine（`degraded=true`）；运行中失败 → 降级收尾（保留已完成产物）

**高风险审批流**（`mail.send` 命中 `APPROVAL_RULES`）：
`approval.required → ApprovalService.create 注册 asyncio.Event → 引擎等待（每 15s 发 ping 心跳）→ 前端 POST /api/v1/approvals/{id} → decide 落库 + set event → 批准则执行 / 拒绝则跳过并标记 REJECTED → 超时 180s 判 APPROVAL_TIMEOUT → run.failed`

**取消 / 重试 / 重放**：
- 取消 = 取消生产者任务 → 补一条 `run.cancelled` 帧落库 → 级联取消待审批（幂等）
- 重试 = 取原 run 的 user 消息在同会话重跑；产物可 regenerate
- 重放 = `resume()` 先回放 `run_events`（`?after=` / `Last-Event-ID`）再订阅 broker，15s 无事件发 ping

### 核心模块的实现逻辑说明

| 模块 | 职责 |
|---|---|
| `api/v1/*` | 薄 HTTP 层（12 个路由文件：health/threads/files/runs/approvals/artifacts/settings/models/templates/skills/extensions/usage），全部经 `deps.ContainerDep` 取服务 |
| `services/run_service.py` | **运行编排中枢**：生产者-消费者架构、事件持久化、broker 广播、取消/重试/回放、审计导出（JSON/CSV） |
| `agents/runtime.py` | 唯一内核装配入口：工具注册表 + 子智能体 + 提示词 + 技能 + 模型路由 + 引擎选择 |
| `agents/model_router.py` | 供应商路由：fallback 链、错误七分类、重试/熔断、价格表成本估算、用量分组累计 |
| `tools/spec.py` | 工具抽象：`@tool` 装饰器注册、签名反射生成 JSON Schema、`group.verb` ↔ OpenAI function 名映射 |
| `services/settings_service.py` | 配置分层热更新：白名单校验 + DB 覆盖 + mutate Settings 并重绑 runtime |
| `infra/db/` | SQLAlchemy 2.0 ORM + 8 仓储实现 + Alembic 迁移（0001→0002） |

## 四、关键技术设计

### 封装的通用能力 / 公共组件

1. **分层契约强制**：import-linter 两条 layers 契约 + 两条 forbidden 契约——`api` 禁止 import `infra`（经 deps 注入端口）；`domain` 禁止依赖 fastapi/sqlalchemy/httpx 等
2. **契约先行**：`contracts/openapi.v1.json` + `events.v1.schema.json`（12 类事件，draft-07）入库，CI `contract` 门禁要求 diff 为空；前端 `schema.d.ts` 由 openapi-typescript 生成（禁止手改）；事件协议 v1.1 **只追加**
3. **模型路由**（ADR 0005）：`MODEL_FALLBACK_CHAIN` 顺序探测；错误分类（auth / rate_limit / timeout / server / bad_format / network / unconfigured）→ 鉴权失败立即熔断 60s，限流/超时/网络退避 1s 重试 1 次，5xx/格式错误直接切换；全失败抛 `ModelUnavailableError` → 引擎降级 mock 标 `degraded`
4. **工具系统**：新增工具 = 一个函数 + 一行 `@tool` 装饰器；`build_schema` 由类型注解反射生成参数 schema；`ToolContext` 共享可变上下文（material_text / todos / artifact_ids）；工具异常不中断运行，转结构化观察回填模型
5. **审批门控**：`ApprovalGate` 端口 + `asyncio.Event`；decide 幂等（`APPROVAL_ALREADY_DECIDED` 409）；超时/取消均落 extra 标记
6. **配置分层热更新**：`core/config.py` 为唯一来源（env > .env > default）；设置中心 11 项白名单 + 严格类型校验，保存即热生效，重启后 `apply_persisted` 仍生效
7. **安全与脱敏**：密钥只存 `env:NAME` 引用（`GET /settings`、`/models` 不回显）；`core/security.sanitize` 对所有工具输入输出脱敏；`settings.redacted()` 供日志/健康检查
8. **可观测性**：trace_id 中间件（`X-Trace-ID` 透传 + 响应头）；结构化 JSON 日志（`bind_log_context` 绑定 trace_id/run_id）；旧 `/api/*` 别名自动打 `Deprecation: true` 头
9. **插件机制**：`plugins.py` 经 entry points 自动发现插件工具；技能经 `SKILL.md` frontmatter 启停

### 数据库设计与接口规范

**8 张表**（`infra/db/models.py`，时间统一 ISO-8601 字符串，扩展字段统一 JSON 列）：

| 表 | 关键字段 | 索引/约束 |
|---|---|---|
| threads | id/title/pinned/deleted_at/extra | 软删除 |
| messages | id/thread_id/role/content/run_id | (thread_id, created_at) |
| runs | id/thread_id/status/mode/engine/provider/model/tokens/cost_cny/error_code/extra | (thread_id, started_at) |
| run_events | id 自增/run_id/seq/event/data | UniqueConstraint(run_id, seq) + 索引 |
| approvals | id/thread_id/run_id/tool/payload/decision/policy_version | (thread_id, run_id) |
| artifacts | id/thread_id/run_id/type/filename/path/size/sha256/deleted_at | (thread_id, run_id) |
| settings | key 主键/scope/value_json/is_secret | |
| model_configs | id/provider/base_url/model/api_key_ref/priority/enabled | |

- 迁移链：`0001`（对齐 v0.1 四表）→ `0002`（V2.1 四表）；对空库与现有 `data/app.db` 均幂等；启动时 `auto_migrate` 自动执行
- 接口规范：`/api/v1` 版本化（32 paths / 40 ops）；统一响应包裹 `trace_id`；统一错误体 `{"trace_id", "error": {"code", "message", "details"}}`；13 个错误码目录（`core/errors.py`）映射 HTTP 状态（400/404/409/413/415/422/429/500/504）

### 权限、校验、异常处理机制

- **权限**：单用户设计，无账号体系（KNOWN_ISSUES #6，V1.0 计划 users + JWT）；高风险工具白名单审批（`APPROVAL_RULES`）即"权限"主手段
- **校验**：上传三重校验（扩展名 + MIME + magic bytes）+ 大小限制；pydantic 请求体验证（失败 400 + details）；设置更新白名单 + 类型 + 取值范围校验
- **异常**：`AppError` 统一抛出 → 四个异常处理器（AppError / HTTPException / RequestValidationError / Exception）→ 统一错误体；工具异常、模型异常均被收敛为结构化数据，不冒泡中断主链路

## 五、初步观察

### 代码结构规范度与可维护性：高

- 分层边界清晰且有 import-linter **强制执行**，领域层零框架依赖，可单测
- 「契约先行」文化落地扎实：OpenAPI/事件快照入库 + CI 六门禁 + ADR 0001–0005 + DoD 30 条 + KNOWN_ISSUES 21 条**如实记录**（含未达标项，不虚报）
- 测试体系分层完整：后端 117 passed / 覆盖率 84.7%、30 条黑盒 smoke、Playwright 6 条、真实模型 smoke（默认跳过，有证据 JSON）
- 文档质量高：README 含 8 分钟 demo 脚本、12 项扩展点清单、每条命令的 Windows 原始写法

### 可识别的潜在问题 / 优化点

1. **【阻断级疑点】前端 `features/artifacts` 模块缺失但被路由引用**：`frontend/src/app/router.tsx:2` 导入 `ArtifactsPage from '../features/artifacts'`，但该目录在仓库中不存在（git 工作树干净，即 HEAD 即如此）。这将直接导致 `npm run build` / `tsc -b` 报 Module not found——与 CHANGELOG「tsc 0 error」的记录矛盾，疑似分支合并遗漏。**建议立即执行 `npm run typecheck` 验证并补齐产物中心页面模块。**
2. 前端测试覆盖率 8.61%，未达 60% 目标（项目自报未达标）
3. 缺 `backend/uv.lock`，依赖版本不可完全复现（干净安装可启动已验证）
4. 架构级妥协（KNOWN_ISSUES 记录在案）：Agent 与 API 同进程无法水平扩展；SQLite 并发写弱；无账号体系数据不隔离；进程崩溃后运行中任务丢失（有重放无检查点）
5. MockEngine 与 RealEngine 的 `_wait_for_approval` 审批等待逻辑重复，可上提公共基类或混入
6. 设置热更新通过直接 mutate pydantic `Settings` 实例实现，简单有效；后续新增可配置项时需同步 `_EDITABLE` 白名单与 `_apply`，易遗漏
7. `data/outbox` 与 `data/trash` 无清理策略，长期演示运行会累积文件

### 理解确认与重点关注文件

**是，我已完整理解项目的整体架构与核心逻辑**：前后端分离的分层单体、契约先行的 API/事件规范、mock/real 双引擎一致性协议、SSE 事件持久化与断线重放、多供应商模型路由与降级链、审批门控与配置热更新，以及「上传 → 计划 → 工具 → 审批 → 产物 → 审计」完整闭环。

后续开发/调试建议重点关注的 3 个核心文件：

1. **`backend/app/services/run_service.py`** — 运行编排中枢：SSE 生产者/消费者、事件持久化、取消/重试/回放、审计导出。任何运行期行为改动都绕不开它。
2. **`backend/app/agents/real_engine.py`** — 真实模型 ReAct 内核：工具循环、审批流、降级兜底、内核计划推进。mock↔real 行为差异与交付可靠性逻辑集中在此。
3. **`backend/app/core/config.py`** — 配置唯一来源：所有 env/DB 分层、供应商 Key/BaseURL 解析、路径派生、热更新的地基。

（前端对应核心文件：`frontend/src/features/workbench/state/workbench.ts` — 工作台状态机 reducer，是前后端事件契约的消费端，联调问题首先对照它。）
