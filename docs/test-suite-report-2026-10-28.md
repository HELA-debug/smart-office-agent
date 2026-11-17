# 全量测试矩阵（2026-10-28）

一句话：**2461 条用例**，后端 1287（其中新增接口矩阵 977 条）、前端 1174（新增 80 条），
全部通过。目标是「接口层出问题时，测试先叫，而不是用户先看到 500」。

## 1. 口径

| 层 | 用例数 | 运行方式 | 耗时 |
| --- | --- | --- | --- |
| 后端（pytest） | 1287 passed / 42 skipped | `cd backend && pytest tests` | 约 85s |
| ├ 接口矩阵（新增） | 977 | `pytest tests/api` | 约 33s |
| └ 既有单测 / 集成 / 契约 | 310 | — | 约 52s |
| 前端（vitest） | 1174 passed | `npm --prefix frontend test` | 约 174s |
| └ HTTP 错误矩阵（新增） | 80 | `vitest run src/shared/lib/api.matrix.test.ts` | 约 5s |

跳过项是刻意跳过的：真实模型联调（需要 Key）、会拉起系统文件管理器的端点
（`artifacts/open`、`storage/reveal`、`projects/reveal`）、非 GET 的老前缀等价性。

## 2. 后端接口矩阵：为什么这么切

覆盖的是运行时 OpenAPI 里的 **53 条路径 / 65 个操作**，一个不漏。分四层，职责不重叠：

### 2.1 协议层（`tests/api/test_contract_matrix.py`，310 条）

不关心业务，只回答「外壳对不对」：

| 检查 | 条数 | 说明 |
| --- | --- | --- |
| 路由可达 | 28 | 每个只读/下载端点发一次合法请求，不能落到 404/405 |
| 错误带 X-Trace-ID | 42 | 错误响应必须有 trace，日志能对上 |
| 错误体形状 | 42 | 只能是 `{trace_id, error:{code, message, details?}}`，且 status 必须 4xx |
| 坏 JSON → 400 | 18 | 不再是 500（见 §4.1） |
| 错 Content-Type → 400 | 18 | `text/plain` 带 JSON 也不收 |
| 必填 body 缺失 → 400 | 12 | 且 details 要说清缺哪个字段 |
| 不存在的路径参数 → 4xx | 31 | 逐参数替换，其余保持真实 |
| 方法不允许 → 405 | 53 | 每条路径挑一个未注册方法 |
| 老前缀等价 | 65 | `/api/x` 与 `/api/v1/x` 同结果，且带 `Deprecation` |
| 未知路由 | 1 | 404 + 统一错误体 |

### 2.2 语义层（4 个文件，191 条）

| 文件 | 条数 | 覆盖 |
| --- | --- | --- |
| `test_semantics_threads.py` | 58 | 标题规则（空/空白/超长截断/emoji）、改名、置顶排序、搜索（标题/ID/未命中/已删）、分页边界、软删、批量删去重与上限、上传 4 种合法格式、5 种非法扩展名、路径穿越清洗、多文件、空文件、DOCX 解析字数 |
| `test_semantics_runs.py` | 29 | SSE 事件序列（首帧 `run.started`、末帧 `run.completed`、seq 单调唯一）、事件回放与流一致、`?after=` 与 `Last-Event-ID` 等价、非法 after、取消幂等、重试产生新 run 且不动原 run、审批状态机（已决 409 / 不存在 404 / 非法 decision 400 / thread 不匹配 404）、拒绝审批的工具记账 |
| `test_semantics_artifacts.py` | 28 | 过滤（thread/run/type/分页/include_uploads）、下载的 attachment 与 inline、预览 HTML、软删 → 404、回收站、恢复、彻底删除、批量删的部分成功与去重、文件真的进了回收站目录 |
| `test_semantics_assets.py` | 76 | 设置（来源标注、非法值、未知键、规则数组）、模型（Key 不泄露、明文 Key 拒绝、无 Key 探测优雅失败）、模板（内置保护、section 来源枚举、渲染前校验）、技能（导入/停用/删除闭环、草稿降级）、存储（目录浏览、新建、重名、分隔符拒绝）、项目（重复 409、路径校验、搜索）、反馈、用量区间、审计导出、工具/子代理/提示词包目录 |

### 2.3 模糊层（`tests/api/test_fuzz_matrix.py`，476 条）

固定随机种子，失败可复现。只断言一件事：**不 5xx**。

- 每个带路径参数的操作 × 8 种畸形 id（注入、路径穿越、超长 512、emoji、空串、`%00`、`OR 1=1`）
- 每个带请求体的操作 × 9 种畸形 body（`{}`、`[]`、`null`、字符串、数字、六层嵌套、类型错、5000 字、`__proto__`）
- 8 个查询型端点 × 6 种脏 query（注入、超大分页、`%00`、超长中文、重复参数、非布尔）
- 读端点忽略未知 query（前端缓存旧参数不该炸）
- 超长路径、`..`、根路径、`//`、HEAD

