# 已知问题清单（KNOWN ISSUES）

> 计划书 9.3「最小质量体系」要求所有未修问题记录在此，D9 前完成。
> 每条格式：**现象 → 影响 → 绕过方式**。演示前先读一遍。
> 最后更新：2026-11-07（补入意图三层重构后的现状；文档总索引见 [docs/README.md](docs/README.md)）

> **怎么读这份文件**：上面的汇总表是**唯一权威**。正文里第 7、13、14、15、18、19 条
> 保留的是当时的问题描述，结论已经写在汇总表里（多数是「已解决」），不要拿正文当现状读。
> 判断一条问题是否还在，只看汇总表那一行的状态列。

## 汇总

| # | 问题 | 影响 | 是否有绕过 | 计划 |
|---|------|------|-----------|------|
| 1 | 开发机未安装 Docker | 无法本地执行 `docker compose up` 实测 | 有（YAML/配置静态校验 + 本地进程启动） | 有 Docker 的机器补跑（DoD 工程第 19 条未验） |
| 2 | 开发机未安装 GNU make | `make xxx` 命令不可用 | 有（README 每条命令均给出原始命令；等价命令已实测） | 可选安装 |
| 3 | 本机无 PostgreSQL 实例 | 迁移未在真实 PG 执行 | 有（SQLite 从零 upgrade 成功；PG 语法由 Alembic 生成） | 部署机验证 |
| 4 | 单进程内跑 Agent | 长任务阻塞 worker，无法水平扩展 | 有（单人使用；超时/取消/重试） | V1.0 拆 Agent Server |
| 5 | SQLite 并发写弱 | 多实例/并发写不稳定 | 有（单实例演示；`DATABASE_URL` 可切 PG） | V1.0 换 PG |
| 6 | 无真实账号体系 | 数据不隔离 | 有（单用户演示，不暴露公网） | V1.0 加 users+JWT |
| 7 | 审批策略需重启才生效（旧版） | B3 后设置中心已支持热更新 | 已解决（`PUT /api/v1/settings` 热生效） | — |
| 8 | 无断点续跑/重试 | 进程崩溃时运行中任务丢失 | 有（事件落库 + Last-Event-ID 重放；取消/重试接口） | V1.0 启用引擎检查点 |
| 9 | 真实模型端到端 | 仅单次 DeepSeek 真实链路 PASS | 有（mock 兜底；多供应商未逐一实测） | 多供应商/长任务压测 |
| 10 | 前端移动端未适配 | 小屏布局拥挤 | 有（桌面演示 ≥1440×900） | V1.0 M4 |
| 11 | 演示依赖预置样例文件 | `data/samples/meeting_notes.docx` 缺失时 Demo 卡住 | 有（`python scripts/make_sample.py` 生成） | 随仓库生成 |
| 12 | 本机 pytest 首跑需先起后端 | 未启动 api 时 smoke 全失败 | 有（`tests/README.md` 写明；`make smoke` 自动起 mock） | 已缓解 |
| 13 | Windows 代理变量干扰 httpx | `Invalid port: ':1]'`（NO_PROXY 含 `[::1]`） | 已修（conftest 清理 NO_PROXY + `trust_env=False` + CI env） | 已解决，保留记录 |
| 14 | B0 阶段 CI 六门禁为骨架 | B1/B2 前相应 job 会明确失败 | 已校准（B1/B2/B5 文件就绪；见 #18/#20 仍待修项） | 已解决 |
| 15 | 契约快照与 Alembic 迁移 | 之前未生成 | 已解决（contracts 快照 + Alembic 0001/0002，SQLite 从零验证） | — |
| 16 | 真实模型 Key 未联调 | 之前多供应商/ReAct 未验证 | 已缓解（DeepSeek 真实 smoke PASS；千问/GLM 未逐一实测） | 后续联调 |
| 17 | **缺 uv.lock**（pyyaml 已补） | 依赖版本不可完全复现（干净安装可启动已验证） | 见下文 #17 | 补锁文件 |
| 18 | 前端生成类型一致性（已解决） | task-14 已重生成；CI 比对时去除 CLI banner 后一致 | 已解决 | — |
 | 19 | ~~前端覆盖率 < 60%~~ **已闭环（72.05%）** | DoD 工程第 13 条已达标 | — | 保留条目记录历史与门槛口径 |
