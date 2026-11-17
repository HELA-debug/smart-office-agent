# 上线前检查清单

只记录**上线时必须处理、但现在不该动**的事项。每条都写明为什么现在不处理——
否则下次有人看到「mock 还在」，会以为忘了删。

## 1. 关闭 mock（演示引擎）

**现状**：`MockEngine` 是脚本化引擎，设置页可以切「演示模式（不联网）」。它现在有两个用途：
本地演示、以及真实供应商全部探测失败时的降级兜底。

**上线要做**：

- [ ] 设置页隐藏 mock：`provider` 下拉去掉 `mock`（`frontend/src/features/settings/SettingsPage.tsx`），
      `mockMode` 开关整块拿掉。
- [ ] 后端强制 `MOCK_MODE=false`，且不允许运行时改成 true（否则用户能自己切进假回答）。
- [ ] 供应商全挂时**不要**降级到 mock——回一段脚本话让用户以为是模型答的，比直接报错更伤信任。
      改走 `degraded` 明示 + `run.failed`/`model_unavailable` 文案。
- [ ] 保留 `MockEngine` 代码：单元测试、离线演示、CI 都要用；只是不暴露给终端用户。

**为什么现在不删**：删掉就没有降级链路、也没有不联网可跑的测试与演示，
且真实模型不可用时界面会直接白屏。

## 2. 模型与配额

- [ ] `.env` 用生产 Key，`MODEL_NAME` 固定为正式档位，关掉 `MODEL_FALLBACK_CHAIN` 里的 `mock`。
- [ ] `model_token_budget` 按租户/账号设定上限，避免单轮跑飞。
- [ ] 确认理解层（`reading.py`）的额外调用已被计入成本看板（每轮一次，约 300–800 tokens）。

## 3. 审计与数据

- [ ] 回收站保留期、产物磁盘配额、日志脱敏（不要把素材正文写进日志）。
- [ ] `file.delete` 的审批规则在生产必须开启（`APPROVAL_RULES` 含 `file.delete`）。

## 4. 质量门槛

- [ ] `python scripts/eval_reading.py` 的**危险错误必须为 0**（误生成文件的唯一入口）。
- [ ] 概率类回归跑一遍 `docs/acceptance.md` 的验收项。
