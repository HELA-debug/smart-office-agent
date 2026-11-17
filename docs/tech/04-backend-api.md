# 04 · 后端 API 层

> 事实来源：`backend/app/api/`。字段级契约以 [`docs/api.md`](../api.md) 与 `contracts/openapi.v1.json` 为准，本文讲端点清单与实现要点。

## 4.1 依赖注入

`api/deps.py` 只有一个容器依赖：

```python
@dataclass
class AppContainer:  # 15 个槽位
    settings, runtime, threads, artifacts, approvals, runs, settings_service,
    usage, models, templates, skills, projects, prompt_packs, feedback, database

ContainerDep = Annotated[AppContainer, Depends(get_container)]
```

- **没有 `get_db`**：SQL 访问全部经 service 的 `session_scope` 短事务，api 层不碰 ORM。
- **没有 `current_user`**：单用户，鉴权在中间件层。

## 4.2 鉴权中间件（`api/auth.py`）

| 行为 | 说明 |
|---|---|
| 形态 | 纯 ASGI 中间件（**不是** `BaseHTTPMiddleware`），避免缓冲 SSE 流 |
| 开关 | `API_TOKEN` 为空 → 构造时就不生效，零开销透传 |
| 请求头 | `X-API-Token` |
| 免鉴权路径 | `/`、`/api/v1/health`、`/api/health` |
| 比较方式 | `hmac.compare_digest` 常量时间 |
| 预检 | `OPTIONS` 直接放行；非 http/websocket 协议透传 |
| 失败响应 | 统一错误体 401 `UNAUTHORIZED` |

## 4.3 路由聚合（`api/v1/router.py`）

17 个子路由按序 include：

```text
health → threads → files → runs → approvals → artifacts → settings → models
→ templates → skills → projects → storage → desktop → extensions → usage → feedback → prompts
```

挂载（`main.py`）：

| 前缀 | 说明 |
|---|---|
| `/api/v1` | 正式版本 |
| `/api` | 兼容别名，`include_in_schema=False`，响应带 `Deprecation: true` + `Link: </api/v1>; rel="successor-version"` |
| `/api/v1/openapi.json` | 前端 `gen:api` 用的版本化快照，只含 `/api/v1` 路由 |

## 4.4 端点全清单（72 个）

### health（1）

| 方法 路径 | 作用 |
|---|---|
| `GET /health` | 版本 / 模式 / 降级状态 / 引擎状态 / 扩展点摘要 |

`_engine_state()` 同时返回：

| 字段 | 含义 |
|---|---|
| `engine` | 配置值（用户选的） |
| `engine_effective` | 实际生效值 |
| `engine_reason` | 不一致时的人话原因：选的是演示模式 / `MOCK_MODE=true` 还开着 / 没配 Key / 缺 base_url / 探测失败 |
| `git_sha` / `git_sha_live` | 进程启动版本 vs 仓库当前 HEAD。**不一致说明后端进程比代码旧** |

### threads（7）

| 方法 路径 | 作用 |
|---|---|
| `POST /threads` | 新建会话（title 可选）→ 201 |
| `GET /threads` | 列表：搜索 `q`（标题或 ID）+ 分页，置顶优先 |
| `GET /threads/{tid}` | 详情：字段 + `messages` + `artifacts` + `uploads` |
| `PATCH /threads/{tid}` | 重命名 / 置顶 |
| `DELETE /threads/{tid}` | 软删 → 204 |
| `POST /threads/reorder` | 拖动排序（按传入顺序重写 `sort_index`） |
| `POST /threads/bulk-delete` | 批量软删（空或 >200 → 400） |

### files（3）

| 方法 路径 | 作用 |
|---|---|
| `POST /threads/{tid}/files` | 上传 → 201；单文件字段 `file`、多文件字段 `files` |
| `GET /threads/{tid}/files` | 会话素材列表 |
| `DELETE /files/{file_id}` | 软删素材（入回收站） |

### runs（8）

