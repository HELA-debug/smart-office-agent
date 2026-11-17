# B4 真实模型内核 · 验收证据

本目录保存 B4（真实模型内核）的**真跑证据**，全部来自 2026-10-23 本机实际运行；
证据文件只含事件/用量/产物摘要，**不含任何 API Key 或明文密钥**。

## 文件

| 文件 | 来源 | 内容 |
|------|------|------|
| `real_deepseek.json` | 8001 真实模式服务（DeepSeek 真 Key） | 建会话 → 上传 docx+txt → SSE 真 ReAct 工具循环 → 审批 → DOCX 下载；事件序列、tokens/cost、工具调用、DOCX 开头段落 |
| `real_deepseek_b4r.json` | 8003 真实模式服务（B4R 回归，任务原文“把这份材料整理成 600 字周报，发我邮箱草稿”） | 正文回填修复后的端到端证据：file.read → doc.generate_report → mail.send → 审批批准 → DOCX 下载 |
| `real_b4r2_run1.json` / `real_b4r2_run2.json` | 8003 真实模式服务，**同一 SQLite DB 连续两次真实运行**（B4R2 消息 ID 回归） | 两次 run 均 completed；messages 主键全局唯一（`{run_id}_mstepN`），第 2 次运行无 UNIQUE 冲突 |
| `real_b4r2_final.json` | 8003 最终代码（B3P 合并后） | 单次真实 smoke：health `engine=real/engine_effective=real`，completed + DOCX 下载，验证新 RunService 与 RealEngine 集成 |
| `degrade_wrong_key.json` | 8002 故意错误 Key 服务 | 探测 401 → 自动降级 mock（`run.started.degraded=true`）→ 主链路仍完成、产物可下载 |
| `real_deepseek_run.json` | `pytest -m real`（`tests/e2e/test_real_deepseek.py`） | 同一真实链路的 pytest 版证据（事件序列/工具/tokens/cost/DOCX 段落） |
| `run_evidence.py` | 可复现脚本 | 对运行中的服务走完整链路并落盘 JSON（自动批准审批） |

## 复现命令

```bash
# 1) 仓库根启动真实模式服务（端口 8001，数据目录隔离）
DATABASE_URL=sqlite:///data/b4_evidence/app.db \
UPLOAD_DIR=./data/b4_evidence/uploads \
ARTIFACT_DIR=./data/b4_evidence/artifacts \
OUTBOX_DIR=./data/b4_evidence/outbox \
./.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001

# 2) 走完整链路并写证据
./.venv/Scripts/python.exe backend/tests/evidence/run_evidence.py \
    --base-url http://127.0.0.1:8001 --label real_deepseek

# 3) 故意错误 Key 验证降级（端口 8002）
DEEPSEEK_API_KEY=sk-invalid-b4-degrade OPENAI_API_KEY= \
DATABASE_URL=sqlite:///data/b4_degrade/app.db ... uvicorn ... --port 8002
./.venv/Scripts/python.exe backend/tests/evidence/run_evidence.py \
    --base-url http://127.0.0.1:8002 --label degrade_wrong_key

# 4) 真实模型集成测试（默认跳过；需 RUN_REAL_MODEL_TEST=1）
cd backend
RUN_REAL_MODEL_TEST=1 ../.venv/Scripts/python.exe -m pytest tests/e2e/test_real_deepseek.py -q -s
```

## 关键结果（摘要）

- B4R2 消息 ID 回归（同一 DB 连续两次真实运行，`real_b4r2_run1.json` / `real_b4r2_run2.json`）：
  两个不同 thread 各跑一次短任务“把这份材料整理成 200 字摘要”，均
  `run.started{real, engine:real, provider:deepseek} → file.read → doc.generate_report → artifact.ready → run.completed{completed}`；
  run1 `tokens=6486 / cost=0.015204 / elapsed=13.7s`，run2 `tokens=6480 / cost=0.015072 / elapsed=15.3s`；
  DB 校验：`messages` 6 行、主键 6 个全唯一（形如 `r_20261023_e183c3_mstep1`），`run_events` 92 行，
  2 份 DOCX（37,045 / 37,060 字节）可下载；第 2 次运行未再出现 `UNIQUE constraint failed: messages.id`。
- B4R 真实回归（提示词 v1.2.0，`real_deepseek_b4r.json`）：任务原文
  “把这份材料整理成 600 字周报，发我邮箱草稿” → `run.started{mode:"real",engine:"real",provider:"deepseek"}`，
  模型基于 file.read 注入的正文自主调用 `todo.write / file.read / doc.generate_report / mail.send`，
  `approval.required(mail.send)` 批准后 `run.completed{status:"completed"}`；
  `tokens=14670`（in 13581 / out 1089），`cost_cny=0.035874`，5 次模型调用、6 次工具调用，
  DOCX `art_d2d455039d`（37,247 字节）下载成功；审批预览 `to=me@example.com`、正文含素材要点。
- 真实模式（B4 初版，`real_deepseek.json`）：11 次模型调用，`tokens=26048`，`cost_cny=0.058612`；
  模型自主调用 `file.read/file.list/todo.write/doc.generate_report/mail.send`，审批后产出 DOCX。
- 兜底路径（单测覆盖，真实模式未触发时 `fallback_actions=[]`）：模型漏产出 → 内核自动补
  `doc.generate_report`；漏发送 → 自动补 `mail.send`（走审批），`stop_reason="fallback"`、
  `run.completed.fallback_actions` 可观测。
- 错误 Key：`run.started {mode:"mock", engine:"mock", degraded:true}`，
  主链路（计划 → 工具 → 审批 → DOCX）仍完整走通，产物可下载（37,258 字节）。
- 真实模型测试：6 次工具调用，5 次模型调用，`tokens=14130`，`cost_cny=0.03453`。
