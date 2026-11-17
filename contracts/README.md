# contracts/ —— 前后端契约快照（入库，CI 校验）

本目录是 V2.1「契约可校验」的落地点，由脚本从**代码单一事实来源**生成，**禁止手改**。

| 文件 | 来源 | 用途 |
|---|---|---|
| `openapi.v1.json` | `backend/app/main.py` 的 FastAPI 应用（`app.openapi()`） | 前端 `openapi-typescript` 生成类型；接口评审；CI diff 锁版本 |
| `events.v1.schema.json` | `backend/app/core/events.py`（`EVENT_NAMES` / `REQUIRED_FIELDS`） | SSE 事件帧 JSON Schema；前端 fixture 校验、契约测试 |

## 生成 / 校验

```bash
# 生成（在仓库根执行；自动 mock 模式 + 内存库，不触碰真实 Key）
.venv/Scripts/python.exe scripts/export_openapi.py

# 只校验快照是否与代码一致（CI 等价）
.venv/Scripts/python.exe scripts/export_openapi.py --check

# CI 逻辑：重新导出后要求 diff 为空
.venv/Scripts/python.exe scripts/export_openapi.py && git diff --exit-code contracts/
```

前端类型生成（需先有快照）：

```bash
cd frontend
npx --no-install openapi-typescript ../contracts/openapi.v1.json \
  -o src/shared/api/generated/schema.d.ts     # 或 npm run gen:api（从后端拉取）
```

> `frontend/src/shared/api/generated/` 为生成目录，**禁止手改**；
> CI `contract` 门禁会把「用快照生成的类型」与仓库里的生成文件做 diff。

## 变更规则（与 `docs/events.md` / `docs/api.md` 一致）

- **只允许追加**：新增事件 / 新增字段可以；已有字段名称、语义、类型不得修改。
- **快照必须同 PR 更新**：代码改接口 → 重新导出 → 把 `contracts/` 变更一起提交，
  否则 CI `contract` 门禁红。
- **破坏性变更**：升版本（`/api/v2`、`events version=2`）+ ADR + 旧版保留一个迭代。
- 事件 v1.1 追加 `run.cancelled` / `tool.started` / `heartbeat`，v1 前端忽略未知事件即可兼容。
