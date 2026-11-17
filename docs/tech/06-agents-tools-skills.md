# 06 · 引擎 · 模型 · 工具

> 事实来源：`backend/app/agents/`、`backend/app/providers/`、`backend/app/tools/`、`backend/app/subagents/`

## 6.1 runtime — 引擎选择与降级判定 ★

`agents/runtime.py` 是运行时装配与"到底用哪个引擎"的裁决处。

### `prepare_engine()`（`:87-133`）

```text
expected_real = not mock_mode and provider != "mock"

if force_mock or not settings.real_model_configured:
    建 MockEngine
    degraded = False if force_mock else (self.degraded or expected_real)
else:
    真实模式 → await router.probe_chain()   （60s 缓存）
    探测通了 → 复位 degraded = False 并清空 degraded_reason
    全失败   → degraded = True + 记原因 + 建 MockEngine
```

> 历史坑：以前失败时只 `set degraded` 不清，导致进程重启前一直跑 mock，用户以为在跟大模型说话。现在**探测成功必须显式复位**。

### 关键结构

| 成员 | 作用 | 行号 |
|---|---|---|
| `AgentRuntime` | 持有 `degraded` / `degraded_reason` / `git_sha` / `extra` | `:70-84` |
| `EngineSelection(engine, mode, degraded, provider, model)` | 一次选择的结果 | `:61-67` |
| `health()` | 返回 status/version/**git_sha 与 git_sha_live**/mode/provider/model/degraded/degraded_reason/tools/subagents/skills/engines/approval_tools | `:136-159` |
| `load_prompt(name="system.md")` | 读提示词，正则抽 `version:`，剥掉首个 HTML 注释块 | `:171` |
| `read_skill(path)` | SKILL.md frontmatter 解析（已安装技能与技能库共用） | `:202` |
| `load_skills()` / `load_catalog()` | 扫 `*/SKILL.md`；技能库额外带 `slug` 与 `content_chars` | `:220` / `:240` |
| **`build_runtime(settings, storage)`** | 装配入口：提示词 + 技能 + 子智能体 + 工具 + 门控策略 + `ModelRouter` | `:261-292` |

常量：`PROMPTS_DIR = app/prompts`、`SKILLS_DIR = app/skills`、`CATALOG_DIR = app/skills_catalog`。

## 6.2 engine_protocol — 引擎接口

```python
class AgentEngine(Protocol):
    name: str
    def run(self, ctx: RunContext) -> AsyncIterator[EngineEvent]: ...
```

**唯一接口方法就是 `run`**。新增引擎（如 `deepagents`）只需实现该协议并在 `registry.py` 工厂里返回，事件协议/工具注册表/门控策略都不用动。

| 成员 | 说明 | 行号 |
|---|---|---|
| `RunContext` | 28 个字段：thread_id/run_id/trace_id/message/mode/model/degraded/messages/artifacts/approvals/tools/approval_tools/uploads/output_format/prompt_extra/project/approval_mode/history/context_summary/context_meta 等。`approvals` 与 `approval_tools` 只是**保留字段**（事件契约里 `run.completed.approvals` 仍是必填，引擎固定发空数组），审批卡这一层已经拿掉 | `:21-58` |
| `APPROVAL_MODES` | `always_ask` / `risky` / `all_allow`；`normalize_approval_mode()` 非法一律回落 `risky` | `:61` / `:64` |
| **`approval_mode` 的含义** | 不是「弹不弹卡」（没有卡了），而是**门控给多少善意推定**：它只调放行线，见 `policy.MODE_BARS` | — |
| `EngineEvent(event, data, comment=None)` | `comment` 是 SSE 心跳，**不落库** | `:91-97` |

## 6.3 上下文窗口（context_window.py）

| 默认值 | 值 | 行号 |
|---|---|---|
| `DEFAULT_MAX_TURNS` / `MAX_CHARS` / `MAX_TURN_CHARS` / `SUMMARY_CHARS` | 8 / 6000 / 1200 / 800 | `:33-36` |

| 方法 | 要点 | 行号 |
|---|---|---|
| `collect_turns(messages)` | 扁平消息聚成交替轮次，**按 `run_id` 分组**（时间戳只到秒，同秒内顺序不可靠）；`run_summary` 不进上下文；**没有助手回复的半截轮次丢弃**（否则重试时模型看到同一句出现两遍） | `:83-118` |
| `summarize_turns()` | **抽取式摘要，不调模型**；倒着写再翻回来，预算不够优先保最近 | `:127-149` |
| `build_plan()` | 从最近往前装；**最近一轮无论多长都要留下**（kept 为空时继续），否则"刚说完就失忆" | `:152-188` |
| `ContextPlan.meta()` | 产出 `context.compacted` 事件 data（turns_total/kept/dropped/summary_chars） | `:72` |

## 6.4 mock_engine — 演示引擎

`class MockEngine`（`name = "mock"`，646 行）。生成的是**固定模板的假步骤**，让演示完整可看。

步骤序列：

```text
run.started → 思考流 → opening 旁白（channel=process，不落库）
→ plan.updated(t1 in_progress)
→ file.list → tool.finished
→ plan.updated(t1 completed, t2 in_progress)
→ file.read（subagent_status="running"）→ tool.finished
→ 有素材则 doc.analyze_material（真跑 python 子进程，只读不写盘，故不过门控）→ tool.finished
→ 决定模板与标题 → 第二次思考（讲"为什么用这个模板"）
→ plan.updated(t3 in_progress)
→ doc.generate_report（走门控，放行即执行——不再挂起等授权）→ artifact.ready
→ 正式回复 + plan.updated + run.completed
```

| 细节 | 说明 | 行号 |
|---|---|---|
| 节奏 | `_pause(speed, factor)`，由 `mock_model_speed`（默认 0.05）控制 | `:644` |
| 思考模板 | `THINKING_TEMPLATE` **开工前只讲方法，不编交付物细节** | `:61-65` |
| 周报识别 | `WEEKLY_REQUEST_WORDS = ("周报","日报","月报","报告")` | `:68` |
| 扩展钩子 | `_enrich()` 可被子类覆盖（mock 不做事） | `:87` |

## 6.5 real_engine — 真实 LLM 引擎 ★

### 常量

| 常量 | 值 | 含义 |
|---|---|---|
| `MAX_STEPS_HARD_LIMIT` | 200 | 步数硬上限（与 `model_max_steps` 取小），只防死循环 |
| `OBSERVATION_LIMIT_CHARS` | 4000 | 普通工具回执超此长度转摘要 |
| `MATERIAL_OBSERVATION_LIMIT` | 24000 | `file.read` 正文注入上限 |
| `PASSAGE_OBSERVATION_LIMIT` | 8000 | `file.search` 片段注入上限（单独一档：片段是已选过的高相关内容，按通用上限截会只留第一条依据） |
| `RESPONSE_CHUNK_CHARS` / `THINKING_CHUNK_CHARS` | 12 / 12 | 流式切片粒度 |
| `THINK_THOUGHT_MAX_TOKENS` | 360 | 思考过程独立调用的 token 预算 |
| `READ_STEPS_BASE` / `READ_STEPS_PER_FILE` | 2 / 2 | 只读档步数配方：首尾各一步 + 每份材料两步 |
| `DRAFT_STEPS_BASE` | 3 | 商量档：读 + 成文 + 每份材料一步 |
| `RESTATE_PROMPT_LIMIT` | 120 | 复述注入上限（第二道闸，第一道在 `reading.GOAL_MAX_CHARS`） |