### 2.4 种子数据（`tests/api/conftest.py`）

进程内 `TestClient`（单条 3–5ms，比真起 uvicorn 快一个量级），一份 session 级种子：
基座会话 + 上传素材 + 8 轮真实 mock 运行产出的 8 个产物 + 模板 + 项目 + 已决审批。

两个安全阀：

1. **技能目录沙箱**：`skills_dir` / `catalog_dir` 复制到临时区再指过去，
   跑完再比对仓库里的 `app/skills` 有没有被改，变了就当场 fail。
2. **破坏性端点标记 `ext`**：`open` / `reveal` / 写 `.env` 的 `models/key` /
   `skills/install` 只打错误路径，绝不触发真实系统调用。

## 3. 前端补充（`src/shared/lib/api.matrix.test.ts`，80 条）

HTTP 基础设施是「一出错全站一起错」的那一层，按 **状态码 × 响应体形态** 的笛卡尔积钉住：

- 9 个 4xx × 5 种 body（标准错误体 / 只有 detail / HTML / 空 / 无 error 字段）= 45 条，
  统一断言「不可重试、且有可读文案」；
- 4 个 5xx × 5 种 body = 20 条，统一断言「可重试」；
- 取值优先级：标准体透传 code/message/trace；只有 detail 时当文案、code 回退 `HTTP_<status>`；
  HTML 与空体一律走「请求失败（HTTP xxx）」，不把 HTML 塞进提示；
- 2xx：带 trace、204 空体、2xx 但非 JSON 都不抛错；
- 连通性广播：4xx 说明服务活着 → `online`；连接失败 → `offline`；
- 请求构造：JSON 带 `Content-Type` + `no-store`；FormData 不设 `Content-Type`（留 boundary）。

## 4. 这轮测试暴露并修掉的缺陷

### 4.1 坏 JSON 请求体把 400 变成 500（`app/core/errors.py`）

复现：`POST /api/v1/threads`，`Content-Type: application/json`，body 是 `{"title": `。

现象：返回 **500 INTERNAL**，日志里是
`TypeError: Object of type bytes is not JSON serializable`。

原因：`RequestValidationError.errors()` 的 `input` 字段在 JSON 解析失败时是**原始 bytes**，
`ctx.error` 是异常实例，直接 `JSONResponse(...)` 序列化就炸。
后果不只是状态码难看——客户端会把「格式写错」当成「服务挂了」，还会误触发重试与
「后端断开」提示。

修法：加 `_jsonable()`，bytes 转 `<N bytes>`、异常转 `str`，再交给 JSONResponse。
现在稳定返回 400 + `details`。

### 4.2 全空白的「技能想法」照样生成垃圾技能（`app/api/v1/skills.py`）

`SkillDraftIn.idea` 只有 `min_length=1`，`"   "` 能过。修法：入口 `strip()` 后为空直接 400。

### 4.3 项目文件列表漏掉 `.md`（`app/services/project_service.py`）

接口描述写的是「docx/pdf/xlsx/md/txt/pptx」，实际 `DOC_EXTS` 没有 `.md`，
项目里的笔记类文件永远扫不出来。修法：补 `.md`。

## 5. 发现但**没有**在这轮动的

| 项 | 现状 | 为什么不顺手改 |
| --- | --- | --- |
| `mypy app` 35 条历史错误 | `docx_utils` 21 条、`thread_service` 把 `list` 方法用作类型名等 | 与本次改动无关，改动面大，单独一次清理更安全 |
| 405 的错误码是 `BAD_REQUEST` | `_STATUS_TO_CODE` 没有 405 映射 | 加新错误码会牵动前端文案映射与契约，需单独评审 |
| `POST /models` 传 `id` 不生效 | 服务端按 `provider + model` 匹配已有登记，新登记 id 由后端生成 | 「一个供应商一条登记」是有意设计，但接口文档的 `id` 描述容易误导，建议改文案 |
| 老前缀 `/api/x` 只对 GET 做等价断言 | 写操作等价性仍由集成测试覆盖 | 矩阵里重复写一遍收益低 |

## 6. 怎么跑

```bash
# 后端全量
cd backend && ../.venv/Scripts/python.exe -m pytest tests -q

# 只跑接口矩阵
cd backend && ../.venv/Scripts/python.exe -m pytest tests/api -q

# 前端全量
npm --prefix frontend test
```

新增接口时只需要在 `backend/tests/api/matrix.py` 的 `OPS` 里加一行，
协议层、路径参数、方法不允许、畸形输入四组用例会自动长出来。
