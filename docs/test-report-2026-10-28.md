# Office Agent MVP · 测试报告（2026-10-28）

> 对应计划：`docs/test-prompts-2026-10-28.md`（2000 用例版）。
> 本轮定位：**先跑自动化能覆盖的那一层**（门禁 + 视觉巡检 + 端到端），把命中的缺陷修掉，
> 手工/读屏/真机部分留作下一批。
> 环境：本机单端口 `http://127.0.0.1:8000`（`SERVE_FRONTEND=1`，后端 `real` 引擎 / deepseek harness），
> 构建产物 `frontend/dist`（2026-10-28 14:2x 构建），浏览器 Edge（Playwright `channel: msedge`）。

---

## 1. 一句话结论

自动化门禁 **全绿**（`pytest 349` / `vitest 1094` / `playwright 38` / `tsc`·`eslint` 干净 / 契约快照一致）；
新增的 **36 个「页面 × 视口 × 主题」视觉巡检**用例在修复后 **0 布局问题、0 对比度不足**。
本轮共发现并修复 **5 个缺陷**，其中两个是「界面说错话」（真实模型下仍写"演示模式、不会外发"），
一个是「小字看不清」（浅色 `faint` 只有 2.35:1），一个是「桌面端拿的是旧代码」。

---

## 2. 门禁结果

| 层 | 命令 | 结果 |
|---|---|---|
| 后端单测 / 集成 / 契约 | `pytest tests/unit tests/integration tests/contract -q` | **349 passed** |
| 前端单测 | `cd frontend && npm test` | **1094 passed**（53 个测试文件） |
| 端到端 | `cd frontend && npx playwright test` | **38 passed**（1.7 min） |
| 类型 / Lint | `npx tsc --noEmit` + `npm run lint` | 干净 |
| 构建 | `npm run build` | 成功（仅有既有的 chunk >500kB 提示） |
| 契约快照 | `scripts/export_openapi.py --check` | `openapi.v1.json` / `events.v1.schema.json` 一致 |

---

## 3. 视觉 / 对比度巡检（36 用例）

脚本 `frontend/scripts/ui-sweep.cjs`（Node + Playwright，只读操作），覆盖
**6 个路由 × 3 档视口（1440×900 / 1024×768 / 390×844）× 亮暗两主题 = 36 用例**：

| 路由 | 检查项 |
|---|---|
| `/` 工作台 | 横向溢出（`scrollWidth > clientWidth`） |
| `/artifacts` 产物中心 | 越界元素（右沿超出视口 / 左沿为负，排除横向滚动容器内部） |
| `/audit` 审计用量 | 文字对比度（正文 4.5:1，大字 3:1；逐元素取实际合成背景色） |
| `/settings` 设置 | 控制台 error / pageerror |
| `/knowledge` 知识库 | 4xx / 5xx 响应 |
| `/skills` 插件与技能 | 截图取证（`docs/test-evidence-2026-10-28/shots/`） |

**结果**：`cases=36 布局/请求问题=0 对比度不足=0`；36 张截图与 `sweep.json` 原始数据同目录留存。
修复前的同一轮巡检里，`settings / skills / knowledge / audit` 四页共 ≥19 个组合命中对比度不足，
`workbench` 与 `artifacts` 未触发（这两页小字密度低）。

---

## 4. 缺陷清单

| 编号 | 页面/组件 | 严重级 | 标题 | 期望 | 实际 | 状态 |
|---|---|---|---|---|---|---|
| D-01 | 设置 · 可用模型与 Key 状态 | P2 | 每个供应商都挂「首选」徽标 | 只标本机正在用的那一个 | 5 行全部显示「首选」（后端内置供应商 `priority` 全为 0，前端按 `priority === 0` 判断） | **已修** |
| D-02 | 工作台 · 空状态底部 | P1 | 真实模型下仍写「演示模式（不联网）…不会外发」 | 跟随实际引擎 | 文案硬编码；`real` 引擎下既说错引擎，也把「素材会发给模型」这件事说反了 | **已修** |
| D-03 | 工作台 · 输入区底部 | P1 | 同上，另一处硬编码「演示环境…不外发」 | 跟随实际引擎 | 同 D-02 | **已修** |
| D-04 | 全站小字（亮/暗） | P1（可访问性） | 11–13px 说明文字对比度不足 | ≥4.5:1 | 浅色 `muted` #64748b 在画布上 4.36、`faint` #94a3b8 只有 **2.35**；深色 `faint` 在悬停行 3.9；深色主按钮白字 4.33 | **已修** |
| D-05 | 桌面端窗口 | P1 | 桌面端与网页端不同步 | 同一份代码 | 本机服务进程是旧进程：`POST /api/v1/skills/draft` 返回 **405**、模型列表只有 4 个供应商（缺 WorkBuddy） | **已修** |

### 复现与修复

