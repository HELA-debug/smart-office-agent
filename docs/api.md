# 接口契约（V2.1 / API v1）

> **本文件是前后端合同**（与 `contracts/openapi.v1.json` 快照、`/openapi.json` 自动生成一致）。
> 变更规则：**只允许追加**字段/接口；破坏性变更升 `/api/v2` 并补 ADR。已有字段名称、语义、类型不得修改。
>
> - 代码事实来源：`backend/app/api/v1/`（router 注册见 `router.py`）
> - 契约快照：`contracts/openapi.v1.json`（`scripts/export_openapi.py` 生成，CI diff 校验）
> - 事件协议：`docs/events.md`（v1.1）与 `contracts/events.v1.schema.json`

## 0. 通用约定

- **Base path**：`/api/v1`。旧的 `/api/*` 为兼容别名（响应头 `Deprecation: true`、`Link: </api/v1>; rel="successor-version"`），
  计划在 v0.3 移除；新代码一律用 `/api/v1`。
- **trace_id**：所有 JSON 响应顶层带 `trace_id`，且与响应头 `X-Trace-ID` 一致；便于日志检索。
- **时间**：ISO-8601 带时区（`Asia/Shanghai`），如 `2026-10-23T15:01:45+08:00`。
- **错误体**：`{"trace_id":"...","error":{"code":"...","message":"...","details":...}}`
  （错误码目录见 `backend/app/core/errors.py` 的 `ERROR_CODE_CATALOG`）。
- **分页**：`page`（≥1）、`page_size`（1–100）；列表响应含 `total/page/page_size`。
- **认证**：本版单用户，无鉴权；不要将服务暴露到公网。
- **OpenAPI**：`/openapi.json`、`/docs`（53 条路径 / 65 个操作）。

## 1. 接口清单（51 paths / 63 operations）

### 1.1 健康检查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 状态、版本、git_sha、模式（mock/real）、供应商/模型、降级标记、工具/子智能体/技能、引擎状态 |

`engine`（配置值：mock/real/deepagents）与 `engine_effective`（实际生效）可能不同：
无 Key / `MOCK_MODE=true` / 真实模型不可用时实际生效为 `mock`。

### 1.2 会话

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/threads` | 新建会话（`title` 可选）→ 201 |
| GET | `/threads` | 列表：`q` 标题/ID 搜索、分页、置顶优先 |
| GET | `/threads/{thread_id}` | 详情：会话字段 + `messages` + `artifacts` + `uploads`（本会话素材，供右栏「本次素材」直接读取） |
| PATCH | `/threads/{thread_id}` | 重命名（`title`）/ 置顶（`pinned`） |
| DELETE | `/threads/{thread_id}` | 软删（列表不再返回；再次 GET → 404） |
| POST | `/threads/bulk-delete` | 批量软删（左栏「批量清理」）：body `thread_ids` 1–200 个 → `{deleted}`；不存在/已删的 ID 忽略，重复调用幂等；空数组 → 400 |

### 1.3 素材上传

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/threads/{thread_id}/files` | 单文件字段 `file`；多文件字段 `files`（可重复）；→ 201 |
| GET | `/threads/{thread_id}/files` | 当前会话素材列表（含解析字数/预览） |
| DELETE | `/files/{file_id}` | 软删素材（移入 `data/trash`） |

- 支持格式：**`.docx .xlsx .pdf .txt`**（4 种；`.md` / `.csv` 已下线——普通用户用不到）。
- 校验：扩展名 + MIME + magic bytes 三重校验；文件名 sanitize；大小上限 `MAX_UPLOAD_MB`。
- 失败：`415 UNSUPPORTED_FILE_TYPE`（`details.reason ∈ unsupported_type | mime_mismatch | magic_mismatch`）、
  `422 FILE_PARSE_ERROR`、`413 PAYLOAD_TOO_LARGE`。

