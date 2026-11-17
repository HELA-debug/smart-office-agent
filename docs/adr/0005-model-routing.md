# ADR 0005：模型路由（DeepSeek 默认 + OpenAI 兼容多供应商 + fallback）

- 状态：已采纳（V2.1 B4）
- 日期：2026-10-23
- 决策人：A（后端 / Agent 内核）
- 影响面：模型接入、成本、降级策略、设置中心、审计用量

## 背景

V2.0 只有 mock 与单一 OpenAI 兼容接口，无法证明「可替换」；V2.1 决策 D1 要求：
**DeepSeek 为默认**，通义千问（DashScope）与智谱 GLM 的 Provider 接口保留（OpenAI 兼容、可切换/fallback），
Key 只存引用，不允许明文入库/日志/API 回显。

同时真实模型输出不稳定，演示与 CI 必须能在无 Key/断网时降级，不能阻塞主链路。

## 决策

1. **Provider 协议化**：`ModelProvider` Protocol（`chat` / `probe` / 能力探测），
   `providers/base.py + registry.py` 提供 OpenAI 兼容通用实现；
   新增供应商 = 一个 Provider 类 + 配置，不改路由器。
2. **默认供应商 DeepSeek**（`MODEL_PROVIDER=deepseek`、`MODEL_NAME=deepseek-chat`，
   Base URL `https://api.deepseek.com/v1`）；千问/GLM/OpenAI 通过同名 OpenAI 兼容接口接入。
3. **fallback 链**：`MODEL_FALLBACK_CHAIN=deepseek,qwen,glm,mock`。
   依次尝试：错误分类 → 重试 1 次（backoff）→ 切下一家 → 全部失败抛 `ModelUnavailableError`
   → 引擎降级到 MockEngine，事件带 `degraded=true`，`run.completed.stop_reason` 记录原因。
4. **Key 只存引用**：`ModelConfig.api_key_ref` 只允许 `env:NAME`；设置 API 只返回
   `configured/ref`，不返回明文；日志与事件对敏感字段 `sanitize()`。
5. **超时/熔断/成本**：`MODEL_TIMEOUT_SECONDS`、单次重试、供应商熔断冷却 60s；
   价格表 `backend/config/model_prices.yaml`（元/百万 tokens），每次调用累计
   `input/output/total tokens` 与 `cost_cny`，写入 `run.completed.usage/run/user 审计`。
6. **步数与预算上限**：`MODEL_MAX_STEPS`（默认 8）与单 run token 预算（200k）双重保护；
   超限以 `stop_reason=max_steps|token_budget` 正常收尾并保留产物。
7. **展示降级状态**：`/health` 返回 `mode/engine/engine_effective/degraded/provider/model`；
   前端顶部提示「演示模式」；`run.started.mode=real|mock` 明确本次实际使用引擎。

## 备选方案与不采用原因

| 方案 | 不采用原因 |
|---|---|
| 只接 DeepSeek，不做多供应商 | 无法验证「可替换/可 fallback」，供应商故障即演示失败 |
| 用 LangChain 统一抽象 | 依赖树大、版本耦合；本版只需 OpenAI 兼容最小协议 |
| 接非 OpenAI 兼容原生 SDK（各家私有格式） | 工具调用格式差异大，15 人日内无法稳定归一 |
| 设置页存明文 Key（DB） | 违反安全规则（Key 只存引用），泄露风险高 |
| 真实模型失败直接让运行失败 | 演示/CI 不稳定；应降级 mock 并明确标注 |

## 影响与代价

正面：

- 一家故障自动切下一家；全部不可用仍能 mock 完成主链路并标注。
- 成本可观测（tokens/成本进 run 与审计页）；演示可控（默认 mock）。
- 新增供应商/模型只需注册 + 配置，不改业务与事件协议。

负面：

- 供应商质量差异（工具调用正确率）需要实测；本版只验证 DeepSeek 真实链路。
- fallback 的「重试/熔断/降级动作」增加状态复杂度（由 `stop_reason/fallback_actions` 记录）。
- 真实模型成本与速率限制需在演示/联调时控制（默认 mock）。

## 验证方式

- `/health` 显示 provider/model/mode/engine_effective；无 Key 时 `degraded`/mock。
- 真实 DeepSeek 运行证据：`backend/tests/evidence/real_deepseek*.json`（工具调用、审批、DOCX、tokens≈14.8k）。
- `pytest backend/tests/unit/test_model_router.py test_provider_adapters.py` 覆盖 fallback/重试/成本。
- 安全：`GET /settings`、`GET /models`、探测失败原因均不含明文 Key（契约测试断言）。
