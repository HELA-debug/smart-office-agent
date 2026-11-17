# 技术文档集（office-agent-mvp V2.1）

> 面向**维护者与二次开发者**的完整技术文档。事实来源以代码为准，每篇都标注了源码路径。
> 想快速跑起来请先读根 [README.md](../../README.md)；本文是"读代码 + 改代码 + 上线"的那一层。

## 阅读路径

| 你想干什么 | 从这里开始 |
|---|---|
| 第一次接手，想知道这项目是什么、能做什么 | [01-overview](01-overview.md) → [02-architecture](02-architecture.md) |
| 改后端某个接口 / 加一个 service | [04-backend-api](04-backend-api.md) → [05-backend-services](05-backend-services.md) |
| 改模型接入、成本、降级 | [06-agents-tools-skills](06-agents-tools-skills.md) → [14-security-cost](14-security-cost.md) |
| 加工具 / 子智能体 / 技能 | [06-agents-tools-skills](06-agents-tools-skills.md) |
| 改表结构 / 目录布局 | [07-data-storage](07-data-storage.md) |
| 改 SSE 事件、前端流式渲染 | [08-events-sse](08-events-sse.md) → [09-frontend](09-frontend.md) |
| 上线 / 打包 / 排障 | [10-configuration](10-configuration.md) → [11-deployment-packaging](11-deployment-packaging.md) → [15-troubleshooting](15-troubleshooting.md) |

## 目录

| 编号 | 文档 | 内容 |
|---|---|---|
| 01 | [项目概述](01-overview.md) | 定位、能力矩阵、版本与成熟度、术语表、非目标 |
| 02 | [总体架构](02-architecture.md) | 分层与依赖方向、组合根、中间件栈、一次请求的完整生命周期、四种部署形态、ADR 摘要 |
| 03 | [后端 core 层](03-backend-core.md) | config / errors / events / logging / paths / security / net_guard / pricing / static_site / utils |
| 04 | [后端 API 层](04-backend-api.md) | 鉴权中间件、容器依赖注入、72 个端点全清单、schema 与错误体 |
| 05 | [后端 services 层](05-backend-services.md) | 19 个 service 逐个说明，含配置生效机制、运行时事件落库、用量计算 |
| 06 | [引擎 · 模型 · 工具](06-agents-tools-skills.md) | 引擎协议、mock/real 引擎、ModelRouter、Provider 适配器、6 类工具、子智能体、技能与提示词包 |
| 07 | [数据与存储](07-data-storage.md) | 8 张表结构、Alembic 迁移、仓库层、SQLite 连接参数、磁盘目录布局、回收站语义 |
| 08 | [事件与 SSE](08-events-sse.md) | 事件契约 v1.4、15 类事件、落库与广播、断线续传、心跳与审批挂起 |
| 09 | [前端](09-frontend.md) | 工程配置、分层与边界、feature 清单、状态机、渲染链路、主题令牌、测试 |
| 10 | [配置参考](10-configuration.md) | 全部环境变量、DB 覆盖优先级、目录覆盖、机密处理 |
| 11 | [部署与打包](11-deployment-packaging.md) | Docker Compose、Nginx/SSE、PyInstaller exe、桌面分发、单端口模式、备份 |
| 12 | [开发工作流](12-development.md) | 常用命令、Makefile target、分支与提交规范、代码风格与架构边界、契约更新流程 |
| 13 | [测试与质量门禁](13-testing-quality.md) | 四层测试、契约快照门禁、CI 六门禁、覆盖率阈值、本地钩子 |
| 14 | [安全与成本](14-security-cost.md) | 上传防护、SSRF、沙箱、审批、机密处理、成本计价口径与对账 |
| 15 | [故障排查](15-troubleshooting.md) | 按现象索引的排查手册（引擎不匹配、费用对不上、探针失败等真实案例） |

## 与其他文档的关系

| 文档 | 定位 | 与本文区别 |
|---|---|---|
| 根 `README.md` | 用户/上手视角：怎么跑起来、怎么配置模型 | 本文不重复操作手册，只讲实现 |
| `docs/api.md` | API v1 契约正文（"合同"） | 本文 04 篇是端点清单与实现说明，字段级契约以 `docs/api.md` + `contracts/` 为准 |
| `docs/events.md` | 事件协议正文 | 本文 08 篇补充落库/广播/续传的**实现机制** |
| `docs/adr/` | 架构决策记录 0001–0005 | 本文 02 篇给出摘要与现状，决策理由看 ADR |
| `docs/acceptance.md` | DoD 30 条验收清单 | 验收口径，非实现细节 |
| `KNOWN_ISSUES.md` | 已知问题与绕过方式 | 本文 15 篇给排查动作 |

## 维护约定

1. **事实优先**：文档与代码冲突时以代码为准，并顺手改文档。每篇顶部标注"事实来源"路径。
2. **只追加**：接口与事件字段只增不改（契约规则见 `contracts/README.md`）。
3. **改代码就改文档**：改了端点、事件、表结构、环境变量，必须同 PR 更新本文对应章节。
4. **不写散文**：能用表格就不用段落，能用清单就不用长句。