| 20 | pip-audit 本机无法运行 | 本机缓存目录权限错误，依赖漏洞未本地验证 | 有（CI security job 执行；本机可设 PIP_AUDIT_CACHE_DIR） | CI 验证 |
| 21 | Playwright 依赖本机 Chrome | 无 Chrome 环境无法跑 E2E | 有（`channel: 'chrome'`；CI nightly 安装 chromium） | CI nightly |
| 22 | 用户级 `PYTHONHOME` 劫持 venv 标准库 | `.venv` 的 python 直接崩在 `import re`（`SRE module mismatch`），后端起不来 | 已解决（2026-11-08 删除该用户变量，实测干净环境启动 + health 200） | — |
| 23 | 会议转写默认用 `base` 模型（145MB，约 4 倍实时） | 同音字会错（实测「客户验收」→「客户厌收」、「交付经理」→「交付经历」），专有名词不稳 | 有（`ASR_MODEL=small` / `medium` 更准，代价是更慢、模型更大；`ASR_MAX_MINUTES` 控上限） | 按机器与场景调默认档位 |

---

## 1. 开发机未安装 Docker

- **现象**：`docker --version` → `command not found`；`docker compose version` 同样不可用。
- **影响**：DoD 第 1 条（compose 3 分钟可访问）无法在本机实测；镜像构建未执行。
- **绕过**：
  1. 用本地方式验证等价链路：`.venv` 起 uvicorn 8000 + `npm run dev` 5173；
  2. 用 `python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"` 做 YAML 语法校验；
  3. `nginx -t` 不可用时按语法逐项人工核对（`deploy/nginx.conf.template` + 三个
     `deploy/nginx-*.conf` 片段；片段必须放 `snippets/`，放 `conf.d/` 会被顶层自动
     include 而导致 nginx 启动失败，已有单测 `test_snippets_are_not_placed_in_conf_d` 兜底）；
  4. 在安装 Docker 的机器/CI 上执行 `docker compose up --build -d` 补验证。
- **根因**：环境无 Docker Desktop/engine，非仓库问题。

## 2. 开发机未安装 GNU make

- **现象**：`make --version` → `command not found`（Windows 未装 make）。
- **影响**：`Makefile` 的便捷目标无法在本机实测；不影响功能。
- **绕过**：README 对所有流程都给出**原始命令**，可直接复制；Windows 上也可安装
  `choco install make` 或使用 Git Bash 自带环境。

## 3. 本机无 PostgreSQL 实例

- **现象**：无法执行 `psql -f deploy/migrations/0001_init.sql`。
- **影响**：DoD 第 8 条的「在 PG 上跑一次迁移」未实测。
- **绕过**：`deploy/migrations/0001_init.sql` 按 PostgreSQL 语法编写并含 SQLite 兼容说明；
  可用 `docker run postgres:16`（需 Docker）或部署机验证。

## 4. 单进程内跑 Agent（架构妥协）

- **现象**：Agent 与 FastAPI 同进程（ADR 0001 的主动决策）。
- **影响**：长任务占用 worker；并发多任务时响应变慢；进程崩溃任务丢失。
- **绕过**：演示单人顺序操作；`APPROVAL_TIMEOUT_SECONDS=180` 内完成审批。
- **计划**：V1.0 按目录边界拆出独立 Agent Server，接口不变。

## 5. SQLite 并发写弱

- **现象**：SQLite 单写者锁；多实例共享同一文件不安全。
- **影响**：仅适合单机演示；多实例部署不可用。
- **绕过**：单实例运行；需要并发时把 `DATABASE_URL` 换成 PostgreSQL 并跑迁移。

## 6. 无真实账号体系

- **现象**：无 users 表、无登录/JWT，所有会话归属于「匿名单用户」。
- **影响**：无法区分用户、数据不隔离。
- **绕过**：演示环境仅本人使用。
- **计划**：V1.0 加 users 表 + JWT（约半天）。

## 7. 审批策略写死在配置

- **现象**：需审批的工具来自 `APPROVAL_RULES` 环境变量，启动时读取。
- **影响**：调整审批策略必须重启 api 进程，运行中不可热更新。
- **绕过**：修改 `.env` 后重启 `uvicorn`；演示前确认配置。
- **计划**：V1.5 抽成 YAML/DB 配置。

## 8. 无重试与断点续跑

- **现象**：运行状态只在内存/DB，无检查点；进程崩溃后运行中的 run 丢失。
- **影响**：长任务失败需从头再来；审批等待超时会 `run.failed`。
- **绕过**：失败后重新发起同一任务；审批超时错误 `APPROVAL_TIMEOUT` 可重试。
- **计划**：V1.0 启用检查点（deepagents 自带，见 ADR 0003）。

## 9. 真实模式未做端到端验证

