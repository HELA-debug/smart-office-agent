# Frontend · Office Agent 工作台（v0.3 · B3 基础功能页面）

React 19 + Vite 7 + TypeScript + Tailwind CSS v4 + react-router-dom。
单页三区工作台，由 `docs/events.md` 的 SSE 事件驱动状态机；数据请求全部收敛到 feature api 层。

## 质量脚本

```bash
npm install                # 依赖解析见 .npmrc（legacy-peer-deps）；慢时可加 --registry=https://registry.npmmirror.com
npm run dev                # http://127.0.0.1:5173（/api 代理到 http://127.0.0.1:8000）
npm run lint               # ESLint flat config（strict + import/order + feature 边界）
npm run lint:fix
npm run format             # Prettier 全量格式化
npm run format:check       # CI 用：只检查
npm run typecheck          # tsc -b（strict + noUncheckedIndexedAccess）
npm run build              # scripts/build.mjs：tsc -b + vite build（用仓库内 .tmp 规避 Windows TEMP 锁）
npm test                   # Vitest + RTL（reducer / 卡片）
npm run test:coverage      # 覆盖率报告（lcov + text）
npm run gen:api            # 后端 OpenAPI → src/shared/api/generated/schema.d.ts
npm run e2e                # Playwright 冒烟（本机 Chrome，无需下载浏览器）
```

联调时后端不在 8000：`VITE_API_TARGET=http://127.0.0.1:8099 npm run dev`。
`?mock=1`（或 `VITE_MOCK=1`）启用本地 mock 事件流（同一套 reducer，演示兜底）。
`?run_mode=mock|real`（或 `VITE_RUN_MODE`）覆盖单次运行模式（随 `POST /runs/stream` 的 mode 下发；真实模型不可用时演示兜底）。

## 目录结构（feature 化）

```
src/
  app/                     # App.tsx / router.tsx / providers.tsx / error-boundary.tsx
  features/
    workbench/             # 工作台页面、ChatStream/Composer/StatusBar/RightPanel、state（reducer+hook）
    sessions/              # 会话列表（服务端搜索/分页）、改名/置顶/软删、会话 API
    runs/                  # 计划/工具/子智能体/审批卡、SSE/审批接口（运行过程可视化）
    artifacts/             # 产物卡、产物中心 /artifacts（筛选/预览/软删/重新生成）、上传 API
    audit/                 # 审计抽屉、审计用量 /audit（按日聚合、JSON/CSV 导出）、审计 API
    settings/              # 设置中心 /settings（模型/Key 状态/连通性测试/审批/热更新）、设置 API
  shared/
    ui/                    # 设计系统 primitives / Icons / PageShell / 通用占位页
    lib/                   # api 内核（超时/错误/trace）、sse、format、markdown、redact、mock fixture
    types/                 # 手写类型（events/api/view），与 docs 契约对应
    api/generated/         # openapi-typescript 生成物（禁止手改）
    config/                # runtime（baseURL/mock）、feature flags、任务模板
  styles/tokens.css        # Tailwind @theme 设计 token（含 90% 基准字号与空状态自适应节奏）
  test/setup.ts            # Vitest + jest-dom 初始化
e2e/                       # Playwright 冒烟
scripts/gen-api.mjs        # OpenAPI → TS 类型脚本
scripts/build.mjs          # 构建入口（本地 .tmp + tsc + vite build）
```

### 视觉基准（90%）

整页基准字号是 **90%**（`tokens.css` 的 `html { font-size: 90% }`，即 14.4px 根），
视觉密度等价于浏览器 90% 缩放：信息更疏、留白更多。两条约定：

- **尺寸一律用 rem**（Tailwind 的字号/间距/圆角天然如此）。需要写死时用 `[Nrem]` 而不是 `[Npx]`，
  换算 `N/16`；只有 1px 描边、滚动条、阴影这类不参与缩放的细节保留 px。
- 首屏（空状态）的垂直节奏用 `clamp(..., vh, ...)` 随窗口高度伸缩，`max-height: 700px`
  切紧凑版（图标与标题并排、隐藏重复说明）；内容用 `my-auto` 居中，空间不足时自动顶部对齐。
- 右栏「窄面板转下拉」阈值 270px，对应 20rem 面板在 90% 基准下的实宽 288px。

### 职责归类说明

