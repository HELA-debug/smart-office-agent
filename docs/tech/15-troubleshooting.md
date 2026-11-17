# 15 · 故障排查

> 按**现象**索引。每条给：可能原因 → 排查动作 → 处理方式。

## 15.1 引擎类

### 顶栏显示"mock"徽标，设置页却显示"真实模型"

| 项 | 内容 |
|---|---|
| 原因 | `ENGINE=real` 与 `MOCK_MODE=true` 矛盾，且旧代码 `degraded=false` 不给原因，前端无从解释 |
| 排查 | `GET /api/v1/health` 看 `engine` / `engine_effective` / `engine_reason` / `degraded_reason` |
| 处理 | 设置页改**执行引擎**即可（引擎是权威值，会自动同步演示模式）；启动时 `apply_persisted()` 也会修好并写回 DB |
| 常见成因 | `.env` 里 `MOCK_MODE=true` 没改，或设置页只改了演示模式 |

### 以为在用真模型，其实全程 mock

| 项 | 内容 |
|---|---|
| 排查 | `GET /api/v1/health` → `degraded` 与 `degraded_reason`；再看 `git_sha` 与 `git_sha_live` 是否一致 |
| 原因 A | 探测判据太严：以前要求"正文非空"，而推理模型 `max_tokens` 小时正文就是空串 → 必然探测失败 → 静默降级 |
| 原因 B | 探测成功没复位 `degraded`，进程重启前一直跑 mock |
| 原因 C | 缺 Key 或缺 base_url（尤其 workbuddy 无公共默认端点） |
| 处理 | 现在的判据是"端点是否给出**合法回执**"（`allow_empty=True`）；失败原因由 `engine_reason` 明说：选的是演示模式 / `MOCK_MODE=true` / 没配 Key / 缺 base_url / 探测失败 |

### 模型名与回执对不上

| 项 | 内容 |
|---|---|
| 现象 | 配置写 `deepseek-chat`，回执返回 `deepseek-flash` |
| 说明 | `deepseek-chat` 是官方**旧别名**，会被静默路由并按 Flash 计费 |
| 处理 | 配置里直接填回执真名 `deepseek-flash`；账单按回执名归 |

## 15.2 成本类

### 算出来的钱和控制台差很多

按顺序自查：

1. **模型名**：控制台按回执名归账，用回执名筛选，不要用配置名。
2. **缓存分档**：本应用基本是未命中（¥1–2/百万），控制台展示的多是含命中的平均价（¥0.02–0.04/百万），直接对比会差 50 倍。
3. **命中率**：看 `run.extra["usage"]` 里的 `cache_hit_tokens` / `cache_miss_tokens`；命中率长期 0% 说明提示词前缀不稳定。
4. **改过价没有**：审计是按**现价**重算的，改了 `model_prices.yaml` 后历史值会跟着变。

### 控制台看不到当天的请求

| 检查项 | 动作 |
|---|---|
| Key 筛选 | 确认筛选用的是本应用实际用的那把 Key（可能同时配了多把） |
| 时间范围 | 选"今天"，注意控制台数据有约 5 分钟延迟 |
| 是否真调用了 | 看审计里的 `request_ids` / `verified_calls`；日志搜 `event="model_call"`，缺 id 会打 `model_call_unverified` |

### 单次成本突然变高

1. 是否落在高峰时段（工作日 09–12 / 14–18，单价 ×2）。
2. 缓存命中率是否掉了（提示词前缀被改动/上下文被裁剪）。
3. 是否触发了截断重试（日志 `event="model_truncated_retry"` / `model_empty_retry"`，会把预算放大到 6000–16000）。

## 15.3 产物与界面类

### 新产物要刷新页面才出现 / 产物仓库不刷新

| 项 | 内容 |
|---|---|
| 原因 | 产物变动没有广播出去，各页面各自持有旧数据 |
| 处理 | 删除/生成/恢复后会调 `notifyArtifactsChanged()`，工作台订阅到就 `loadSessions({silent:true})` |
| 自查 | 产物卡片数量是否随右侧仓库同步变化 |

### 产物数大于 1，但对话里铺了好几张

| 项 | 内容 |
|---|---|
| 原因 | 曾经按 `run_id` 分组，同一轮出的多份会一起铺开（「会议纪要 + 周报」、拼装版 + 错版同轮出） |
| 处理 | `ArtifactDelivery` 不再分组：只铺列表末位那一份，其余全部进「更早的产物」折叠区 |
| 判定 | 「最新」= 产物列表末位（后端 `created_at asc`，实时事件按发生顺序追加），**刷新后仍一致** |

### 上一轮的历史产物没有自动移入"更早的产物"折叠区

| 项 | 内容 |
|---|---|
| 原因 | 用"挂载时间"判断归属 |
| 处理 | 按产物列表顺序取末位当「最新」，**刷新后仍一致** |

### 卡片里多出四行说明文字

已移除。单价与查询时间都移进了 `title`（hover 可见），避免窄卡截断。