- **现象**：CI 与本机验证均使用 `MOCK_MODE=true`；真实模型路径代码存在但未联网验证。
- **影响**：真实模式可能有适配问题（鉴权、流式解析、超时降级）。
- **绕过**：演示一律 mock；真实模式失败自动降级 mock 并标 `degraded:true`。
- **计划**：D7 用真实 Key 验证一次（不写入仓库、不进 CI）。

## 10. 前端移动端未适配

- **现象**：桌面优先布局，小屏下三栏拥挤。
- **影响**：手机浏览器体验差；验收要求「移动端仅保证可打开」。
- **绕过**：演示使用 1440×900 以上窗口。
- **计划**：V1.0 M4 响应式适配。

## 11. 演示依赖预置样例文件

- **现象**：`data/samples/meeting_notes.docx` 不随 git 提交（`data/` 被忽略）。
- **影响**：干净环境首次演示前若忘记生成，上传步骤无素材。
- **绕过**：`python scripts/make_sample.py`（或 `make sample`）一条命令生成；
  `docs/demo.md` 演示前检查清单已列为必检项。

## 12. 测试需要先启动后端

- **现象**：smoke 用例通过 HTTP 访问 `http://127.0.0.1:8000`。
- **影响**：后端未启动时 pytest 全部连接失败（不是代码 bug）。
- **绕过**：按 `tests/README.md` 先启动后端；或 `BASE_URL` 指向其他实例。
  也可用 pytest `--base-url` 参数覆盖（默认 `http://127.0.0.1:8000`）。

## 13. Windows 代理变量干扰 httpx（已解决，保留记录）

- **现象**：本机 `HTTP_PROXY/HTTPS_PROXY` 指向本地代理，且 `NO_PROXY` 含 `[::1]`；
  httpx 0.28 初始化时解析代理 URL 抛 `httpx.InvalidURL: Invalid port: ':1]'`，10 条 smoke 全部 ERROR。
- **影响**：只在带系统代理的 Windows 开发机出现；CI 与无代理环境不受影响。
  易被误判为「后端挂了」，实际是测试环境问题。
- **绕过（三层，均已落地）**：
  1. `tests/conftest.py` 在导入 httpx 前把 `NO_PROXY` / `no_proxy` 统一设为 `localhost,127.0.0.1`；
  2. 测试 HTTP 客户端显式 `httpx.Client(..., trust_env=False)`，不读环境代理；
  3. CI workflow 全局 `env: NO_PROXY=localhost,127.0.0.1`；
  4. 业务代码统一走 HTTP 客户端工厂（`trust_env=False` + 显式 `HTTPS_PROXY`，由后端实现）。
- **本地手动绕过**：
  ```bat
  set NO_PROXY=localhost,127.0.0.1
  set no_proxy=localhost,127.0.0.1
  ```
  ```bash
  export NO_PROXY=localhost,127.0.0.1
  export no_proxy=localhost,127.0.0.1
  ```
- **注意**：若需要经代理访问外部模型，必须显式传 `proxy=`，不要依赖环境变量。

## 14. B0 阶段 CI 六门禁为骨架（已解决）

- **现象**：B0 时 `backend-lint/test`、`contract`、`frontend-quality` 依赖的文件尚未交付，会明确失败。
- **现状**：B1/B2/B5 后 `backend/pyproject.toml`、`backend/app/`、`scripts/export_openapi.py`、
  `contracts/`、前端 lint/format/typecheck/test 脚本均已就绪；CI 命令已校准（含 30 条 smoke 步骤）。
- **仍待修**：#17（pyyaml/uv.lock）会让干净环境 CI 启动失败；#18 会让 contract 门禁红。
- **绕过**：本地用 `make verify`（或 README 原始命令）逐项执行。

## 15. 契约快照与 Alembic 迁移（已解决）

- **现状**：`contracts/openapi.v1.json`（32 paths / 40 ops）、`contracts/events.v1.schema.json`（12 类事件）
  已生成且 `--check` 幂等；Alembic `0001→0002` 从零 upgrade 成功（8 张业务表 + `alembic_version`）。
- **验证**：`python scripts/export_openapi.py --check`；`cd backend && python -m alembic upgrade head`。
- **注意**：本地若 `contracts/` 尚未 `git add`，`git diff` 看不到差异——用 `--check` 或先提交快照。

## 16. 真实模型端到端（已缓解）

- **现状**：8000 真实模式（DeepSeek）单次 smoke PASS：`run.started.mode=real` → 自主工具调用
  （`file.read` / `doc.generate_report`）→ `approval.required` → 批准 → `run.completed`
  （tokens≈14.8k，成本≈¥0.036）→ DOCX 下载可打开。