- `features/workbench`：页面编排、状态机、中栏对话流、右栏容器、顶部状态条（工作台 chrome）。
- `features/sessions`：会话列表与 `/threads` 接口（左栏）。
- `features/runs`：运行过程可视化的卡片（计划/工具/子智能体/审批）与 SSE/审批接口。
- `features/artifacts`：产物与上传（素材）能力及接口。
- `features/audit`：审计抽屉与接口。
- 跨 feature 的纯数据类型放 `shared/types/view.ts`，组件通过 props 接收数据，不互相依赖内部状态。

### feature 边界（ESLint 强制）

- `features/*` 之间只能通过目标 feature 的 `index.ts` 引用；引用内部文件会 `boundaries/entry-point` 报错。
- `shared/*` 不得反向依赖 any feature；`app` 可以依赖 feature 与 shared。
- 验证方式：临时新建 `src/features/workbench/__probe.ts` 引 `../sessions/components/SessionList`，
  运行 `npx eslint` 会报 “no policy allowing dependencies…”（验证后删除）。

## B3 页面与联调（v0.3）

| 路由         | 功能                                                                                                                  | 关键接口                                                                      |
| ------------ | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `/`          | 工作台三区：会话（⋮ 菜单：置顶/重命名/删除、分页）、个人模板、流式对话+思考过程、审批、产物、多文件上传、产物格式选择 | `/api/v1/threads`、`/runs/stream`、`/approvals/{id}`、`/files`                |
| `/settings`  | 设置中心：供应商/模型/Key 状态/添加 Key/连通性测试/审批工具/mock/上传上限/降级链；保存即生效                          | `GET/PUT /settings`、`GET/POST /models`、`POST /models/{id}/test`             |
| `/artifacts` | 产物中心：跨会话、类型/会话筛选、每页 12 条 + 下拉选页、预览弹窗（docx→HTML）、下载、软删                             | `GET /artifacts`、`DELETE /artifacts/{id}`、`POST /artifacts/{id}/regenerate` |
| `/audit`     | 审计用量（dsh 风格）：累计/近 30 天/请求次数总览、时间维度筛选、消费金额趋势图、按模型分组、真实用量                  | `GET /usage/summary`、`GET /threads/{id}/audit`                               |

- 类型来源：`npm run gen:api` → `shared/api/generated/schema.d.ts`；业务代码通过 `shared/api/types.ts` 的别名使用，禁止手改生成目录。
- SSE 断线重连：失败后进入 `reconnecting` 状态，最多 3 次退避重连 `GET /runs/{id}/events/stream`（带 `Last-Event-ID`），按事件 seq 去重；失败给出错误条 + 重试。
- 思考过程（v1.2）：`thinking.delta/thinking.completed` → `ThinkingBlock`（流式打字机 → 完成后折叠「已思考」可展开）；首段在开场消息前，审批后追加一段二次思考。
- 上传：支持多文件（`files` 字段一次提交，后端不支持时回退 `file` 逐个上传）、XHR 真实进度、扩展名/大小前端校验、解析预览（后端 `text_preview` 前 200 字）。
- 产物格式：输入区「产物格式」下拉（`shared/config/output-formats.ts`）——第一项默认与首个上传素材同格式，
  其余为其他可选格式（docx/pdf/xlsx/md/txt）；用户改选后随 `POST /runs/stream` 的 `output_format` 下发，
  后端按格式渲染（docx=python-docx、xlsx=openpyxl、pdf=reportlab、md/txt=文本渲染）。
- 产物预览：`ArtifactPreviewModal` —— docx 用 mammoth 转 HTML（文档级排版）、md/txt/csv/html 文本渲染、
  pdf/xlsx 引导下载；不接第三方在线预览（WPS 开放平台需企业凭证，本期不做）。
- 统一 hover 提示：`shared/ui/primitives.tsx` 的 `Tooltip`（深色气泡），`IconButton` 已内置，替换全站原生 `title`。
- 限额容器：右栏三区（审批/产物/素材）各自 `max-h` + 内部滚动；产物中心分页；均不撑大页面。
- 设置保存白名单字段：`model_provider/model_name/mock_mode/approval_rules/mail_to/max_upload_mb/fallback_chain/model_timeout_seconds/approval_timeout_seconds`；Key 不回显，仅展示 `configured` 与 `api_key_ref`。
- 添加 Key：`POST /models` 只登记 `env:NAME` 引用（不落明文），保存后需在服务端环境变量注入真实值方可生效；连通性用 `POST /models/{id}/test` 验证。
- 真实模型不可用时可加 `?run_mode=mock` 强制 mock 运行（仅影响运行时 mode 字段，不写配置）。

## 契约与类型生成

