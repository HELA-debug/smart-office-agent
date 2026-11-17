# ADR 0001：单容器 + 进程内 Agent 的最小架构

- 状态：已采纳（D1）
- 日期：2026-10-22
- 决策人：A（后端）/ C（交付基建）
- 影响面：部署、目录结构、后续拆分成本

## 背景

两周内要交付一个「端到端可跑、过程可见、可替换、可降级、可交接」的毛胚。可选路线有三条：

1. 前后端分离 + 独立 Agent 服务 + 消息队列（与 V1.0 终态一致，但部署面大）；
2. 单容器：FastAPI 同时提供 BFF 与进程内 Agent，SQLite + 本地目录；
3. Streamlit / Gradio 快速原型（省前端，但无法演示「审批卡 / 计划卡 / 工具卡」这一产品形态）。

## 决策

采用路线 2：**docker compose 起 web + api 两个服务，Agent 与 BFF 同进程，SQLite + 本地目录存储**。

具体约束：

- 目录边界即未来服务边界：`backend/tools`、`backend/connectors`、`backend/subagents`、`backend/store`；
  拆分时按目录整体搬走，接口不变。
- `backend/agent.py` 是唯一装配入口，接口层只调用 `run_stream(...)` 这类窄接口，不感知编排细节。
- 存储通过 `store/repo.py` 接口访问，业务代码不写 SQLite 专有 SQL；迁移脚本按 PostgreSQL 语法提供。
- 两条部署路径都保留：本地 uvicorn + Vite（开发快），docker compose（干净机器可复现）。

## 备选方案与不采用原因

| 方案 | 不采用原因 |
|------|------------|
| 独立 Agent 服务 + 队列 | 多一套部署单元与网络故障面，两周内收益为零；接口已按可拆分设计，V1.0 再拆 |
| Streamlit / Gradio | 演示不出计划卡、审批卡、产物卡与三区布局，等于放弃产品形态验证 |
| 只用 docker 开发 | 迭代慢（每次改代码重建镜像），本地热更新体验差 |

## 后果

正面：

- 一条 `docker compose up` 即可跑；无外部依赖也能 mock 演示。
- 拆分 Agent 服务时只改 `agent.py` 的调用方式与部署文件，不动业务代码。

负面/代价：

- 单进程无法水平扩展，长任务会占用 worker（写进 KNOWN_ISSUES）。
- SQLite 并发写弱，多实例共享不可用；换 PG 需改 DSN 并跑迁移。
- Agent 崩溃会连带 API 进程；无断点续跑（V1.0 启用检查点）。

## 验证方式

- `docker compose up --build -d` 后浏览 `http://127.0.0.1:8080`（见 DoD 第 1 条）。
- 本地 `uvicorn backend.main:app --port 8000` + `npm run dev` 可完整演示。
- 目录核对：`deploy/migrations/0001_init.sql` 为 PG 语法，SQLite 兼容由 repo 实现消化。