- **2026-11-07 补充**：真实链路已多次复测，覆盖「商量不落盘」（只读 + 给方案 + 问一句，零产物）、
  「拍板才生成」（读 + 生成 + 交代未确认数据）、「无动作词追问」（能读到文件）三类。
- **仍缺**：千问/GLM 未逐一实测（千问 Key 尚未配置，配置方式见 `.env` 的 `DASHSCOPE_API_KEY`
  或设置页「添加 Key」）；长任务、限流、超时降级的真实场景未压测。
- **纪律**：不读取、不打印、不提交 `.env`；CI secret scan 排除 `.env`，只扫 git 跟踪文件。

## 17. 缺 backend/uv.lock（pyyaml 已修复）

- **现象**：B5 发现 `backend/app/agents/model_router.py` 使用 `import yaml` 但 pyproject 未声明 pyyaml；
  Lead 已在 `backend/pyproject.toml` 补 `"pyyaml>=6.0"`。**仍缺 `backend/uv.lock`**（依赖未锁定）。
- **影响**：干净环境可安装并启动（已验证），但依赖版本不可完全复现（DoD 工程第 20 条只能算部分达标）。
- **绕过**：CI 用 `pip install -e backend` 取最新兼容版本；本机通过 clean venv 验证可启动。
- **修复建议**：后端 owner 生成并提交 `backend/uv.lock`（或 requirements.lock）。

## 18. 前端生成类型一致性（已解决）

- **现象（已修）**：B5 中期 `frontend/src/shared/api/generated/schema.d.ts` 缺少 B3 新增接口。
- **现状**：前端 task-14 已重新生成并入库；QA 用 `contracts/openapi.v1.json` 生成后，
  去掉 openapi-typescript CLI 的 4 行 banner 再比对，与仓库文件 **完全一致**。
- **CI 校准**：`contract` job 已按同样规则归一化 banner 后 diff；快照与代码 diff 为空。
- **规则**：generated 目录禁止手改；改接口后必须 `npm run gen:api` 并提交。

## 19. 前端覆盖率从 8.61% 提到 72.05%（已达标，保留记录）

- **结论**：DoD 工程第 13 条「前端覆盖率 ≥60%」**已达标**。
  `cd frontend && npm run test:coverage` →
  `All files 72.05% Stmts / 63.37% Branch / 63.07% Funcs / 73.15% Lines`
  （774 tests passed，28 个测试文件）。
- **门槛**：`frontend/vitest.config.ts` 的 `coverage.thresholds` 四项同时卡 **60**，
  低于门槛命令以非 0 退出，CI 已接入（`npm run test:coverage`）。
- **补测路径**（按评审建议的顺序）：`workbench` reducer → `shared/lib`（sse/api/markdown/format）
  → 五个 feature 的 `api.ts` → UI 基础组件 → `useWorkbench` hook → `mock-run` 流脚本 → 页面组件。
- **仍未覆盖的大块**（继续提升的着力点，已不影响阈值）：
  `SettingsPage.tsx`（710 行）、`SessionList.tsx`（525 行）、`AuditPage.tsx`（439 行）、
  `ArtifactsPage.tsx`（288 行）、`Composer.tsx`（284 行）、`WorkbenchPage.tsx`（227 行）。
- **备注**：后端覆盖率 84.70%（≥70% 达标），core 88%（≥85% 达标）。

## 20. pip-audit 本机无法运行（环境权限）

- **现象**：`python -m pip_audit -r deploy/requirements.api.txt` → `PermissionError: [WinError 5] ...AppData\\Local\\pip-audit`。
- **影响**：本机未完成 Python 依赖漏洞扫描；npm audit 未本地执行（需网络）。
- **绕过**：CI security job 会执行 pip-audit / npm audit / bandit；本机可先
  `set PIP_AUDIT_CACHE_DIR=<可写目录>` 后重试。bandit 本地已跑：无 medium/high。
- **关键**：不要把「本机没跑」当成通过；DoD 第 15 条以 CI 结果为准。

## 21. Playwright 依赖本机 Chrome（E2E 可复现性）

- **现象**：`frontend/playwright.config.ts` 使用 `channel: 'chrome'`（复用本机 Chrome，避免下载浏览器）。
- **影响**：无 Chrome 的机器/CI 无法直接跑；本地已跑 6 passed（需 5173 + 8000 在线）。
- **绕过**：CI 的 nightly e2e job 使用 `npx playwright install --with-deps chromium` 并去掉 channel
  依赖（job 内会安装浏览器）；本地无 Chrome 时安装 Chromium 或改为 headless chromium project。