### 主循环 `run()`（`:226-397`）

```text
1. _reset + normalize_approval_mode + router.begin_run()
2. router.ensure_available() 为假 → 整条运行降级 _run_as_mock
3. 发 run.started（带 provider/engine）
4. read_turn() 读懂这一轮（意图层，另有一次模型调用，purpose=reading）
   └ reading.needs_confirm → 把 reading.question 当 reply 发出去 → run.completed(awaiting_user) → return
4b. 发首帧 plan.updated
5. _compose_thought() + _stream_thinking()   ← 先输出思考过程
6. _initial_messages(ctx) + tools.openai_tools()
7. for step in 1..max_steps:
     result = router.chat_with_tools(messages, tools, temperature, max_tokens)
     有文本 → _stream_text（还有 tool_calls 时 channel=process 旁白，否则 channel=reply 正式回复）
     无 tool_calls → finished_normally = True，break
     否则 → _assistant_message 入 messages + _execute_tool_calls
     每轮检查 token 预算
8. _reliability_fallback()
9. _mark_plan_done + 终帧 plan.updated
10. 发 run.completed（含 stop_reason / fallback_actions / usage）
```

> **第 4 步的追问必须真的说出去。** 早退分支曾经只发 `run.completed`
> （`stop_reason=awaiting_user`），`reading.question` 从没进对话流：用户连发三条
> 「你咋不做修改」一个字都收不到，而理解层那次调用已经扣了钱。判据是「用户收到了
> 一句话」，不是「我们内部做了判断」——所以这里走 `_stream_text(channel="reply")`，
> 让问句进 messages 表；`question` 意外为空时用一句通用追问兜底，不允许静默收尾。

### `_initial_messages()` 的两段式：稳定前缀 + 本轮尾段 ★

拼接被拆成两个函数，边界就是这个规则本身：

```text
_stable_system(ctx, delivery)                 ← 只放「按档位固定」的内容
  基础提示词 → CONSULT_RULES
  → chat : READ_TOOLS_BRIEF → CHAT_REPLY_RULES
    read : TOOL_RULES → READ_REPLY_RULES
    draft: TOOL_RULES → DRAFT_TOOL_OVERRIDE → DRAFT_REPLY_RULES
    deliver: TOOL_RULES → DELIVERY_RULES →【产物格式】→ REPLY_RULES

_turn_tail(ctx, delivery, reading)            ← 只放「每轮都变」的内容，顺序固定
  RAG_RULES（有素材才给）→ prompt_extra（本轮路由规范）
  → context_summary（更早对话要点）→ 授权状态（最后一个）
```

**强约束**：`_turn_tail()` 的返回值是 system 的最后一节，只允许往它里面追加，
禁止把里面的内容挪回 `_stable_system()`，也禁止在它之后拼任何东西。理由两条：

1. **缓存**：DeepSeek 认**前缀**，前缀一变整段按未命中收费（¥1–2/百万，命中 ¥0.02–0.04）。
   每轮都变的内容一旦散落在前面，后面几段稳定内容全部跟着作废。
2. **冲突**：尾段里都是**本轮**的口径（有没有素材、授权到哪一步、本门类怎么做）。
   夹在中间时，后面又接上「用户要文件就落盘」这类固定规矩，模型看到的就是两句
   互相打架的话，只能挑一句执行——线上表现为行为忽左忽右，提示词读起来却完全正常。

历史上这里踩过一次 0% → 96% 的缓存命中率（把 `prompt_extra` 插在 `REPLY_RULES`
之前），两轮成本 ¥0.019 / ¥0.016。现在的结构把这条经验变成可执行的边界，
而不是一句注释。

### 说人话：内部术语不许漏到回复里

模型会复述它在提示词里看到的词。以前 `system.md` 和 `TOOL_RULES` 里写「六节骨架」，
线上回复就真的说「改回六节骨架 / 三段结构」——用户没读过我们的文档，看到这四个字
只会停下来猜，然后就不看了。**提示词里的行话，迟早会变成用户脸上的一脸问号。**

所以规则放在两处，而不是一处：

- `system.md` 的「# 说人话」：给对照示例（说「摘要、进展、数据这几节」而不是「六节骨架」；
  说「小节标题不居中」而不是「heading 对齐」），并列出禁止出现的词
  （骨架 / 版式引擎 / preset / body / outline / blocks / 词表 / 渲染器）。
- `REPLY_RULES`：收尾答复再收一次——讲结构就把节名念出来，不要用内部叫法。

提示词自身也要清：`TOOL_RULES` 里的「六节骨架」已改成「最常见的周报分节（摘要 / 进展 /
数据 / 风险 / 下周计划）」，`doc-layout` 技能里「写文档也不会每篇都六节」改成「每篇都长成
一个样」。只要这个词还出现在模型读的文本里，它迟早会说出来。

配套的两处约束：

- **复述截断**：`reading.restate` 注入前过 `_clip_restate()`（120 字，超长补「…」）。
  它贴在用户消息最末尾，最长的那段会盖住目标本身，还让每轮输入多付一截钱。
- **商量档覆盖 `TOOL_RULES`**：`DRAFT_TOOL_OVERRIDE` 紧跟在 `TOOL_RULES` 之后，
  明写「本回合禁止调用任何写文件工具，即使需求提到产出文件，仅输出方案文本」。
  只切档不改工具约定是不够的——那一大段里「用户要文件就调 doc_generate_report」
  还在生效，模型读到「周报」两个字就会照那条办。

### 工具调用循环 `_execute_tool_calls()`（`:523-689`）

```text
tools.resolve(name)
→ _clean_args（只保留 schema 声明的参数，容忍模型多传）
→ 未注册 → 发 tool.finished(ok=False) 并回 observation（不中断运行）
→ spec.effect_kind(args) → decide_write(...)：不放行就发 tool.finished(skipped)，不执行
→ 发 tool.started
→ await asyncio.to_thread(spec.handler, tool_ctx, **args)   ← 同步工具放线程
→ 异常 → 转 error.code="TOOL_ERROR"，不中断运行
→ 发 tool.finished
→ 按「本次新登记了哪些产物」补发 artifact.ready（artifacts_before 差集）
→ _advance_plan
→ observation 入 messages（file.read 额外注入 _material 正文）
```

| 细节 | 说明 |
|---|---|
| 计划推进 | `_advance_plan(tool, ok)` **按"做到哪一步"推进，而不是按工具名硬编码**；`doc.generate_report`/`code.run_python` 落地后直接收口 |
| 模型计划优先 | 模型写了 `todo.write` 就以模型计划为准（`_current_plan` `:470`） |
| 消息 id | `f"{run_id}_m{suffix}"`，保证跨 run 唯一 |

### 门控与脚本执行怎么接上 ★

这一轮把「审批卡」整层删掉了，理由是它同时坏了两件事：

1. **对话流被切碎**。工具流水 → 思考过程 → 方案卡 → 又插一张带两个按钮的审批卡，
   用户一眼扫过去分不清哪块是要他动手的地方。
2. **拦下时前端显示「脚本执行失败」**。门控没放行发的是
   `tool.finished(ok=False)`，界面一律画成失败——事实是「它决定先不做」，
   观感却是「这软件跑脚本老失败」。点一次按钮的麻烦还能忍，**把"没动手"说成
   "失败了"忍不了**：用户会开始怀疑产物到底有没有出来。

