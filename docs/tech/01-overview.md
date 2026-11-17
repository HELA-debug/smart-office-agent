# 01 · 项目概述

## 1.1 它是什么

一个**单用户、桌面优先**的办公 Agent 工作台。链路是：

```text
上传素材 → 计划 → 工具调用 → 写盘前自检门控 → 产物文件（docx/pdf/xlsx/pptx/txt）→ 审计用量
```

三条硬约束贯穿全部设计：

| 约束 | 含义 |
|---|---|
| **契约先行** | OpenAPI 与事件 Schema 有入库快照，CI 做 diff；破坏性变更必须升版本并补 ADR |
| **无 Key 也能跑** | 默认演示模式，断网可完整演示；配了 Key 才走真实模型 |
| **动手前先自检** | 每一次会写盘的调用都先过门控（效果三档 + 档位放行线）；判不准就不做并说明，**不把用户拉进来点按钮** |

> 事实来源：`README.md`、`backend/app/main.py`、`docs/adr/`

## 1.2 能力矩阵

| 能力 | 状态 | 实现要点 |
|---|---|---|
| 会话管理 | 稳定 | 新建/搜索/分页/置顶/拖动排序/软删/批量清理（`threads.sort_index`） |
| 素材上传与解析 | 稳定 | 支持 `.docx/.txt/.pdf/.xlsx`；另外 `.md/.csv` 可解析但不作为上传白名单 |
| 任务运行（SSE） | 稳定 | `POST /api/v1/threads/{id}/runs/stream`，15 类事件流式推送 |
| 文档生成 | 稳定 | `doc.generate_report`，模板 `weekly`/`meeting`/`summary` + 自定义模板 |
| 代码执行 | 稳定（高风险） | `code.run_python` 受控子进程；效果由 AST 定档（读 / 写产物 / 动已有文件） |
| 写权限门控 | 稳定 | `policy.decide_write`：效果三档 × 信任档位调放行线；拦下就跳过并说明，不打断用户 |
| 产物管理 | 稳定 | 下载/预览/打开/软删/回收站/恢复/彻底删除/批量删除/重新生成 |
| 审计与用量 | 稳定 | 按官方分时价重算成本，支持 JSON/CSV 导出 |
| 模型路由 | 稳定 | 5 供应商 + fallback 链 + 重试 + 熔断 + 降级 |
| 技能（Skill） | 稳定 | `SKILL.md` 启停即时影响提示词，支持导入/技能库安装/让模型起草 |
| 项目文件夹 | 稳定 | 把本机目录登记为项目，扫描文档，按需求搬运成素材 |
| 技能插件（plugins） | 机制可用 | 通过 entry_points 组 `office_agent.plugins` 发现，当前无内置插件 |
| 子智能体 | 1 实现 + 2 占位 | `doc_agent` 可用；`research_agent`/`sheet_agent` 占位 |
| 桌面分发 | 稳定 | PyInstaller exe + PWA 两条路径 |

## 1.3 版本与成熟度

| 项 | 值 |
|---|---|
| 版本 | `v0.2.0`（V2.1 标准骨架） |
| 后端 | Python 3.13 / FastAPI / SQLAlchemy 2.0 / Alembic / pydantic-settings |
| 前端 | React 19 / TypeScript 5.9 / Vite 7 / Tailwind v4 / Vitest 5 / Playwright 1.64 |
| 契约 | OpenAPI 60 paths / 72 operations；事件契约 v1.4（schema 版本 1） |
| 测试 | 后端全绿 + 根级 30 条 smoke；前端 60 文件约 808 用例；E2E 39 用例 |
| 目标场景 | **本机自用 / 小团队内网**。不要直接暴露公网（无多用户、无强鉴权） |

## 1.4 术语表

文档与代码里反复出现的词，先对齐：

| 术语 | 含义 |
|---|---|
| **thread（会话）** | 一轮长期对话容器，含消息、素材、产物 |
| **run（运行）** | 一次"用户发一句话 → Agent 干完活"的执行单元，有 id、状态、事件流 |
| **engine（引擎）** | 执行 run 的策略：`mock`（本地脚本）/ `real`（真模型）/ `deepagents`（规划中） |
| **provider（供应商）** | 模型服务方：deepseek / qwen / glm / openai / workbuddy |
| **degraded** | 降级标记：本该用真模型但没能用上，实际跑的是 mock |
| **artifact（产物）** | Agent 生成的文件。`type=upload` 的"产物"是上传素材，默认不在产物列表出现 |
| **approval（审批）** | **已停用的一层**。事件常量 `approval.required`、`/approvals` 接口与 approvals 表都还在（契约不破），但引擎不再发：写盘由门控自己判，判不准就跳过并说明 |
| **seq** | 事件序号，run 内单调递增，是断线续传的游标 |
| **trace_id** | 一次 HTTP 请求贯穿日志与响应头的标识 |
| **prefix 稳定** | 提示词前缀刻意保持不变，以命中 DeepSeek 上下文缓存（见 06 篇） |

## 1.5 明确的非目标

避免后续误解，本项目**不做**：

- 多用户与权限体系（单用户桌面工具）
- 公网 SaaS 部署（鉴权只有可选的单 Token）
- 联网检索与长期记忆（仅 `research_agent` 占位）
- 真正的进程级沙箱（`code.run_python` 是受控子进程，**不是内核沙箱**，靠门控 + 环境变量白名单约束）
- 多语言（界面全中文硬编码，无 i18n 框架）

## 1.6 一页速览：改一个需求通常动哪里

| 需求 | 主要落点 |
|---|---|
| 加一个 HTTP 接口 | `backend/app/api/v1/<module>.py` → `router.py` → 契约快照 → 前端 `api.ts` |
| 加一个工具 | `backend/app/tools/builtin/<name>.py`，用 `@tool(...)` 注册 |
| 加一个供应商 | `backend/app/providers/registry.py` + `core/config.py` 的 Key/URL 字段 |
| 加一种产物格式 | `tools/builtin/doc.py` 的 `OUTPUT_FORMATS` + 三个 `*_utils.py` |
| 改成本算法 | `backend/config/model_prices.yaml`（改完不用重启） |
| 加一个页面 | `frontend/src/features/<x>/` + `app/router.tsx` |
