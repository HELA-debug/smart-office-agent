# 03 · 后端 core 层

> 事实来源：`backend/app/core/*.py`。环境变量的运维视角见 [10 篇](10-configuration.md)。

## 3.1 config.py — 配置唯一来源

`Settings(BaseSettings)`（pydantic-settings）是配置的**结构定义**，`.env` 位置为 `DATA_ROOT/.env`。

### 生效优先级（容易搞反，重点）

```text
DB settings 表  >  进程环境 / .env  >  字段默认值
```

- `config.py:3` 说的"env 优先级"只描述 **pydantic 字段解析**：进程 env > `.env` > 默认值。
- 运行期还有 `SettingsService` 叠的一层 DB 覆盖，它**盖在 env 之上**（`settings_service.py:3`、`:91-98`）。
- 也就是说：设置中心里改过的值，重启 `.env` 也改不回来。
- 密钥类字段只从环境读，**不落 DB**（DB 里存 `env:DEEPSEEK_API_KEY` 引用）。

### 字段全表

| 分类 | 字段 | 默认值 | 行号 |
|---|---|---|---|
| 应用 | `app_name` / `version` / `environment` / `log_level` / `log_format` / `git_sha` | `office-agent-backend` / `0.2.0` / `dev` / `INFO` / `json` / `""` | `:52-60` |
| 引擎 | `engine` | `real`（`mock`\|`real`\|`deepagents`） | `:63` |
| 模型 | `model_provider` / `model_name` / `model_fallback_chain` | `mock` / `mock-scripted` / `mock` | `:64-66` |
| 模型 | `mock_mode` / `mock_model_speed` | `True` / `0.05` | `:67-68` |
| 模型 | `model_timeout_seconds` / `model_max_steps` / `model_max_tokens` | `30.0` / `8` / `2000` | `:69-71` |
| 模型 | `model_temperature` / `model_token_budget` | `0.3` / `200_000` | `:73-74` |
| 上下文 | `context_max_turns` / `context_max_chars` / `context_max_turn_chars` / `context_summary_chars` | `8` / `6000` / `1200` / `800` | `:78-83` |
| 凭据 | `deepseek_api_key` / `qwen_api_key` / `dashscope_api_key` / `glm_api_key` / `openai_api_key` / `workbuddy_api_key` | 全为 `""` | `:85-92` |
| 端点 | `openai_base_url` / `deepseek_base_url` / `qwen_base_url` / `glm_base_url` / `workbuddy_base_url` | 全为 `""` | `:94-99` |
| 代理 | `https_proxy` / `http_proxy` | `""` | `:102-103` |
| 存储 | `database_url` / `auto_migrate` | `sqlite:///data/app.db` / `True` | `:106-107` |
| 存储 | `upload_dir` / `artifact_dir` / `trash_dir` / `templates_file` | `./data/uploads` 等 | `:108-111` |
| 存储 | `feedback_dir` / `feedback_email` | `./data/feedback` / `""` | `:114-115` |
| 单端口 | `serve_frontend` / `frontend_dist` | `False` / `""` | `:121-122` |
| 审批 | `approval_rules` / `approval_timeout_seconds` | `code.run_python,file.delete` / `180` | `:127-128` |
| HTTP | `allowed_origins` / `max_upload_mb` | 两个 localhost / `20` | `:131-132` |
| HTTP | `api_token` | `""`（留空 = 关闭鉴权） | `:134` |
| 解析防护 | `max_uncompressed_mb` / `max_archive_entries` / `max_pdf_pages` / `max_parsed_chars` | `256` / `2000` / `500` / `1_000_000` | `:136-139` |
| 出网防护 | `model_base_url_allowlist` | `""`（留空 = 只拦内网段） | `:142` |

`PROVIDER_DEFAULTS`（`:33-39`）：deepseek/qwen/glm/openai 都有官方默认端点；**workbuddy 故意留空**，必须由用户填，否则 `configured=False` 直接被路由跳过。

### 派生属性（常用）

| 成员 | 作用 | 行号 |
|---|---|---|
| `approval_tools` / `cors_origins` / `fallback_chain` | 字符串 → 集合/列表，空则回落安全值 | `:151` / `:155` / `:160` |
| `resolve_path` / `resolve_data_path` | 相对路径分别按 `RESOURCE_ROOT` / `DATA_ROOT` 解析 | `:164` / `:169` |
| `storage_overrides()` / `set_storage_dir()` | 目录覆盖读写（`data/storage-overrides.json`） | `:182` / `:194` |
| `provider_base_url(p)` / `provider_api_key(p)` / `model_for_provider(p)` | 供应商三件套 | `:259` / `:273` / `:287` |
| `engine_kind` / `configured_provider` | 归一化，非法值按 `real` / 空按 `mock` | `:291` / `:297` |
| `real_model_configured` | `not mock_mode and provider != "mock" and 有 Key and 有 base_url` | `:302` |
| `mode` / `is_prod` / `is_auth_enabled` | `real`\|`mock` / 环境判定 / `bool(api_token)` | `:312` / `:316` / `:320` |
| `ensure_dirs()` | 建 uploads/artifacts/trash + sqlite 父目录 | `:331` |
| `persist_secret(env, val)` | 落盘 `.env`，`chmod 0o600` | `:371` |
| `redacted()` | 脱敏快照（供日志与健康检查） | `:400` |
| `get_settings()` | `@lru_cache(maxsize=1)` 单例 | `:412` |

