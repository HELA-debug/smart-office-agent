# 09 · 前端

> 事实来源：`frontend/`。完整路径前缀 `frontend/`，下文简写。

## 9.1 技术栈

| 项 | 版本 |
|---|---|
| React / React DOM / react-router-dom | 19.1 / 19.1 / 7.6 |
| TypeScript | 5.9 |
| Vite / @vitejs/plugin-react | 7.1 / 5.0 |
| Tailwind CSS / @tailwindcss/vite | 4.1 |
| Vitest / @vitest/coverage-v8 / jsdom | 5.0 / 5.0 / 29 |
| @playwright/test | 1.64 |
| ESLint / Prettier | 9.39 / 3.9 |
| mammoth（docx → HTML 预览） | 1.13 |

运行时依赖只有 3 个（react / react-dom / react-router-dom）+ mammoth，**没有 msw**：演示数据由 `shared/lib/mock-run.ts` + `?mock=1` 提供。

## 9.2 工程配置

| 文件 | 要点 |
|---|---|
| `vite.config.ts` | server `127.0.0.1:5173` strictPort；proxy 仅 `/api` → `VITE_API_TARGET \|\| http://127.0.0.1:8000`，配 `timeout: 0` / `proxyTimeout: 0` / `Accept-Encoding: identity`（SSE 与 180s 审批挂起需要）；**无路径别名** |
| `vitest.config.ts` | jsdom；**`fileParallelism: false`**（20+ 文件并行会触发 V8 OOM，导致部分文件静默不执行、覆盖率虚低） |
| `eslint.config.js` | flat config；`import/order` 强制；**`eslint-plugin-boundaries` 强制分层**（见 9.3） |
| `tsconfig.app.json` | `strict` + `noUncheckedIndexedAccess` + `verbatimModuleSyntax` + `noEmit` |
| `playwright.config.ts` | `workers: 1`、`fullyParallel: false`（并发多实例 Edge 会崩）；项目用 `channel: 'msedge'`（本机不额外下载浏览器）；`webServer` 自动起 `npm run dev` |

构建脚本 `npm run build` 走 `scripts/build.mjs`（先 `tsc -b` 再 `vite build`，并把 TEMP/TMP 指向 `frontend/.tmp`）。

## 9.3 分层与边界（由 ESLint 强制）

| 层 | 路径 | 可依赖 | 跨层规则 |
|---|---|---|---|
| app | `src/app/**` | feature、shared | 外壳：BrowserRouter、Provider、路由、TitlebarDock |
| feature | `src/features/*` | shared、feature | **只允许通过 `index.ts` 被引用** |
| shared | `src/shared/**` | shared | ui / lib / config / types |
| styles | `src/styles/**` | shared | 仅 `tokens.css` |
| test | `src/test/**` | 任意 | 测试 setup |

其他规则：`no-explicit-any: error`、`consistent-type-imports`、`import/order`（builtin→external→internal→parent→sibling→index→object→type）、`no-console`（只留 warn/error）。

## 9.4 目录与 feature 清单

| feature | 页面 | 调用的后端端点 |
|---|---|---|
| **workbench** | `/`（三栏工作台） | `runs/stream`、`prompts/enhance`、`desktop/package*`、`threads`、`settings`、`usage/summary`、`threads/{id}/audit` |
| **sessions** | 左栏会话列表 | `threads`（含 reorder、bulk-delete）、`files` |
| **artifacts** | `/artifacts` | `artifacts*`（列表/下载/预览/打开/软删/恢复/purge/批量删）、`trash`、`files/{id}` |
| **runs** | 卡片组件（供工作台复用） | `runs*`（列表/详情/事件/cancel/retry）、`approvals` |
| **audit** | `/audit` + 右栏抽屉 | `threads/{id}/audit`、`usage/summary`、`audit/export` |
| **projects** | `/projects/:id` + 左栏项目区 | `projects*`、`projects/{id}/files`、`projects/{id}/reveal` |
| **skills** | `/skills` | `skills*`、`skills/catalog*`、`skills/import`、`skills/draft`、`prompt-packs`、`tools` |
| **settings** | `/settings` | `settings`、`storage/*`、`models*`、`tools`、`subagents`、`skills`、`feedback`、`health` |

shared 层：

