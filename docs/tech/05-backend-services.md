# 05 · 后端 services 层

> 事实来源：`backend/app/services/*.py`

## 5.1 settings_service — 配置生效机制 ★

这是"设置中心保存即生效"的实现核心，也是最容易出矛盾的地方。

### 可编辑白名单

`_EDITABLE`（`:21-32`）只允许 10 项，白名单外一律 `AppError(BAD_REQUEST)`：

```text
engine(str)  model_provider(str)  model_name(str)  fallback_chain(list)
approval_rules(list)  mock_mode(bool)  max_upload_mb(int)
model_timeout_seconds(float)  approval_timeout_seconds(int)  feature_flags(dict)
```

### 核心方法

| 方法 | 作用 | 行号 |
|---|---|---|
| `_source(key, overrides)` | 来源判定：`db`（在覆盖表）→ `env`（字段被显式设置过）→ `default` | `:91-98` |
| `effective()` | 返回生效值 + `sources` + `env_hints` + `secrets` + 各目录绝对路径 | `:117-149` |
| **update(patch)** | ① 白名单 ② 类型校验 ③ 业务校验（engine∈三值、provider 非空、`max_upload_mb∈[1,200]`）④ **engine/mock_mode 归一成对落库** ⑤ 逐项 upsert ⑥ `_apply()` ⑦ 返回 `effective()` | `:174-235` |
| **`_switches(overrides)`** | 把「执行引擎」与「演示模式」归一成一对 `(engine, mock_mode)` | `:238-252` |
| **`apply_persisted()`** | 启动时调用（`main.py:130`）：应用 DB 覆盖后，**若 DB 里存在历史矛盾则按 engine 修好并写回 DB** | `:254-273` |
| **`_apply(overrides)`** | 热更新：写回 Settings 各字段 → 应用 model_configs → 同步 `runtime.settings` / `runtime.approval_tools` / `runtime.router.settings` → **`runtime.router.reset_providers()`** | `:275-304` |

### `_switches()` 的归一规则（重要）

```text
engine 是权威值。
- 给了 engine  → 按它推导 mock_mode（mock_mode == (engine == "mock")）
- 只给了 mock_mode（老客户端）→ 反推 engine
- 都给了但互相矛盾（engine=real + mock_mode=true）→ 以 engine 为准
- 值非法 → 按 real 处理
```

为什么要修矛盾并写回 DB：否则每次启动纠一遍、下次保存又带回来，用户会看到"设置页显示真实模型，顶栏却是 mock 徽标"。

### 为什么要 `reset_providers()`

Provider 实例在构造时把 `base_url` 拍成了快照，还缓存了探测结果。改了地址/模型后**不清缓存就得重启**才生效。

## 5.2 run_service — 事件落库与 SSE 广播 ★

架构：**生产者任务 + SSE 消费者生成器**。

```
asyncio.create_task(_produce(...))   ← 生产者：跑引擎、落库、广播
yield 队列项                          ← 消费者：当前这个 SSE 连接
_broker[run_id] = set[Queue]          ← 其他订阅者（并发的续传连接）
```

### start() 的 14 步

| 步骤 | 内容 | 行号 |
|---|---|---|
| 1-2 | 校验会话、读审批规则 | `:109+` |
| 3 | `runtime.prepare_engine(force_mock=...)` 选引擎 | |
| 4 | `_stage_project()` 把项目文件搬成素材 | `:661` |
| 5 | `conversation.prepare()` 规范化 + 附件 + 上下文计划 | |
| 6 | `threads.ensure_title` | |
| 7 | `prompt_packs.render()` | |
| 8 | `new_id("r")` + `bind_log_context` | |
| 9 | `runs.add` | |
| 10 | `conversation.record_user`（**带本轮附件快照**） | |
| 11 | 建 `asyncio.Queue`，登记 `_broker[run_id]` | |
| 12 | 组 `RunContext` | |
| 13 | `create_task(_produce(...))` | |
| 14 | 循环 yield 队列项，`None` 结束；finally 取消生产者 + `_close_broker` + 复位日志上下文 | |

### `_produce()` 落库顺序（不能反）

```text
for event in engine.run(ctx):
    if 是 comment（心跳）: 直接入队，不落库
    else:
        seq += 1
        events.append(RunEventEntity(...))   ← 先落库
        _publish(run_id, chunk)              ← 再广播
        queue.put_nowait(chunk)              ← 再给当前连接
    终态事件 → _finish_run()
```

**先落库再广播**：保证断线重放一定能拿到该帧。

### 取消与异常

