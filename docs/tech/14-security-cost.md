# 14 · 安全与成本

> 事实来源：`core/security.py`、`core/net_guard.py`、`tools/builtin/code.py`、`api/auth.py`、
> `core/pricing.py`、`services/usage_service.py`、`backend/config/model_prices.yaml`

## 14.1 威胁模型

本机单用户桌面工具，**默认不面向公网**。防护目标是：

| 威胁 | 措施 |
|---|---|
| 恶意上传（伪造类型、压缩炸弹、超大文档） | 三重签名校验 + 解压估算 + 页数/字数上限 |
| 模型把 Key 带去不该去的地方 | 出网 URL 白名单 + SSRF 网段黑名单 |
| 模型生成脚本搞破坏 | 环境变量白名单（无 Key）+ 受控工作目录 + 高风险默认审批 |
| 任意路径读写、目录穿越 | `ensure_within` + 只认服务端记录的路径 |
| 别人访问我的服务 | 可选 `API_TOKEN` + 端口只绑回环 |
| 机密进日志/响应 | 脱敏 + 引用制 |

**不是**防护目标的：内核级隔离、多用户权限、模型本身的提示注入（本项目靠审批 + 工具白名单兜底）。

## 14.2 上传防护

| 环节 | 实现 |
|---|---|
| 白名单 | 扩展名 `.docx/.txt/.pdf/.xlsx`；MIME 校验；内容签名校验（docx 含 `word/`、xlsx 含 `xl/`） |
| 大小 | `MAX_UPLOAD_MB` 默认 20（1–200，热更新） |
| 压缩炸弹 | `check_zip_bomb()`，解压前估算，`max_compression_ratio=200` |
| 条目数 | `MAX_ARCHIVE_ENTRIES=2000` |
| PDF | 估页数，超 `MAX_PDF_PAGES=500` 拒绝；扫件无文字 → `FILE_PARSE_ERROR` |
| 文本 | utf-8-sig / utf-8 / gb18030 依次尝试 |
| 解析长度 | 超 `MAX_PARSED_CHARS` 截断并附「已截断：原文 N 字」 |
| 文件名 | `safe_filename()` 保留中文，限 120 字符 |

失败原因码（前端据此给具体提示）：`empty` / `ext` / `mime` / `content` / `size` / `zip_bomb` / `pages`。

## 14.3 出网防护

模型 `base_url` 会把 Key 带出去，所以 provider 每次调用前都会 `_assert_base_url_allowed()`。

| 层 | 内容 |
|---|---|
| 协议 | 只许 http / https |
| 网段黑名单 | 16 段，含 `169.254.0.0/16`（云元数据）、`100.64.0.0/10`（CGNAT）、`::ffff:0:0/96`、私有网段 |
| 本地主机名 | `localhost` / `127.0.0.1` / `::1` 等直接拒绝 |
| DNS | 先解析再逐 IP 判段（防 DNS rebinding 到内网） |
| 白名单 | `MODEL_BASE_URL_ALLOWLIST` 留空 = 只拦内网段；填了则**只放行列出的域名** |

## 14.4 代码执行沙箱

`code.run_python` 的定位（源码注释明示）：**这不是内核级沙箱**，脚本仍能访问本机文件系统，所以默认必须人工确认。

| 措施 | 说明 |
|---|---|
| 环境变量白名单 | 13 个系统变量，不含任何 Key/token |
| 工作目录 | `data/workspace/<run_id>/{in,out}` |
| 输入隔离 | 素材复制到 `in/`，清单以 `OA_INPUTS` JSON 给出 |
| 输出约束 | 仅 `.docx/.pdf/.xlsx/.md/.txt` 登记，单文件 ≤30MB |
| 超时 | `max(5, min(120, timeout))`；超时杀进程并在 stderr 写明 |
| 默认审批 | 在 `APPROVAL_RULES` 内，执行前挂起等用户确认 |
| 失败不登记 | `ok=False` 时不产出产物（半成品 docx 一打开就是坏的） |

## 14.5 审批

| 项 | 规则 |
|---|---|
| 三种模式 | `risky`（只拦名单内）/ `always_ask`（所有 high 风险 + 名单）/ `all_allow`（全放行） |
| 判定 | `needs_approval(mode, tool_name, risk, approval_tools)` |
| 默认名单 | `code.run_python,file.delete`（`doc.generate_report` 默认不拦） |
| 超时 | `APPROVAL_TIMEOUT_SECONDS=180` → `run.failed(APPROVAL_TIMEOUT)` |
| 保活 | 挂起期间每 15s 发心跳 |
| 唤醒 | `asyncio.Event.set()`，不轮询 |
| 幂等 | 已决/超时/取消 → `APPROVAL_ALREADY_DECIDED` |

## 14.6 路径安全