### 1.4 运行（含 SSE）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/threads/{thread_id}/runs/stream` | 发起任务，**SSE** 返回（见 `docs/events.md`）；body 可带 `mode: mock|real`、`output_format: docx|pdf|xlsx|txt`、`approval_mode: always_ask\|risky\|all_allow` |
| GET | `/runs` | 运行列表（`thread_id`、`status` 过滤 + 分页） |
| GET | `/threads/{thread_id}/runs` | 会话运行列表 |
| GET | `/runs/{run_id}` | 运行详情（status/mode/engine/provider/model/tokens/cost/耗时） |
| POST | `/runs/{run_id}/cancel` | 取消：中断生产并保证推送 `run.cancelled`；重复调用幂等（`idempotent=true`） |
| **POST** | **`/runs/{run_id}/retry`** | **重试：返回 SSE 流**（新 run；前端按 `run.started.run_id` 重新挂流） |
| GET | `/runs/{run_id}/events` | 事件回放 JSON（`after=<seq>` 只返回 `seq > after`） |
| GET | `/runs/{run_id}/events/stream` | 事件回放 **SSE**：支持 `Last-Event-ID` / `?after=` 断线续传 |

- 运行状态：`running | completed | rejected | failed | cancelled`。
- 断线续传：客户端重连带 `Last-Event-ID: <最后收到的 seq>`，服务端回放 `> seq` 的事件；
  事件 `id` 与 `run_events.seq` 一致（从 1 递增）。
- `run_id` 形如 `r_20261023_ccc2a2`；`run.completed` 后从 `GET /runs/{run_id}` 可查最终状态与用量。

### 1.5 审批

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/threads/{thread_id}/approvals/{approval_id}` | 提交决议：`decision ∈ approved | rejected`，`comment` 可选 |

- 审批挂起期间 SSE 连接保持打开；决议后同一流继续推送后续事件。
- 重复提交 / 已超时 → `409 APPROVAL_ALREADY_DECIDED`；审批不存在 → `404 NOT_FOUND`；
  `decision` 非法 → `400 BAD_REQUEST`。
- 超时（`APPROVAL_TIMEOUT_SECONDS`，默认 180s）→ `run.failed`，`error.code=APPROVAL_TIMEOUT`。
- 审批通道自身故障（落库/事件通道不可用）**不会**终止运行：该工具不执行，
  推一帧 `tool.finished(ok=false, output.reason="approval_unavailable",
  error.code=APPROVAL_UNAVAILABLE)`，运行照常 `run.completed`。问不出来 ≠ 默许。

### 1.6 产物中心

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/artifacts` | 跨会话产物列表：`thread_id` / `run_id` / `type` 过滤 + 分页。**只列 Agent 生成的产物**：上传素材（`type=upload`）默认被排除，要连素材一起看就带 `include_uploads=true`（或直接 `type=upload`） |
| GET | `/artifacts/{artifact_id}` | 元数据（含 `sha256`、`download_url`、`preview_url`） |
| GET | `/artifacts/{artifact_id}/download` | 下载文件（软删后 404）。默认 `Content-Disposition: attachment`；带 `?inline=1` 时改成 `inline`，供 PDF / HTML 预览 iframe 内嵌（不带会被浏览器当成附件直接落盘） |
| GET | `/artifacts/{artifact_id}/preview` | HTML 片段预览 |
| DELETE | `/artifacts/{artifact_id}` | 软删（文件移入 `data/trash`；下载/预览 404） |
| POST | `/artifacts/batch-delete` | 批量软删（body `{artifact_ids: []}`，单次上限 200；部分成功语义） |
| GET | `/artifacts/trash` | 回收站列表（已软删，按删除时间倒序，带 `deleted_at` / `restorable`）；同样默认不含上传素材，需要时带 `include_uploads=true` |
| POST | `/artifacts/{artifact_id}/restore` | 从回收站恢复（文件挪回原目录，记录恢复） |
| DELETE | `/artifacts/{artifact_id}/purge` | 彻底删除（清回收站文件 + 记录，不可恢复） |
| POST | `/artifacts/{artifact_id}/open` | 用系统默认程序打开产物（装了 WPS 即用 WPS） |
| POST | `/artifacts/{artifact_id}/regenerate` | 基于原 run 任务消息**重新生成（返回 SSE）**，产生新 run/新产物 |