所以现在只有两条路：**按他的话办，或者不做并说明**。没有人被拉进来点按钮。

```text
spec.effect_kind(args)  ← 这一次落在哪一档（读 / 写产物 / 动已有文件）
  → decide_write(risk, reading, effect=…, continuing=…, mode=…)
      ├ 放行     → 执行
      └ 不放行   → tool.finished(ok=False, skipped=True, output.reason="<gate.reason>")
                   ＋一句人话摘要（"这一步先没动：还没听到你说动手"）
                   模型收到 hint，改成「说打算 + 问一句」，本轮继续
```

| 事实 | 对应字段 | 前端怎么显示 |
|---|---|---|
| 门控没放行 | `ok=False, skipped=True` | 「这一步先没动」+ 原因，**不是失败色** |
| 执行时抛异常 | `ok=False, error.code="TOOL_ERROR"` | 失败，错误详情收进展开层 |
| 同一工具后面成了 | 由 `selectRetriedIds()` 派生 | 「已重试」，不计进「×N 步失败」 |

最后一行是这轮的另一半工作：**返工不该摊到用户脸上**。一次运行里模型先试了个
写法没成、换个写法成了，是它自己的事；把两次都画出来、还统计成「×2 步失败」，
用户只会觉得「这软件不太行」。

> **为什么不再问一句「要我现在做吗」**：那本质上是不信任自己的判断，把决策成本
> 转嫁给用户。门控已经按「他这句话到底让没让你动手」逐次判过，放行就意味着
> 那句话本身是授权；再问一遍等于同一件事问两次，点久了就是闭眼点。
> 判不准的时候，正确做法是**不做并说明**，而不是弹一张卡让他替我们拍板。

### 写权限门控 `policy.decide_write()` ★

先回答一个问题：**这一次调用会动到什么**。答案不是工具名，是调用本身，而且是三档：

| 效果 | 含义 | 例子 |
|---|---|---|
| `EFFECT_READ` | 只读，不碰盘 | `file.read`、`os.listdir` 脚本、打印统计 |
| `EFFECT_OUTPUT` | 往产物目录写一份新的 | `doc.generate_report`、`make_pdf()`、`to_excel()` |
| `EFFECT_DESTRUCTIVE` | 动已有文件（删 / 改名 / 覆盖） | `file.delete`、`os.remove`、`shutil.rmtree` |

档位由 `ToolSpec.effect_kind(args)` 给出，**没声明效果的 high 风险工具按
`EFFECT_DESTRUCTIVE` 处理**——认不出这一步会动什么，就没资格替它担保。
以前只有「写 / 不写」二元，「再生成一版」和「把旧稿删了」走同一道门槛，
后者一句「你看着弄」就放过去了，而它做完收不回来。

`code.run_python` 两头都干——打印 PDF 页数是一件事，生成 PDF 是另一件事。
所以它带一个效果分类器（`tools/builtin/code.py::_script_effect`），AST 扫一遍脚本：
`open(..., "w")` / `save()` / `to_excel()` / `make_pdf()` / `shutil.copy` 算
`OUTPUT`；`os.remove` / `shutil.rmtree` / `unlink` / `subprocess.*` 算
`DESTRUCTIVE`。**先判 destructive 再判写**——`os.remove` 同时出现在写词表里，
顺序反了删除会被当成普通写盘。判不出来（语法错、模式是算出来的）按 destructive 办。

**落盘入口不一定叫 `save`**，这是踩过的坑：线上一条脚本用 `PdfWriter.write()`
写出了 PDF，词表里没有 `write`，于是被判成只读——既没过门控、也没弹审批，文件
直接落盘。所以词表补了三类：`writer.write(...)`（排除 `sys.stdout/stderr`）、
`doc.build(...)`（reportlab 的落盘入口），以及 `_WRITE_CTORS`（`PdfWriter` /
`SimpleDocTemplate` / `Workbook` / `Presentation` 这些「构造即写」的类；
`Document()` 无参算写、`Document(path)` 算读）。回归方法：把库里所有历史脚本捞出来
重算一遍，看「产出了文件却判成只读」是否为 0——现在 80 段脚本里那条 0 命中，
唯一的反例是脚本只打印目录、文件由前一步产出。

档位（`MODE_BARS`）调的是**放行线**，不是「弹不弹卡」——卡片已经没有了：

| 档位 | `authorized` 线 | `direct` 线 | 人话 |
|---|---|---|---|
| `always_ask`（谨慎） | 0.85 | 0.85 | 模棱两可就别动 |
| `risky`（标准） | 0.72 | 0.75 | 说出口就算数 |
| `all_allow`（放手） | 0 | 0 | 别拿把握度挡他 |

按顺序过九道，前面全是「拦住」，只有命中某条才放行：

| 顺序 | 条件 | reason |
|---|---|---|
| 1 | 低风险（写任务计划这类，不碰用户文件） | `low_risk` |
| 2 | 句子里写着「先别 / 我点头了再 / 只是问问」 | `hold` |
| 3 | 句子里写着「算了 / 不用了」 | `retracted` |
| 4 | 档位是 `all_allow`（他自己把门开到最大） | `all_allow` |
| 5 | 会动已有文件，且 `commitment=authorized` 且把握 ≥ 0.85 | `authorized` / **`destructive`** |
| 6 | `commitment=authorized` 且把握 ≥ 档位线（消息 > 1200 字再抬到 0.85） | `authorized` / `unsure` / `long_message` |
| 7 | `commitment=proposed`，但本轮已有产物且 `stance=direct` | **`continuing`** |
| 8 | `commitment=proposed` | `not_committed` |
| 9 | `stance=direct` 且把握 ≥ 档位 `direct` 线 | `direct` |

要点：

- **确定性信号只做减法**。「他说了『行』」授权了什么，只有结合上一轮才知道；而
  「他说了『先别』」是自足的。放行一次的代价是一份没人要的文件，多问一句的代价
  是半句话。
- **第 7 道是这一轮体感改善的关键**：「标题再深一点」这种话，理解层判 `proposed`
  （他是在提要求，不是在授权），按老逻辑每一步都要重新授权一次，用户的感觉就是
  「改个颜色它又在拦我」。既然本轮已经有一份他认可方向的产物，这句话本身就是
  改动指令——`continuing` 放行，不再问。
- **第 5 道宁可错拦**：删除 / 覆盖是唯一「做完收不回来」的动作，一句「你看着弄」
  能担保「再生成一版」，担保不了「把旧稿删了」。这条线不看档位，`all_allow` 之外
  一律 0.85。
- **拦下也留痕**：`tool.finished(ok=False, skipped=True, output={skipped,reason,gate})`，
  摘要走 `_gate_card_note()` 翻成一句第二人称的话（"这一步先没动：还没听到你说动手"）。
  不用 `policy.reason_label()`：那是第三人称（"他还在商量"），而看的人就是"他"。
  前端据此把这一步画成「没动」而不是「失败」——`skipped` 不算失败，也不计入
  「×N 步失败」。
