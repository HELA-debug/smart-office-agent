# 事件协议 v1.2（SSE 流式事件契约）

> 本文件是前后端的**合同**。后端按此发送，前端按此渲染。
> 变更规则：**只允许追加**新事件类型或新字段；已有字段的名称、语义、类型不得修改。
> 前端遇到未知事件类型必须忽略，不得报错。
>
> - 代码事实来源：`backend/app/core/events.py`（`EVENT_NAMES` / `REQUIRED_FIELDS` / `EVENT_VERSION`）
> - 机器可校验 Schema：`contracts/events.v1.schema.json`（由 `scripts/export_openapi.py` 生成）
> - 事件持久化：`run_events` 表；`id`（帧序号）= `run_events.seq`

## 1. 传输格式

```
id: 12
event: tool.finished
data: {"version":1,"run_id":"r_20261023_ccc2a2","tool":"file.read", ...}

```

- 每帧固定：`id: <seq>` / `event: <事件名>` / `data: <单行 JSON>` / 空行。
- `id` 从 1 递增，与 `run_events.seq` 一致；**断线续传靠它**。
- **所有** `data` 必须包含 `version`（当前固定 `1`）与 `run_id`；
  另含 `trace_id`（请求追踪，可选但当前均带）。
- 连接在 `run.completed` / `run.failed` / `run.cancelled` 后关闭。
- **心跳**：审批等待期间每 15s 发一帧 SSE **注释** `: ping`（非事件帧，不占 `seq`），
  防止反代/浏览器断开长连接。v1.1 保留 `heartbeat` 事件名作为未来可选事件，当前不发送事件帧。
- 事件 JSON 的单行格式：`ensure_ascii=False`、紧凑分隔符（`{"version":1,...}`）。

### 1.1 断线续传（v1.1 新增能力）

- SSE 主链路：`POST /api/v1/threads/{thread_id}/runs/stream`
  - 原始请求体 `{message}` 发起新 run；
  - 断线后带 `{"run_id": "r_xxx"}` 重新 POST（或访问 `/runs/{run_id}/events/stream`），
    并带 `Last-Event-ID: <seq>` 或 `?after=<seq>`，服务端回放 `> seq` 的事件。
- JSON 回放：`GET /api/v1/runs/{run_id}/events?after=<seq>`。
- 30 秒内重连不丢事件（事件先落库再推送）。

## 2. 事件清单（v1.3 = v1 的 6 类 + 2 类文本流 + 3 类 v1.1 追加 + 2 类 v1.2 追加 + v1.3 可选字段）

| # | 事件 | 触发时机 | 前端用途 | 版本 |
|---|------|----------|----------|------|
| 1 | `run.started` | 运行开始 | 切到 `streaming` | v1 |
| 2 | `message.delta` | 助手文本增量 | 追加渲染流式文本（首字 ≤ 3s） | v1（追加于 v1.0 实现） |
| 3 | `message.completed` | 助手单条消息结束 | 固定气泡，结束打字态 | v1（同上） |
| 4 | `plan.updated` | 计划新增/变更 | 渲染/更新计划卡 | v1 |
| 5 | `tool.started` | 工具调用开始（真实引擎） | 工具卡进入 running | **v1.1 追加** |
| 6 | `tool.finished` | 工具调用结束（成功或失败） | 追加/更新工具卡 | v1 |
| 7 | `approval.required` | 高风险动作执行前 | 弹出审批卡并阻塞 | v1 |
| 8 | `artifact.ready` | 产物登记完成 | 右栏出现产物卡 | v1 |
| 9 | `run.completed` | 运行正常结束（含审批拒绝） | 收尾、显示用量 | v1（v1.1 追加字段） |
| 10 | `run.failed` | 运行异常结束 | 错误条 + 重试 | v1 |
| 11 | `run.cancelled` | 用户取消 / 服务端终止 | 显示已取消 | **v1.1 追加** |
| 12 | `heartbeat` | 预留（当前用 SSE 注释帧） | 保活 | **v1.1 预留** |
| 13 | `thinking.delta` | 决策行增量（判断 / 等你回话 / 出错） | 对话里一行淡字（v1.5） | **v1.2 追加** |
| 14 | `thinking.completed` | 一句决策话结束 | 同样只占一行，不再折叠成摘要 | **v1.2 追加** |