| 方法 路径 | 作用 |
|---|---|
| `POST /threads/{tid}/runs/stream` | **发起任务（SSE）**；body 带 `run_id` 时走续传 |
| `GET /runs` | 运行列表（可按 `thread_id`/`status` 过滤 + 分页） |
| `GET /threads/{tid}/runs` | 会话运行列表 |
| `GET /runs/{run_id}` | 运行详情 |
| `POST /runs/{run_id}/cancel` | 取消（**幂等**，非 running 返回 `idempotent=True`） |
| `POST /runs/{run_id}/retry` | 重试（同会话同消息新建 run，返回 SSE） |
| `GET /runs/{run_id}/events` | 事件回放（JSON，`after` 只回 `seq > after`） |
| `GET /runs/{run_id}/events/stream` | 事件回放（SSE，支持 `Last-Event-ID` / `?after=`） |

SSE 响应头：`Cache-Control: no-cache, no-transform`、`Connection: keep-alive`、`X-Accel-Buffering: no`、`X-Trace-ID`。

`RunRequestIn` 字段：`message`、`mode`、`output_format`（docx/pdf/xlsx/pptx/txt）、`run_id`（续传）、`project_id`、`project_files`、`approval_mode`、`attachment_ids`。

### approvals（1）

| 方法 路径 | 作用 |
|---|---|
| `POST /threads/{tid}/approvals/{approval_id}` | 提交决议（`approved`/`rejected` + 备注）→ 唤醒挂起的运行 |

### artifacts（11）

| 方法 路径 | 作用 |
|---|---|
| `GET /artifacts` | 产物列表（分页 + 筛选，**默认排除 `type=upload`**） |
| `GET /artifacts/trash` | 回收站列表 |
| `POST /artifacts/{aid}/restore` | 恢复 |
| `DELETE /artifacts/{aid}/purge` | 彻底删除（不可恢复） |
| `POST /artifacts/{aid}/open` | 系统默认程序打开 |
| `POST /artifacts/batch-delete` | 批量软删（**部分成功**语义，返回 requested/deleted/failed/trashed） |
| `GET /artifacts/{aid}` | 元数据（隐藏内部路径，出 `has_preview_file` 等布尔） |
| `GET /artifacts/{aid}/download` | 下载；`?inline=1` 浏览器内联 |
| `GET /artifacts/{aid}/preview` | HTML 片段预览 |
| `DELETE /artifacts/{aid}` | 软删（入 `data/trash`） |
| `POST /artifacts/{aid}/regenerate` | 基于原 run 的任务消息重生成 → **返回 SSE 流** |

### settings（2）

| 方法 路径 | 作用 |
|---|---|
| `GET /settings` | 生效值 + **来源 db/env/default** + 密钥引用 |
| `PUT /settings` | 更新并**热生效**（只取 `model_dump()` 中非 `None` 的键） |

### models（5）

| 方法 路径 | 作用 |
|---|---|
| `GET /models` | 供应商列表（**不含明文 Key**，只回 `env:NAME` 引用与探测状态） |
| `POST /models` | 新增/更新登记 → 201 |
| `PUT /models/{mid}/key` | 保存 Key（明文只落本地 `.env`，响应只回掩码） |
| `GET /models/{mid}/balance` | 账户余额（目前仅 DeepSeek 有 `/user/balance`） |
| `POST /models/{mid}/test` | 真实探测（失败返回脱敏原因，不抛 400） |

### templates（4）

| 方法 路径 | 作用 |
|---|---|
| `GET /templates` | 内置 + 自定义模板 |
| `POST /templates` | 新增自定义模板 → 201（存 settings 表，镜像 `data/templates.json`） |
| `DELETE /templates/{tid}` | 删除 → **204 无响应体**（内置不可删） |
| `POST /templates/{tid}/render` | 按模板同步生成 DOCX |

### skills（8）

| 方法 路径 | 作用 |
|---|---|
| `GET /skills` | 已安装技能 + 启用状态 + `prompt_chars` |
| `GET /skills/catalog` | 技能库（**未安装的不进提示词**） |
| `POST /skills/catalog/{sid}/install` | 从技能库安装 → 201 |
| `PATCH /skills/{sid}` | 启停（**立即影响运行时提示词**） |
| `POST /skills/draft` | 让模型写一张技能便签（无模型时返回本地骨架） |
| `POST /skills/import` | 上传 SKILL.md 导入 → 201 |
| `DELETE /skills/{sid}` | 删除（挪进 `app/skills/.trash`，可人工捞回） |
| `GET /prompt-packs` | 内置提示词包（`max_per_run: 2`） |

### projects（6）