- **判据挂在句子上，不挂在模型的分数上**：模型把「这几份材料我想整理成摘要」读成
  authorized 时把握通常只有 0.6 上下，正好卡在放行线之下，于是不放行、也不问。
  这是有意的：他只是在说一个打算，我们没有资格替他把「打算」当成「下令」。
  相应地，词表必须收全授权转移这一类：「你看着调 / 你看着办 / 你拿主意 /
  你说了算 / 看着来吧」都在 `_HANDOVER_RE` 里，漏一个的后果不是「多问一句」，
  而是「明明说了算却还是不动」——实测「你看着调一下吧」被判 authorized/0.62。
- **撞门两次就关闸**：`_write_disabled` 之后本轮不再走门控，直接回 `write_disabled`。
  模型不会因为一句"别再试"就停手，它会换个工具名再来。
- **确定性层回答的是两个不同的问题，别混成一个**：

  | 函数 | 回答 | 认什么 | 用途 |
  |---|---|---|---|
  | `commit_verdict` | 他**决定了**没有 | 决策陈述（就按这个 / 直接生成 / 生成吧 / 落盘） | 能不能写盘 |
  | `order_verdict` | 他有没有**让我做** | 上面那些 + 直接下令（把标题居中 / 删掉第二段） | 只记 `goal`，不给权限 |

  语料 45 条 authorized：前者召回 7 条（16%），后者 24 条（53%），误判都是 0。

- **理解层落地前有两道校正，方向相反、都不能省**（`reading._settle`）：

  | 顺序 | 函数 | 方向 | 触发 |
  |---|---|---|---|
  | 1 | `apply_hold` | 往下压 | 他说「先别 / 只是问问 / 我点头了再」 |
  | 2 | `apply_commit` | 往上抬 | `commit_verdict` 命中 **且** 有上文 |

  为什么抬这一道必须有：`commit_verdict("你生成吧")` 是 True，但模型的 JSON 说
  `proposed`，于是 `delivery=draft`、提示词要求"最后问一句"、门控也拦——用户得到
  的是「你说『就这样』我就出」。确定性判据已经逐条排掉否定/假设/引述/句尾疑问，
  在这件事上它比模型的犹豫可靠。抬档要求"有上文"，是因为短句里的「这个 / 这样」
  需要指代对象；第一轮就一句「按这个来」仍然交给模型。
  两道顺序不能换：「先别生成吧」白名单不成立，压完停住；「先别管格式，直接生成吧」
  被抬回来，与"明确指令优先于叫停"一致。
  看着后者更好用，但**兜底只认前者**——祈使句缺的不是语气，是**范围**（哪份
  文件、哪一段）。`fallback_reading` 里没人替他翻历史确认，按 `order_verdict`
  放行就是对着猜出来的文件动手。所以它只把「要做什么」写进 `goal`：
  理解模型挂了时，模型至少知道任务是什么，而不是回一句"你想做什么"。
  `test_fallback_never_guesses` 钉着这条，改动时别绕过。

### 可靠性兜底 `_reliability_fallback()`

模型"说完就停"时补做交付。**两把钥匙同时转到底**才补：

```text
条件：命中 EXPLICIT_BUILD_MARKERS（用户话里）或 PROMISE_MARKERS（模型话里）
    且 reading.commitment == authorized
    且 未命中 hold_verdict（先别 / 我只是问问）
    且 未命中 MODEL_REFUSAL_MARKERS（模型说做不了）
    且 无 artifact 且 有素材
→ 补 doc.generate_report（走门控），成功则 stop_reason="fallback"
→ 先补生成再说话（这样收尾这句话能带上文件名）
```

> 为什么必须叠：单看 marker，「就按这个格式改标题」也含「就按这个」；单看
> `authorized`，「跑个脚本统计字数」同样判成 authorized，于是补出一份周报。
> 两条都是线上真出过的「文件乱生成」。
>
> `commitment == proposed` 直接跳过——他还在商量，兜底补动作等于替他拍板。
>
> 跳过时日志必带 `marker`（命中的短语原文）与 `skip`（`no_marker` / `hold` /
> `proposed` / `no_commit` / `model_refused`），事件名按 skip 分列。线上复盘
> 「这份文件为什么冒出来」时，第一个要回答的就是「哪句话被当成了命令」。

### 步数 `_max_steps_for(delivery, breadth)` 与全局上限

```text
起步预算（跨过只记日志，不打断）
chat    : 2（有素材 3）
read    : 2 + 2×份数，封顶 model_max_steps
draft   : 3 + 份数，封顶 model_max_steps
deliver : model_max_steps

主循环跑的是全局上限 _max_steps()（默认 60，硬顶 200）。
```

**步数不是给用户的东西**。以前走到起步预算就 exit，还要往聊天流里发一句
「这一轮到步数上限了，还要改的地方你说一句」——把自家预算变成用户的活。现在跨过
起步预算只记一条 `run_auto_continue` 日志，自动续跑，直到模型给出不带工具的最终答复；
`token_budget` / `max_steps` / `no_progress` 也只写 `stop_reason` 与日志
（`skip=no_user_note`），界面上不出现任何「步数 / 上限 / 预算」字样。

放开车之后的刹车是**有没有新信息**：连续 4 步同样的工具调用 + 同样的旁白判空转，
而不是再数一次步数。8 → 24 → 60 的两次上调都是同一个原因：「读 N 份材料 → 检索核对 →
写 → 自查 → 改一版」十几二十步是常态，卡在 24 会在收尾前把任务掐断，用户看到的是
「做了一半的文件」。真实模式下默认 60 而不是硬顶 200，仍然只是给成本留余量。

只读档的**起步预算**不比交付档紧。以前它被封在 6 步：便宜的档位反而更紧，
而它跑不完的代价是模型拿前两份的内容把第三份「补」出来——「没读到」写成
「没有」，从成稿里根本看不出来。多跑几步只花几毛钱 token。

### 收尾文案 `_closing_text()` / `_closing_note()`

`_emitted_text` 为 False（整轮没有一条 `channel="reply"`）时兜底要说一句话。
判据不是「有没有说过话」，而是「为什么停」——先后顺序越靠前的越不是用户的错：

```text
有产物            → 报文件名（唯一一种可以宣布完成的）
门控没放行         → 按 gate.reason 分五句（先别动 / 已撤回 / 消息太长 / 没把握 /
                     会动已有文件）——一律说「我没动」，不说「失败」
no_progress       → 「绕了几圈没往前走」+ 请他说清哪份文件、哪一段
max_steps/token_budget → 「还没收尾」+ 说一声「继续」
都没有            → 聊天档「没接上话」，其他「没能给出答复」
```

`last_text`（模型说的最后一段）**照给**，后面再追加这句原因：光给 `last_text`
会让「我先读一下这两份材料」冒充结论。文案里不出现步数 / 上限 / 预算 / token。

状态位：`_last_gate_reason` 存最后一次门控原因（`_write_blocks` 只有次数），
`_write_disabled` 是撞门两次后的关闸标记。审批那一套状态位（`_approval_unavailable` /
`_approval_failed` / `_auth_asked`）随审批层一起删掉了。

### 其他