| 目录 | 关键内容 |
|---|---|
| `shared/ui/` | `primitives.tsx`（Button/Badge/Card/Modal/Tooltip 等，568 行）、`Icons.tsx`（60+ 自绘 SVG）、`Select`（自绘圆角下拉）、`Checkbox`、`Toast`、`Markdown`、`PageShell`、`FloatingMenu`、`BarChart`/`AreaChart`、`ServiceDownBanner`、`StaleBuildBanner`、`TitlebarDock` |
| `shared/lib/` | `api.ts`（ApiError / requestV1 / 后端掉线广播）、**`sse.ts`**（streamRun / resumeRunEvents）、`format.ts`、`theme.ts`、`thinking-pref.ts`、`mock-run.ts`（623 行演示数据）、`share.ts`、`download.ts`、`redact.ts`、`build-info.ts`、`build-watch.ts`、`desktop.ts`、`backend-status.ts`、`artifacts-signal.ts`、`titlebar.ts`、`markdown.ts` |
| `shared/config/` | `runtime.ts`（API 基址、超时、`SSE_MAX_RECONNECTS`）、`providers.ts`（供应商标签与官方控制台链接）、`approval-modes.ts`、`output-formats.ts`、`feature-flags.ts`（含导航项） |
| `shared/types/` | `events.ts`（事件类型 + `parseRunEvent` 校验）、`view.ts`（跨 feature 视图模型）、`api.ts`（手写契约类型） |
| `shared/api/` | `generated/schema.d.ts`（**由 OpenAPI 生成，禁止手改**）+ `types.ts`（45 条类型别名） |

## 9.5 状态管理

### 文件职责（features/workbench/state/）

| 文件 | 行数 | 职责 |
|---|---|---|
| `types.ts` | 307 | `WorkbenchStatus`、`ConnectionState`、`TimelineItem`（message/note/thinking/plan/tool/subagent）、`UploadItem`、`QueuedMessage`、`WorkbenchAction`（约 40 个） |
| `workbench.ts` | 539 | reducer 主体；SSE 分支委派 `run-events.ts`，整理动作委派 `helpers.ts`；**队列逻辑在 reducer 里**（`queue/add`、`queue/remove`、`queue/promote`、`queue/pause`…） |
| `run-events.ts` | 325 | 11+ 类事件的逐个迁移 |
| `mappers.ts` | 140 | DTO → 视图模型（拆 artifacts 与 uploads、过滤 run_summary 等） |
| `helpers.ts` | 189 | 跨事件整理纯函数（upsertTimeline、settlePendingApprovals、cancelPlanProgress…） |
| `selectors.ts` | 26 | `selectBlockingApproval`、`selectRunBusy`、`selectIsStreaming` |
| `background-tasks.ts` | 71 | 模块级 store + `useSyncExternalStore`（切走会话也能继续跑任务） |
| `last-thread.ts` | 36 | localStorage `oa:last-thread` |
| **`useWorkbench.ts`** | 1192 | 控制器 hook，返回 24 个成员 |

### useWorkbench 关键机制

| 机制 | 说明 |
|---|---|
| 常量 | `NOTICE_TTL_MS=5000`、`BULK_DELETE_CHUNK=200`、`MAX_SESSION_PAGES=20`（100/页 → 上限 2000 会话） |
| 启动 | 挂载即 `checkHealth()` + `loadSessions()`；仅一次"恢复上次会话"（取 `oa:last-thread`，失败则清除） |
| 发送 | **忙时不拦人**：`selectRunBusy` 为真时连素材一起 `queue/add` |
| 上传时机 | `staged` 文件在真正发送时才上传（`flushStagedUploads`），避免"选文件就凭空多一个会话" |
| 队列出队 | `drainQueue()` 用 `drainingRef` 加锁，状态空下来时取本会话最早一条执行 |
| 停止 | 本地断流 + 队列 pause + `cancelRun`；404 时提示"当前后端版本较低" |
| 产物联动 | `onArtifactsChanged` → `loadSessions({silent:true})`，解决"新产物要刷新才出现" |

### 渲染链路

```text
WorkbenchPage（data-testid=workbench-shell）
├─ 左栏 SessionList + ProjectsSection（可折叠，状态存 localStorage）
├─ 中栏
│  ├─ StatusBar        健康 / 模式 / 降级 / 连接态 / 主题开关 / 左右栏开关
│  ├─ ChatStream       items → splitTurns() 按 user 消息切轮
│  │  ├─ MessageBubble（user / assistant / system 三形态）
│  │  ├─ renderTraces() → filterTraces(traces, thinkingView)
│  │  │  ├─ ThinkingBlock   流式「正在思考」→ 完成后折叠「已思考」
│  │  │  ├─ PlanCard / ToolCard / SubagentCard
│  │  │  └─ ExecutionTrace  2 条以上过程收成一行折叠区
│  │  ├─ InlineApproval    审批内联进对话流
│  │  └─ ArtifactDelivery   只铺最新 1 份 +「更早的产物 · N 个」折叠
│  ├─ RunSummaryCard   一行收尾：成了没 / 几个文件 / 花了多少
│  ├─ BackgroundTasksBar（mm:ss 计时 + 回会话 / 停止）
│  └─ Composer（1049 行）
│     ├─ ComposerQuickAccess  模型与用量胶囊
│     └─ QueuedMessages       计数胶囊 + 每任务一卡（编辑/删除/优先执行）
└─ 右栏 RightPanel（桌面侧栏；<1024px 变抽屉）产物仓库 + DesktopAppCard
```