回收站实现要点：

- 删除只把文件挪到 `data/trash/`，并在产物 `extra.trash` 里记下「原路径 → 回收站路径」，
  恢复时按这份映射挪回去；靠文件名猜是不可靠的（同名文件会冲突）。
- `restore` 会清空 `deleted_at` 与 `extra.trash`；`purge` 才会真正删文件 + 删记录。
- `open` 由服务端调用系统文件关联（Windows `os.startfile` / macOS `open` / Linux `xdg-open`），
  失败不抛 5xx，而是 `opened=false` + `error`，由界面提示。

- `type ∈ docx | pdf | txt | xlsx | upload`。
- 批量软删是**部分成功**语义：`{ "artifact_ids": ["a1","a2"] }` →
  `{ "requested": 2, "deleted": 1, "failed": [{"artifact_id":"a2","deleted":false,"message":"产物不存在：a2"}], "trashed": [...] }`。
  重复 ID 自动去重；`artifact_ids` 超过 200 条 → `400 BAD_REQUEST`。

### 1.7 设置中心（热更新）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/settings` | 当前生效值 + 来源（`db/env/default`）+ 环境变量提示 + 密钥**引用**（不返回明文） |
| PUT | `/settings` | 保存即热生效（无需重启）；未知字段/非法值 → 400 |

可写白名单：`approval_rules`、`mock_mode`、`model_provider`、`model_name`、`fallback_chain`、
`max_upload_mb`、`model_timeout_seconds`、`approval_timeout_seconds`、`feature_flags`。

### 1.7.1 本机存储目录

设置页要能真的「访问」存储路径（而不是只显示一行 `./data/uploads`），所以单开两个只读/无副作用接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/storage/paths` | 上传目录 / 产物目录的**绝对路径**、是否存在、文件数 |
| POST | `/storage/reveal` | 在系统文件管理器中打开目录（body `{"kind":"uploads"\|"artifacts"}`） |

- 只接受 `uploads` / `artifacts` 两个固定 kind，任意路径一律 400/422 —— 不做通用文件系统入口。
- 改目录写到 `data/storage-overrides.json`，不改 `.env`；新目录对之后写入的文件生效，
  已存在的文件不动（界面会明确告知这一点）。
- 目录不存在时 `reveal` 会先创建；唤起文件管理器失败不返回 5xx，而是 `opened=false` + `error` 原因，由界面提示。
- `GET /settings` 里的 `upload_dir` / `artifact_dir` 现在返回服务端解析后的绝对路径；
  `database_url` 仍然返回，但界面不再展示（对用户无意义）。

### 1.8 模型供应商

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/models` | 供应商列表（内置 + 自定义）；`api_key_ref` 只返回引用，如 `env:DEEPSEEK_API_KEY` |
| POST | `/models` | 新增/更新登记；`api_key_ref` **只允许 `env:NAME`**，禁止明文 Key |
| POST | `/models/{model_id}/test` | 真实探测（无 Key 立即返回 `ok=false`；失败原因脱敏，不泄露 Key） |

- 内置模型 id 形如 `env:deepseek` / `env:qwen` / `env:glm` / `env:openai` / `env:workbuddy`；
  自定义登记生成 `mc_xxxxxxxx`。
- 供应商默认 Base URL：DeepSeek `https://api.deepseek.com/v1`、
  千问 DashScope `https://dashscope.aliyuncs.com/compatible-mode/v1`、
  GLM `https://open.bigmodel.cn/api/paas/v4`（可被环境变量/设置覆盖）。
- **WorkBuddy 没有默认 Base URL**（接口地址按账号给）：`workbuddy` 行的 `base_url` 初始为空，
  必须先用 `POST /models` 填 `base_url`（或设置页「填接口」），此时 `configured` 才可能为 true。
  缺地址时 `/models/{id}/test` 返回 `ok=false` 并附「还没填接口地址」的原因，不抛 400。