## 3.2 errors.py — 统一错误体

错误体格式（所有 4xx/5xx 一致）：

```json
{ "trace_id": "tr_xxx", "error": { "code": "BAD_REQUEST", "message": "...", "details": {} } }
```

| 项 | 内容 | 行号 |
|---|---|---|
| 错误码目录 | 13 个：`BAD_REQUEST` `NOT_FOUND` `CONFLICT` `APPROVAL_ALREADY_DECIDED` `UNSUPPORTED_FILE_TYPE` `FILE_PARSE_ERROR` `PAYLOAD_TOO_LARGE` `MODEL_TIMEOUT` `MODEL_RATE_LIMIT` `TOOL_ERROR` `APPROVAL_TIMEOUT` `UNAUTHORIZED` `INTERNAL` | `:22-52` |
| HTTP 映射 | 401/404/409/409(审批已决)/413/415/422/429/500/504 | `:55-69` |
| `AppError(code, message, *, status_code, details)` | 业务异常基类 | `:86` |
| `_jsonable()` | 把 `bytes`/异常实例转可序列化，**避免 400 变 500** | `:116` |
| `register_exception_handlers(app)` | 4 个 handler：`AppError` / HTTPException / 校验错误（只回前 3 条）/ 兜底 | `:135` |

## 3.3 events.py — 事件契约 v1.4

| 项 | 内容 | 行号 |
|---|---|---|
| `EVENT_VERSION` | `1` | `:16` |
| 15 个事件常量 | `run.started` `message.delta` `message.completed` `thinking.delta` `thinking.completed` `plan.updated` `tool.started` `tool.finished` `approval.required` `artifact.ready` `run.completed` `run.failed` `run.cancelled` `heartbeat` `context.compacted` | `:18-33` |
| `TERMINAL_EVENTS` | `{run.completed, run.failed, run.cancelled}` | `:53` |
| `REQUIRED_FIELDS` | 每个事件 data 的必填字段（如 `tool.finished → tool, ok, risk, summary, duration_ms, input, output`） | `:56-86` |
| `EVENT_JSON_SCHEMA` | 契约测试用，只校验 `version`/`run_id` | `:89` |
| `build_event(run_id, event, **data)` | 构造事件体，禁止覆盖 `version`/`run_id` | `:103` |
| `validate_event_data(event, data)` | 返回缺失字段列表 | `:110` |
| `sse_frame(seq, event, data)` | 输出 `id/event/data` + 空行 | `:123` |
| `sse_comment(text="ping")` | 心跳注释帧（不落库） | `:129` |
| `parse_last_event_id(value)` | 解析续传游标 | `:133` |

## 3.4 logging.py — 结构化日志

| 成员 | 作用 | 行号 |
|---|---|---|
| `TZ` | 固定 UTC+8（日志时间不随服务器时区漂移） | `:12` |
| `trace_id_var` / `run_id_var` | `contextvars`，请求与运行两级上下文 | `:14-15` |
| `setup_logging(level, fmt)` | JSON / text 两种格式；把 `httpx`/`httpcore`/`uvicorn.access`/`sqlalchemy.engine` 降到 WARNING | `:65` |
| `bind_log_context(trace_id, run_id)` | 返回两个 Token，供 `finally` 复位 | `:76` |
| `reset_log_context(tokens)` | 跨 Context 收尾兜底，防上下文泄漏 | `:81` |

日志里可直接检索的字段：`trace_id`、`run_id`、`event`。模型调用会打 `event="model_call"`，没有回执 id 时打 `event="model_call_unverified"`。

## 3.5 paths.py — 只读资源根 vs 可写数据根

PyInstaller onefile 下这两件事必须分开，否则用户数据会被塞进只读的临时目录。

| 成员 | 作用 |
|---|---|
| `is_frozen()` | 全项目唯一的形态判断入口（`getattr(sys, "frozen", False)`）。`IS_FROZEN` 是它导入时的快照，仅为兼容旧引用保留，别拿它判路径 |
| `_source_root()` / `_bundle_root()` | 源码态取仓库根；打包态取 `sys._MEIPASS`（cx_Freeze 没有这个属性，退回仓库根） |
| `_user_data_dir()` | Win → `%LOCALAPPDATA%\Office Agent`；macOS → `~/Library/Application Support/Office Agent`；Linux → `$XDG_DATA_HOME/office-agent` |
| `RESOURCE_ROOT` / `DATA_ROOT` | 前者只读（代码/提示词/技能/迁移），后者可写（数据库/上传/产物/.env）；都在导入时定死，要重算请调 `resource_root()` / `data_root()` |
| `APP_NAME` | 不只是产品名，也是数据目录名；改名必须同时做旧目录迁移 |
| `OA_DATA_DIR` 环境变量 | 可显式指定数据目录，源码态与打包态都生效 |

