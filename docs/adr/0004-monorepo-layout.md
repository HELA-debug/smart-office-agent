# ADR 0004：Monorepo 分层布局（backend/app + frontend/src/features）

- 状态：已采纳（V2.1 B1/B2）
- 日期：2026-10-23
- 决策人：A（后端）/ B（前端）/ C（质量基建）
- 影响面：目录结构、依赖方向、CI 路径、后续拆分

## 背景

V2.0 毛胚是「一个大 main.py + components 平铺」：能跑通，但职责混杂——
`main.py` 600+ 行、业务逻辑与 HTTP 耦合、前端组件直接调 API、契约与实现无机器校验。
V2.1 要求「标准骨架」：分层、契约可校验、扩展点协议化，且单人可维护。

## 决策

采用 **monorepo + 双侧分层**：

```text
backend/
  pyproject.toml        # 工程根（ruff/mypy/pytest/coverage 唯一配置源）
  app/
    main.py             # create_app() 组合根：仅装配
    api/v1/             # 路由 + Pydantic schema；只依赖 services/deps
    core/               # config/logging/errors/events/security/utils（无业务）
    domain/             # entities/enums/ports；不依赖框架
    services/           # thread/run/approval/artifact/settings/template/skill/usage
    agents/             # runtime + engine_protocol + mock_engine + real_engine + model_router
    tools/              # spec/registry/builtin/*
    subagents/          # spec/registry + 1 实现 + 2 占位
    skills/             # SKILL.md 目录
    infra/              # db（SQLAlchemy+Alembic）/ storage / http / parsing
    plugins.py          # entry points 插件加载
  tests/{unit,integration,contract,e2e}/
frontend/src/
  app/                  # App/router/providers/error-boundary
  features/<domain>/    # workbench/sessions/artifacts/settings/runs/audit（含 api.ts/state/components）
  shared/{ui,lib,types,config}/  # 设计系统、SSE/API 客户端、类型、env/flags
  styles/tokens.css
contracts/              # OpenAPI / 事件 JSON Schema 快照（入库，CI diff 锁）
```

**硬规则**（由 CONTRIBUTING + import-linter/ESLint boundaries 约束）：

1. 依赖方向 `api → services → domain ← infra`；`api` 禁止直接 import `infra`。
2. `domain` 不依赖 FastAPI/SQLAlchemy；外部资源走 `domain/ports.py` 的 Protocol。
3. 配置唯一来源 `core/config.py`；禁止散落 `os.getenv`。
4. 前端 feature 之间只能通过 `index.ts` 公共出口互相引用；生成类型目录只读。
5. 契约快照 `contracts/` 入库；改接口必须同 PR 更新并通过 CI `contract` 门禁。

## 备选方案与不采用原因

| 方案 | 不采用原因 |
|---|---|
| 保持 V2.0 单文件/平铺结构 | 无法验证分层与扩展性；新增功能持续腐化 |
| 拆成多个独立服务/仓库（backend-api、agent、web） | 15 人日预算下部署与协作成本过高；目录边界已预留拆分点 |
| 前端按技术类型分层（components/hooks/api 平铺） | B3 页面变多后跨 feature 耦合难控；feature 化更利于并行 |

## 影响与代价

正面：

- 改一个 feature 只动一个目录；新增工具/Provider/模板有明确落点。
- CI 可按目录跑 lint/mypy/pytest；契约快照锁住接口，前端生成类型。
- 目录边界即未来服务边界，V1.0 拆分不需要重写业务。

负面：

- 初期迁移成本（B1/B2 一次性重构）；`git blame` 历史被重写。
- 对开发者要求更高：跨层 import 会被门禁拦住，需要先想清楚归属。
- 旧 `/api` 别名与旧前端页面需要兼容期。

## 验证方式

- 目录核对：`backend/app/{api,core,domain,services,agents,tools,connectors,subagents,infra}/` 与
  `frontend/src/{app,features,shared}/` 均存在且被实际使用。
- 依赖方向：`ruff`/mypy 与 code review；前端 ESLint `boundaries` 规则。
- 契约：`contracts/openapi.v1.json` 32 paths / 40 operations 与 `/openapi.json` 一致（CI contract）。
- 行为基线：迁移前后 API 契约与 smoke 用例通过（V2.0 10 条 → V2.1 30 条）。