- fallback 链：`MODEL_FALLBACK_CHAIN=deepseek,qwen,glm,mock`；`mock` 表示降级到 mock 引擎。

### 1.9 模板 / 技能 / 扩展点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/templates` | 模板列表（内置 weekly/meeting/summary + 自定义） |
| POST | `/templates` | 创建自定义模板（`sections: [{heading, source}]`） |
| DELETE | `/templates/{template_id}` | 删除自定义模板（内置不可删） |
| POST | `/templates/{template_id}/render?thread_id=` | 用模板同步生成 DOCX 产物 |
| GET | `/skills` | 已加载技能、启用状态、当前提示词长度；带 `title/category/icon/badge` 展示字段 |
| GET | `/skills/catalog` | 技能库：可一键添加的内置技能（`installed` 标记是否已添加），附 `categories` |
| POST | `/skills/catalog/{skill_id}/install` | 从技能库添加：复制目录到 `app/skills/` 并默认启用 → 201；不存在 → 404，已添加 → 409 |
| PATCH | `/skills/{skill_id}` | 启用/停用（立即影响运行时提示词） |
| POST | `/skills/draft` | 「让模型帮你写」：`{idea}` → 一份可直接导入的 SKILL.md（`markdown/name/title/description/triggers/model/source/note`）。不落盘；`source=local` 表示当时没有可用模型、返回的是本地骨架 |
| POST | `/skills/import` | 导入 SKILL.md（multipart 字段 `file`）→ 201；同名已存在 → 409 |
| DELETE | `/skills/{skill_id}` | 删除技能：文件挪进 `app/skills/.trash/`（可恢复），立即影响提示词 |
| GET | `/tools` | 工具注册表（含 JSON Schema 与 risk），当前 9 个：`doc.analyze_material`（low，只读脚本解析素材结构）、`file.list` / `file.read` / `file.search` / `todo.write` / `todo.list`（low）、`doc.generate_report` / `code.run_python` / `file.delete`（high，默认需审批） |
| GET | `/subagents` | 子智能体（1 实现 + 2 占位） |

### 1.10 审计与用量

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/threads/{thread_id}/audit` | 会话审计：runs / approvals / artifacts |
| GET | `/usage/summary` | 用量聚合：`range ∈ 7d|30d|today|all`，可选 `thread_id`；按日/供应商/模型。响应里 `calls` 是**运行内已记账**口径，`ledger` 是**全量调用账本**（含探测/标题/增强等 run 外调用与失败重试，`since` 给出账本完整起点）；两者并列，不合并 |
| GET | `/audit/export` | 审计导出：`format ∈ json|csv`，返回文件下载（CSV 带 BOM） |

### 1.11 意见反馈

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/feedback` | 提交意见反馈：写一条本机存档（`data/feedback/feedback.jsonl`），并返回邮件素材 `subject / body / mailto`。后端不发信——`mailto` 交给用户自己的邮件程序；`FEEDBACK_EMAIL` 未配置时 `target`/`mailto` 为空，前端退化成「复制内容」。正文超长（编码后 > 1900 字符）会收短并置 `truncated=true`，全文仍在存档里 |

## 2. 关键结构示例

### 2.1 健康检查

```json
{"trace_id":"tr_x","status":"ok","version":"0.2.0","git_sha":"b230706",
 "mode":"real","provider":"deepseek","model":"deepseek-chat","degraded":false,"mock":false,
 "tools":8,"subagents":3,"skills":["weekly-report"],"prompt_version":"1.3.0",
 "engines":["mock","real","deepagents"],"engine":"real","engine_effective":"real",
 "engine_supported":true,"approval_tools":["code.run_python","doc.generate_report","file.delete"]}
```

### 2.2 会话