| 成员 | 说明 | 行号 |
|---|---|---|
| `_run_as_mock(ctx, event)` | 无可用供应商时整条交给 MockEngine，**跳过其重复的 run.started** | `:883-909` |
| `_degrade_midrun()` | 运行中模型不可用：发降级说明 + 收口计划 + `run.completed(degraded=True)` | `:911-947` |
| `_stream_thinking()` | 决策行：一句话（decision / error / ask），只在模型要调工具时出现；不是独立一次模型调用，也不用模板 | `:950` |
| `_stream_text(channel)` | `channel="reply"` 落 messages 表；`"process"` 不落库（重开会话只该看到问题+最终回复）。分片间隔 24ms、整段封顶 1.8s——`sleep(0)` 会让所有片子在同一帧到达，看起来是"整段蹦出来" | `:1026` |
| 按任务类型分派计划 | `PLAN_FORMAT` / `PLAN_DOC` / `PLAN_EXTRACT` / `PLAN_CODE` / `PLAN_ANSWER` + `_PLAN_KEYWORDS` | `:97-131` |

## 6.6 model_router — 供应商路由 ★

### 常量

| 常量 | 值 |
|---|---|
| `PROBE_CACHE_TTL_SECONDS` | 60 |
| `RETRY_BACKOFF_SECONDS` | 1.0 |
| `CIRCUIT_COOLDOWN_SECONDS` | 60 |
| `TOKEN_BUDGET_PER_RUN` | 200_000 |
| `RECEIPT_LIMIT` | 40 |

### 并发安全的用量计

```python
_CURRENT_METER: ContextVar[_MeterSlot | None]
```

> 改造前 `begin_run()` 换掉 `self._usage`，两个会话并发跑时 B 的 begin_run 会把 A 累计的 tokens 清零，账单与预算判断全错。改成 ContextVar 后每个 run 在自己的任务上下文里拿到自己的计；槽位带 router 身份防止多路由实例串账。

### 主流程

| 方法 | 要点 | 行号 |
|---|---|---|
| `chain(start=None)` | 顺序：`start → 主供应商 → fallback 链`，去重并去掉 mock | `:257-265` |
| `begin_run(preferred)` | 为当前任务上下文换一只新 `UsageAccumulator`（`budget=model_token_budget`） | `:343-355` |
| **`chat_with_tools(...)`** | 遍历链 → 未配置记 `skipped: 未配置（缺少 Key）` → 熔断中记 `skipped: 熔断冷却中` → `_call_with_retry()` → 成功则记 `preferred` 并复位 `_degraded`；全失败 → `degraded=True` + 抛 `ModelUnavailableError` | `:408-450` |
| `probe(provider, force)` | 单供应商探测，**60s 缓存**，探测绝不冒泡异常 | `:452-481` |
| `probe_chain()` | 逐家探测，返回 `(首个可用 provider, "")` 或 `(None, "；".join(reasons))` | `:483-497` |
| `ensure_available()` | **不发网络请求**的可用性判断（供引擎决定是否直接降级） | `:499-513` |
| `reset_providers()` | 清 provider 实例/探测缓存/熔断计时（设置改了立即生效） | `:534-543` |
| `_invoke()` | 调 provider → 算延迟 → **无 request_id 时打 `model_call_unverified` 警告** → 计价 → 累计 → 打 `model_call` 日志 | `:561-633` |
| **`_call_with_retry()`** | 见下 | `:635-681` |
| `estimate_cost(...)` | `cache_miss` 缺省时按 `prompt_tokens - hit` 算（**上限，宁高不低**） | `:683-712` |

### 调用账本 `model_calls` ★

`runs.extra.usage` 回答的是「这次运行花了多少」，**回答不了**「这个 Key 一共发了多少请求」。
后者才是能拿去和供应商控制台比的数。差额有三个来源，都不属于任何一次 run：

| 来源 | 例子 | 旧口径 |
|---|---|---|
| run 外调用 | 连通性探测、会话标题、提示词增强、技能起草 | 完全没记 |
| 失败 | 401 / 429 / 超时 | 完全没记 |
| 内部重试 | `max_tokens` 截断后放大预算再发一次 | 只记了最后一次 |

结构（`core/call_journal.py` + `infra/db/ledger.py`，表 `model_calls`）：

```python
CallEntry(provider, model, purpose, status, run_id, thread_id, request_id,
          finish_reason, input/output/cache_hit/cache_miss tokens,
          cost_cny, peak, latency_ms, attempt, error_code, error_message, created_at)
```

| 决策 | 为什么 |
|---|---|
| 记账点在 **`ModelProvider.chat` 的每次回执**，不在 `ModelRouter.__invoke` | 截断重试发生在 provider 内部的 `budgets` 循环里，按上层记账会稳定少算一半 |
| 用途走 ContextVar（`bind_purpose`），run 归属走 `bind_scope` | provider 不必知道「这是主循环还是标题生成」；`_produce` 在 task 入口绑 run_id，并发不串账 |
| `run_id` 可空 | 空值就是事实：账本里一半请求不属于任何运行 |
| `status=failed` 计入次数、金额记 0 | 对面收了请求可能也计费，但没有 usage；硬估只会让账更乱 |
| **写入时不算金额**，汇总时按现价重算 | 与 `UsageService` 同口径；价格表改一次，历史账不能自相矛盾 |
| `since` = 最早一条记录时间 | 历史请求补不回来，界面必须说清账本从哪一刻起完整 |

`UsageOut.ledger`（`UsageLedgerOut`）与 runs 口径**并列**，不合并：
`calls/failed_calls/tokens/cost_cny/since/by_purpose/by_provider/by_day`。

### 重试策略（按错误类别）

| 类别 | 行为 |
|---|---|
| `AUTH`（401/403） | **立即熔断 60s 并切换**，不重试 |
| `RATE_LIMIT`（429）/ `TIMEOUT` / `NETWORK` | 第 0 次：退避 1s 重试一次 |
| 5xx `SERVER` / `BAD_FORMAT` | 立即切换下一家 |
| `UNCONFIGURED` | 跳过 |

最多 2 次尝试（`for attempt in range(2)`）。

### 数据结构

| 结构 | 字段 |
|---|---|
| `ChatResult` | text / provider / model / prompt_tokens / completion_tokens / tool_calls / finish_reason / cost_cny / **cache_hit_tokens / cache_miss_tokens** / peak / **request_id** / latency_ms |
| `UsageAccumulator` | input/output/cache_hit/cache_miss / cost_cny / calls / by_provider / budget / receipts（≤40 条，含 `verified=bool(request_id)`） |
| `as_dict()` | 额外给 `calls_detail` / `verified_calls` / `budget` / `currency("CNY")` |

## 6.7 providers — 供应商适配器

### 支持的 5 家

| 供应商 | 默认端点 | 默认模型 | Key 环境变量 |
|---|---|---|---|
| deepseek | `https://api.deepseek.com/v1` | `deepseek-flash` | `DEEPSEEK_API_KEY`（兼容 `OPENAI_API_KEY`） |
| qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | `DASHSCOPE_API_KEY` / `QWEN_API_KEY` |
| glm | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` | `GLM_API_KEY` |
| openai | `https://api.openai.com/v1` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| workbuddy | **无公共默认值，必须用户填** | `workbuddy-chat` | `WORKBUDDY_API_KEY` |

> `deepseek-chat` 是官方会静默路由到 `deepseek-flash` 的**旧别名**。

### 错误分类（7 类）

| 类别 | 触发 | `retryable` |
|---|---|---|
| `AUTH` | 401 / 403 | 否（熔断） |
| `RATE_LIMIT` | 429 | 是 |
| `TIMEOUT` | 超时 | 是 |
| `SERVER` | 5xx | 否 |
| `BAD_FORMAT` | 缺 choices / tool_calls 不合法 | 否 |
| `NETWORK` | 连接/DNS/代理 | 是 |
| `UNCONFIGURED` | 无 Key 或 Base URL | — |

