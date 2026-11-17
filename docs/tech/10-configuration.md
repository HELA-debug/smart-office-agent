# 10 · 配置参考

> 事实来源：`.env.example`、`backend/app/core/config.py`、`backend/app/services/settings_service.py`

## 10.1 配置生效优先级

```text
DB settings 表  >  进程环境 / .env  >  字段默认值
```

后果与注意：

| 现象 | 原因 |
|---|---|
| 改了 `.env` 不生效 | 该键在设置中心保存过，DB 覆盖盖在上面 |
| 想让 `.env` 生效 | 去设置中心把该项改回，或直接改 DB `settings` 表 |
| 密钥改不动 | 密钥只从环境读，DB 里存的是 `env:NAME` 引用 |

`.env` 位置：`DATA_ROOT/.env`（源码态在仓库根，打包态在 `%LOCALAPPDATA%\Office Agent`）。变量名大小写不敏感。

## 10.2 环境变量全集

### 应用

| 变量 | 默认 | 说明 |
|---|---|---|
| `APP_ENV` | `dev` | `prod` 会关闭 `/docs`、`/redoc`、`/openapi.json` |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | 由 Dockerfile 启动命令读取，Settings 不读；本地直接跑 uvicorn 时用命令行参数 |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` | `json`（生产/CI，便于 trace_id 检索）/ `text`（本地） |

### 引擎与模型

| 变量 | 默认 | 说明 |
|---|---|---|
| `ENGINE` | `real` | `mock` / `real` / `deepagents`（规划中） |
| `MOCK_MODE` | `true` | `true` 时不调用任何外部模型 |
| `MODEL_PROVIDER` | `deepseek` | deepseek / qwen / glm / openai / workbuddy / mock |
| `MODEL_NAME` | `deepseek-chat` | 建议填回执真名 `deepseek-flash` |
| `MODEL_FALLBACK_CHAIN` | `deepseek,qwen,glm,mock` | 依次尝试 |
| `MODEL_TIMEOUT_SECONDS` | `60` | |
| `MODEL_MAX_STEPS` | `60` | 与硬上限 200 取小；只防死循环，不是「做到第几步就交差」 |
| `MODEL_MAX_TOKENS` | `0` | **0 = 不限制**（不带该字段，由模型按自身上限决定）；填正数才当硬顶 |
| `MODEL_TEMPERATURE` | `0.3` | |
| `MODEL_TOKEN_BUDGET` | `1000000` | 单次运行预算；只防跑飞（等于 deepseek 上下文上限） |
| `MOCK_MODEL_SPEED` | `0.05` | 演示模式节奏 |
| `MODEL_BASE_URL_ALLOWLIST` | 空 | 留空 = 只拦内网段；填了则只放行白名单域名 |

### 供应商凭据

| 变量 | 对应供应商 |
|---|---|
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | DeepSeek（默认） |
| `DASHSCOPE_API_KEY` / `QWEN_API_KEY` | 千问（两者任一即可） |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `GLM_API_KEY` / `GLM_BASE_URL` | 智谱 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | OpenAI（可选） |
| `WORKBUDDY_API_KEY` / `WORKBUDDY_BASE_URL` | WorkBuddy，**无公共默认端点，必须两项都填** |

Key 也可以在设置页粘贴：后端写入本机 `.env`（`chmod 600`）并立即生效，DB 只存 `env:NAME` 引用。

### 存储

| 变量 | 默认 |
|---|---|
| `DATABASE_URL` | `sqlite:///data/app.db`（可换 PostgreSQL） |
| `AUTO_MIGRATE` | `true` |
| `UPLOAD_DIR` / `ARTIFACT_DIR` / `TRASH_DIR` | `./data/{uploads,artifacts,trash}` |
| `SERVE_FRONTEND` / `FRONTEND_DIST` | `0` / 空（空 = `frontend/dist`） |

### 审批

| 变量 | 默认 | 说明 |
|---|---|---|
| `APPROVAL_RULES` | 代码默认 `code.run_python,file.delete`；`.env.example` 给的是 `doc.generate_report,file.delete,code.run_python` | 命中名单的**高风险**工具才拦 |
| `APPROVAL_TIMEOUT_SECONDS` | `180` | 超时 → `run.failed(APPROVAL_TIMEOUT)` |