```json
{"trace_id":"tr_x","thread_id":"th_001","title":"整理周报",
 "created_at":"2026-10-23T15:00:00+08:00","updated_at":"2026-10-23T15:00:00+08:00",
 "pinned":false,"message_count":4,"artifact_count":1}
```

详情额外带上三块数组（`messages` / `artifacts` / `uploads`）。`uploads` 是本次会话上传的素材，
字段与上传接口一致（少了二进制相关内容），右栏「本次素材」直接用它，不用再拼 `$ref`：

```json
{"uploads":[{"file_id":"art_upload_01","filename":"走观秋.docx","size":18234,"type":"docx","ext":"docx",
 "chars":246,"parsed":true,"text_preview":"秋日午后，我取完快递往回走……","created_at":"..."}]}
```

批量清理：`POST /threads/bulk-delete` 收 ID 集合，回真正删掉的条数（跨页选中也一次提交）：

```json
{"thread_ids":["th_001","th_002","th_003"]}
```
```json
{"trace_id":"tr_x","deleted":3}
```

### 2.3 上传（单文件兼容 v0.1；多文件多 `files` 列表）

```json
{"trace_id":"tr_x","file_id":"art_upload_01","artifact_id":"art_upload_01",
 "filename":"会议记录.docx","size":18234,"type":"docx","ext":"docx",
 "chars":860,"parsed":true,"text_preview":"本周……","files":[{...}]}
```

### 2.4 发起运行 / 断线续传

```json
{"message":"把这份材料整理成 600 字周报，发我邮箱草稿","mode":"real"}
```
```json
{"message":"...","output_format":"md"}
```

- `output_format`：产物格式。缺省时**与首个上传素材同格式**（如素材为 txt 则生成 txt），
  无素材时回落 `docx`；非法值返回 `400 BAD_REQUEST`。
```json
{"message":"...","run_id":"r_20261023_ccc2a2","mode":"real"}
```
带 `run_id` 时等价于回放该运行的事件（配合 `Last-Event-ID`/`after`），不产生新 run。

### 2.5 审批

```json
{"decision":"approved","comment":"可以"}
```
```json
{"trace_id":"tr_x","approval_id":"a_01","decision":"approved",
 "decided_at":"2026-10-23T15:01:00+08:00","resumed":true}
```

### 2.6 产物元数据

```json
{"trace_id":"tr_x","artifact_id":"art_01","type":"docx","filename":"会议记录_工作周报_2026-W43.docx",
 "size":18234,"sha256":"9f2c...","created_at":"...","thread_id":"th_001","run_id":"r_001",
 "download_url":"/api/v1/artifacts/art_01/download","preview_url":"/api/v1/artifacts/art_01/preview",
 "sources":["会议记录.docx"]}
```

- `filename`：`<素材名>_<产物类型>_<日期>`（类型 ∈ 文件摘要 / 工作周报 / 会议纪要），同名再排 `(2)(3)`。
  素材名放在最前面：右栏窄、文件名从尾部截断，能区分「是哪份材料出的稿」的部分必须落在前半段；
  素材名末尾的日期会去掉，截断时也不切出「（智慧能源」这种半截括号。
- `sources`：生成该产物的素材文件名，产物中心与会话详情的产物列表都会带上。

### 2.7 设置（来源 + 密钥引用）

```json
{"trace_id":"tr_x","approval_rules":["code.run_python","doc.generate_report","file.delete"],"mock_mode":false,
 "model_provider":"deepseek","model_name":"deepseek-chat",
 "fallback_chain":["deepseek","qwen","glm","mock"],
 "sources":{"model_provider":"env","approval_rules":"db"},
 "secrets":{"deepseek":{"configured":true,"ref":"env:DEEPSEEK_API_KEY"}},
 "feature_flags":{},"database_url":"sqlite:///data/app.db",
 "upload_dir":"D:/office-agent/data/uploads","artifact_dir":"D:/office-agent/data/artifacts"}
```

### 2.8 审计