| 场景 | 行为 | 行号 |
|---|---|---|
| 用户取消 | 取消生产者任务 → 生产者落 `run.cancelled(reason="cancelled_by_user")` → 队列收到哨兵结束 | `:318-349` |
| 无活跃生产者（服务重启后补取消） | 直接补一条 `run.cancelled` 事件 + 收尾 | `:318-349` |
| `CancelledError` | `task.uncancel()` + `seq = max(seq, max_seq) + 1` 防撞号 | `:260-292` |
| 其他异常 | 落 `run.failed`，`error_code=INTERNAL`，`retryable=True` | `:260-292` |
| 取消时 | 同时把未决审批打上 `{"cancelled": True}` | `:753` |

### 断线续传 `resume()`

```text
events.list_after(run_id, after) 回放历史
→ 若 run 仍 running：_subscribe 订阅队列
→ asyncio.wait_for(queue.get(), timeout=15.0)，超时 yield 心跳 ": ping"
→ 跳过 seq <= last_seq 的重复帧
```

### 其他关键方法

| 方法 | 作用 | 行号 |
|---|---|---|
| `list_runs(...)` | **分页下推 SQL**（`count()` + limit/offset），不做内存切片 | `:391-413` |
| `audit(thread_id)` | 会话审计；`cost_cny` 用 `run_usage()` **按现价重算**；带 `request_ids`（最近 3 条）、`verified_calls`、`provider_model` | `:457` |
| `export_audit(fmt, thread_id)` | JSON/CSV；线程与 run 都**按 200 分批**（`_EXPORT_BATCH`）；CSV 用 `utf-8-sig` 兼容 Excel | `:523-581` |
| `_retitle_if_auto()` | 首轮跑完用模型把自动标题换成贴题名字，失败静默保留 | `:294-315` |
| `validate_attachments()` | 附件不属于该会话 → 400 | `:351` |
| `retry_message()` / `regenerate_source()` | 取原 run 的用户消息 + 当时附件；upload 类产物拒绝重新生成 | `:360` / `:377` |
| `_publish` / `_subscribe` / `_close_broker` | 广播：`_broker: dict[str, set[Queue]]`；`QueueFull` 静默丢弃；`_close_broker` 推 `None` 哨兵 | `:802-822` |

## 5.3 usage_service — 用量与成本 ★

| 方法 | 要点 | 行号 |
|---|---|---|
| `summary(thread_id, range_key, limit)` | 返回 runs/real_runs/mock_runs/tokens/cost/cach 命中与未命中/price_note/平均耗时/按状态/供应商/模型/天 | `:33-125` |
| `run_usage(run)` | 从 `run.extra["usage"]` 取 tokens；miss 缺失按 `input - hit` 推；老 run 只有总 tokens 时**当输入按未命中价估**；调 `pricing.cost_for(at=started_at)` | `:156-184` |
| `pricing_note()` | 一句话口径说明，**带当前生效单价**，如「按官方闲时价估算：输入未命中 ¥1、命中 ¥0.5、输出 ¥4 每百万 tokens」 | `:187-194` |

两条硬规则：

1. **成本一律按现价重算**，不直接用 run 上存的旧值——改价后历史值会与官方差几十倍。
2. **mock 运行单列**：`mode=="mock" or provider=="mock"` 的 run 不计入 tokens/cost，只累加 `mock_runs`。mock 的 token 从没花过钱，混进去会误导对账。

## 5.4 其余 service 一览