| 细节 | 说明 |
|---|---|
| 滚动跟随 | `PIN_THRESHOLD_PX=140`，仅在底部附近才跟随；流式时跟随 `[data-streaming="true"]` 那条气泡末尾 |
| 思考呈现 | `filterTraces` 按 `thinkingView` 裁剪：`off` 全清、`brief` 只留 plan、`full` 全给 |
| 产物归属 | `ArtifactDelivery` 按最后一条产物的 `run_id` 判定"最新一轮"，**保证刷新后仍可见** |

## 9.6 主题与外观

| 项 | 实现 |
|---|---|
| 令牌定义 | `src/styles/tokens.css`（900 行），`@theme { --color-* }` + `html.dark { ... }` 覆盖 |
| 浅色主色 | canvas `#f3f5f9`、surface `#ffffff`、line `#e2e8f0`、ink `#0f172a`、brand `#2563eb` |
| 深色主色 | canvas `#101317`、surface `#1b1e24`、line `#2a2f37`、ink `#eef1f6`、brand `#4d8df6` |
| 切换 | `document.documentElement.classList.toggle('dark')` + 改写 `meta[name=theme-color]`；`index.html` 有内联脚本防首屏闪色 |
| 缩放 | 两个**独立**变量：`--ui-scale` 写 `html` 的 `font-size`（rem 派生）；`--font-scale` 只乘进 `--text-*` 字号令牌 |
| 字体 | 6 套字族（system/yahei/source-han/songti/kaiti/xingkai）→ `--font-sans` |
| 标题栏 | `--titlebar-h`（桌面窗口让位），`env(titlebar-area-height, 0px)` 兜底 |

## 9.7 本地持久化 key

| key | 用途 | 默认 |
|---|---|---|
| `oa:last-thread` | 最近打开的会话 | — |
| `oa:theme` | 深/浅色 | dark |
| `oa:ui-scale` | 界面缩放 85–110 | 90 |
| `oa:font-scale` | 字号 85–130（step 5） | 100 |
| `oa:font-weight` | 字重 300–600（step 50） | 400 |
| `oa:font-family` | 字体样式 | system |
| `oa.thinking_view` | 思考呈现 full/brief/off | full |
| `oa.approval-mode` | 审批策略 | risky |
| `oa.leftRail` | 左栏展开/收起 | — |
| `oa:rail-projects-open` | 左栏项目区折叠 | — |
| `oa.mock.projects` | 演示模式项目列表 | — |
| `oa:build-reloaded-at`（**sessionStorage**） | 30s 刷新闸门，防 reload 循环 | — |

## 9.8 路由

| 路径 | 页面 |
|---|---|
| `/` | 工作台 |
| `/settings` | 设置中心 |
| `/artifacts` | 产物中心 |
| `/audit` | 审计用量 |
| `/skills` | 插件与技能 |
| `/projects/:projectId` | 项目文件（选文件后经路由 state 带回 `/`） |
| `/knowledge` | 占位页（唯一 `real: false`） |
| `*` | 重定向到 `/` |

`App.tsx` = BrowserRouter + AppProviders + TitlebarDock + ServiceDownBanner + StaleBuildBanner + AppRouter。

## 9.9 测试

| 类型 | 规模 |
|---|---|
| 单测 | 60 文件 / 约 808 用例 / 约 13,900 行（vitest + jsdom） |
| E2E | `e2e/smoke.spec.ts` 单文件 / 5 describe / 39 用例（依赖 `?mock=1`，后端不可用时 skip） |
| 覆盖率阈值 | statements/branches/functions/lines 各 **60** |

覆盖重点：`useWorkbench.test.ts`（72 case：健康检查、会话恢复、上传、审批、停止/重试、队列出队、后台任务）、`sse.test.ts`（36 case：帧解析、终态关流、续传去重）、`StreamComponents.test.tsx`（38 case）、`Composer.test.tsx`（29 case）。