行号不写进表：注释一加就漂，照着旧行号找代码反而容易看错。

## 3.6 security.py — 上传与脱敏

| 成员 | 作用 | 行号 |
|---|---|---|
| `SUPPORTED_UPLOAD_EXTS` | `{.docx, .txt, .pdf, .xlsx}` | `:15` |
| `UploadValidationError(msg, *, reason)` | 带原因码，便于前端给具体提示 | `:37` |
| `validate_upload(...)` | 三重校验：扩展名 → MIME → 内容签名 | `:46` |
| `UploadLimits` | 5 个阈值 + `max_compression_ratio=200` | `:85` |
| `check_zip_bomb(data)` | 解压前估算，挡压缩炸弹 | `:104` |
| `_validate_ooxml` / `_validate_pdf` / `_validate_text` | docx 含 `word/`、xlsx 含 `xl/`；PDF 估页数；文本尝试 utf-8-sig/utf-8/gb18030 | `:141` / `:158` / `:179` |
| `sanitize(value)` | 按敏感键名递归打码，超 2000 字截断 | `:203` |
| `safe_filename(name)` | 保留中文，限 120 字符 | `:223` |
| `ensure_within(path, root)` | 路径穿越防护 | `:230` |
| `masked_secret(s)` | `sk-****abcd` | `:243` |

## 3.7 net_guard.py — 出网 SSRF 防护

模型 `base_url` 会把 Key 带出去，所以出网前必须校验（`_assert_base_url_allowed()`，providers/base.py:254）。

| 成员 | 作用 | 行号 |
|---|---|---|
| `_BLOCKED_NETWORKS` | 16 个网段，含 `169.254.0.0/16`（云元数据）、`100.64.0.0/10`（CGNAT）、`::ffff:0:0/96` | `:22-39` |
| `validate_outbound_url(url, *, allowlist)` | 只许 http/https；先 DNS 解析再逐 IP 判段；失败原因 `host_not_allowed` / `local_address` / `dns_failed` | `:84` |

配合 `MODEL_BASE_URL_ALLOWLIST`：留空时只拦内网段；填了就**只放行白名单域名**。

## 3.8 pricing.py — 成本计价

| 成员 | 作用 | 行号 |
|---|---|---|
| `PRICE_TABLE_PATH` | `backend/config/model_prices.yaml` | `:27` |
| `load_price_table(path)` | **按 mtime 缓存**：改 yaml 不用重启 | `:62` |
| `is_peak(at, table)` | 默认工作日 `09:00-12:00`、`14:00-18:00` | `:119` |
| `price_for(provider, model, *, at, table)` | 返回 `PriceSet(cache_hit, cache_miss, output, peak, hit_known)` | `:147` |
| `cost_for(..., cache_hit_tokens, cache_miss_tokens, output_tokens, at)` | 算钱（元，保留 6 位） | `:190` |
| 兜底价 | `_FALLBACK_HIT=0.04 / MISS=2.0 / OUTPUT=8.0`——**按高峰全未命中估，宁高不低** | `:30-32` |

命中/未命中两档的来历（yaml 头部注释）：

> DeepSeek 控制台上"1.19 亿 tokens 只花 ¥5.86"看着像 ¥0.05/百万，其实是那批 token 绝大多数命中了上下文缓存（¥0.02–0.04/百万）。本应用每轮上下文都在变，基本是未命中（¥1–2/百万），两个平均价直接对比会差 50 倍。

## 3.9 static_site.py — 单端口托管

| 成员 | 作用 | 行号 |
|---|---|---|
| `_BACKEND_OWNED` | `api` / `docs` / `redoc` / `openapi.json` 四个前缀由后端独占，SPA 兜底不得吞掉 | `:23` |
| `ImmutableStaticFiles` | `/assets/*` 加 `Cache-Control: public, max-age=31536000, immutable` | `:30` |
| `mount_spa(app, dist)` | 注册 `GET /{spa_path:path}`：后端前缀 404 → dist 内文件直出 → 否则回落 `index.html`；带目录穿越防护 | `:58` |

## 3.10 utils.py — 时间/ID/文本

| 成员 | 作用 | 行号 |
|---|---|---|
| `new_id(prefix)` | `r` 前缀 → `r_YYYYMMDD_hex6`；其他 → `{prefix}_hex10` | `:27` |
| `derive_thread_title(message, limit=24)` | 去客套前缀派生会话标题 | `:87` |
| `is_default_thread_title` | 判断标题是否还是自动生成的（决定是否可被模型改写） | `:66` |
| `read_build_info()` / `detect_git_sha()` | 打包态读 `build_info.json`，否则 `git rev-parse --short HEAD`（timeout=2） | `:103` / `:119` |