### `ProviderResult` 字段

`text / tool_calls / finish_reason / model / prompt_tokens / completion_tokens / cache_hit_tokens / cache_miss_tokens / request_id`

- `cache_hit` / `cache_miss` 用于按两档计价（单价差 50 倍）。
- `request_id` 是"这真是一次外部调用"的凭据，审计页据此统计 `verified_calls`。

### `chat()` 的空正文/截断重试 ★

```text
budgets = [max_tokens, min(max(max_tokens*3, 6000), 16000)]

对每个预算：
  _post → truncated = (finish_reason == "length")
  _parse_result(data, allow_empty=True)
  若 BAD_FORMAT 且 truncated 且还有下一个预算 → 记 model_truncated_retry 后放大重试
  若正文与 tool_calls 都空 且 truncated → 记 model_empty_retry 后放大重试
最终仍空 → 抛 BAD_FORMAT（带 finish_reason 与已放到多大的预算）
```

为什么要放大预算：

> 推理模型（如 deepseek-flash）先写 `reasoning_content`，`max_tokens` 太小时正文就是空串——**这不是故障**。而工具参数是一整段 JSON，2000 的输出预算常在参数中间被截断。

### `probe()` 的判据

> 判据是「**端点是否给出合法回执**」，不是「有没有正文」。

改之前要正文非空，deepseek-flash 必然探测失败，进而把整个引擎静默降级成 mock——用户以为在跟大模型说话，其实是本地脚本。现在用 `max_tokens=32, allow_empty=True`。

### 回执解析

| 项 | 说明 |
|---|---|
| 缓存字段 | 认两种写法：`usage.prompt_cache_hit_tokens`（DeepSeek）或 `usage.prompt_tokens_details.cached_tokens`（OpenAI） |
| miss 缺失 | 按 `prompt_tokens - hit` 推 |
| request_id | 取 `data["id"]` |
| 出网前 | `_assert_base_url_allowed()` 兜底 SSRF 校验 |

## 6.8 tools — 工具系统

### 注册机制

```python
@tool("file.read", description="...", risk=Risk.LOW)
def read_file(ctx: ToolContext, ...) -> dict: ...
```

| 机制 | 说明 | 行号 |
|---|---|---|
| 工具名规则 | 必须匹配 `^[a-z0-9]+(?:\.[a-z0-9_]+)+$` | `spec.py:140` |
| Schema 自动生成 | `build_schema(handler)` 由函数签名生成 JSON Schema：跳过首个 `ctx` 参数与 `_` 开头的私有参数；有默认值的写 `default`，无默认值的进 `required` | `spec.py:90` |
| OpenAI 名映射 | `file.read` → `file_read`（function 名只允许 `[a-zA-Z0-9_-]`）；`resolve()` 两种写法都认 | `spec.py:116` / `:195` |
| 高风险描述 | 自动追加「（高风险：执行前内核会核对这一步是否由他明确要求，没说就别硬做）」 | `spec.py:200` |
| 效果分档 | `effect_kind(args)` → `read` / `output` / `destructive`；没声明效果的 high 风险工具按 `destructive` 办 | `spec.py:112-142` |

### 工具清单

| 工具 | 风险 | 效果档 | 功能 |
|---|---|---|---|
| `file.list` | low | read | 列出会话已上传素材（文件名/字数/解析状态） |
| `file.read` | low | read | 读取素材正文；超长时返回分节目录 + 前若干块 + 剩余块数，可用 `block_ids` 补读 |
| `file.search` | low | read | 素材内检索（BM25 + 中文 bigram），返回带 `[S3]` 引用编号的片段与 `match` 档位 |
| `file.delete` | **high** | **destructive** | 删除本会话产物（软删入回收站） |
| `todo.write` / `todo.list` | low | read | 写入/读取任务计划 |
| `doc.analyze_material` | low | read | **只读**脚本体检素材结构（段落/字数/标题层级/图片/表格/关键句） |
| `doc.generate_report` | **high** | output | 生成报告产物并登记；正文可用 `body` 传整篇 Markdown |
| `code.run_python` | **high** | 由脚本 AST 定 | 受控目录执行 Python 脚本 |
| — | — | — | `xlsx.py` 当前**不注册工具**，只提供纯函数 `summarize_workbook` |

> `doc.generate_report` 是 `output`：往产物目录写一份新的，可覆盖可重跑，只要他这一轮
> 让你出文件就放行。`file.delete` 是 `destructive`：做完收不回来，所以即使档位是
> 「标准」，它也要 0.85 的明确授权。

### 文档版式 `services/doc_render.py` ★

`doc.generate_report` 的 docx 与 `.preview.html` 都从这里出。以前两条路各写各的：
docx 走 python-docx 的默认模板（宋体 12pt + 蓝色 Calibri 标题 + 零间距），
预览走 `.prose-docx`（22px 大标题居中、19/17/16px 小节左对齐并按级缩进、正文 15px 首行缩进 2em、27px 行高）。同一个文件在预览里好看、
下载下来难看，用户会以为交付件是凑的。

**一份 blocks 同时喂给两条路**：`parse_markdown(body)` 切出 heading / paragraph /
bullet / number / table / quote / code / figure / rule，`DocxRenderer` 写 Word，
`blocks_to_html` 写预览。这样「预览里有表格、下载的 Word 里表格变成几行竖线」
这类分叉从结构上就不可能发生。

| 版式 | 页面（cm） | 中文/西文 | 大标题 / 一级 / 二级 / 三级 / 正文 | 行距 |
|---|---|---|---|---|---|
| `report`（默认） | 2.2 / 2.2 / 2.4 / 2.4 | 宋体 / Times New Roman | 22（二号，居中）/ 16 / 14 / 12 / 12pt | 1.5 |
| `gongwen` | 3.7 / 3.5 / 2.8 / 2.6 | 仿宋_GB2312 / Times New Roman | 22 / 16 / 16 / 16 / 16pt | 1.5 |
| `compact` | 2.0 × 4 | 宋体 / Times New Roman | 18 / 14 / 12 / 12 / 10.5pt | 1.25 |

几条刻意的取舍：

- **标题样式用内置 `Title` / `Heading N`**，只在上面覆盖字体、字号、颜色。用 Normal 写
  「一段比较大的字」，Word 导航窗格和 mammoth 的 styleMap 就认不出标题，转出来的
  HTML 里 h1 直接丢了。
