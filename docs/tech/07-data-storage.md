# 07 · 数据与存储

> 事实来源：`backend/app/infra/db/`、`backend/app/infra/storage.py`、`backend/app/core/config.py`

## 7.1 表结构（8 张）

时间统一存 **ISO-8601 字符串**（`String(40)`）；扩展字段统一用 **JSON 列**（`models.py:3-4`）。

### threads（会话）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String(64) PK | |
| `title` | String(200) | |
| `pinned` | Boolean | 置顶 |
| `sort_index` | Float 可空 | **用户拖动顺序**，值小靠前；NULL = 没手动排过 |
| `deleted_at` | 可空 | 软删 |
| `created_at` / `updated_at` | String(40) | |
| `extra` | JSON | |

索引：`ix_messages_thread_created` 在 messages 上。

### messages（消息）

| 字段 | 说明 |
|---|---|
| `id` / `thread_id` / `role` / `content` | 基础字段 |
| `run_id` | 可空；用于上下文按 run 分组 |
| `extra` | 存 `uploads` 快照与 `attachment_ids` |

### runs（一次运行）

| 字段 | 说明 |
|---|---|
| `id` / `thread_id` / `status` | |
| `mode` | `mock` / `real` |
| `engine` / `provider` / `model` | 默认 `mock` / `mock` / `mock-scripted` |
| `tokens` / `cost_cny` | 当时记的估算值（审计时会按现价重算） |
| `started_at` / `finished_at` / `error_code` | |
| `extra` | `elapsed_ms` / `degraded` / `artifact_ids` / `approvals` / `usage` |

### run_events（事件流）

| 字段 | 说明 |
|---|---|
| `id` | Integer 自增 |
| `run_id` / `seq` / `event` / `data`(JSON) / `created_at` | |
| 唯一约束 | `uq_run_events_run_seq(run_id, seq)` |

### approvals（审批）

| 字段 | 说明 |
|---|---|
| `id` / `thread_id` / `run_id` / `tool` / `payload` | |
| `decision` / `comment` | 决议与备注 |
| `policy_version` | 默认 `v1` |
| `extra` | `timed_out` / `cancelled` / `args` |

### artifacts（产物与素材）

| 字段 | 说明 |
|---|---|
| `id` / `thread_id` / `run_id` | |
| `type` | `upload` 表示上传素材，其余为产物类型 |
| `filename` / `path` / `size` / `sha256` / `content_type` | |
| `deleted_at` | 软删 |
| `extra` | `chars` / `parsed` / `ext` / `text_path` / `text_preview` / `sources` / `trash` / `preview_path` |

### settings（键值设置）

| 字段 | 说明 |
|---|---|
| `key` | PK |
| `scope` | 默认 `global` |
| `value_json` | JSON（ORM 列名 `value_json`，实体字段是 `value`，映射在 repo 内完成） |
| `is_secret` | |
| `updated_at` | |

承载：`templates.custom`、`skills.disabled`、`projects.list`、各项配置覆盖。

### model_configs（供应商登记）

| 字段 | 说明 |
|---|---|
| `provider` / `base_url` / `model` | |
| `api_key_ref` | **只存 `env:NAME` 引用，不存明文 Key** |
| `priority` / `enabled` | 默认 100 / True |

## 7.2 索引一览

| 索引 | 表 | 列 |
|---|---|---|
| `ix_messages_thread_created` | messages | thread_id, created_at |
| `ix_runs_thread_started` | runs | thread_id, started_at |
| `uq_run_events_run_seq`（唯一） | run_events | run_id, seq |
| `ix_run_events_run_seq` | run_events | run_id, seq |
| `ix_approvals_thread_run` | approvals | thread_id, run_id |
| `ix_artifacts_thread_run` | artifacts | thread_id, run_id |

## 7.3 Alembic 迁移

所有迁移**先 `inspect` 现有表/列/索引再决定动作**，因此对 v0.1 旧库原地升级是幂等的。

| 版本 | 文件 | 内容 |
|---|---|---|
| 0001 | `0001_initial.py` | 建 5 张表：`threads` / `messages` / `approvals` / `artifacts` / `settings`；建 3 个索引 |
| 0002 | `0002_v21_tables.py` | 建 `runs` / `run_events` / `settings`（缺则建）/ `model_configs`；加列 `threads.pinned`、`threads.deleted_at`、`artifacts.deleted_at`、`approvals.policy_version`；建 `ix_runs_thread_started`、`ix_run_events_run_seq` |
| 0003 | `0003_thread_sort_index.py` | 加列 `threads.sort_index`（Float 可空） |

调用时机：`session.py:run_migrations()` 在 lifespan 启动时执行 `alembic upgrade head`（`AUTO_MIGRATE=true` 时）。

## 7.4 仓库层

