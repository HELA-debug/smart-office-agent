# 文档总索引

> 这个目录以前是「谁顺手写了什么就放这儿」，日期后缀、压缩包、快照报告混在一起，
> 谁也说不清哪份还在维护。现在按**用途**分七类，每份文件都有归属。
>
> 找入口请按下面的表读，不要靠文件名猜。

## 一、先记住一条规则：活文档 vs 快照

| 类型 | 特征 | 怎么对待 |
|---|---|---|
| **活文档** | 文件名**不带日期**（`api.md`、`events.md`、`release-checklist.md`、`tech/`） | 随代码一起改，过期就是 bug |
| **快照** | 文件名带**日期后缀**（`*-2026-10-28.md`、`test-evidence-*/`） | 当时的证据，**不要更新**；要新结论就新建一份 |

日期后缀的意义是「某一天截的图」，不是「版本号」。看到两份日期不同的同类报告，
新的那份才代表现状，旧的那份只能用来追溯。

## 二、按用途找文档

| 我要… | 读这份 | 说明 |
|---|---|---|
| 把项目跑起来 | 根 [README.md](../README.md) | 环境、命令、目录、常见坑 |
| 第一次接手，想知道这是什么 | [tech/01-overview](tech/01-overview.md) → [tech/02-architecture](tech/02-architecture.md) | 定位、能力矩阵、分层与依赖方向 |
| 改接口 / 加 service | [api.md](api.md) → [tech/04-backend-api](tech/04-backend-api.md) → [tech/05-backend-services](tech/05-backend-services.md) | 端点全清单与错误体 |
| 改 SSE 事件 / 前端流式渲染 | [events.md](events.md) → [tech/08-events-sse](tech/08-events-sse.md) → [tech/09-frontend](tech/09-frontend.md) | 事件契约**只追加**，改字段要同 PR 更新 `contracts/` |
| 改模型接入、成本、降级 | [tech/06-agents-tools-skills](tech/06-agents-tools-skills.md) → [tech/14-security-cost](tech/14-security-cost.md) | 含 fallback 链与 intent/reading/policy 三层 |
| 加工具 / 子智能体 / 技能 | [tech/06-agents-tools-skills](tech/06-agents-tools-skills.md) | 工具声明、风险等级、schema 裁剪 |
| 改表结构 / 存储布局 | [tech/07-data-storage](tech/07-data-storage.md) | SQLite WAL、软删、Alembic |
| 配置项是什么意思 | [tech/10-configuration](tech/10-configuration.md) | `.env` 全量对照 |
| 打包 / 部署 / 上线 | [tech/11-deployment-packaging](tech/11-deployment-packaging.md) → [release-checklist.md](release-checklist.md) | 上线前必须做、但现在不该动的项 |
| 出问题了怎么查 | [tech/15-troubleshooting](tech/15-troubleshooting.md) | 按现象索引 |
| 验收 / 演示 | [acceptance.md](acceptance.md) → [demo.md](demo.md) | DoD 30 条与 8 分钟脚本 |
| 某个设计为什么这么定 | [adr/](adr/)（0001–0005） | 决策记录，含被否掉的方案 |

## 三、目录清单

### 契约（改代码前必读，只追加不改写）

| 文件 | 内容 |
|---|---|
| [api.md](api.md) | API v1 契约：路径、请求/响应体、错误码；旧 `/api` 兼容层 |
| [events.md](events.md) | SSE 事件契约：12 类事件、时序、重放、thinking 的 kind 语义 |

配套：仓库根 `contracts/`（自动生成的 JSON 快照，CI 比对）、`deploy/migrations/`（DDL 基线）。

### 技术文档集 `tech/`（活文档，15 篇）

见 [tech/README.md](tech/README.md)：01 概述 · 02 架构 · 03 core · 04 API · 05 services ·
06 agents/tools/skills · 07 数据 · 08 事件 · 09 前端 · 10 配置 · 11 部署打包 ·
12 开发流程 · 13 测试质量 · 14 安全与成本 · 15 排障。

### 验收与演示（活文档）

| 文件 | 内容 |
|---|---|
| [acceptance.md](acceptance.md) | DoD 30 条逐条勾选 + 证据链接 |
| [demo.md](demo.md) | 8 分钟 Demo 脚本、备用台词、演示前检查清单 |

### 运行时知识库（活文档，被脚本与提示词引用）

这四份是**给模型和生成脚本看的**能力边界，不是给人读的教程。改脚本能力时必须同步改，
否则模型会照着旧文档去调不存在的参数。

| 文件 | 对应代码 |
|---|---|
| [docx-knowledge-base-2026-10-25.md](docx-knowledge-base-2026-10-25.md) | `backend/app/services/docx_utils.py` |
| [pdf-knowledge-base-2026-10-25.md](pdf-knowledge-base-2026-10-25.md) | `backend/app/services/pdf_utils.py` |
| [xlsx-knowledge-base-2026-10-25.md](xlsx-knowledge-base-2026-10-25.md) | `backend/app/services/xlsx_utils.py` |
| [txt-knowledge-base-2026-10-25.md](txt-knowledge-base-2026-10-25.md) | `backend/app/services/txt_utils.py` |

> 文件名里的日期是「首次成文日期」，但这四份属于活文档——代码变了它们就得变。

### 快照报告（一次性，不再更新）

| 文件 | 记录的是 |
|---|---|
| [test-report-2026-10-28.md](test-report-2026-10-28.md) | 当日后端测试矩阵结果 |
| [test-suite-report-2026-10-28.md](test-suite-report-2026-10-28.md) | 当日全量套件（前后端）结果与覆盖 |
| [test-evidence-2026-10-28/](test-evidence-2026-10-28/) | 同批截图与 `sweep.json` 原始数据 |

### 决策记录 `adr/`

| 编号 | 决策 |
|---|---|
| [0001](adr/0001-minimal-architecture.md) | 最小架构：单进程单体 + 分层，不拆微服务 |
| [0002](adr/0002-mock-first.md) | mock 优先：没有模型也能跑通全链路 |
| [0003](adr/0003-builtin-engine-vs-deepagents.md) | 自研引擎而不是接 deepagents |
| [0004](adr/0004-monorepo-layout.md) | 单仓前后端布局 |
| [0005](adr/0005-model-routing.md) | 模型路由与 fallback 链 |

### 发布

| 文件 | 内容 |
|---|---|
| [release-checklist.md](release-checklist.md) | 上线前清单，首条是 mock 下线（代码保留，只关开关） |

## 四、写文档的约定

1. **动的文件才带版本**：契约类只追加，改字段等于改接口，必须同 PR 更新 `contracts/`。
2. **别新建 `xxx-新.md`**：直接改原文件；要保留旧结论就写进 CHANGELOG，不要复制一份。
3. **快照报告一律带日期后缀**，并在文件名里写清「测的什么」，避免三个月后没人认得。
4. **不把压缩包放进 `docs/`**：`tech.zip` 这类由 `tech/` 现场打包的产物不进仓库（已清理）。
5. **文档里引用的路径必须可点**：写相对路径，别写本机绝对路径。