`tool.started` / `run.cancelled` / `heartbeat` 是 v1.1 追加，不修改上述 6 类事件的任何语义；
`thinking.delta` / `thinking.completed` 是 v1.2 追加，语义独立于 `message.*`（思考不等于回答），
旧前端忽略即可照常工作。v1 前端遇到未知事件类型必须忽略。

## 3. 各事件 data 结构

### 3.1 run.started

```json
{"version":1,"run_id":"r_20261023_ccc2a2","trace_id":"tr_x","thread_id":"th_001",
 "mode":"real","model":"deepseek-chat","engine":"real","provider":"deepseek",
 "started_at":"2026-10-23T15:00:00+08:00","degraded":false}
```

- `mode ∈ mock | real`；mock 引擎不发送 `provider`（v1 字段集），真实引擎追加 `engine/provider`。
- `degraded=true` 表示真实模型不可用、本次降级（前端顶部提示「演示模式」）。

### 3.2 message.delta

```json
{"version":1,"run_id":"r_x","message_id":"m_open","delta":"我先读取你上传的素材，","index":0,"channel":"process"}
```

- `index` 从 0 递增，前端按 `message_id` 聚合。
- `channel`（v1.3 追加，可选，缺省 `reply`）：
  - `reply` = 对话里的**正式回复**，渲染成助手气泡；
  - `process` = **中间旁白**（「我先读素材…」这类），前端收进「执行过程」折叠条，
    不单独起气泡、也不落 messages 表——一次运行常有几段旁白，每段都带一遍
    「Office Agent + 时间」抬头，一屏下来正文就没了。
  - 旧前端忽略该字段，按普通消息渲染（向后兼容）。

### 3.3 message.completed

```json
{"version":1,"run_id":"r_x","message_id":"m_open","content":"我先读取你上传的素材，然后按周报模板成文。","channel":"process"}
```

### 3.4 plan.updated

```json
{"version":1,"run_id":"r_x","todos":[
  {"id":"t1","content":"读取上传材料","status":"completed"},
  {"id":"t2","content":"提炼周报要点","status":"in_progress"},
  {"id":"t3","content":"生成 DOCX 周报","status":"pending"},
  {"id":"t4","content":"发送邮件草稿（需审批）","status":"pending"}
]}
```

- `status ∈ pending | in_progress | completed | cancelled`
- 每次推送**完整** todos 列表（前端整体替换，不做增量 diff）。

### 3.5 tool.started（v1.1 追加）

```json
{"version":1,"run_id":"r_x","trace_id":"tr_x","tool":"file.read","risk":"low",
 "input":{"files":["会议记录.docx"]},"step":1}
```

- 真实引擎（ReAct）在每次工具调用前发送；mock 引擎不发送（仍只发 `tool.finished`）。
- `step` 为本次运行内的工具调用步序（从 1 开始）。

### 3.6 tool.finished

```json
{"version":1,"run_id":"r_x","tool":"file.read","ok":true,"risk":"low",
 "summary":"已读取 2 个文件，共 1,240 字","duration_ms":180,
 "input":{"files":["会议记录.docx"]},
 "output":{"files":[{"filename":"会议记录.docx","chars":860}],"chars":1240},
 "artifact_id":null}
```

- 工具失败时 `ok=false` 并带 `error:{"code":"TOOL_ERROR","message":"..."}`；**运行不中断**。
- 敏感字段（密钥、密码等）由后端 `sanitize()` 脱敏后才写入 `input/output`；邮箱允许展示。
- `doc.generate_report` 成功时 `output.artifact_id` 为登记到产物表中的 ID；拒绝审批时 `output.skipped=true` 且不产生新文件。
- 三类"没执行"的 `output.reason`，语义不同，前端文案不要混用：

  | `output.reason` | 含义 | `error.code` |
  |---|---|---|
  | `not_authorized` | 写权限门控拦下（他还在商量 / 说了先别 / 说了算了），`output.gate` 给具体原因 | 无（`ok=false`） |
  | `approval_rejected` | 用户点了"拒绝" | `TOOL_ERROR` |
  | `approval_unavailable` | 审批通道自己坏了（库断了、事件丢了），**运行继续** | `APPROVAL_UNAVAILABLE` |