| Repo | 方法要点 |
|---|---|
| `SqlThreadRepository` | `add` / `get` / `list` / `count` / `update` / **`min_sort_index()`** / **`reorder()`** / `soft_delete` / `soft_delete_many` |
| `SqlMessageRepository` | `add` / `list_by_thread(include_run_summary=True)` / `count_by_thread` |
| `SqlRunRepository` | `add` / `get` / `update` / `list_by_thread` / `list_recent` / `count` |
| `SqlRunEventRepository` | **`append`** / **`list_after(run_id, after_seq)`** / `max_seq` |
| `SqlApprovalRepository` | `add` / `get` / `decide` / `update_extra` / `list_by_thread` |
| `SqlArtifactRepository` | `add` / `get` / `list` / `count` / `count_by_thread` / `soft_delete` / `restore` / `hard_delete` |
| `SqlSettingsRepository` | `list_all` / `get` / `upsert` / `as_dict` |
| `SqlModelConfigRepository` | `list_all` / `add` / `update` / `delete` / `get` |

## 7.5 数据库连接

`session.py`：

| 项 | 配置 |
|---|---|
| URL 处理 | `build_database_url()` 把 SQLite 相对路径解析到 **`DATA_ROOT` 下的绝对路径**（不受启动 cwd 影响），并自动 `mkdir` |
| 通用 | `pool_pre_ping=True`, `future=True` |
| SQLite 额外 | `connect_args={"check_same_thread": False, "timeout": 15}` |
| PRAGMA | `journal_mode=WAL`、`busy_timeout=5000`、`foreign_keys=ON`（`connect` 事件里执行） |
| 事务 | `session_scope()` 短事务：正常 commit，异常 rollback + raise，finally close |
| 会话 | `sessionmaker(bind=engine, expire_on_commit=False, future=True)` |

> 列表查询一律**分页下推 SQL**（`count()` + `limit/offset`），不做内存切片——这在几千条产物时差别很大。

## 7.6 磁盘目录布局

相对 `DATA_ROOT`（源码态 = 仓库根，打包态 = `%LOCALAPPDATA%\Office Agent`）：

```text
data/
├── app.db                      SQLite（+ -wal / -shm）
├── uploads/                    上传素材：<new_id('f')><ext>，解析文本存 <name>.parsed.txt
├── artifacts/                  产物：同名按「名字(2)(3)」向后排，不塞随机串
├── trash/                      回收站：<new_id('t')>_<safe_name>
├── workspace/<run_id>/         code.run_python 沙箱（in/ + out/）
├── templates.json              自定义模板镜像（供 doc 工具无 DB 读取）
├── feedback/feedback.jsonl     意见反馈，一行一条 JSON
├── storage-overrides.json      目录覆盖
├── desktop_package.json        桌面安装包上次保存位置
└── .env                        （打包态；源码态在仓库根）
```

只读侧（`RESOURCE_ROOT`）：`backend/app/prompts/`、`backend/app/skills/`、`backend/app/skills_catalog/`、`backend/config/`、`backend/app/infra/db/migrations/`。

## 7.7 存储服务行为

| 方法 | 行为 |
|---|---|
| `save_upload()` | 存为 `uploads/<new_id('f')><ext>`，返回 `(ensure_within(stored, root), ext)` |
| `save_text()` | 存为 `<name>.parsed.txt`——**不能与原文件同名**，否则 txt/md 上传时 `with_suffix` 会覆盖原文件 |
| **`new_artifact_path()`** | 同名不塞随机串，按「名字(2)(3)」往后排——用户在下载目录里要能一眼看出先后 |
| `trash(path)` | 移入 `data/trash/<new_id('t')>_<safe_name>`（保留原文件名 + 短 ID 防重名） |
| `restore_file()` | 挪回原路径，原目录不存在自动创建 |
| 根目录解析 | uploads/artifacts/trash 三个根**按 settings 实时解析**（不是构造时烤死），用户在设置里改了目录后新产物直接落新目录，无需重启 |

## 7.8 删除语义

| 操作 | 行为 |
|---|---|
| 软删 | 文件移到 `data/trash`，artifact 记录保留并在 `extra["trash"]` 记原路径↔回收站路径映射 |
| 恢复 | 文件挪回原路径，记录复活 |
| 彻底删除（purge） | 文件 unlink + 记录 hard delete，**不可恢复** |
| 批量删除 | 去重保序 + **部分成功**语义：返回 requested/deleted/failed/trashed，不让一个坏 id 拖垮整批 |
| 删除会话 | 软删；不级联硬删文件 |

## 7.9 备份建议

| 内容 | 方式 |
|---|---|
| 全量 | 停服务后整包复制 `data/`（SQLite 的 WAL 建议先 `sqlite3 .backup` 或停服务） |
| 表级导出 | `python scripts/export.py --out data/export/export.json`（threads/messages/approvals/artifacts 四表，支持 `--import [--replace]` 回灌） |
| 数据库 | 直接复制 `app.db` + `app.db-wal` + `app.db-shm` 三个文件（只复制 db 会丢最近事务） |