- **标题编号按文档类型走**，五套方案在 `doc_lexicon.NUMBERING_SCHEMES`：`cn`（一、／（一）／三级以下
  不编号，周报这类例行汇报）、`decimal`（1.／1.1／1.1.1／1.1.1.1，论文、方案、白皮书）、
  `article`（第一条／（一）／三级以下不编号，合同协议）、`none`（纪要与手册不编号）、
  `gb`（一、／（一）／1.／（1），只有公文类）。
  **一套方案里不许混用两种数字体系。** 「一、→（一）→1.→（1）」把汉字与阿拉伯数字串在同一条
  线上，扫标题时编号字形一直在跳，看着像两个人拼的稿。中文方案只走到「（一）」这一级，三级起
  留空模板不编号——中文没有通行的第三级纯中文序号，硬凑只能借「1.」「①」这类外来的，又混回去；
  层级靠字号、加粗与缩进区分，中文报告里本来就这样。`gb` 是唯一例外：GB/T 9704《党政机关公文
  格式》把层次序数写成「一、（一）1.（1）」，公文不这么写属格式不合规，所以只有公文类型取它。
  `resolve_numbering()` 收方案名也收文档类型名；
  `guess_doc_type()` 从标题里认类型（长键优先：「述职报告」不能被「报告」抢走）。
  **标题序号一律由渲染器统一重排**：先把作者手写的编号剥掉（`_LEADING_NUMBER`），再按方案
  数一遍。以前是「有编号就不动」，模型在汉字稿里写一节「二、」、下一节又写「2.1」，一篇里
  两套编号并排（「二、」下面挂「2.1」），看着像两个人拼的。剥的时候认「一、」「（一）」
  「1.」「1.1」「①」这几种，也认「2.1 测试数据记录」这种编号后接空格的写法；
  「3 个要点」这类数量词不剥（`_MEASURE_WORDS`）。`none` 方案不剥也不加——纪要本来就没序号。
  稿子直接从二级小节开头时，缺的上级序号按 1 补，拼出来是「1.1」而不是「0.1」。
- **层级靠缩进，不只靠编号**：一级顶格、往下每级缩 1 字符（`NUMBERING_INDENTS`，`w:leftChars`，
  按字符存而不是 pt——二号字的 1 字符和五号字的不是一个宽度）。只缩一格：正文段首本来就空
  两格，标题也缩两格会和段首撞在同一条线上，而正文续行在最左边，读起来像正文比标题还宽。
  公文由 `Preset.heading_indent=False` 整篇关掉——GB/T 9704 规定各级标题顶格，
  给公文加缩进属于格式不合规。紧凑版式不在此列：它只是「更密」，层级规则照旧。
  预览侧对应 `.doc-h1~doc-h4` 的 `margin-left: 0/1/2/3em`，
  顶格版式的 HTML 干脆不带这些类。
- **表格列宽按内容分**（汉字算两格宽），不是均分：「完成」「材料未提供」这种短列均分
  会白占三分之一版面，真正要读的那列被挤成四条窄行。
- **不再往正文写「生成时间 ｜ 模式 ｜ 来源」**。那是给我们自己看的；用户拿到手是一句
  噪音，还会把真正的第一节往下推。素材为空时也不每节写一句「素材里没有…」，
  只在标题下留一行「…框架 · 待补素材」。
- **`body` 是主路径；不给时按素材自己的小节成文**：`_split_named()` 保留每个小节的
  原标题与顺序（`[(归类键, 原标题, 行)]`），`_sections_from_material()` 照它排，
  素材没写的节不出现。六节骨架（摘要/进展/数据/风险/计划/来源）只在素材连小节标题
  都没有时兜底，且兜底时会**去掉内容重复的节**（一句带数字的进展句会被「进展」和
  「关键数据」同时命中，重复出现会让读者以为是两件事）。
- **词表外的小节也认**：中文序号打头（`一、` / `（一）`）、短、不带句读的行按小节处理
  （`_LOOSE_HEADING`）。只认中文序号——`1. 完成联调` 那种多半是列表项，认成小节会把
  一份清单拆成十节。
- **标题从内容里起**：`title_from_material()` 取素材首行（≤24 字、不带句读、不是
  「时间：…」这类栏目行、不是图注），拼成「素材标题 · 产物类型（周）」。首行是
  「工作周报」这种通用词时退回「素材名 · 类型」——通用词当标题没有信息量。
- **大标题居中、宋体、全文最大**。这三个约束是构造出来的：`Preset.__post_init__` 会把
  `title_size` 顶到「比所有小节与正文都大」——只调正文大小的人，不会顺手把标题调小。
- **整篇只有大标题居中**。一级到四级标题一律左对齐、按层级缩进（一级顶格，往下每级 1 字符）、
  不首行缩进（样式级与段落级各钉一次：样式从 `Normal` 继承两端对齐，只改段落的话脚本用
  样式写出的标题又会飘回去）。
  这条在预览里更容易踩：Word 的 `Title` 和 `Heading N` 经 mammoth 转出来**都会落到 `<h1>`**，
  `.prose-docx h1` 一带居中，正文里的「摘要 / 本周进展 / 关键数据」就全成了页面中间的
  大标题。所以 styleMap 把 `Title` 映射成 `h1.doc-title`（唯一居中、22px），`Heading 1~4`
  映射成 `h2.doc-h1` → `h5.doc-h4`（19 / 17 / 16 / 15px），与后端 `blocks_to_html` 的标签
  和类名一字不差——两条预览路径（mammoth 与后端兜底）排出来是同一个样子。
  小节标题的左对齐带 `!important`：改版前的产物里 `Heading` 存的是 `w:jc="center"`，
  mammoth 会把它转成 inline style 带进预览，普通声明压不住。
  `src/styles/prose-docx.test.ts` 直接读 `tokens.css` 卡住这条。
- **正文首行缩进 2 字符**，写的是 `w:ind/@w:firstLineChars=200`（Word 里「首行缩进 2 字符」
  就是这个字段），同时写 `w:firstLine` 兜底给 WPS / python-docx 读。存 pt 的话，
  字号一换缩进就不再是两格。
  预览这条以前漏了：规则只写在 `.prose-docx p.doc-para` 上，而 mammoth 转出来的正文是
  **裸 `<p>`**（不带类），界面里的正文全是顶格的——用户在 Word 里看到空两格、预览里没有，
  只会认为没按他说的做。现在缩进落在标签上（`.prose-docx p { text-indent: 2em }`），
  副标题 / 元信息 / 图注 / 表格与列表里的段落进白名单清零；紧凑版式反过来标 `doc-flat`。
  副标题也因此改用 `Subtitle` 样式——预览按样式名认成 `.doc-lead`，不会跟着缩进两格。
- **中文正式稿不带项目符号**：`- ` 条目一律排成正文段落（空两格分句），docx 与预览都不出
  圆点。以前只在「一组全是完整句子」时才转段落，混进一条短句整组就打回圆点，同一篇里
  一节是段落、一节是圆点，看着像排版坏了；而且 Word 里是一串 `· ` 字面量、预览里是一串
  `<ul>`，两边还不太一样。现在一条一段，两边同一份结构。有序条目把序号写进行首
  （「1. 打开电源」）——序号本身是信息，不能丢。真正并列的对照内容应该写成表格。
- **三档版式，默认只有一档**：`report`（默认）/ `gongwen` / `compact`。`compact` 跟默认版式
  是**同一套排版规则**——标题照样逐级内缩、正文照样首行缩进两格——密度靠字号（五号）、
  行距（1.25）、段距（4pt）、页边距（2cm）挤出来，预览侧包一层 `.doc-compact` 同步缩一档。
  以前它是「通篇顶格」，一页正文连成一片、标题只剩字号差异，看着像没排过版。
  用户说「紧凑 / 密排 / 资料 / 说明书 / 手册 / 附录 / flat / dense」都落到这档
  （`resolve_preset()` 认这些说法）；默认仍是 `report`——紧凑那档看着省地方，
  但当交付件的默认版式不够正式。