## 15.4 模型行为类

### 模型"说完就停"，没生成文件

| 项 | 内容 |
|---|---|
| 处理 | `_reliability_fallback()`：命中文档意图 + 无产物 + 有素材 → 补 `doc.generate_report` |
| 例外 | 若模型明确拒答（`MODEL_REFUSAL_MARKERS`），**不补**（结论说没产出、下面又冒出文件会自相矛盾） |
| 表现 | 收尾语会带上文件名（先补生成再说话），`stop_reason="fallback"` |

### 工具调用参数被截断

| 项 | 内容 |
|---|---|
| 原因 | 工具参数是一整段 JSON，2000 的输出预算常在参数中间被截断 |
| 处理 | 检测到 `finish_reason == "length"` 时自动把预算放大到 `min(max(3x, 6000), 16000)` 重试一次 |
| 日志 | `event="model_truncated_retry"` |
| 仍失败 | 抛 `BAD_FORMAT`，报错里带 `finish_reason` 与已放到多大的预算 |

### 返回正文是空的

| 项 | 内容 |
|---|---|
| 说明 | 推理模型先写 `reasoning_content`，`max_tokens` 太小时正文就是空串——**这不是故障** |
| 处理 | 业务调用会走放大重试；探测则用 `allow_empty=True` 只判"回执合法" |

### 思考过程永远只有那三步

| 项 | 内容 |
|---|---|
| 说明 | 真实引擎的思考是**模型现场写的推理**，不是写死模板（模板只在 mock 引擎里） |
| 呈现 | 设置 → 外观 → 思考过程：完全显示 / 只看主要步骤 / 不显示（`oa.thinking_view`） |

## 15.5 请求与连接类

### 审批一直转圈，最后超时

| 项 | 内容 |
|---|---|
| 时长 | `APPROVAL_TIMEOUT_SECONDS` 默认 180s |
| 保活 | 挂起期间每 15s 发心跳 |
| 结果 | 超时 → `run.failed(APPROVAL_TIMEOUT, retryable=True)` |
| 部署侧 | 检查 Nginx SSE location 是否配了 `proxy_read_timeout 360s`；Vite 代理是否配了 `timeout: 0` |

### SSE 断线后接不上

| 项 | 内容 |
|---|---|
| 机制 | 前端最多重连 3 次，退避 800ms × n，用 `Last-Event-ID` 续传 |
| 服务端 | 先回放 `seq > after` 的历史，再继续订阅；间隔 15s 发心跳 |
| 全部失败 | `RECONNECT_FAILED`；流结束却没收到终态 → `STREAM_CLOSED` |

### httpx 报 `InvalidURL: Invalid port: ':1]'`

| 项 | 内容 |
|---|---|
| 原因 | Windows 环境 `NO_PROXY` 里带方括号的 IPv6 项 |
| 处理 | 启动时 `sanitize_no_proxy_env()` 自动清理本进程的 `NO_PROXY`/`no_proxy`；Makefile 与 CI 也显式设 `NO_PROXY=localhost,127.0.0.1` |

### 后端进程比代码旧

`GET /api/v1/health` 里 `git_sha`（进程启动时）与 `git_sha_live`（仓库当前 HEAD）不一致 → 重启后端。前端侧有 StaleBuildBanner 提示。

## 15.6 部署与打包类

| 现象 | 排查与处理 |
|---|---|
| 页面白屏 / 接口 404 | 单端口模式检查 `SERVE_FRONTEND=1` 与 `FRONTEND_DIST`；`mount_spa` 必须挂在 `/api` 之后 |
| 上传被拒（413） | `MAX_UPLOAD_MB` 与 Nginx `client_max_body_size` 两边都要调，且保持一致 |
| SSE 被缓冲成一整块 | Nginx SSE location 是否排在 `location /api/` 之前；`X-Accel-Buffering: no`、`gzip off` |
| 打包后数据找不到 | 数据目录是 `%LOCALAPPDATA%\Office Agent`（可用 `OA_DATA_DIR` 指定）；用户数据本就不进 exe |
| 打包后启动时报缺模块 | 检查 `hiddenimports`（alembic、migrations 必须按 data 带） |
| 端口被占 | 启动脚本会 `--port` 自动往后找空闲端口 |
| 前端覆盖率虚低（如 20%） | 关掉并行：`vitest.config.ts` 里 `fileParallelism: false` 已处理 |

## 15.7 一般性排查顺序

1. `GET /api/v1/health`：引擎、降级原因、provider/model、git sha 是否一致。
2. 取响应头 `X-Trace-ID`（或响应体顶层 `trace_id`），在日志里搜它。
3. 看 `run.extra`：含 `usage`（tokens/缓存/request_id）、`degraded`、`artifact_ids`、`approvals`。
4. 前端 StaleBuildBanner / ServiceDownBanner 是否弹出。
5. 仍无解：用 `?mock=1` 跑一遍，确认是链路问题还是模型问题。
