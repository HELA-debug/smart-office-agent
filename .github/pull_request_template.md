# Pull Request

## 变更说明

<!-- 一句话说明本 PR 做了什么、为什么 -->

## 关联 Issue / 批次

<!-- 例：Closes #12 / B1 后端分层 -->

## 变更类型

- [ ] feat（新功能）
- [ ] fix（缺陷修复）
- [ ] refactor（重构，行为不变）
- [ ] test（测试）
- [ ] docs（文档）
- [ ] chore（工程/依赖/CI）

## 自检清单（提交前逐项确认）

- [ ] `pre-commit run --all-files` 通过（或说明未安装原因）
- [ ] `make test` 通过；新增/修改逻辑有对应测试
- [ ] 若涉及接口/事件：`docs/events.md`、`docs/api.md` **只追加**，`contracts/` 快照已更新且 `git diff --exit-code contracts/` 为空
- [ ] 若为破坏性变更：已升版本（`/api/v2` 或 `events version=2`）并补 ADR
- [ ] 覆盖率未下降（后端 ≥70%，前端 ≥60%）
- [ ] 无真实密钥/个人信息入库；日志已脱敏；未提交 `.env`
- [ ] 测试结束仓库根干净：`git status --porcelain` 为空
- [ ] `CHANGELOG.md` 的 `[Unreleased]` 已更新（面向用户的变更）
- [ ] 文档（README / demo / acceptance / ADR）已同步

## 验证证据

<!-- 粘贴关键测试输出、截图、演练记录（不要上传含密钥的日志） -->

```text
（粘贴 pytest / vitest / CI 输出摘要）
```

## 风险与回滚

<!-- 影响面；若不满足预期如何回滚（revert / 迁移回滚 / 开关） -->

- 影响面：
- 回滚方式：

## 评审提示

<!-- 希望 reviewer 重点看哪里；未决问题；后续 TODO -->