## 22. 用户级 `PYTHONHOME` 劫持 venv 标准库（环境问题）

- **现象**：`.venv\Scripts\python.exe -m uvicorn ...` 立刻退出，堆栈里是 `E:\lib\re\__init__.py`
  这类**不在 `.venv` 内**的路径，最后一行 `assert _sre.MAGIC == MAGIC` → `AssertionError: SRE module mismatch`。
- **原因**：`setx` 留下了一条用户变量 `PYTHONHOME=E:\`（指向另一个 Python 的安装根）。它的优先级高于
  venv 自己的 `pyvenv.cfg`，解释器于是拿 A 版本的二进制配 B 版本的标准库，版本一对不上就崩在 `import re`。
- **影响**：所有手动启动方式（cmd 里直接敲、IDE 终端）都会失败；前端 5173 随之刷一排
  `ECONNREFUSED 127.0.0.1:8000`、页面顶部显示「还没连上本地服务」——都是连带反应，不是前端坏了。
- **绕过**：`启动开发模式.cmd` / `启动 Office Agent.cmd` 开头已 `set "PYTHONHOME="`，用它们启动即可；
  手动启动时先在同一窗口执行 `set PYTHONHOME=`（`make` 里对应 `unexport PYTHONHOME`）。
- **根治**：`setx PYTHONHOME ""` 后重开窗口，或「系统属性 → 环境变量 → 用户变量」里删除该条。
- **排查口径**：`echo %PYTHONHOME%` 有值即中招；`python -c "import sys; print(sys.path)"` 里出现
  非 `.venv`、非 `%LOCALAPPDATA%\Programs\Python` 的 Lib 路径同样可疑。
- **本机处理记录（2026-11-08）**：`E:\` 根目录装的是 **Python 3.11.9**，而 `.venv` 是 **3.13.14**，
  把 `PYTHONHOME` 指到 `E:\` 等于让 3.13 去读 3.11 的 `Lib`。已删除该用户变量；
  验证 `E:\python.exe` 脱离 `PYTHONHOME` 仍可用（`sys.prefix` 由 exe 位置推导，不需要这个变量），
  并实测干净环境启动后端：`/api/v1/health` → 200。


## 23. 会议转写的准确率取决于本地模型档位（能力边界）

- **现象**：默认 `ASR_MODEL=base`（约 145MB，CPU 上约 4 倍实时）转 30 秒会议录音，
  语义与时间轴都对，但同音字会错：实测「客户验收」被听成「客户厌收」、「交付经理」
  被听成「交付经历」；人名（张伟/李娜）与数字（82%、11 月 15 日）正常。
- **影响**：转写稿可以直接当素材喂给模型写纪要（模型能靠上下文纠正一部分），但**不适合
  直接贴进对外的正式文件**，仍要人过一眼。
- **绕过**：`ASR_MODEL=small`（约 460MB，约 1.7 倍实时）或 `medium` 明显更准，机器慢就
  用 `base`；`ASR_LANGUAGE=en` 可切换语种（非中文时不加简体提示、不做繁简转换）。
- **不做的事**：不引入云端 ASR（音频要出本机，和「素材只写本机目录」的调性冲突），
  也不对结果做二次大模型润色（会把「客户原话」改成「模型以为的意思」，纪要最怕这个）。
- **观察口径**：`/api/v1/health` 的 `media.asr_model` 就是当前档位；识别结果的
  `media.meta` 里有 `model` / `duration` / `segments`，报问题时带上这三项。

## 24. 会议视频只用音轨，画面里的字不会被识别（设计边界）

- **现象**：一段带 PPT 录屏的会议 mp4，转写结果只有人说的话；屏幕上打的关键数字、
  决议列表里的条目**不会出现**。视频再短也一样。
- **为什么这么做**：会议视频要的是「谁说了什么」，抽画面做 OCR 会把幻灯片上的标题、
  页脚、水印混进正文，模型会当成发言内容引用，纪要反而更乱。要读图上的字，请把那一页
  单独截图，按图片上传（两条素材可以同时挂在一个会话里）。
- **另一个边界**：**没有音轨的视频**（录屏忘开麦、只导出画面）现在会直接报
  「这个视频里没有音轨」，不可重试 —— 这不是 bug，重试一百次也还是没有声音。
- **观察口径**：识别结果的 `media.meta.source` 会写 `video` 或 `audio`，
  `media.meta.audio_codec` 是实际解到的音轨编码（`aac` / `pcm_s16le` …）；
  转写失败时带上这两个值，能快速区分「文件没音轨」和「编码解不开」。