**D-01**：设置页 → 可用模型与 Key 状态 → 观察每行徽标。
修复：`ModelListCard` 新增 `activeProvider`（取 `settings.model_provider`），只给生效的那一行挂
**「当前使用」**；同时删掉每行重复的「选择」按钮（与左侧「模型供应商」下拉做同一件事），
卡片底部补一句「换主模型：在左边『模型供应商』里选，保存后生效」。
回归：`ModelListCard.test.tsx` 新增两条断言（无「选择」按钮、「当前使用」只有 1 个）。

**D-02 / D-03**：工作台空状态与输入区底部各有一句写死的话，涉及「素材会不会发出去」。
修复：`EmptyState` 增加必填 `mock` 属性、`Composer` 复用已有的 `isMock`；
`WorkbenchPage` 统一派生 `engineMock = (health.mode ?? (地址里的 mock=1)) === 'mock'` 传给两处。
真实模式文案：`真实模型：素材会发给模型解析，产物只写入本地目录`。
回归：`StreamComponents.test.tsx` 增加一条「切到真实模型后不得再出现演示模式」。

**D-04**：逐元素量对比度（把半透明层按 alpha 合成后再算比值）。
修复 `tokens.css`：
- 浅色 `--color-muted` `#64748b → #556377`（画布 5.60:1），`--color-faint` `#94a3b8 → #5c6a7d`（5.05:1，悬停行 4.68:1）；
- 深色 `--color-muted` `#9199a5 → #adb5c0`（最亮底 6.07:1），`--color-faint` `#737b88 → #9aa2ae`（4.87:1）；
- 深色主按钮 `--color-brand-solid` `#3a76e0 → #2f63c4`（白字 5.67:1），hover 同步压到 `#2a5cb8`。
复测：同一巡检脚本 36 用例 → 对比度不足 **0**；亮暗两套截图的层级仍分得开（`ink > ink-soft > muted > faint`）。

**D-05**：`curl http://127.0.0.1:8000/api/v1/models` 只返回 `deepseek/qwen/glm/openai`；
`POST /api/v1/skills/draft` 405。说明「桌面端装的窗口」连到的服务是上一轮的进程。
修复：重启服务（`scripts/launch.py --no-browser`），并补上「窗口自己跟新」的机制：
- `shared/lib/build-watch.ts`：首屏 3s 后与每次切回窗口时拉一次 `/index.html`（`cache: no-store`），
  比对入口脚本名（vite 内容哈希），变了就刷新一次（30s 闸门防循环）；
- `public/sw.js` 版本 `v2 → v3`，让装过的机器丢掉旧的 shell/manifest 缓存。
复测：`/api/v1/models` 已含 `workbuddy`，`/skills/draft` 返回 400（空入参校验，接口存在），
桌面端窗口切回来即为网页端同一份代码。

---

## 5. 本轮顺带确认的正常项

- 桌面端窗口（`window-controls-overlay` 模拟）三块面板贴顶、不与 — □ ✕ 重叠（e2e 已有断言）。
- 全站底色一致：`shell === canvas`，子页面顶栏与内容区同色，`theme-color`（meta + manifest）已同步。
- 6 个路由在 390px 下无页面级横向滚动（设置页的分区 pill 在 `overflow-x-auto` 容器内，属设计行为）。
- 36 次加载中控制台 error = 0、接口 4xx/5xx = 0。

---

## 6. 与 2000 用例计划的差距

| 计划大类 | 计划量 | 本轮实际 | 说明 |
|---|---|---|---|
| ① 页面视觉 | 800 | 36（脚本）+ 人工抽查 6 页 | 覆盖布局/溢出/对比度/暗色；未覆盖 hover/focus 动效逐项核对 |
| ② 用户功能 | 900 | 38（E2E 主链路） | 审批、上传、产物、审计、设置已有自动化；异常链路（超时/断网/连点）部分覆盖 |
| ③ 细节质量 | 300 | 7（对比度 + 文案 + 契约） | 读屏、触控热区 44px、输入框 16px 未测 |

**建议下一批**（按性价比排序）：
1. ③ 键盘可达与焦点环：全站 Tab 顺序 + `focus-visible` 可见性（脚本可自动遍历）；
2. ② 审批超时 180s、后端断开重连、连续发送三条的排队行为；
3. ① hover / 按下 / 动效时长与 `prefers-reduced-motion` 实测；
4. ③ 移动端触控热区（<44×44 的可点元素）与 iOS 输入框字号。

---

## 7. 如何复跑

```bash
# 后端门禁
cd backend && ../.venv/Scripts/python.exe -m pytest tests/unit tests/integration tests/contract -q

# 前端单测 / 端到端 / 构建
cd frontend && npm test
cd frontend && npx playwright test
cd frontend && npm run build

# 视觉巡检（需要 8000 端口的服务在跑；产物写到 docs/test-evidence-2026-10-28/）
cd frontend && node scripts/ui-sweep.cjs
```

证据目录：`docs/test-evidence-2026-10-28/`
- `sweep.json`：36 条用例的原始判定（溢出元素、对比度比值、控制台/网络报错）
- `shots/*.png`：36 张整页截图，文件名 = `路由-视口-主题`