### 3.7 approval.required

```json
{"version":1,"run_id":"r_x","approval_id":"a_01","tool":"doc.generate_report","risk":"high",
 "message":"即将发送邮件，请确认（mock 模式不会真实外发）",
 "preview":{"to":"me@example.com","subject":"本周周报（2026-W43）",
  "title":"本周工作周报（2026-W43）","format":"DOCX","impact":"将生成文件并写入产物目录"}}
```

- 此事件之后运行**暂停**，直到审批决议提交或超时（`APPROVAL_TIMEOUT_SECONDS`，默认 180s）。
- 超时 → `run.failed`，`error.code="APPROVAL_TIMEOUT"`（HTTP 层对应 504 语义）。
- 钉住时序见第 4 节；审批期间 SSE 连接保持打开并每 15s 发 `: ping` 注释帧。

### 3.8 artifact.ready

```json
{"version":1,"run_id":"r_x","artifact_id":"art_01","type":"docx",
 "filename":"周报_会议记录_2026-W43.docx","size":18234,
 "download_url":"/api/v1/artifacts/art_01/download",
 "preview_url":"/api/v1/artifacts/art_01/preview",
 "sources":["会议记录.docx"]}
```

- `type ∈ docx | pdf | txt | xlsx | upload`
- `preview_url` 返回 HTML 片段（DOCX 渲染为只读 HTML），供右栏预览。
- `filename` 带素材名（`周报_会议记录_2026-W43.docx`），同名再加 `(2)(3)`：同一天出多份产物时，
  右栏不用点开就能分清哪份对哪份。
- `sources`（可选）是生成该产物的素材文件名，右栏 hover 提示用它说明「这份从哪来」。

### 3.9 run.completed

**v1 字段（不变）**：

```json
{"version":1,"run_id":"r_x","status":"completed",
 "tokens":8123,"cost_cny":0.06,"elapsed_ms":41700,
 "artifact_ids":["art_01"],
 "approvals":[{"approval_id":"a_01","tool":"doc.generate_report","decision":"approved"}],
 "degraded":false}
```

**v1.1 追加字段（只加不改；真实引擎均带，mock 引擎带 `engine/model/usage`）**：

```json
{"engine":"real","model":"deepseek-chat","provider":"deepseek",
 "stop_reason":"completed",
 "fallback_actions":["deepseek:retry_once","qwen:circuit_open"],
 "usage":{"provider":"deepseek","model":"deepseek-chat",
   "input_tokens":12000,"output_tokens":2800,"total_tokens":14800,"cost_cny":0.036}}
```

- `status ∈ completed | rejected`（审批被拒时 `status="rejected"`，运行正常结束，产物保留）。
- `stop_reason ∈ completed | max_steps | token_budget | degraded | cancelled | awaiting_user` 等（真实引擎；
  达到步数上限/Token 预算时终止并在 `message.completed` 说明）。
- `awaiting_user`：这一轮没有动手，只问了一句。出现在意图理解判定「缺关键信息且没把握」时——
  猜错要白干一轮还附赠一份没人要的文件，问一句只要半句话。此时不产生 `tool.*` 与 `artifact.*`。
- `fallback_actions`：本次运行发生的降级/重试动作（脱敏，便于审计）。
- `usage`：输入/输出 tokens 分开；mock 引擎给估算值，真实引擎来自供应商返回。

### 3.10 run.failed

```json
{"version":1,"run_id":"r_x",
 "error":{"code":"MODEL_TIMEOUT","message":"模型调用超时，已切换演示模式","retryable":true},
 "degraded":true,"elapsed_ms":2805}
```

- `error.code ∈ MODEL_TIMEOUT | MODEL_RATE_LIMIT | TOOL_ERROR | FILE_PARSE_ERROR | APPROVAL_TIMEOUT | INTERNAL`。
- 前端在错误条上展示 `message`，保留已生成内容，提供「重试」（`POST /runs/{id}/retry`，返回 SSE）。

### 3.11 run.cancelled（v1.1 追加）

```json
{"version":1,"run_id":"r_x","reason":"cancelled_by_user","degraded":false}
```