| 方法 路径 | 作用 |
|---|---|
| `GET /projects` | 项目列表（含文件数/最近修改/`missing`） |
| `POST /projects` | 把本机文件夹登记为项目 → 201 |
| `PATCH /projects/{pid}` | 重命名 / 置顶 |
| `DELETE /projects/{pid}` | 移除登记（**不删文件**） |
| `GET /projects/{pid}/files` | 项目内文档列表（按修改时间倒序，`q` 过滤） |
| `POST /projects/{pid}/reveal` | 文件管理器打开 |

### storage（5）

| 方法 路径 | 作用 |
|---|---|
| `GET /storage/browse` | 浏览本机文件夹（**只列子目录**，上限 300 条） |
| `POST /storage/browse/mkdir` | 新建文件夹（失败返回 `ok=false` + 原因，不抛 500） |
| `GET /storage/paths` | 上传/产物目录绝对路径、是否存在、文件数 |
| `POST /storage/reveal` | 文件管理器打开（**只接受 uploads/artifacts 两个固定 kind**） |
| `PUT /storage/paths` | 改存储目录（传空 = 恢复默认，落 `storage-overrides.json`） |

跨系统打开文件管理器：Win → `os.startfile`；macOS → `open`；Linux → `xdg-open`。**只接受服务端自己记录的路径，不接受前端传任意路径**。

### desktop（4）

| 方法 路径 | 作用 |
|---|---|
| `GET /desktop/package` | 安装包可交付状态 + 上次保存位置 |
| `POST /desktop/package/download` | 复制到本机下载目录 |
| `POST /desktop/package/reveal` | 文件管理器定位 |
| `POST /desktop/package/open` | 打开 / 重新安装 |

安全边界：`reveal`/`open` 只认 `data/desktop_package.json` 里记录的路径；状态文件先写 `.json.tmp` 再 `os.replace`。

### extensions（2）

| 方法 路径 | 作用 |
|---|---|
| `GET /tools` | 已注册工具（含 JSON Schema） |
| `GET /subagents` | 已注册子智能体（1 实现 + 2 占位） |

### usage（3）

| 方法 路径 | 作用 |
|---|---|
| `GET /threads/{tid}/audit` | 会话审计 |
| `GET /usage/summary` | 用量汇总（`range` ∈ `7d`/`30d`/`today`/`all`） |
| `GET /audit/export` | 审计导出（`format` ∈ `json`/`csv`，流式响应） |

### feedback（1）

| 方法 路径 | 作用 |
|---|---|
| `POST /feedback` | 本机存档 `data/feedback/feedback.jsonl` + 生成 mailto 链接（**不发任何网络请求**） |

### prompts（1）

| 方法 路径 | 作用 |
|---|---|
| `POST /prompts/enhance` | 提示词增强；无模型时退本地规则版 |

## 4.5 schemas 与通用约定

- `api/v1/schemas.py` 共 **83 个** pydantic 模型，全部带 `ConfigDict(extra=...)`。
- 通用约定（与 `docs/api.md` 一致）：

| 约定 | 内容 |
|---|---|
| Base path | `/api/v1` |
| trace_id | 响应顶层 + 响应头 `X-Trace-ID` |
| 时间 | ISO-8601 带时区（Asia/Shanghai） |
| 错误体 | `{"trace_id","error":{"code","message","details"}}` |
| 分页 | `page` ≥1、`page_size` 1–100；响应含 `total/page/page_size` |
| 认证 | 可选单 Token（见 4.2） |

## 4.6 常见 400/409 场景速查

| 场景 | 错误码 |
|---|---|
| `after` 不是整数 | `BAD_REQUEST` |
| 上传类型不合法 / 伪造签名 | `UNSUPPORTED_FILE_TYPE`（415） |
| 上传内容解析失败 / 空文件 | `FILE_PARSE_ERROR`（422） |
| 超大小 | `PAYLOAD_TOO_LARGE`（413） |
| 重复提交审批决议 | `APPROVAL_ALREADY_DECIDED`（409） |
| 审批超时 | `APPROVAL_TIMEOUT`（504） |
| 附件不属于该会话 | `BAD_REQUEST`（不启动时就拦，别让模型空跑一轮） |
| 技能同名 / 模板 ID 与内置冲突 | `CONFLICT`（409） |