- 手写契约类型：`shared/types/events.ts`（SSE v1，一一对应 docs/events.md）、`shared/types/api.ts`。
- 生成类型：`npm run gen:api`，优先 `/api/v1/openapi.json`，回退 `/openapi.json`；
  后端未启动时脚本明确提示并以非 0 退出。生成文件**禁止手改**，契约变更后重跑。
- B1 的 `/api/v1` 契约发生变化后请重新生成（当前生成的 `schema.d.ts` 来自同机 8000 的
  最新 OpenAPI，包含 `/api/v1/*` 路径）。

## 测试

- `workbench.test.ts`：状态机 idle → streaming → waiting_approval → done/error、事件解析忽略未知项、
  审批阻塞、停止/失败收尾。
- `PlanCard.test.tsx` / `ApprovalCard.test.tsx`：计划进度与折叠、审批三按钮/提交中/已决议状态。
- 新增 B3 单测：设置表单校验（`settings/form.test.ts`）、产物筛选（`artifacts/filter.test.ts`）、运行状态/耗时汇总（`runs/lib/run-view.test.ts`）。
- `e2e/smoke.spec.ts`：11 条（工作台/知识库可达、右栏用量与额度、个人模板、输入框快捷气泡、
  会话 ⋮ 菜单、思考过程、审计页、设置 Key 弹窗、设置保存生效、产物中心分页）。
  浏览器走本机 Edge（`channel: 'msedge'`，Chrome 同内核）；本机并发多实例会崩 worker，故 `workers: 1` 串行。

### 覆盖率现状与门槛

```bash
npm run test:coverage   # 覆盖率报告 + 60% 门槛校验
```

当前 `All files | 74.50% Stmts | 65.40% Branch | 66.23% Funcs | 75.64% Lines`
（30 个测试文件 / 792 条用例）。门槛写在 `vitest.config.ts` 的 `coverage.thresholds`，
四项指标同时卡 60%，低于门槛时命令以非 0 退出（CI 已接入）。

覆盖重点（按评审建议的优先级补齐）：

- `features/workbench/state/`：`workbench.ts` reducer 90%、`useWorkbench.ts` 97%
  （健康检查、会话 CRUD、断流续传、审批幂等、上传四条失败路径、mock 模式）
- `shared/lib/`：`sse.ts` 98%（含 `streamRun` / `resumeRunEvents` 的成功、HTTP 错误、
  断流、abort）、`api.ts` 100%、`mock-run.ts` 78%（含完整事件脚本与三种中断点）、
  `format.ts` / `redact.ts` / `markdown.ts` 接近全覆盖
- 五个 feature 的 `api.ts`（settings/runs/sessions/artifacts/audit）真实请求与 mock 两条路径
- `shared/ui/`：`primitives.tsx` 95%、`Icons.tsx` 100%、`AreaChart.tsx` 覆盖 hover 与边界
- 工作台组件：气泡 / 思考块 / 流容器 / 状态栏 / 空态 / 运行摘要 / 用量卡 / 快捷入口 / 产物卡与预览弹窗

仍未覆盖的大块（继续提升的着力点）：`SettingsPage.tsx`、`SessionList.tsx`、
`AuditPage.tsx`、`ArtifactsPage.tsx`、`Composer.tsx`、`WorkbenchPage.tsx`。

> 注意：测试在 `vitest.config.ts` 里关闭了文件级并行（`fileParallelism: false`）。
> 并行时每个 worker 各加载一份 jsdom，实测会触发 V8 OOM，
> 表现为「部分测试文件静默不执行、覆盖率虚低到 22%」，比直接崩溃更难排查。

## 安全

- 模型 Key 只存在于项目根 `.env`；前端不读取、不打印、不写入任何密钥。
- 工具入参/出参在 ToolCard 中再次脱敏（密钥字段打码、邮箱保留首字母）。
- 上传/产物展示只使用接口返回的 URL，不在前端拼接凭据。

## 截图

- B3 真实后端联调：`frontend/screenshots/lead21/`
  - `settings.png` / `settings-saved.png`（设置中心 + 保存生效）
  - `sessions-managed.png`（会话搜索/改名/置顶）
  - `upload-multi.png`（txt + xlsx 多文件上传与解析预览）
  - `artifacts.png` / `artifacts-filter.png` / `artifacts-preview.png`（产物筛选/预览）
  - `audit.png` / `audit-thread.png`（用量聚合 + 会话明细）
  - `workbench-approval.png` / `workbench-done.png`（v1 主链路：审批→产物→用量）
- B2/v0.1 历史证据保留在 `frontend/screenshots/`（`real-backend-*.png`、`b2-*.png` 等）。
