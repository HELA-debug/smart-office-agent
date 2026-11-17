# tests —— V2.1 黑盒 smoke（30 条 + 1 条真实模型）

纯黑盒 HTTP 测试：只依赖 `docs/api.md` / `docs/events.md` 契约，**不 import 后端代码**。
默认连 **mock 服务**（`http://127.0.0.1:8004`），不访问外网；若后端不是 mock 模式会立即退出，
防止 smoke 误打真实模型产生费用。

## 前置

1. Python 3.13 + 项目根 `.venv`；
2. 测试依赖：`pytest httpx python-docx pypdf openpyxl`；
3. mock 后端（任选其一）：
   - `make smoke`（自动起停 mock 服务 8004）；
   - 手动：在仓库根执行

```bash
MOCK_MODE=true ENGINE=mock DATABASE_URL=sqlite:///data/b5_mock.db \
  UPLOAD_DIR=./data/b5/uploads ARTIFACT_DIR=./data/b5/artifacts OUTBOX_DIR=./data/b5/outbox \
  .venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8004
```

## 运行

```bash
# 30 条 smoke（默认 8004；--base-url 可覆盖）
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m pytest tests -v --base-url=http://127.0.0.1:8004

# 真实模型 smoke（1 条，默认跳过；消耗真实 token，跑在真实模式服务 8000）
RUN_REAL_MODEL_TEST=1 BASE_URL=http://127.0.0.1:8000 \
  .venv/Scripts/python.exe -m pytest tests/test_real_smoke.py -q
```

预期：`30 passed, 1 skipped`（真实模型用例默认跳过）。测试结束要求仓库根干净
（文件只写 `tmp_path`；CI `backend-test` 有 `git status --porcelain` 断言）。

## 30 条用例清单

### test_smoke_core.py（10）

| # | 用例 | 覆盖 |
|---|------|------|
| 1 | `test_health_v1` | health 字段/版本/引擎/trace_id |
| 2 | `test_health_legacy_deprecation` | 旧 `/api` 兼容 + `Deprecation`/`Link` 头 |
| 3 | `test_thread_create_and_detail` | 建会话 + 详情（messages/artifacts） |
| 4 | `test_thread_list_search_pagination` | 标题搜索 + 分页 total/page_size |
| 5 | `test_thread_update_rename_pin` | 重命名 + 置顶 |
| 6 | `test_thread_soft_delete` | 软删（列表消失、GET 404） |
| 7 | `test_settings_effective_and_secret_refs` | 设置来源 + 密钥只返回引用（无明文） |
| 8 | `test_settings_hot_update` | 保存即生效（sources=db） |
| 9 | `test_settings_validation_errors` | 未知字段/越界 → 400 |
| 10 | `test_extensions_models_tools_skills_subagents` | 模型列表/脱敏探测、工具 schema、子智能体、技能启停 |

### test_smoke_files.py（5）

| # | 用例 | 覆盖 |
|---|------|------|
| 11 | `test_upload_six_formats` | docx/xlsx/pdf/txt/md/csv 解析 |
| 12 | `test_upload_multi_files` | `files` 多文件字段 + v0.1 兼容字段 |
| 13 | `test_upload_unsupported_type_415` | 扩展名/MIME 校验（415 + reason） |
| 14 | `test_upload_fake_magic_415` | 伪造 docx/pdf（magic bytes 415） |
| 15 | `test_files_list_and_delete` | 素材列表/删除/不存在会话 404 |

### test_smoke_flow.py（15）

| # | 用例 | 覆盖 |
|---|------|------|
| 16 | `test_sse_full_flow_approve` | 全链路：事件顺序/version/run_id、批准、run.completed、运行详情/列表、产物 meta/下载（python-docx 结构）/预览 |
| 17 | `test_sse_reject_flow` | 拒绝：`status=rejected`、无 run.failed、mail skipped、产物保留、outbox 无新增、审计 rejected |
| 18 | `test_approval_duplicate_409` | 重复审批 409 `APPROVAL_ALREADY_DECIDED` |
| 19 | `test_approval_timeout_failed` | 审批超时 → `run.failed(APPROVAL_TIMEOUT)`（热更新 timeout=2s 后还原） |
| 20 | `test_cancel_run` | 取消 → `run.cancelled` + 重复取消幂等 |
| 21 | `test_retry_run` | 重试（SSE）→ 新 run completed |
| 22 | `test_event_replay_json` | `GET /runs/{id}/events?after=seq` 回放 |
| 23 | `test_event_replay_sse_last_event_id` | `Last-Event-ID` SSE 续传 |
| 24 | `test_artifact_list_filter` | 产物中心：跨会话 + 类型筛选 + 分页 |
| 25 | `test_artifact_delete_then_gone` | 软删后下载/预览/元数据 404 |
| 26 | `test_artifact_regenerate` | 重新生成（SSE）→ 新产物 |
| 27 | `test_templates_create_render` | 内置渲染 + 自定义模板创建/渲染/删除 |
| 28 | `test_audit_and_usage` | 审计 runs/approvals/artifacts + 用量聚合 |
| 29 | `test_audit_export` | 审计导出 JSON/CSV（attachment、CSV BOM） |
| 30 | `test_legacy_api_full_flow` | 旧 `/api` 上传 + SSE 全链路 + Deprecation |

### 真实模型（默认跳过）

`test_real_smoke.py::test_real_model_end_to_end`：真实模式单次运行，断言 `run.started.mode=real`、
`approval.required`、`run.completed`（artifact + tokens/cost + approvals）、DOCX 可下载打开。

## 与 `backend/app/evals/smoke_cases.json` 的对应

`backend/app/evals/smoke_cases.json` 为 V2.0 的 10 条 evals 用例（历史资产），映射关系：

| evals | 本套 smoke |
|---|---|
| smoke-01 health | #1 / #2 |
| smoke-02 建会话 + 列表 | #3 / #4 |
| smoke-03 上传 txt | #11 |
| smoke-04 上传 docx | #11 / #14 |
| smoke-05 不支持类型 | #13 |
| smoke-06 全链路批准 | #16 |
| smoke-07 拒绝 + 无外部写 | #17 |
| smoke-08 重复审批/404 | #18 / #15 |
| smoke-09 DOCX 结构 | #16（结构断言） |
| smoke-10 审计 + 库 | #28 / #29 |

> V2.1 新增场景（取消/重试/断线重放/设置热更新/模型探测/旧接口）没有对应 legacy evals，
> 由 #19–#30 覆盖。

## 失败判定

- **测试自身问题**（契约变更、环境、并发/时序）→ 修测试；
- **后端 bug** → 保留请求/响应证据（`-vv` + SSE 事件列表）报告 Lead/后端 owner，**不改 backend 源码**；
- **环境问题** → 先查 `KNOWN_ISSUES.md`（Docker/make/代理/端口占用）。