| 场景 | 防护 |
|---|---|
| 文件读写 | `ensure_within(path, root)` |
| SPA 静态服务 | 目录穿越防护 + 后端前缀独占 |
| 存储 reveal | 只接受 `uploads` / `artifacts` 两个固定 kind，不接受前端传任意路径 |
| 项目搬运 | `staging_paths()`：`root.resolve() not in candidate.parents` 则跳过 |
| 桌面包 reveal/open | 只认 `data/desktop_package.json` 里记录的路径 |
| 技能删除 | 只允许删技能根目录的**直接子目录** |

## 14.7 鉴权

| 项 | 说明 |
|---|---|
| 形态 | 纯 ASGI 中间件（不缓冲 SSE） |
| 默认 | `API_TOKEN` 空 = 关闭鉴权（本地开发默认） |
| 生效 | 非空则除 `/`、`/health` 外都要 `X-API-Token` |
| 比较 | `hmac.compare_digest` 常量时间 |
| 部署建议 | 配置 Token + 端口只绑回环 |

## 14.8 成本：计价口径

### 为什么要有缓存命中/未命中两档

> DeepSeek 控制台上"1.19 亿 tokens 只花 ¥5.86"看着像 ¥0.05/百万，其实是那批 token 绝大多数命中了上下文缓存（¥0.02–0.04/百万）。本应用每轮上下文都在变，基本是未命中（¥1–2/百万），两个平均价直接对比会差 50 倍，谁看都觉得是编的。

### 计价链路

```text
回执 usage.prompt_cache_hit_tokens / prompt_cache_miss_tokens
（或 OpenAI 写法 usage.prompt_tokens_details.cached_tokens）
→ ProviderResult.cache_hit_tokens / cache_miss_tokens
→ ModelRouter.estimate_cost(at=...) → pricing.cost_for()
   ├─ 查 model_prices.yaml：providers.<p>.models.<m> → default
   ├─ is_peak(at)：工作日 09-12 / 14-18 → 单价 × peak_multiplier
   └─ 命中价 × hit + 未命中价 × miss + 输出价 × output
→ UsageAccumulator.add() 累计
→ run.extra["usage"] 落库
```

| 规则 | 说明 |
|---|---|
| 命中缺失 | 按未命中价的一半兜底 |
| miss 缺失 | 按 `prompt_tokens - hit` 推（**上限，宁高不低**） |
| 老 run 只有总 tokens | 当输入按未命中价估 |
| 未知模型 | 兜底价 `0.04 / 2.0 / 8.0` |
| 改价 | 按 mtime 热加载，**改 yaml 不用重启** |
| 审计 | **一律按现价重算**，不用当时存的旧值 |

### mock 运行不计成本

`usage_service` 把 `mode=="mock" or provider=="mock"` 的 run 单列，只累加 `mock_runs`，不计入 tokens/cost。理由：mock 的 token 从没花过钱，混进去会误导对账。

## 14.9 成本：怎么证明"真的调用了模型"

这是排查"控制台对不上"的核心手段。

| 证据 | 来源 |
|---|---|
| `request_id` | 每次调用取回执里的 `data["id"]`；审计页 `verified_calls` = 有 id 的调用数 |
| `verified` 标记 | 每条回执（≤40 条）都带 `verified=bool(request_id)` |
| 无 id 告警 | 日志 `event="model_call_unverified"`（多半是自建网关吃掉了回执） |
| 供应商实际模型名 | 审计里 `provider_model` 取回执真名（如 `deepseek-flash`），不是配置名 |
| 账户余额 | `GET /api/v1/models/{id}/balance`（目前仅 DeepSeek 提供） |
| 控制台筛选 | 用回执里的模型名筛选，别用配置名；按"今天"筛选时注意控制台有约 5 分钟延迟 |

### 常见"对不上"的四个原因

| 现象 | 原因 |
|---|---|
| 名字对不上 | 配置写 `deepseek-chat`，回执是 `deepseek-flash`（官方旧别名会被路由）。**按回执名归账单** |
| 单价看着太贵 | 控制台展示的是含缓存命中的平均价；本应用基本未命中，单价自然高 |
| 控制台看不到当天请求 | ① 按 Key 筛选时用的是另一把 Key；② 时间范围没选今天；③ 控制台数据有延迟 |
| 本地算的比官方少 | 本地是估算；未命中价已按上限估，若仍偏少，先查 `cache_hit` 是否被解析到 |

## 14.10 成本：降低开销的三个杠杆

| 杠杆 | 做法 |
|---|---|
| **提高缓存命中率** | system 提示词前缀保持稳定（易变内容后置）。实测前缀稳定后命中率 0% → 96%，单轮成本降到 ¥0.02 量级 |
| 缩短上下文 | `context_max_turns` / `context_max_chars` / `context_max_turn_chars`，超出的走**抽取式摘要**（不额外调模型） |
| 控制步数与输出 | `model_max_steps`（≤12）、`model_max_tokens`、单次运行 token 预算 `MODEL_TOKEN_BUDGET` |

其它：标题建议（40 tokens）、提示词增强（20s 超时）都是"锦上添花"，失败即静默跳过，不会为了小功能额外花钱。