> 注意两处默认值不同：代码里 `doc.generate_report` 默认不拦（产物可覆盖可重跑），`.env.example` 把它加上了。以你实际 `.env` 与 DB 为准。

### HTTP 与解析防护

| 变量 | 默认 | 说明 |
|---|---|---|
| `ALLOWED_ORIGINS` | 两个 localhost（+8080） | 留空回落 localhost |
| `MAX_UPLOAD_MB` | `20` | 1–200 |
| `API_TOKEN` | 空 | 留空 = 关闭鉴权；配置后需 `X-API-Token` 头 |
| `MAX_UNCOMPRESSED_MB` | `256` | 解压后上限 |
| `MAX_ARCHIVE_ENTRIES` | `2000` | |
| `MAX_PDF_PAGES` | `500` | |
| `MAX_PARSED_CHARS` | `1000000` | 超长截断并附说明 |

### 其他

| 变量 | 说明 |
|---|---|
| `FEATURE_FLAGS` | 逗号分隔 `k=v`；DB 优先，缺失回落环境变量 JSON |
| `FEEDBACK_EMAIL` | 留空 = 只本机存档 + 界面退化为"复制内容自己发" |
| `VITE_API_BASE` | 前端构建用，默认 `/api` |
| `OA_DATA_DIR` | 显式指定数据目录（打包态用） |
| `HTTPS_PROXY` / `HTTP_PROXY` | 出网代理，值必须以 `http://`/`https://` 开头 |
| `NO_PROXY` | 注意：Windows 上含 `[::1]` 会让 httpx 报 `Invalid port`，后端启动时已自动清理 |

## 10.3 设置中心可热更新的 10 项

```text
engine  model_provider  model_name  fallback_chain  approval_rules
mock_mode  max_upload_mb  model_timeout_seconds  approval_timeout_seconds  feature_flags
```

其他键一律拒绝（`BAD_REQUEST`）。改完立即生效，包括 provider 实例缓存清空。

### engine 与 mock_mode 的归一

```text
engine 是权威值 → mock_mode == (engine == "mock")
只给 mock_mode → 反推 engine
矛盾组合（engine=real + mock_mode=true）→ 启动时按 engine 修正并写回 DB
```

## 10.4 目录覆盖

| 项 | 说明 |
|---|---|
| 覆盖文件 | `data/storage-overrides.json` |
| 可覆盖 | uploads、artifacts（trash 随配置） |
| 传空 | 恢复默认 |
| 生效 | **无需重启**（根目录按 settings 实时解析） |

## 10.5 价格表

`backend/config/model_prices.yaml`：

| 项 | 说明 |
|---|---|
| 热加载 | 按 mtime 缓存，**改完不用重启** |
| 查找顺序 | `providers.<p>.models.<m>` → `providers.<p>.default` → `default` |
| 分时 | 表内写闲时价；`peak.weekdays` + `peak.ranges` 时段内按 `peak_multiplier` 翻倍 |
| 缓存分档 | `input_cache_hit` / `input_cache_miss` / `output`（元/百万 tokens） |
| 兜底 | `0.04 / 2.0 / 8.0`（按高峰全未命中估，宁高不低） |
| 模型名 | 用供应商回执里的真名，如 `deepseek-flash` |

## 10.6 机密处理清单

| 环节 | 做法 |
|---|---|
| 存储 | 明文只落本机 `.env`（`chmod 600`）；DB 只存 `env:NAME` 引用 |
| API 出参 | `GET /models` 不返回明文 Key；`GET /settings` 只回引用；保存后只回掩码 `sk-****abcd` |
| 日志 | `sanitize()` 按敏感键名递归打码，超 2000 字截断；响应体里的 Key 也会 `_redact` |
| 子进程 | `code.run_python` 的环境变量白名单**不含任何 Key/token** |
| CI | secret 扫描排除 `.env*`；`.env` 不得入库 |
| 前端 | `redact.ts` 对密钥字段打码、邮箱保留首字母 |