- **行距可整篇覆盖**：`line_spacing` 认「单倍 / 1.15 / 1.5 / 双倍 / 固定值28磅」，
  不传就跟着版式走（`services/doc_lexicon.resolve_line` 负责解析）。

### 四份格式词表 ★

每种产物格式有一份自己的词表：**字号、格这些「词」只写在这里**，工具库与版式引擎
都从这里取，改一档字号不用在两个文件里找第二遍数字。

| 词表 | 管什么 | 谁在用 |
|---|---|---|
| `doc_lexicon.py` | 字号（初号 42 → 八号 5）、字体（29 族，中英成对）、行距、首行缩进、12 套标题刻度、14 种页面、58 类文档 → 整套版式、4 套标题编号、表格样式同义词 | `docx_utils`、`doc_render` |
| `slide_lexicon.py` | 画幅（16:9 / 4:3 / 16:10 / A4 横 / 竖版）、9 种版式、字号（封面 40 / 标题 36 / 正文 20）、每页 6 条上限、5 套配色 | `pptx_utils`、`render_pptx` |
| `sheet_lexicon.py` | 数字格式（金额 / 百分比 / 日期 / 文本…）、列名 → 格式、列宽、11 类表（台账 / 汇总 / 考勤 / 库存…） | `xlsx_utils.write_table` |
| `text_lexicon.py` | 折行宽度（76 半角 ≈ 38 汉字）、分隔线、项目符号、章节标记、四级编号、5 种文本布局 | `text_utils`、`render_text` |

每份都有「认得出就照做、认不出就给默认」的解析函数（`resolve_size` / `resolve_line` /
`resolve_doc_type` / `resolve_numbering` / `resolve_font` / `resolve_layout` / `resolve_theme` /
`resolve_sheet_type` / `resolve_text_layout`）。**报错还是兜底看场合**：写脚本时认错字要报错（免得白跑一轮），
判文档类型时认不出要能继续（判错一个词不该让整份文档生成失败）。

四份词表都不进提示词的工具库清单，但随 `UTIL_SUPPORT` 一起复制进脚本工作目录——
少了任何一份，对应的 `*_utils` 一 import 就 `ImportError`。

### `code.run_python` 沙箱 ★

**它不是内核级沙箱**——脚本仍能访问本机文件系统，所以内核按最严的一档看它：
AST 扫出删除 / 覆盖就要求 0.85 的明确授权，判不出来也按 `destructive` 办。

| 机制 | 实现 |
|---|---|
| 环境变量白名单 | 只含 `PATH / SYSTEMROOT / WINDIR / COMSPEC / TEMP / TMP / HOME / USERPROFILE / APPDATA / LOCALAPPDATA / LANG / LC_ALL`——**不含任何 API Key / token** |
| 注入变量 | `OA_INPUT_DIR`=`<root>/in`（目录）、`OA_OUTPUT_DIR`=`<root>/out`、`OA_ARTIFACT_DIR`、`OA_UPLOAD_DIR`、`OA_INPUTS`=JSON 清单（含 filename/path/ext/chars，**不是目录**）、`OA_RUN_DIR` |
| 工作目录 | `<artifact_dir>/../workspace/<run_id>/{in,out}` |
| 工具库 | `UTIL_MODULES = (docx_utils, pdf_utils, xlsx_utils, text_utils)` 复制进工作目录，脚本可 `from docx_utils import *`；`UTIL_SUPPORT = (doc_lexicon, slide_lexicon, sheet_lexicon, text_lexicon)` 一并复制但不进提示词清单 |
| 子进程 | `subprocess.run([sys.executable, script], cwd=root, env=child_env, timeout=...)`；超时 `exit_code=-1` 并在 stderr 写明 |
| 超时 | `max(5, min(120, timeout_seconds))` |
| 产物登记 | 按扩展名白名单 + 30MB 上限 + **sha256 比对**（内容没变记 `unchanged` 不重复登记）+ 同名重写（旧版软删并记 `superseded`） |
| **失败不登记** | `ok=False` 时 `registered=[]`——"脚本失败也登记，半成品 docx 一打开就是坏的" |
| 缺失文件回报 | 点名了但会话里没有的文件会列进 `missing`，避免脚本 glob 空目录报 `IndexError` 看起来像代码写错 |
| 错误提示 | 取 traceback 最后一句真正的异常；`TypeError` 未预期关键字参数时把真实签名递过去；`NameError` 时用 `difflib` 找最接近的导出名（AST 读 `__all__`，不执行脚本） |

## 6.9 subagents — 子智能体

| 名称 | 状态 | 工具 | 行为 |
|---|---|---|---|
| `doc_agent` | `implemented` | `file.read`, `doc.generate_report` | 读素材 → 生成 weekly 报告 → 返回 `{ok, agent, tool_results, artifact_id, summary}` |
| `research_agent` | `placeholder` | — | 预留联网检索，当前返回 `NOT_IMPLEMENTED` |
| `sheet_agent` | `placeholder` | — | 预留表格清洗，当前返回 `NOT_IMPLEMENTED` |

注册：`@subagent(name, description, prompt, tools, status, step_limit)` → `SUBAGENT_REGISTRY`。

## 6.10 skills 与 skills_catalog

| 项 | 内容 |
|---|---|
| 已安装技能目录 | `backend/app/skills/`（10 个：data-brief、**doc-layout**、doc-qc、meeting-minutes、outline-first、**ppt-layout**、project-retro、**sheet-layout**、**text-layout**、weekly-report） |
| 技能库目录 | `backend/app/skills_catalog/`（9 个，含四份版式技能） |
| 文件格式 | `<slug>/SKILL.md`，frontmatter 含 `name` / `description` / `triggers` / `enabled`，展示用 `title` / `category` / `icon` / `badge` |
| 提示词注入 | 基础提示词 + 「# 可用技能（按需参考）」+ 各启用技能正文 |
| 启停存储 | settings 表键 `skills.disabled` |
| 删除 | 挪进 `app/skills/.trash/<name>-<时间戳>` |
| **未安装的技能不进提示词** | 技能库只供一键安装 |

四份版式技能的分工是「**规则写在技能里、词表写在 lexicon 里**」：

| 技能 | 管哪种产物 | 内容 |
|---|---|---|
| `doc-layout` | Word | 7 类文档骨架、四级标题、字号行距、表格/列表、八条自检 |
| `ppt-layout` | PPT | 页序、一页一个观点、六条上限、字号配色、八条自检 |
| `sheet-layout` | Excel | 表类型、列规范、数字格式、合计与命名、八条自检 |
| `text-layout` | txt / Markdown | 三样分层手段、折行宽度、常见文本写法、八条自检 |

技能里只写「该怎么判断」，具体字号、列宽、符号一律指向对应词表——两处各写一套，
改了一处另一处迟早对不上。

## 6.11 prompt packs

目录 `backend/app/prompts/packs`。按需求关键词自动匹配并注入本轮 system prompt：

- `MAX_PACKS_PER_RUN = 2`
- `MAX_INJECT_CHARS = 4200`
- 主提示词：`backend/app/prompts/system.md`

## 6.12 plugins（可选扩展）

`backend/app/plugins.py`：通过 `importlib.metadata.entry_points(group="office_agent.plugins")` 发现插件并调用 `register(registry)`。单个插件加载失败只 warning 不中断；已加载插件名存进 `runtime.extra["plugins"]`。当前无内置插件。