```json
{"trace_id":"tr_x","thread_id":"th_001","runs":[
  {"run_id":"r_001","status":"completed","mode":"real","engine":"real",
   "provider":"deepseek","model":"deepseek-chat","tokens":14800,"cost_cny":0.036,
   "started_at":"...","finished_at":"...","elapsed_ms":41700,
   "approvals":[{"approval_id":"a_01","tool":"doc.generate_report","decision":"approved"}],
   "artifacts":[{"artifact_id":"art_01","type":"docx","filename":"会议记录_工作周报_2026-W43.docx"}]}]}
```

## 3. 错误码

| HTTP | code | 场景 |
|------|------|------|
| 400 | `BAD_REQUEST` | 参数缺失/格式错误（含设置未知字段、未知状态） |
| 404 | `NOT_FOUND` | thread / run / artifact / approval / template / model 不存在 |
| 409 | `CONFLICT` | 资源冲突（如模板 ID 重复） |
| 409 | `APPROVAL_ALREADY_DECIDED` | 审批已处理/已超时/已随运行取消 |
| 415 | `UNSUPPORTED_FILE_TYPE` | 上传扩展名 / MIME / magic bytes 校验失败 |
| 422 | `FILE_PARSE_ERROR` | 文件解析失败或内容为空 |
| 413 | `PAYLOAD_TOO_LARGE` | 超过 `MAX_UPLOAD_MB` |
| 429 | `MODEL_RATE_LIMIT` | 模型限流 |
| 504 | `MODEL_TIMEOUT` | 模型调用超时 |
| 504 | `APPROVAL_TIMEOUT` | 审批超时导致运行终止 |
| 500 | `TOOL_ERROR` | 工具执行失败（运行不中断） |
| 500 | `INTERNAL` | 未预期内部错误 |

> 错误码的单一事实来源：`backend/app/core/errors.py`（`ERROR_CODE_CATALOG` / `ErrorCode` / `_STATUS_BY_CODE`）。
> 新增错误码时同步本节与 `docs/events.md` 的 `run.failed.error.code`。

## 4. 前端状态机（与事件对应）

| 状态 | 进入条件 | 界面 | 离开条件 |
|------|----------|------|----------|
| `idle` | 新建/选中会话 | 空状态 + 输入可用 | 用户提交 |
| `streaming` | `run.started` | 主按钮变「排队」+ 独立「停止」，流式追加 | 终态事件 |
| `waiting_approval` | `approval.required` | 对话流内联审批卡（右栏只放产物），输入仍可用（发送即排队） | 审批决议 |
| `done` | `run.completed` | 产物卡 + 用量 | 用户继续输入 |
| `cancelling` | 用户点「停止」 | 停止按钮 loading | `run.cancelled` |
| `reconnecting` | SSE 断开且 run 未结束 | 「重连中」提示 | 携带 `Last-Event-ID` 续传成功 |
| `error` | `run.failed` / 超时 | 错误条 + 重试 | 重试或新建 |

### 4.1 任务队列（前端，纯本地状态）

- `streaming` / `waiting_approval` 期间输入框**不再禁用**：此时提交的消息进前端队列，
  显示在输入框上方的「N 条任务排队中」卡片里（可编辑回输入框、可删除，删除时其已上传素材一并软删）。
- 当前运行进入终态（`done` / `error` / `cancelled`）后，队列按 FIFO 自动取下一条发起运行，
  不需要用户再点发送；队列项记着入队时的 `thread_id`，只在该会话里执行。
- 用户点「停止」会把队列置为**暂停**（避免刚停就又自己跑起来），卡片上出现「继续执行」；
  再写一条新消息也会自动解除暂停。
- 队列只存在于内存：刷新页面即清空（已上传的素材是服务端资产，不受影响）。

## 5. 版本与兼容

- v1 接口只追加；`contracts/openapi.v1.json` 快照入库，CI `contract` 门禁要求 diff 为空。
- 旧 `/api/*` 别名保留一个迭代（响应头 Deprecation），v0.3 移除。
- 破坏性变更：新增 `/api/v2` 与 ADR，旧版保留一个迭代。