- 由 `POST /api/v1/runs/{run_id}/cancel` 触发；该帧落库后关闭 SSE 流。
- 重复取消幂等：HTTP 200 + `{cancelled:false,status:"cancelled",idempotent:true}`，不再补发事件。

### 3.12 heartbeat（v1.1 预留）

- 当前保活使用 SSE 注释帧：`: ping`（约每 15s，审批等待期间）。
- 未来如需要应用层心跳事件，将发送 `event: heartbeat` + `data: {"version":1,"run_id":...}`；
  前端 `switch` 的 `default` 分支已能忽略未知事件，兼容无成本。

### 3.13 thinking.delta / thinking.completed（v1.2 追加，v1.5 语义收窄）

```json
{"version":1,"run_id":"r_x","message_id":"m_think1","delta":"两份表头口径对不上，","index":0,"kind":"ask"}
{"version":1,"run_id":"r_x","message_id":"m_think1","content":"两份表头口径对不上，先按哪份算？","elapsed_ms":120,"kind":"ask"}
```

- `kind`（v1.5 追加，可选）：这一行的场合。
  - `decision`：它在两个方向之间做了选择；
  - `ask`：它停下来等用户回话；
  - `error`：某一步没成，得换个做法。
  缺省按 `decision` 处理，旧前端忽略该字段即可。
- 语义（v1.5 起）：**决策点的一句话**，不是每轮开工的推演。只在三种时候出现：
  判断、等你回话、某步出错；一轮通常 0～2 条，且长度不超过 64 字。
  没有决策就一条都不发——静静地干活比先念一遍流程更像人。
- 渲染：前端把它当一行淡字摊在对话里（出错时告警色），不再做成「正在思考」面板，
  也不再显示「已思考 1.8 秒」。`elapsed_ms` 保留但界面不再使用。
- 顺序：在其后的 `message.delta` / `tool.started` 之前；同一 run 的多条按 `message_id` 区分。
- 兼容：未知该事件的旧前端忽略即可，不阻塞主链路。

## 4. 事件顺序（主链路）

```
run.started
  -> message.delta* -> message.completed            # 开场说明（channel=process，进「执行过程」）
  -> plan.updated
  -> tool.started* / tool.finished(file.list)
  -> plan.updated
  -> tool.finished(file.read)
  -> plan.updated
  -> tool.finished(doc.generate_report)
  -> artifact.ready
  -> plan.updated
  -> approval.required                              # 挂起；15s 注释心跳
      批准 -> tool.finished(doc.generate_report, ok=true)
      拒绝 -> tool.finished(doc.generate_report, ok=false, output.skipped=true)
      通道故障 -> tool.finished(..., error.code=APPROVAL_UNAVAILABLE) + 继续
      超时 -> run.failed(APPROVAL_TIMEOUT)
  -> plan.updated
  -> message.delta* -> message.completed            # 结论（channel=reply，唯一的助手气泡）
  -> run.completed(status=completed|rejected)
```

- `thinking.delta* -> thinking.completed` **不是固定环节**：只在它要定方向、要问你、或某步没成时
  插在对应位置（v1.5）。上面这条主链没有决策，就一条都不发。

- 取消可在任意执行阶段发生：`run.cancelled` 为终态（之后不再有 `run.completed`）。
- 审批拒绝是**正常结束**：发 `run.completed(status=rejected)`，不发 `run.failed`。

## 5. 审批交互时序

```
frontend                                  backend
   |  POST /v1/threads/{tid}/runs/stream -> |
   | <---- run.started / message.delta ...  |
   | <---- approval.required (运行挂起)      |
   | <---- : ping (每 15s 心跳，保持连接)     |
   |  POST /v1/threads/{tid}/approvals/{aid} -> |  (解除挂起)
   | <---- tool.finished(doc.generate_report) |
   | <---- run.completed                     |
```

## 6. 版本兼容

- 前端匿名解析 JSON，只依赖本文档列出的字段；未知字段忽略、未知事件忽略。
- 新增字段：直接加（v1.1 的 `run.completed` 追加字段即此方式）。
- 新增事件：在本文档追加一节 + `contracts/events.v1.schema.json` 更新 + 前端 `types/events.ts` 追加类型。
- 破坏性变更：升 `version` 为 2，同时保留 v1 端点一个迭代，并补 ADR。