| 文件 | 职责与关键方法 |
|---|---|
| **thread_service** | 会话 CRUD + 首条消息回填标题。`create()` 新会话 `sort_index = min-1` 排最前（`:29`）；`reorder()` 拖动排序（`:43`）；`list()` 搜索/分页下推 SQL（`:50`）；`detail()` 含 messages/artifacts/upload 三份（`:87`）；`ensure_title()` 只在默认标题时回填（`:153`）；`soft_delete_many()` **不校验存在性**，避免分页列表里已被删的项让整批失败（`:145`） |
| **approval_service** | 实现 `ApprovalGate` 端口。`create()` 落库 + 注册 `asyncio.Event`（`:31`）；`wait()` 用 `asyncio.wait_for` 等唤醒，超时写 `extra.timed_out`（`:53`）；`decide()` 校验决议值 → 已决/超时/取消 → `APPROVAL_ALREADY_DECIDED`，通过则 `event.set()` 唤醒引擎（`:70`） |
| **artifact_service** | 产物/素材全生命周期。`upload_many()` ≤10 个（`:121`）；`list_artifacts()` 默认排除 upload 且分页下推 SQL（`:255`）；`preview()` 按类型渲染（docx→HTML、xlsx→HTML 表格前 5 sheet×120 行×20 列、pdf→iframe、txt→纯文本）（`:299`）；`delete()` 软删并在 `extra["trash"]` 记原路径↔回收站映射（`:458`）；`delete_many()` 去重保序 + 部分成功（`:552`）；`_media_type()` 按扩展名兜底让 PDF 能内联（`:600`） |
| **model_service** | 供应商登记 + 探测 + 对账。`upsert_model()` 要求 `api_key_ref` 必须是 `env:` 形式，登记后调 `settings_service.apply_persisted()`（`:150`）；`save_key()` 写入进程 env + `.env` + 回指引用，返回掩码（`:208`）；`balance()` 仅 DeepSeek 支持（`:255`）；`test_model()` 用 `max_tokens=1` 真实探测，**缺地址/缺 Key 返回人话原因而不是抛 400**（`:313`） |
| **template_service** | 模板 CRUD + 按模板同步生成。`BUILTIN_TEMPLATES` 三个（weekly/meeting/summary），weekly 绑 `weekly-report` 技能（`:32-70`）；`sync_file()` 镜像到 `data/templates.json` 供 doc 工具无 DB 读取（`:185`）；`render()` 直接调 `file.read` + `doc.generate_report` 并落 `artifact.ready`（`:199`）；内置模板 `enabled` 受技能开关影响 |
| **skill_service** | 技能启停/导入/删除 + **提示词即时重建**。`set_enabled()` 写 `skills.disabled` 并 `_rebuild_prompt()`（`:116`）；`apply_persisted()` 启动时把禁用名单应用到 runtime（`:145`）；`delete_skill()` 挪进 `app/skills/.trash/<name>-<时间戳>`（`:154`）；`_rebuild_prompt()` = 基础提示词 + 「# 可用技能（按需参考）」+ 各启用技能正文（`:219`） |
| **project_service** | 项目登记与只读扫描。`_scan()` BFS，跳隐藏/黑名单/符号链接（`:107`）；`add()` 拒绝程序目录及其上级、拒绝上传/产物目录（`:194`）；`staging_paths()` **路径越界防护**：`root.resolve() not in candidate.parents` 则跳过（`:265`）；上限 20 个项目 / 400 文件 / 3 层 / 单次搬运 10 文件 30MB |
| **conversation_service** | 一轮请求的规范化/附件归属。`prepare()` 规范化 + 附件 + `plan_from_messages`（`:128`）；`uploads_for()` 显式传 ids 就只认这几个，不传则兼容老客户端取全量（`:93`）；`record_user()` 把附件快照写进 `message.extra`（`:159`）；`attachments_of_run()` 重试时原样带上当时附件（`:179`） |
| **feedback_service** | 本机存档 + 生成 mailto，**不发任何网络请求**。`_append()` 一行一条 JSON 追加到 `data/feedback/feedback.jsonl`（`:114`）；诊断信息含引擎/mock 状态/model/git sha/客户端窗口与屏幕（`:125`） |
| **title_suggester** | 用模型生成 ≤24 字贴题标题。`suggest_title()` 用 `asyncio.wait_for(..., 3.0)`，temperature 0.3、max_tokens 40，**任何异常返回空串**（`:49`）——锦上添花，不能拖住运行 |
| **prompt_enhancer** | 提示词增强，`_same_as_source` 时回落原文；无模型时走 `rule_based_prompt()` 本地规则兜底（`:99`） |
| **prompt_packs** | 按需求关键词自动匹配提示词包注入本轮 system prompt，`MAX_PACKS_PER_RUN=2`、`MAX_INJECT_CHARS=4200`（`:21`、`:24`） |
| **skill_drafter** | 让模型把一句话需求写成合法 `SKILL.md`；45s 超时；有 `_local_draft()` 本地骨架兜底（`:171`） |
| **docx_utils / pdf_utils / xlsx_utils / text_utils** | 四个文档加工工具库，会被 `code.run_python` 复制进沙箱工作目录供脚本 import。docx 含 6 套页面预设（PAGE_DEFAULT/COMPACT/GONGWEN/THESIS/RESUME/LETTER）；pdf 用 reportlab 内置中文 CID 字体 `STSong-Light`；xlsx 基于 openpyxl；text 处理 Markdown 与编码探测（utf-8/gb18030） |

## 5.5 依赖注入关系

```text
RunService ← threads, conversation, artifacts, approvals, runs(events), settings_service,
             runtime, usage, prompt_packs, storage, projects, title_suggester
TemplateService ← 9 个依赖（含 settings_service、artifacts、storage、runtime）
ModelService ← model_config_repo, settings, settings_service（改登记后触发 apply_persisted）
```

`build_container()` 中的构造顺序见 [02 篇 2.4](02-architecture.md)。
