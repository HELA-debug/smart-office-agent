# 08 · 事件与 SSE

> 事实来源：`backend/app/core/events.py`、`backend/app/services/run_service.py`、`frontend/src/shared/lib/sse.ts`、
> `frontend/src/shared/types/events.ts`。事件字段级契约以 [`docs/events.md`](../events.md) 为准。

## 8.1 事件清单（15 类）

| 事件 | 触发时机 | 关键 data 字段 |
|---|---|---|
| `run.started` | 运行开始 | provider / engine |
| `thinking.delta` | 思考流增量 | text |
| `thinking.completed` | 思考结束 | text |
| `message.delta` | 正文增量 | text / channel |
| `message.completed` | 正文完成 | text / channel |
| `plan.updated` | 计划推进 | todos |
| `tool.started` | 工具开始 | tool |
| `tool.finished` | 工具结束 | tool / ok / risk / summary / duration_ms / input / output |
| `approval.required` | **保留但不再发**：审批卡停了，常量与 reducer 分支留着不破契约 | approval_id / tool / preview |
| `artifact.ready` | 产物登记 | artifact 摘要 |
| `heartbeat` | 挂起期间心跳 | 无（SSE 注释帧，**不落库**） |
| `context.compacted` | 上下文被裁剪 | turns_total / kept_turns / dropped_turns / summary_chars |
| `run.completed` | 成功结束 | status / tokens / cost_cny / elapsed_ms / artifact_ids / approvals |
| `run.failed` | 失败结束 | error{code,message,retryable} |
| `run.cancelled` | 被取消 | reason |

终态事件：`run.completed` / `run.failed` / `run.cancelled`。

`REQUIRED_FIELDS`（`events.py:56-86`）定义了每类事件 data 的必填字段，`validate_event_data()` 会校验。

## 8.2 帧格式

```text
id: 12
event: tool.finished
data: {"version":1,"run_id":"r_20261031_ab12cd","tool":"doc.generate_report",...}

```

心跳帧（注释，不落库）：

```text
: ping

```

## 8.3 服务端：落库 → 广播 → 投递

```text
engine.run() 产出 EngineEvent
  ├─ comment（心跳）→ 直接入队，不落库
  └─ 正常事件
       seq += 1
       events.append(RunEventEntity)   ← 先落库（保证可重放）
       _publish(run_id, chunk)         ← 再广播给所有订阅者
       queue.put_nowait(chunk)         ← 再给当前连接
```

| 机制 | 说明 |
|---|---|
| 广播表 | `_broker: dict[run_id, set[Queue]]`；多订阅者（并发的续传连接）都能收到 |
| 队列满 | `QueueFull` 静默丢弃，不拖垮生产者 |
| 结束 | `_close_broker()` 向所有队列推 `None` 哨兵，各流自行收尾 |
| 取消 | 取消生产者任务 → 生产者落 `run.cancelled` → 队列收到哨兵结束流 |

## 8.4 断线续传

### 服务端 `resume()`（run_service:430-454）

```text
events.list_after(run_id, after) 回放历史帧
→ 若 run 仍是 running：_subscribe 订阅队列
→ asyncio.wait_for(queue.get(), timeout=15.0)
   超时 → yield 心跳 ": ping"
→ 跳过 seq <= last_seq 的重复帧
```

游标来源优先级（api/v1/runs.py:35）：`?after=` 参数 → `Last-Event-ID` 请求头。非法值 → 400。

### 三个入口

| 入口 | 用途 |
|---|---|
| `POST /api/v1/threads/{tid}/runs/stream` | 发起新运行；body 带 `run_id` 时走续传 |
| `GET /api/v1/runs/{rid}/events?after=` | JSON 回放 |
| `GET /api/v1/runs/{rid}/events/stream` | SSE 回放（带 `Last-Event-ID`） |

### 前端重连

```text
reconnect():
  最多 SSE_MAX_RECONNECTS = 3 次
  退避 SSE_RECONNECT_BASE_DELAY_MS * attempt = 800ms * n
  用 resumeRunEvents({runId, lastEventId})
  全部失败 → dispatch run/failed(RECONNECT_FAILED)
  流结束却没收到终态 → run/streamClosed → 状态转 error(STREAM_CLOSED)
```

## 8.5 前端消费链路

```text
shared/lib/sse.ts
  fetch + ReadableStream + TextDecoder（不用 EventSource，因为发起运行是 POST + JSON）
  → takeFrame()      按 \n\n / \r\n\r\n 切帧
  → parseSseFrame()  解析 id / event / data，忽略注释与未知字段
  → pumpStream()     每帧回调 onFrame；遇终态事件则 reader.cancel()

useWorkbench.applyFrame()
  → seq 去重（seq <= lastSeq 丢弃）
  → JSON.parse 失败忽略
  → parseRunEvent(name, payload)  校验 version===1 与 run_id
  → dispatch({type:'run/event', parsed, frameId, at})

workbench.ts reducer
  → applyRunEvent() 更新 timeline / plan / approvals / artifacts / usage / status
```

| 边界情况 | 处理 |
|---|---|
| 未知事件名 | 忽略（新后端推新事件不会让旧前端崩） |
| 重复帧（续传重放） | 按 seq 去重 |
| 畸形 JSON | 忽略该帧 |
| 长连接空闲 | 每 15s 心跳保活（`: ping` 注释帧，不落库） |
| 后台任务 | 切走会话时流不中断，仍继续计数与收尾 |

## 8.6 部署侧的 SSE 注意事项

Nginx 必须单独配置 SSE location（三条正则），且**必须写在 `location /api/` 之前**：

| 配置项 | 值 |
|---|---|
| `proxy_buffering` | off |
| `proxy_cache` | off |
| `proxy_request_buffering` | off |
| `gzip` | off |
| `chunked_transfer_encoding` | on |
| `proxy_read_timeout` / `proxy_send_timeout` | 360s |
| `X-Accel-Buffering` | no |

后端 SSE 响应头同样带 `X-Accel-Buffering: no`、`Cache-Control: no-cache, no-transform`。

Vite dev 代理也要配：`changeOrigin: true`、`timeout: 0`、`proxyTimeout: 0`、`headers: {'Accept-Encoding': 'identity'}`（SSE 长连接会长时间静默，禁止中间层压缩/缓冲）。

## 8.7 增加一个新事件的操作清单

1. `core/events.py`：加常量 → 加进 `EVENT_NAMES` → 补 `REQUIRED_FIELDS`（若属终态，加进 `TERMINAL_EVENTS`）。
2. 引擎里 `yield EngineEvent(event=..., data=...)`。
3. 前端 `shared/types/events.ts`：加 payload 接口 → 加进 `RUN_EVENT_NAMES` → 在 `run-events.ts` 的 `applyRunEvent` 里处理。
4. 跑 `python scripts/export_openapi.py` 更新 `contracts/events.v1.schema.json`（CI 会 diff）。
5. 更新 `docs/events.md`（只追加原则）。
