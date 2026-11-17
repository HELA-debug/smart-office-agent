# Changelog

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 修复（2026-11-10：换个端口起后端就「渲染不出来」——默认不托管界面）

- **`serve_frontend` 默认改成 True**。手动 `python -m uvicorn ... --port 8080` 不带任何
  环境变量，原来默认关托管 → 根路径只回 `{"name":"office-agent-backend",...}`。8000 是
  启动器起的（它 `setdefault SERVE_FRONTEND=1`）所以有界面，换成 8080 就只剩一行 JSON，
  看着就是「页面渲染不出来」。这坑前后报了两次，改默认值而不是继续提醒用户加变量。
- **dist 没构建时回说明页**：`serve_frontend=True` 但 `frontend/dist/index.html` 不存在，
  根路径回一张 HTML 说明页（写明 `cd frontend && npm.cmd run build`，以及开发态走 vite），
  不再用一行 JSON 让人误判成「界面坏了」。显式 `SERVE_FRONTEND=0` 才回 JSON（纯接口模式）。
- 测试夹具（`tests/conftest.py`、`tests/api/conftest.py`、`test_hardening`、
  `test_model_gate`、`test_real_deepseek`）统一 `serve_frontend=False`：测试不该因为仓库里
  有没有 build 过而变。补三条回归：默认就托管、未构建给说明页、显式关闭仍是 JSON。

### 修复（2026-11-10：旧版 .xls 让人「另存为 .docx」，照着做更错）

- `_unreadable_hint` 对**所有**旧格式都回同一句「另存为 .docx」。拖 `.xls` 的人照着做，
  等于把表格存成 Word 文档。改成按类型给目标：`.xls/.et → .xlsx`、`.ppt/.dps → .pptx`、
  `.doc/.wps/.rtf → .docx`。
- 补两条上传用例：`.xlsx` 拖进来必须当场 `parsed=true`（62 字，`text_preview` 带表格内容）、
  `.txt` 支持 GBK；另加一条钉住「`.xls` 的提示里只能是 `.xlsx`，不能出现 `.docx`」。

### 修复（2026-11-10：双击启动后页面是一行 JSON，看着像「没渲染」）

- **启动器不再复用「只跑接口」的后端**：`already_running_on` 原来只判 `/health` 通就
  复用那个端口。开发时手动起的 `python -m uvicorn backend.app.main:app` 没设
  `SERVE_FRONTEND=1`，只提供 `/api`，根路径是一行
  `{"name":"office-agent-backend",...}` —— 双击启动就打开这行 JSON，用户看到的是
  「页面没渲染出来」，可服务明明是通的，根本猜不到原因。
  新增 `serves_frontend()`（根路径返回 `text/html` 才算带界面），没有界面的端口跳过、
  另起一个（端口照旧往后找），并明确提示一句「8000 上有个只跑接口的后端（没有界面）」。
- **界面产物跟着源码重建**：`frontend/dist` 停在 13:28，而当天 21:49 之后改过
  `drop-files` / `drop-guard` / `Composer` —— 从 8000 打开的是旧界面（拖拽修复根本
  没进去），只有 5173 的 dev server 看得到新代码。已重建（`index-Cuj0waWS.js`）。
  启动器本来就有 `_frontend_sources_newer_than_dist` 检查，但只在「新起一个」时跑；
  这次一并人工重建确认。

### 修复（2026-11-10：拖进来的文件读不到，提示「没读到」）

- **抓取改到事件里同步做完**：`drop-files` 拆成 `captureDrop`（同步，在 drop 回调里抓
  `items` / `files` / 目录条目）与 `expandDrop`（异步展开文件夹）。原来两步揉在一个 async
  函数里，靠「第一个 await 之前都是同步的」侥幸成立——`dataTransfer` 一离开回调就可能被
  清空，前面多加一句 await 就让整套拖拽静默失效。
- **补 `items[i].getAsFile()`**：某些内嵌 webview / 国产内核只实现这一个入口，
  `dataTransfer.files` 一直是空的。以前只看 `files`，那种环境下拖什么都是「没读到文件」。
- **`dragenter` 也要 preventDefault**（输入框与窗口兜底都补上）：部分内核只认 dragenter
  上的 preventDefault，漏了它 drop 照常触发但 `dataTransfer` 是空的。
- **读不到文件内容时不再留死路**：拖的是文件但浏览器没给内容（压缩包预览、网盘占位、
  聊天窗口里拖出来的只是「壳」）→ 提示里写明浏览器给了几个文件/条目，并**直接打开选择框**；
  拖的本来就不是文件（页面上的文字、图片）→ 说清楚，不乱弹窗口。

### 修复（2026-11-10：跑一次测试就把用户的真 Key 换成假 Key）

- **测试会把假 Key 写进真实 `.env`**：`models/{id}/key` 那条门禁用例给 `Settings` 的
  数据库 / 上传 / 产物全指了 `tmp_path`，唯独 `env_file_path` 还硬绑 `DATA_ROOT`，
  于是 `pytest backend/tests` 一跑，夹具里的 `sk-gate-test-…` 就落进仓库 `.env`，
  用户自己的 DeepSeek Key 被覆盖。表现极具迷惑性：界面写着「API Key 无效或已失效」、
  每轮都降级演示模式，而用户从没动过那把 Key。
- **`Settings.env_path`**：`.env` 落盘位置可覆盖（留空 = 数据目录下那份，正式运行不变）。
  三处测试夹具（`tests/conftest.py`、`tests/api/conftest.py`、`test_model_gate.py`）
  都指到 tmp；新增 `test_saving_key_writes_the_test_env_not_the_real_one`，
  断言保存 Key 后真实 `.env` 一个字节都没变——这类自伤不能靠「记得别写」。
- 顺带校正 `.env` 里被写坏的那行（测试残渣清掉），并在供应商段留回 `DEEPSEEK_API_KEY=` 空位。

### 修复（2026-11-10：装不上依赖、PaddleOCR 一推理就崩）

- **`pip install -e "backend[media,ocr-paddle]"` 在构建阶段直接失败**：`backend/` 是扁平布局，
  `app/`、`data/`、`config/` 三个顶层目录并列，setuptools 判定「无法确定该收哪个包」，
  在 `Getting requirements to build editable` 这一步就退出，一个包都没装。
  `pyproject.toml` 补上 `[tool.setuptools.packages.find] include = ["app*"]`，
  并把技能说明与提示词（30 个 `.md`）声明为包内数据，装成 wheel 后不再缺文件。
- **PaddleOCR 推理崩在 oneDNN**：Paddle 3.3.1 在 Windows CPU 上默认启用 oneDNN，
  与 PIR 执行器冲突，抛 `ConvertPirAttribute2RuntimeAttribute not support`
  （栈顶在 `onednn_instruction.cc`），一张图一个字都认不出来，错误还会被当成
  「图片识别失败」。新增 `OCR_MKLDNN`（**默认 false**）：加速是「快一点」，
  识别是「有没有」，默认值只能选后者；用户手动打开且真踩中时，自动关掉加速重建一次
  再试，只降级一次，别的失败（如模型文件损坏）不重试。
- `/health` 的 `media` 增加 `ocr_mkldnn`，排查「图片识别失败」时第一个要看的就是它。

### 变更（2026-11-10：图片识别换成 PaddleOCR，RapidOCR 留作兜底）

**背景**：中文截图（尤其表格里的小字、密排的课表）识别率不稳，而旧链路固定用
RapidOCR 的 onnx 模型，换不了也没兜底可降。

- **新增引擎适配层**（`services/ocr_engine.py`）：两家的输出结构差异全部关在这里，
  统一成「带坐标的文字块」`OcrLine`，下游的分行 / 分栏 / 表格还原一个字都不用改。
  认得 PaddleOCR 3.x 的 `rec_texts/rec_scores/rec_polys/rec_boxes`、外层 `res` 包裹、
  2.x 的 `[[[box, (text, score)], ...]]`、RapidOCR 的 `txts/scores/boxes`，
  以及 Paddle 参数冲突时返回的 `{"error": ...}`（它不抛异常，当「没识别到文字」就误导人了）。
- **`OCR_ENGINE=auto|paddle|rapid`**：默认 `auto` —— 装了 PaddleOCR 就用它，
  没装退回 RapidOCR（离线可用）。显式指定却不装时报错并附安装命令，
  不会「悄悄换一家」让人以为在用 Paddle。
- **坐标形态兼容**：`rec_boxes` 是 `[x1, y1, x2, y2]` 四个数，`rec_polys` 是四个点。
  旧代码只按四点框解析，换成 Paddle 会在第一个块上崩（把 int 当 point[0] 下标）。
- **躺倒的图自动纠正**：正着认出来全是低分乱码时，顺时针转 90°/270° 各再认一遍，
  按平均置信度取最优（`meta.rotated` 记下来）。一块都没认到时不重试——
  那是纯照片，转三遍只是白等三倍时间。
- **发灰的图先拉对比度**：灰度极差 <96（翻拍白板、曝光不足）时做一次线性拉伸；
  判据用**极差**而不是直方图分位数：一页 PPT 里黑字可能只占 0.5%，
  1% 分位直接落在白底上，会把好图当成灰图。
- **能力上报**：`/health` 的 `media` 增加 `ocr_engine`（实际在跑的）、
  `ocr_engine_configured`、`ocr_engines`（两家各装没装）、`ocr_lang`、
  `ocr_textline_orientation`，`media.ocr` 改为「选中的引擎确实可用」。
- **依赖**：`pyproject` 新增可选组 `ocr-paddle`（`paddlepaddle>=3.0` + `paddleocr>=3.0`，
  3.3.1 起有 cp313 win_amd64 wheel），`media` 组保留 rapidocr 作为兜底。

### 修复（2026-11-10：文件拖不进输入框、悬停提示是方角白框）

**背景**：把文件拖到对话框上没反应（前端按后缀白名单先筛一遍，拖进来的东西只要不在名单里
就被丢掉）；右栏「查看本会话全部产物」的悬停提示是浏览器原生 `title` 的方角白框，
跟这一栏的圆角卡片不是一个体系。

- **拖拽收下任何类型**（`Composer` + 新增 `shared/lib/drop-files`）：前端不再按后缀筛，
  收不收交给后端说了算。拖文件夹会递归取里面的文件（单次上限 50 个、深度 8 层，
  跳过 `~$` 锁文件与隐藏文件）；`items` 读不到（内嵌 webview）时回落 `files`，
  两条路都空才说「没读到拖进来的文件」。
- **拖到输入框以外也能加**（新增 `shared/lib/drop-guard`）：浏览器默认「drop 就导航到那个文件」，
  以前只拦了输入框那一小块，拖偏一点落到左栏或对话区，整个应用就跳去打开文件——看着就是
  「拖不进去，还把界面拖没了」。现在窗口级兜住：`dragover` 放行、`drop` 拦住导航，
  没被输入框接住的就转成一个窗口事件交给输入框收。拖**选中的文字**一句都不拦
  （那是应用内的文字拖拽编辑）。
- **后端不再按白名单拒收**（`security.validate_upload`）：未知扩展名只查「非空 + 别是压缩炸弹」，
  能不能读出字由 `parsing.parse_bytes` 如实回答。读不出的（压缩包、旧版 `.doc`）
  **照样收下**并在素材上标 `note`，卡片显示「读不出文字」、悬停说明换成什么格式；
  认得的格式解析失败仍然报错——那种情况是文件坏了，装作收下更糟。
- **读不到字时直说**（`file.read`）：一轮素材全部读不出文字时返回
  「XX 里没有可读文字……换一份能读出字的格式」，不再回一句「共 0 字」让模型自己猜。
- **悬停提示改胶囊形**（`shared/ui/primitives`）：单行提示 `rounded-full`，
  多行的富提示仍用 `rounded-control`（撑成胶囊会变形）。右栏那个入口不再用原生 `title`。

### 修复（2026-11-10：表格内容填错位置、识别原文被摆进交付件）

**背景**：一张课表截图转成 Excel，周五的两节课被填到了周一、周二。根因不在模型
「数错了列」，在上游：OCR 只输出 `A | B | C` 的流水文字，**空格子直接消失**，
下游只能「有内容就往后挤」，于是整行左移。同一份产物里还多出一张「识别原文」表，
那是写稿人自己核对的流水文字（行列本来就是错位的），读者看到只会怀疑数据。

- **OCR 表格还原**（`media_service`）：整页看着像表格（≥3 列 ≥3 行、格子里是短词）时，
  先按文字坐标还原成矩阵再输出 markdown 表——空列用 `—` 占位，列按「横向范围重叠」
  聚类（列缝的中点会被文字长短带偏，6 列能判成 9 列）。不像表格的页面照旧按行输出。
- **`write_grid`（新增，表格版式引擎）**：二维表按 (行, 列) 显式落格，不按顺序流下去；
  少格的行补齐并把行号报回去。课表 / 排班 / 值班表走这条。
- **摘掉「识别原文」附录**（`xlsx_utils.strip_proof_sheets`）：`code.run_python`
  登记产物前删掉同名 sheet 或同表末尾的那一节；「核对说明」保留——那是结论。
- 提示词与 `sheet-layout` 技能写死两条：网格表先摆格子再写；产物不放识别原文。

### 新增（2026-11-10：Excel 版式引擎 + 格式词表，与 Word/PDF 同一套）

- `services/sheet_render.py`：把「表长什么样」从各个函数里收出来，样式只有一份实现。
  三档预设 `default`（台账/明细/汇总，全框线 + 数字右对齐 + 冻结筛选）、
  `grid`（课表/排班，全格居中 + 自动换行 + 双向冻结）、`compact`（密排），
  数值都在 `sheet_lexicon.SHEET_PRESETS`（字号 / 线型 / 行高 / 列宽上限）。
- `write_table`、`style_header` 改走同一份版式；打印改为 A4、按宽度缩一页、每页重复表头
  （不设这三条，8 列的表打印出来右边两列落单页）。

### 新增（2026-11-09：断开模型 Key + 未配置模型时禁止发送）

**背景**：① 项目的 Key 一直留在配置里，分享 / 部署给别人时对方能继续用它跑、
费用记在原主头上；② 真实引擎下一个 Key 都没配时照样能发消息，跑出来的是
本地 mock 假数据，用户还以为真模型在工作。

- **断开 Key（分享 / 部署前止损）**：设置页「可用模型与 Key 状态」里，已配置的
  行由「添加 Key」换成红色「断开」，二次确认后 `DELETE /models/{id}/key`
  ——进程 env、Settings 字段、本地 `.env` 那一行**三处同清**，并清掉探测缓存
  与路由器里的旧实例（provider 构造时把 Key 拍成了快照，不清缓存断开形同虚设）。
  接口地址与模型名保留，重新粘贴 Key 即可接回；`.env` 删行失败（只读文件系统）
  会显式提示手动处理。
- **发送门禁（前后端同口径）**：`/health` 新增 `model_ready` / `model_hint`
  （演示模式恒 `true`，不依赖 Key）。前端拿到 `model_ready=false` 时拦住发送，
  提示怎么把模型配上，模型胶囊显示「未配置模型」（不再拿后端兜底的
  mock-scripted 冒充已选模型）；已配好模型则不拦——Agent 自动用当前那家，
  不必每个会话手动挑。后端 `RunService.ensure_model_ready()` 在**开 SSE 之前**
  兜底拒绝（`start()` 是异步生成器，等它抛错响应头已发出，只能断流）。
- `Settings.model_ready` 是门禁的单一判据，界面与 API 共用。

### 修复（2026-11-09：同一轮里反复出产物、产物点开 404、结果早于思考完成）

**背景**：一次运行里脚本被调 6 次、三度写出同名文件，产物列表于是出现
`说明.txt` / `说明(2).txt`；界面上那张卡还指着被软删的旧记录，点预览直接
「产物不存在（HTTP 404）」。而且产物在整轮还没跑完时就摆了出来——用户看到的是
随时会被覆盖的半成品。

- **同名重写复用同一条记录**（`code.run_python` + `artifact_repo.replace_file()`）：
  同一轮里再写同名文件时覆盖原文件、更新大小/哈希，**id 不变**，不再新建 `(2)`
  副本再把旧记录软删。前端卡片不再指向死记录。
- **`run.completed` 只报还活着的产物**（`RealEngine._live_artifact_ids`）：
  模型中途 `file.delete` 掉的文件、被替换掉的旧记录都不再报，避免刷新后又长出一张
  点不开的卡。
- **本轮产物等整轮跑完再现身**（`ChatStream`）：以前压到「开口说第一句」就放出来，
  现在整轮（含等待审批）都压住，收尾时一次性露出。上一轮的旧产物照常显示。
- **每轮告诉模型「本会话已交付的文件」**（`RunContext.delivered` + `_turn_tail`）：
  用户说「你自己斟酌 / 你看着办」时是在这一版上继续改，不是从零再来一份。
  以前模型看不到手上已有什么，就只能重做一遍。

### 修复（2026-11-09：类型筛选面板也竖排，且两个面板高度封顶）

**背景**：上一版只把「会话」改竖排，「类型」还是 chip 换行——六个类别铺两行，第二行
（PDF / PPT 演示文稿 / 文本）右侧照样空一块。另外会话会一直攒下去，面板跟着内容长高，
几十个会话就能把边框顶出屏幕。

- **类型也改竖排**：一行一个类别、撑满面板宽度，宽度贴着最长项（实测 106px），
  `stacked` 的两个调用点现在只差行数上限。
- **高度按整行封顶**：`PANEL_VISIBLE_ROWS = 6`，`max-height` 用
  `calc(6 * 2rem - 0.25rem + 1rem)` 算出来（chip 1.75rem + 行距 0.25rem + 上下 p-2）。
  取整行而不是随便给个 16rem，是为了不出现「最后一行被切掉半截」——那看着像样式崩了。
  会话第 7 个起在面板内滚，**边框高度永远是 184px**；类型是固定集合，留 8 行余量。
- **底部渐隐**：还有内容时压一层 `from-surface` 渐变，滚到底自动收掉（滚到最下面还
  压着雾，用户会以为最后一项被挡住）。

### 修复（2026-11-09：「会话」筛选面板右侧留白，且下半截被列表盖住）

**背景**：产物中心点开「会话」胶囊，面板固定 22rem 宽、四五个会话 chip 换两行还空着
半块；更糟的是伸到筛选卡外面的那半截被下面的产物卡片盖住，只能看到前两行。

- **根因之一是动画**：`.rise-in` 用 `animation-fill-mode: both`，动画结束后仍保留终态帧，
  而终态里的 `transform: none` 到计算值变成 identity matrix——卡片于是永远带着一个
  transform，也就永远是一个 stacking context。里面 `z-30` 的弹出面板困在卡片上下文里，
  溢出的部分输给 DOM 顺序在后的列表。改成 `backwards`（只垫首帧，结束不残留）。
- **根因之二是定宽**：会话名长短差得远（「全部对话」vs「排版验证（11-09）1」），chip 云
  必然有短行凑不满。会话维度改成**竖排**（一行一个会话，名称在左、数量靠右），面板宽度
  按内容 `fit-content`，贴着最长那一行，不再有行尾空白。类型维度（十几项短词）仍是
  chip 换行、20rem，不动。
- 实测：会话面板 22rem → 146px，四行全露、无遮挡。

### 修复（2026-11-09：对话里只留最新一份产物，其余一律折叠）

**背景**：交付区原按 `run_id` 分组，「这一轮」的所有产物一起平铺（最多 4 份）。
但一轮里完全可以出两三份——拼装版 + 试排的错版、会议纪要 + 周报——用户看到的是
对话底部连续几张同尺寸文件卡，反而认不出「刚生成的那一份」。

- **`ArtifactDelivery` 不再按 run_id 分组**：只铺产物列表末位（最新一份），其余
  **不论是不是同一轮**全部进「更早的产物 · N 个」折叠区。折叠区默认收起，点开是
  限高可滚动的小盒子。判定「最新」用列表顺序（后端 `created_at asc`、实时事件按
  发生顺序追加），刷新页面结果一致。
- 去掉 `CURRENT_LIMIT = 4` 与「本轮还有 N 个」二级折叠：既然只铺 1 份，这一层
  没有存在意义，两处折叠还会让用户算不清「一共几份」。
- 测试：`ArtifactDelivery.test.tsx` 11 条，新增「同一轮两份 PDF 只铺最后一份」
  「7 份只铺 1 份、其余 6 个在折叠区」两条回归护栏。

### 修复（2026-11-09：会话详情的素材带识别状态，前端类型与契约重新对齐）

**背景**：`ThreadDetailOut.uploads` 声明成了 `list[FileOut]`，而 `_upload_dicts()`
返回的是 `UploadItemOut` 的形状（`status` / `media` / `text_preview`）。契约里没有
`media`，前端 `raw.media?.status` 类型直接报错；即便绕过类型，刷新或切回会话后
右栏也分不清「识别中 / 已识别 N 字 / 识别失败可重试」，素材卡片退化成一条灰条。

- **schema 改回真实形状**：`uploads: list[UploadItemOut]`，并在 `UploadItemOut` 之后
  调 `ThreadDetailEnvelope.model_rebuild()`——`from __future__ import annotations`
  会把类型留成 ForwardRef，缺这一步生成 OpenAPI 直接报 not fully defined。
- **`_upload_dicts()` 补齐 `status` / `media`**：状态优先取 `extra.status`，
  其次 `media.status`，最后按 `parsed` 推（`ready` / `processing`）。`created_at`
  保留，不让原来的字段消失。
- **前端类型漂移一并修掉**：`UploadResponse` 补 `text_preview`；
  `uploadTypeLabel()` 对 `MEDIA_KIND_LABELS[kind]` 加兜底（`noUncheckedIndexedAccess`
  下索引结果可能是 `undefined`）。`contracts/openapi.v1.json` 与
  `src/shared/api/generated/schema.d.ts` 重新生成，`tsc -b` 恢复全绿。
- **`.gitignore`** 补 `.pytest-tmp-*/`：Windows 上残留句柄删不掉、只能改名，
  改出来的旧根不该出现在 `git status` 里。
- 测试：`test_thread_detail_uploads_carry_recognition_fields` 钉住「详情里的素材
  必须有 status / media / text_preview / created_at」。全量 1860 → 1861 passed。

### 重构（2026-11-09：媒体格式表单源化，消除「格式表 + 手写集合」两份真相）

**背景**：「要不要识别」原先是 `MEDIA_SPECS` 之外另写的一个 `NEEDS_RECOGNITION`
集合。加了新格式却忘了改另一份，表现是**上传后一直停在「识别中」**——不报错，
只是永远不出字。这一类「不报错的错」在格式表里出现一次，用户就得删了重传。

- **`needs_recognition` 下沉为 `MediaSpec` 字段**：每条规格自己声明要不要进识别
  队列（默认 `True`，只有 srt / vtt 显式关掉）。`needs_recognition(kind)` 改为从
  规格表**派生**的 `_NEEDS_RECOGNITION_KINDS`，手写集合已删除。
- **导入时自检 `_check_specs()`**：ext 必须小写、带点、不重复；kind 必须在
  `KIND_LABELS` 里；MIME 必须小写、不带参数、是 `type/subtype` 形式；同一个 kind
  的 `needs_recognition` 必须一致；表不能为空。写歪了**导入即崩**，不等用户传到
  那个后缀。抛 `RuntimeError` 而非 `assert`——`python -O` 会去掉 assert。
- **`_BY_MIME` 反查索引**：一个 MIME 可能对应多个后缀（`image/jpeg` → `.jpg` /
  `.jpeg`），索引值为 `frozenset[MediaSpec]`；上传校验的精确命中从「线性扫元组」
  变成 O(1) dict 查找（`media_specs_for_mime`）。类别前缀兜底仍在 security 层。
- **职责边界写进模块 docstring**：本层只管后缀与 MIME，**不判断**文件内容真不真
  （`security._validate_media`）、体积（`MAX_MEDIA_MB`）、时长（`ASR_MAX_MINUTES`）、
  用什么模型（`media_service`）。混进来这张表就会变成第二个配置中心。
- **MIME 逐个标注来源**：哪一条是 `audio/x-m4a`（iPhone 录音）、哪一条是
  `image/pjpeg`（老 IE）、`audio/3gpp`（只有音轨的 3gp 语音彩信）——写清「谁报上
  来的」，删值前能判断它还有没有人用。
- 测试：新增 `tests/unit/test_media_domain.py`（40 条），覆盖后缀归一化（大写 /
  无点 / 空白 / `None`）、MIME 一对多、带 `;codecs=` 参数、空表、重复定义、
  同类标志不一致，以及**自检本身**（把源码里的 `.png` 改成 `PNG` 再执行一遍模块
  顶层，确认导入期直接抛错）。全量 1820 → 1860 passed。

### 修改（2026-11-09：人名与产品型号改成从素材里自动学，手填只作兜底）

**背景**：上一版把「人名、产品名、内部简称」全压给 `ASR_HOTWORDS` 手填。实际维护
不起来——型号一直在换代、项目一直换编号，记漏一个就等于没做；而人名早就写在用户
自己的会议纪要里了，让用户再抄一遍纯属多余。改成**两条自动学习链 + 手填兜底**。

- **人名 `asr_lexicon.people()`**：只认两种**明确**写法 —— 纪要里的名单字段
  （`参会：张伟、李娜`、`记录人：王芳`）和转写稿的说话人行（`[00:12] 张伟：……`，
  要出现两次以上）。两条都过「常见姓氏表 + 非字段名黑名单」两道筛子：
  宁可漏掉少见姓的人（还能手填补上），也不把「销售部」「时间」当人名写进 prompt。
  名单字段允许连写（`记录人：王芳参会：张伟`），按下一个字段名断开。
- **产品名 / 型号 / 内部编号 `asr_lexicon.proper_nouns()`**：抽素材里的英数专名
  （`DHT22`、`SSD1306`、`OPS-20261109-0731`），要求出现两次以上、含大写或数字、
  不是文件名（`W45.txt`）、不是英文功能词。大小写变体合并取出现最多的写法
  （模型会照着 prompt 抄，写对一次省掉整篇错字）。全大写且五个字母以上的普通词
  （`NORMAL`、`ALARM` 这类代码里的状态值）降权，不跟真型号抢预算。
- **优先级**：手填（`ASR_HOTWORDS`）→ 人名 → 型号 → 素材词频通用词。名额与字符
  双重限制（`ASR_PEOPLE=4`、`ASR_PROPER_NOUNS=6`、总长 110 字），超了顺延不硬塞。
- **`health.media`** 增加 `people` / `proper_nouns` 两个当前值，调了能看到生效。
- 实测（用户现有 34 份素材）：自动带出 `王芳 / 张伟 / 李娜 / 陈磊` 与
  `OLED / LED / DHT22 / I2C / SSD1306 / SDA`，prompt 64 字未超预算；
  「参会：销售部、财务部」这类反例全部被挡住。

### 新增（2026-11-09：转写同音字纠错——热词进解码器，再让模型按上下文挑一遍）

**背景**：`base` 档 whisper 听得清「yen shou」，但「验收 / 厌收 / 验受」里落哪个字，
靠的是它那点浅薄的中文语言模型。两处同时下手：**解码期**把常用词告诉它，
**解码后**让大模型按上下文指出写错的词——但只许换词，不许改稿。

- **热词表 `services/asr_lexicon.py`（唯一真相）**：约 110 个会议/办公高频词，
  按「项目交付 → 财务合同 → 客户销售 → 数据指标 → 组织协作 → 技术运维 → 会议本身」
  排默认优先级。加词只加名词性、领域性的词，口语词不进表（只会挤占 prompt 预算）。
- **按用户自己的材料排序**：`rank()` 拿用户已有素材统计每个词的出现次数，出现得多的
  排到 prompt 最前面——这就是「他平时怎么说」能拿到的最好代理，`str.count` 就够，
  不用分词、不加依赖。一篇素材都没有时退回默认顺序；语料里一个都对不上（纯英文）
  就干脆不给词，不硬塞通用词添噪。
- **手填优先**：`ASR_HOTWORDS`（逗号分隔）里写的词永远排最前。人名、产品名、内部
  黑话只能写在这里——模型不可能自己猜对。学到的高频词按 TTL 缓存 5 分钟。
- **热词进 `initial_prompt`**：`build_prompt()` 把词接在短提示后面，总长卡在 110 字
  （prompt 预算只有 224 token，塞太满第一段会把词表复读出来）。只在 `zh` 时注入，
  英文会议不塞中文词。用了哪些词记进 `meta.hotwords`，识别不准时能查。
- **第二层：`services/asr_proofread.py`，只做等长换词。** 把转写稿连同热词交给当前配置
  的模型，让它回一份「错写法 → 正确写法」的配对；代码侧四道闸：**等长**（字数不同一律
  不换，堵死增删内容）、**原件存在**、**同形出现超过 3 次跳过**（那多半是正常词）、
  **总计不超过 40 处**。任何失败（没 Key / 超时 / 返回不是 JSON）原样返回。
  改动记进 `meta.corrections` / `meta.corrected`，改了什么用户能查。
- **实测**：真实调用 1.2 秒，「客户厌收通过，下周排齐再对一次，回宽节点要盯」→
  「客户验收通过，下周排期再对一次，回款节点要盯」，三处精确替换、其余一字未动；
  「他很讨厌收到这种邮件」判为不需要改（模型没把「厌收」当错字），干净的稿子也返回未改。

### 修改（2026-11-09：四类识别再往细里拧一轮）

**背景**：初版只解决了「能不能认」，没解决「认得对不对、读起来像不像人排的」。
下面每一条都是**用户一眼能看出错**的具体场景，改动都收在 `media_service.py` 与
`infra/parsing.py` 两个文件里，文档解析（docx/pdf/xlsx/pptx）一律没动。

- **表格 / 双栏不再串成一句话**：以前「中心点 y 相近就算同一行」再按 x 拼起来，
  左边正文和右边侧栏（或一张表）会读成「华东区华南区82%75%」。现在先按 y 聚行，
  再找**纵向贯穿的列缝**——至少两行在同一个 x 位置都有大间隙才认定是列，按 ` | `
  连成一行；只有一行有大间隙（「华东区完成 82%」这种句子里的空格）照旧拼成一句。
  真机验证：3 列 2 行表格 → `区域 | 完成率 | 金额`；双栏 → `左栏… | 右栏…`；
  单栏大空格 → `华东区完成82%`。
- **倾斜不再累积漂移**：行聚类原来拿「上一块」当参照，翻拍白板斜几度就会一路偏移，
  第 10 块被判成下一行。改成以**行首块**为锚，倾斜最多让一行拆两行，顺序不会乱。
- **低分不再一刀切**：`score < 0.5` 整块丢会误伤长句（个别字没认准，平均分被拉低，
  内容其实是对的）。长块门槛放宽到 0.4，短块维持原标准——反光水印那种一两个符号照旧丢。
- **UTF-16 字幕不再静默变乱码**：Windows 存的 srt/vtt 是 UTF-16，落到 gb18030 会
  「成功」解出满屏怪字还不报错。现在先看 BOM，再看零字节分布识别无 BOM 的 UTF-16。
- **多行 NOTE 不再漏进台词**：VTT 的 `NOTE` / `STYLE` / `REGION` 是块不是行，
  以前只跳过开头那行，第二行就成了「谁说的话」。
- **纯数字台词不再被当段序号吞掉**：只有「紧跟时间轴」的数字才算序号；文件截断在
  「2」这种残片上时，靠「序号连号」判断而不是「只要是数字就删」。
- **VAD 静音阈值 500ms → 800ms**：中文句间三四百毫秒停顿很常见，切太碎会断掉跨句
  上下文，人名和术语开始飘。同时 `speech_pad` 保持默认，不再额外吞字。
- **提示语缩短到一句**：`initial_prompt` 是当「前文」续写的，长指令会被整句复读进正文
  第一行。改成「以下是普通话会议录音。」，并加一层「首段是提示语就丢弃」的兜底；
  简体化继续交给 OpenCC。
- **碎片段合并**：「嗯」「对」被 whisper 切成 0.5 秒一段，一段一行会让纪要变成几百行
  碎片。≤2 字且与下一段间隔 ≤2 秒的先攒起来拼到下一句上，时间戳用前一段的起点。

### 新增（2026-11-09：图片与会议录音 / 视频也能当素材，进来先识别成文字）

**背景**：以前「加素材」只认文档。用户手里真正多的东西是**会议现场**——一张白板拍照、
一段 40 分钟的录音、一段腾讯会议的 mp4、还有别人甩过来的 srt 转写稿。这些东西一个都不能
直接喂给模型：模型看得懂文字，看不懂像素和声波。

- **四类素材、一条取字链路**：新增 `domain/media.py` 作为媒体格式的唯一事实源
  （图片 png/jpg/webp/bmp/tif、会议记录 srt/vtt、录音 mp3/m4a/wav/amr/aac/ogg/flac、
  视频 mp4/mov/m4v/avi/mkv/3gp）。它和 `formats.py` 的并集就是上传白名单，
  但**不进** `OUTPUT_FORMATS`——否则产物下拉里会多出点不出来的 PNG、MP3。
- **图片走 OCR，录音/视频走转写，srt/vtt 直接当文本解析**：OCR 用 RapidOCR
  （PP-OCRv6 中文模型，随 wheel 附带、离线可用，一张 1440×900 截图约 3 秒、61 行）；
  转写用 faster-whisper（CTranslate2 int8，CPU 上 `base` 约 4 倍实时）。
  视频**不抽画面**：会议要的是说话内容，画面 OCR 只会把 PPT 上的字混进纪要。
- **入口不分叉：「添加文件」还是原来那一下**。曾经试过在加号里按 图片 / 文档 / 会议记录 /
  会议录音 / 会议视频 展开五个分支，权衡后撤掉：系统对话框永远开在同一个位置，分了类
  也定位不到具体文件夹，用户还是得自己翻盘，反而多一次点击。现在点「添加文件」直接开
  对话框，`accept` 一次给全（文档 + 图片 + 音视频 + srt/vtt），**类型判断交给后台**：
  认出后缀就走对应的识别链路，用户不用先声明「我要加录音」。
- **拖拽按同一份白名单先分流**：`dataTransfer` 没有 accept 兜底，所以 `onDrop` 自己筛，
  不支持的当场报名字并丢掉（「安装包.apk 暂不支持；可以拖图片、文档、会议记录、录音或视频」），
  不让用户看着转一圈再收到 415。拖拽态还有一层覆盖提示「松开即可添加」。
- **识别是异步的，上传不阻塞**：上传接口立刻回 `status=processing`，识别在
  `ThreadPoolExecutor(max_workers=1)` 里排队跑（一个用户不会同时传十段录音，单 worker
  也让 OCR/ASR 排着来，不会十个一起抢 CPU）。结果写 `.parsed.txt` 并回写 `extra.media`；
  前端每 2.5 秒拉一次 `/threads/{id}/files` 同步，出结果就提示「XX 识别完成，58 字已可用」，
  没有待识别的就自动停。**老素材不重复播报**：进会话时把已有结果的素材先标成已提示过。
- **识别没完不许发**：`status=processing` 的素材文字还是空的，这时发出去模型只看得到
  文件名，会「凭空总结」出一份编的纪要。前端在发送前拦（说清「识别完就能发，不用重传」），
  后端 `validate_attachments` 再拦一次（400 + 待识别清单）。
- **失败可重试，不删了重传**：模型首次下载失败、机器临时忙不过来都是常见原因，卡片标红
  并带原因，点「重试」走 `POST /files/{id}/recognize` 重新入队，文件已经在库里。
- **限额分两档**：文档 20MB（原样），图片/音视频 200MB（`max_media_mb`）——一段两小时的
  全员会不止 20MB。
- **繁转简**：whisper 中文常吐繁体（「週／壓／張」），转写时先给一句「用简体、带标点」的
  `initial_prompt`，出字后再用 OpenCC 统一过一遍；opencc 是可选依赖，没装就原样返回。
- **依赖收进可选 extra**：`pip install -e "backend[media]"`。模型与推理框架几百 MB，
  只用文档的用户不该为它付体积；没装时 `/api/v1/health` 会如实报 `ocr: false`，
  上传图片提示「识别组件未安装」而不是静默失败。语音模型首次使用才下载（默认走
  `hf-mirror.com`），落在 `models/asr`（已加进 `.gitignore`）。
- 测试：后端新增 `tests/unit/test_media.py`（白名单/内容校验、srt/vtt 剥时间轴、OCR 空结果、
  转写时间戳与截断、异步状态流转、失败重试、识别中禁止发送、繁转简降级）；
  前端覆盖拖拽分流、`识别中…/识别失败+重试` 徽标、`upload/sync` 与 `upload/retry` 的
  reducer 语义、轮询闭环与「老素材不播报」。

### 加固（2026-11-09：四类识别的边界条件）

初版只保证「能出字」，这轮把「识别率莫名下降」的场景逐个补上，每一处都有单测钉住：

- **图片（OCR）**
  - **EXIF 方向**：手机竖拍是 `Orientation=6`，不转过来模型看到的是躺倒的横排字 ——
    先 `exif_transpose` 再识别。
  - **透明底压白**：透明 PNG 直接转 RGB 会得到黑底，深色文字连同背景一起糊掉。
  - **超长边缩到 2200**：4000×1200 的截图实测从「十几秒」降到 **1.3 秒**、3 行全对；
    同时把 300px 宽的小截图放大一档，检测框才落得上去。
  - **低置信度丢块**：反光/遮挡处的乱码低于 `ocr_min_score`（默认 0.5）不进正文，
    meta 里给 `dropped`；全是低分时报「太模糊」而不是「图里没字」。
  - **按位置重排**：多栏界面按检测顺序返回会左右穿插，按中心点分行、行内再按 x 排，
    同一行被切开的块拼回去（中文不补空格，英文单词间补）。
  - **多页 TIFF** 只认第 1 页，正文里注明「共 N 页，只识别了这一页」。
- **录音 / 视频（转写）**
  - **先探音轨**：录屏忘了开麦的 mp4 以前只会得到一句 `Invalid data found`，
    现在直接说「这个视频里没有音轨，听不到说话内容」（不可重试），也不白跑一遍模型。
  - **容器时长优先**：解码器报的时长可能为 0，用户看到的「这段多长」以容器为准。
  - **重复句去重**：静音/掌声处模型会连吐同一句，连续两次相同且间隔 <3 秒只留一条
    （meta 的 `repeats` 记录丢了几条）。
  - **异常截断**：底层报错只留「类型 + 一行消息」，不把几十行 ffmpeg 日志甩进界面。
  - `ASR_LANGUAGE=auto`（或留空）= 让模型自己判语种，不塞中文前置提示。
- **会议记录（srt / vtt）**
  - **按字幕块合并**：一条字幕被屏幕宽度折成两行，是同一句话，不能当两句引用；
    中文直接相连（「我们下周一再对一次时间定在下午三点」），英文才补空格。
  - **说话人保留**：`<v 张伟>` / `<v.loud 李娜>` 转成「张伟：」「李娜：」（样式类不算名字），
    台词里已写「张伟：」则不再叠一层。
  - 重复导出的同一 cue 去重；老工具只用 `\r` 换行也能解析；块内的纯数字台词
    （「2026」）不再被当成 SRT 段序号丢掉。
- **可观测**：识别结果的 `media.meta` 多了 `size / processed_size / scaled / elapsed /
  score / dropped / audio_codec / source / repeats`；`/api/v1/health` 的 `media` 多报
  `ocr_max_side` / `ocr_min_score` / `asr_language` —— 调参后能确认真的生效。
- 测试：`test_media.py` 从 43 条扩到 **62 条**，新增的 20 条按上面四类分组，
  真图 / 真 wav / 真 mp4 只当输入，推理仍用假引擎（单测不加载模型）。

### 新增（2026-11-08：预览可切「全窗口」，默认仍是半窗口）

**现象**：预览只能在一个 900px 的弹窗里看，屏幕大一点就只剩中间一小块，长文档要一直
滚；想摊开看又没法把窗口放大。

- **默认半窗口**：弹窗 900px、一张 720px 的纸摆在桌面上——够看清版式，又不遮掉背后的
  对话。默认值不记忆：全窗口是「临时放大看」，下次打开还该回到半窗口。
- **标题栏右侧一枚展开键切全窗口**：`Modal` 新增 `fullscreen`（铺满整个窗口、去圆角去
  外边距、只让出桌面端窗口按钮那条 `--titlebar-h`）与 `actions`（关闭键左边的额外操作）。
  全窗口下内容区不再套第二层滚动，纸 / iframe 自己滚，滚轮不会被两层容器抢。
- **全窗口的纸是一整页而不是一段内容**：`.doc-paper--full` 撑满可用高度、留白 48/56、
  去圆角；**正文仍按一行 40 来个汉字排**，字不跟着放大（预览要和 Word 的读感对得上），
  真正需要横向空间的是表格——表格类在全窗口下换满宽（`max-width: 100%`）。
- **Esc 分两级**：`Modal` 新增 `onEscape` 供调用方接管；预览里全窗口按 Esc 先退回半窗口，
  再按一次才关——像看全屏 PDF，不会一按就把预览关掉、还得重新点开。
- 测试：`Modal` 覆盖 `fullscreen` 与 `onEscape`；预览覆盖「默认不是全窗口 / 切过去切回来 /
  全窗口下 Esc 只退回 / 表格类带 `doc-paper--full`」。

### 修复（2026-11-08：标题编号不再混用汉字与阿拉伯数字）

**现象**：中文编号方案排出来是「一、→（一）→1.→（1）」——同一条竖线上，编号字形从汉字
跳到阿拉伯再跳回括号数字，扫标题时视线一直在重新辨认，一份稿子看着像两个人拼的。
`article`（合同）同样挂着「1.」。

- **`cn` 只走到中文能干净表达的层级**：一级「一、」、二级「（一）」，三级起不编号（空模板）。
  中文没有通行的第三级纯中文序号，硬凑只能借「1.」「①」这类外来的，又混回去了；层级靠
  字号、加粗与缩进区分，中文报告里本来就这样。`article` 同理：第一条／（一）／三级起不编号。
- **新增 `gb` 方案**：`一、／（一）／1.／（1）`，只有公文类（公文、通知、通报、公告、请示、
  批复、函、意见、决定、会议通知）取它。GB/T 9704 把层次序数写死，公文不这么写属格式不合规，
  这是「不混排」原则的唯一例外，也是「尽可能少用」里的那个「尽可能」。
- `NUMBERING_ALIASES` 里「公文式」「公文」「国标」「gb」指向 `gb`；`NUMBERING_INDENTS` 补一行。
- 测试：`test_numbering_switches_with_the_document_type` 加 `gb` 一档并改中文档的三级期望；
  新增 `test_chinese_schemes_do_not_mix_han_and_arabic_numerals` 直接卡住「中文方案里不许出现
  `{n}` / `{dot}` 模板」，以后谁再往 cn 里塞阿拉伯序号，测试就红。
- 技能 `doc-layout` 的编号对照表改成五套并写明原因；技术文档与 CHANGELOG 同步。

### 变更（2026-11-08：紧凑版式改为「同一套层级、只是更密」，确认卡片补齐）

**现象**：三档版式里 `compact` 是唯一「通篇顶格」的那档——标题不缩进、正文不空两格，
一页正文连成一片，标题只剩字号差异，看着像没排过版。同时 `Composer` 收了个
`waitingApproval` 的孤儿 prop，`tsc -b` 一直报三条错。

- **`compact` 改成跟默认版式同一套规则**：标题照样逐级内缩、正文照样首行缩进两格，
  密度靠字号（五号）、行距（1.25）、段距（4pt）、页边距（2cm）挤出来。读者认的是同一套
  层级，换个版式照样一眼看到段落从哪起。
- **预览同步**：`blocks_to_html` 在紧凑版式下把整篇包一层 `.doc-compact`，CSS 里整体缩
  一档（正文 15→14、行高 27→24、段距 14→10）。以前预览只把缩进清掉，既没变密，又抹平
  了层级——两个版式打开来几乎一样，用户会以为「紧凑」没生效。
- **版式别名按「用户怎么描述密度」铺开**：`紧凑 / 精简 / 扁平 / 平铺 / 密排 / 密集 /
  高密度 / 资料 / 说明书 / 手册 / 附录 / 速查 / flat / dense / tight / manual /
  handbook / appendix` 都落到 `compact`；去掉已经不成立的「顶格」。`resolve_preset()`
  认不出时自己落回 `report`，不再把原词透传给调用方兜底。
- **确认卡片补齐**：新增 `ApprovalPanel`（待确认卡片 + 已处理的一行流水账），挂在输入区
  上方；`Composer` 收下 `waitingApproval` / `onOpenApproval`，等确认时说清「有一步要你
  确认」并给一条「去确认」。审批状态机与 `submitApproval` 早就接好了，缺的就是这块界面：
  没有它，运行停在 `waiting_approval`，用户只看到输入框变灰。`tsc -b` 的三条错随之消失。
  说明：写操作现在由 `policy.decide_write` 自动判（拦下就发一张「没动 + 为什么」的卡），
  不弹卡问人；这块界面接的是 `ApprovalGate` 发起的那条路（外部接入 / 以后真要停下来问）。

### 修复（2026-11-08：词表增密、思考句带上理由）

- **词表密度提一档**：`DOC_TYPE_ALIASES` 从 27 条铺到 80+ 条（「本月汇报」「红头文件」
  「投标文件」「每周小结」这类口语与行业叫法，加 weekly / prd / cv 等英文写法）；
  `guess_doc_type` 改成**类型键与别名一起按长度倒序匹配**——以前先找类型键再找别名，
  「年度报告」会先命中「报告」，别名根本没机会；`intent.py` 的寒暄 / 确认 / 撤回 / 语气词
  与强授权短语、`real_engine` 的决策标记 / 明确动手 / 承诺标记、演示与表格词表的主题 /
  版式 / 表类型别名同步加厚。
- **思考句带上「为什么」**：`decision_line` 优先挑带理由的那句（因为 / 所以 / 与其 / 宁可）；
  读完素材后补一条 `material_thought`——几份、多少字、几张表、素材自带几个小标题，由此定
  写法（有进展计划按周报写，没有就按素材自己的顺序归纳，免得硬套只能编）。一轮只补一条，
  模型自己给过判断就不重复。

### 修复（2026-11-08：正文不再带项目符号，标题序号全篇只用一套）

**现象**：生成的周报里每段前面挂一个「· 」，一眼看过去像内部速记；同一篇里「二、」下面
又挂着作者手写的「2.1」，两套编号并排，像两个人拼的。

- **`- ` 条目一律排成正文段落**（`doc_render._append_items_or_paragraphs`）：docx 里不再写
  `· ` 字面量，预览里不再输出 `<ul><li>`，两条路都是空两格的一段正文。以前只在「这一组
  全是完整句子」时才转段落，混进一条短句整组就打回圆点，同一篇里一节是段落、一节是圆点。
  有序条目（`1. `）保留序号、写进行首——序号本身是信息。`blocks_from_sections` 里
  「来源引用」的圆点列表也一并收成段落。
- **标题编号统一重排**（`_Numbering.label` 用 `_LEADING_NUMBER` 剥旧号）：作者写没写编号、
  写的是哪一套，都先剥掉再按 `numbering` 方案数一遍，「二、」下面挂「2.1」这种混排不再出现。
  `none` 方案不剥不加；「3 个要点」这类数量词不剥（`_MEASURE_WORDS`）；稿子从二级小节
  开头时缺的上级按 1 补，不会出现「0.1」。
- **版式三档收敛成「默认 + 备选」**：新增 `resolve_preset()`，认「紧凑 / 扁平 / 顶格 / flat」
  这些口语说法落到 `compact`；默认仍是 `report`。工具描述里写明「用户没提紧凑 / 扁平 / 顶格
  就用默认的」——通篇顶格那套看着省地方，但当交付件的默认版式不够正式。
- 测试：`test_doc_render.py` 里断言圆点/`<ul>`/原样保留编号的几条改写为新口径，并新增
  「条目永不出圆点」的端到端断言；后端 1711 passed / 42 skipped。
- `doc-layout` 技能（两份）同步：编号会重排、中文正式稿不用项目符号、三档版式怎么挑；
  自检表加「正文段落前面有没有多出圆点」。
- `docs/tech/06-agents-tools-skills.md` 改写对应三段（编号重排 / 无项目符号 / 三档版式）。

### 新增（2026-11-08：标题编号按文档类型自动选，四套方案）

**背景**：以前不管写周报还是写论文，一级标题都是「一、」。用户提了两件事——「编号样式按文档类型
自动选择挺不错」和「只有文档名字（作文标题那种）居中，正文里各级标题左对齐」。

- `doc_lexicon.py` 新增 `NUMBERING_SCHEMES`（四套，四个层级各一个模板）：
  `cn`（一、／（一）／1.／（1））、`decimal`（1.／1.1／1.1.1／1.1.1.1）、
  `article`（第一条／（一）／1.／（1））、`none`（不编号）。配 `NUMBERING_ALIASES`
  （「层级小数」「不编号」…）与 `resolve_numbering()`。
- `DOC_TYPES` 每一类补 `number` 字段：周报月报与公文走 `cn`，论文 / 方案 / 报告 / 白皮书走
  `decimal`，合同协议走 `article`，纪要 / 简报 / 说明书 / 手册 / 简历 / 讲话稿走 `none`。
- 新增 `guess_doc_type()`：从标题里认类型（「W46 周报」→ 周报），长键优先，
  避免「述职报告」被「报告」抢走；认不出给空串，落回 `cn`。
- `doc_render._Numbering` 改成按方案渲染；识别「编号后接空格」的写法
  （`2.1 测试数据记录`），不再被再套一层变成「1.1 2.1 …」。（后一条已由本文件顶部的
  「标题序号全篇只用一套」取代：现在是把旧编号剥掉重排。）
- `render_docx_blocks` / `blocks_to_html` 新增 `numbering` 参数，预览与下载必须同一套
  ——预览是「一、摘要」、下载是「1. 摘要」，用户会以为拿错了文件。
- `doc.generate_report` 新增 `doc_type` 参数，空着就从标题猜。**只取编号这一项**，
  不动字号行距：类型判错一档，代价应该只是编号款式不对。
- `doc-layout` 技能（两份）第二节重写为「编号按文档类型走」的四套对照表，自检第 4 条
  加上「编号款式跟文档类型对吗」。
- **层级不再顶在同一条竖线上**：`1.` 与 `1.1` 左边缘齐平，读者只能靠多读一个编号判断
  谁是谁的下一层。现在一级顶格、往下每级缩 1 字符（`NUMBERING_INDENTS`，写
  `w:leftChars` 按字符存，字号一换缩进跟着缩放）。只缩一格：正文段首本来就空两格，
  标题也缩两格会和段首撞线，而正文续行在最左边，读起来像正文比标题还宽。
  - `Preset.heading_indent`（默认 True）：`gongwen` / `compact` 设 False——GB/T 9704
    规定公文各级标题顶格，说明书这类紧凑版式同理，加缩进属于格式不合规。
  - 预览侧 `Heading 1~4` 改映射到 `h2.doc-h1` → `h5.doc-h4`，与后端 `blocks_to_html`
    的标签、类名一字不差；缩进量在 `tokens.css` 的 `.doc-h1~doc-h4`（0/1/2/3em）。
  - 后端兜底预览（`_render_docx_preview`）同步加级别类与 inline 缩进。

**大标题居中这条没有改**，也再确认了一遍：`Title` 样式（文档名字）居中且全文最大；
`Heading 1~4` 段落级与样式级都钉了左对齐，预览里 `.prose-docx h1:not(.doc-title)` 带
`!important`，旧产物里存成居中的标题也不会再居中。

### 修复（2026-11-08：预览正文补回「首行缩进两格」，小节标题强制左对齐）

**现象**：界面预览里的正文全是顶格的（Word 里明明空了两格）；打开旧产物时，
「一、本周概况」「二、温湿度相关记录与要点」仍是居中大字。

**原因**是两层，都不在生成逻辑里：

- 缩进规则写在 `.prose-docx p.doc-para` 上，而 mammoth 转出来的正文是**裸 `<p>`**、
  不带这个类，整条规则一次都没命中。用户在 Word 里看到空两格、预览里没有，
  只会判定「你没按我说的做」。
- 旧产物里 `Heading` 段落存的是 `w:jc="center"`，mammoth 会把它转成 inline style
  带进预览；普通 CSS 声明压不住 inline style。

- `frontend/src/styles/tokens.css`：缩进改到标签级 `.prose-docx p { text-indent: 2em }`；
  副标题 / 元信息 / 图注 / 表格与列表里的段落进白名单清零；紧凑版式用 `doc-flat` 显式顶格。
- `tokens.css`：`.prose-docx h1:not(.doc-title)` 和 h2–h6 的 `text-align: left` 加
  `!important`——不管文件里带的是什么对齐，预览一律按「只有大标题居中」呈现。
- `services/doc_render.py`：副标题改用 `Subtitle` 样式（清掉样式自带的斜体），预览按
  样式名映射成 `.doc-lead`；不然它会被当成正文缩进两格，居中的字再缩进，整行往右跑。
- `ArtifactPreviewModal.tsx`：styleMap 增加 `p[style-name='Subtitle'] => p.doc-lead`。
- `artifact_service.py`：兜底预览的正文也写 2em 缩进，副标题 / 图注 / 列表项清零
  （这条路径用 inline style，吃不到 tokens.css）。
- 测试：`prose-docx.test.ts` 扩到 7 条（缩进 2em、白名单、只有大标题居中、`!important`）；
  `test_doc_render.py` 新增副标题样式、紧凑版式两条。

### 变更（2026-11-08：跟用户说话不再用「六节骨架」这类内部叫法）

**现象**：商量方案时回复写「改回六节骨架 / 三段结构不动 / 六节骨架 + 版式一起改」，
用户回了一句「用户又不知道六个骨架啥意思」。

**原因**：`system.md` 和 `TOOL_RULES` 里本来就是用这几个词描述的，模型照着复述。

- `prompts/system.md` 新增「# 说人话」：给对照示例（说「摘要、进展、数据这几节」，
  不说「六节骨架」；说「小节标题不居中」，不说「heading 对齐」），列出禁止出现的词
  （骨架 / 版式引擎 / preset / body / outline / blocks / 词表 / 渲染器）；
  第 4 条里的「六节骨架」改成「周报最常见的那几节（摘要、进展、数据、风险、下周计划）」。
- `agents/real_engine.py`：`TOOL_RULES` 同步改写；`REPLY_RULES` 增加一条
  「讲结构就把节名念出来」。
- `tools/builtin/doc.py`：工具描述与 `_render_docx` 的 docstring 同步。
- `skills/doc-layout/SKILL.md`（`skills/` 与 `skills_catalog/` 两份）：「写文档也不会
  每篇都六节」改成「每篇都长成一个样」。

### 修复（2026-11-08：只有文档大标题居中，一~四级标题改回左对齐）

**现象**：生成的周报在预览里，「摘要 / 本周进展 / 关键数据」每个小节都变成页面中间的
大黑标题，跟文首的「W46 周报」长得一样大——读者分不清哪一行才是全文标题。

**原因**：Word 的 `Title` 和 `Heading N` 经 mammoth 转成 HTML 后**都落到 `<h1>` 上**，
而 `.prose-docx h1 { text-align: center; font-size: 24px }` 是按标签写的，于是每一节都被
当成大标题。这是版式规则写错了一层，不是模型写错了文档。

- `frontend/src/styles/tokens.css`：居中收窄到 `.prose-docx h1.doc-title`（22px）；
  普通 `h1/h2/h3` 左对齐、19 / 17 / 16px 递减，与大标题拉开一档。
- `services/doc_render.py`：`heading()` 显式写 `LEFT` + 取消首行缩进（样式级也钉一次，
  `Normal` 是两端对齐，只改段落会让脚本用样式写的标题飘回去）；`blocks_to_html` 的
  文档标题改出 `<h1 class="doc-title">`，小节标题从 `h2` 起（原来 4 级会挤成同一个 h4）。
- `services/docx_utils.py`：`apply_headings()` 同样钉 `LEFT`——模型写脚本用 `docx_utils`
  生成时，标题不该是另一种排法。
- `services/artifact_service.py`：兜底预览保留标题层级（`Heading N → h{N+1}`），
  原来全部压成 `h2`，看不出层级。
- 技能 `doc-layout`：字号表逐行标「左对齐、不缩进」，新增一条「整篇只有一个元素居中」，
  自检清单补第 5 条。
- 测试：`tests/unit/test_doc_render.py` 2 条（docx 对齐、预览只认一个 doc-title）+
  `src/styles/prose-docx.test.ts` 4 条（直接读 CSS 卡住「只有 doc-title 居中」）。

### 修复（2026-11-08：`PYTHONHOME` 劫持 venv 标准库导致后端起不来）

**现象**：`.venv\Scripts\python.exe -m uvicorn backend.app.main:app ...` 秒退，堆栈里全是
`E:\lib\...` 路径，末行 `AssertionError: SRE module mismatch`；前端 5173 随即刷一排
`ECONNREFUSED 127.0.0.1:8000`。**不是代码挂了，是机器上有条用户级 `PYTHONHOME=E:\`**，
优先级压过 venv 的 `pyvenv.cfg`，解释器拿 A 版本二进制配 B 版本标准库。

定位到的版本差：`E:\` 根目录是 **Python 3.11.9**（`E:\Lib`、`E:\DLLs` 就在那儿），
`.venv` 是 **3.13.14**。`E:\python.exe` 自己并不需要这个变量（`sys.prefix` 由 exe 位置推导），
所以它只是纯负担。已删掉该用户变量，实测干净环境启动 → `/api/v1/health` 返回 200。

- 机器侧：删除用户变量 `PYTHONHOME`（原值 `E:\`，如需还原：`setx PYTHONHOME E:\`）。
- `Makefile`：`unexport PYTHONHOME PYTHONPATH`，避免 `make api` / `make test` 踩同一个坑。
- `README.md`：启动后端一节补「起不来 ①/②」两段排查（SRE mismatch、端口被占），
  并点明前端那排 ECONNREFUSED 只是后端没起的连带反应。
- `KNOWN_ISSUES.md`：新增 #22（现象 / 原因 / 绕过 / 根治 / 排查口径 / 本机处理记录）。
- `启动开发模式.cmd`、`启动 Office Agent.cmd` 早前已 `set "PYTHONHOME="`，本次未改，只做交叉印证。

### 重构（2026-11-08 第八十九轮：四份格式词表 + 四个版式技能，文档骨架交还给素材）

**背景**：上一轮只给 Word 做了词表，PPT / Excel / 纯文本的「字号、格式、符号」还散在
各自的 utils 里；技能也只有 `doc-layout` 一份。另外用户指出一个更根本的问题：
**文档结构不能定死**——「写作文不能每篇都总分总」，骨架和标题都得由这一次的素材决定。

**改法**：

1. **四份词表，一份管一种产物**：
   - `doc_lexicon` 扩到 29 族字体（含近似替换表 `resolve_font`）、12 套标题刻度、
     14 种纸型（含 A3/A5/B5/16 开/32 开/横向，认「A4横版」「16开」）、58 类文档
     （`resolve_doc_type` 认别名、认括号、认不出给默认）、行距 18 档、缩进 0–8 字符、
     表格样式四档（新增 `zebra` 隔行浅底）。
   - 新增 `slide_lexicon`：画幅、9 种版式、字号（封面 40 / 标题 36 / 正文 20）、
     每页 6 条上限、5 套配色；`pptx_utils` 的尺寸与字号改从它取。
   - 新增 `sheet_lexicon`：数字格式语义名、列名 → 格式/列宽、11 类表；
     `write_table` 现在**按表头自动套格式**（金额带货币、占比带百分号、
     `00123` 强制文本），并支持 `sheet_type` 决定冻结首列还是首行。
   - 新增 `text_lexicon`：折行宽度（76 半角 ≈ 38 汉字）、分隔线、项目符号、
     章节标记、四级编号、5 种文本布局；`txt_wrap` 默认宽度与 `render_text` 的
     `【】` 都改从它取。
2. **新增三份版式技能**：`ppt-layout`（页序 / 一页一个观点 / 六条上限 / 字号配色）、
   `sheet-layout`（表类型 / 列规范 / 数字格式 / 合计与命名）、
   `text-layout`（三样分层手段 / 折行 / 常见文本写法）。每份都带八条交付前自检，
   与 `doc-layout` 一样「规则在技能、词表在 lexicon」。`doc-layout` 同步精简并补上
   「骨架由素材决定」。
3. **文档骨架交还给素材**：`_split_named()` 保留每个小节的**原标题与顺序**，
   `_sections_from_material()` 照它成文——素材写「一、退款率复盘」就是「一、退款率复盘」，
   素材没写的节不出现（不再写「素材里没有…」）。词表外的中文序号小节也认
   （`_LOOSE_HEADING`，只认中文序号，避免把 `1. 完成联调` 这种列表项当小节）。
   六节骨架只在素材连小节标题都没有时兜底，且兜底时**去掉重复句**（带数字的进展句
   会同时命中「进展」和「关键数据」）。
4. **标题从素材内容起**：`title_from_material()` 取素材首行（短、不带句读、不是栏目行、
   不是图注），拼成「素材标题 · 产物类型」；首行是「工作周报」这类通用词时退回素材名。
5. **提示词与工具描述改口径**：`system.md`、`TOOL_RULES`、`generate_report` 描述统一成
   「结构由这一次的素材决定，骨架只是兜底」，并点名四份版式技能。

**度量**：后端 1697 passed / 42 skipped（新增 `tests/unit/test_lexicons.py` 19 条 +
骨架/标题 3 条）；ruff 全绿。实机验证：`write_table` 自动套出
`@` / `¥#,##0.00` / `0.0%` / `yyyy-mm-dd`；`write_deck` 九条要点自动拆成 6+3 两页；
素材带自定小节名时生成的 docx 小节标题与素材一致。

### 重构（2026-11-08 第八十八轮：按中文公文习惯补首行缩进、大标题居中，格式词表集中一处）

**背景**：第八十七轮把版式刻出来了，但漏了国内办公文档最硬的三条：正文段首要空两格、
大标题要居中且必须是全文最大的字、正文默认宋体小四。参考稿（`{0A878F9F…}`、
`Clipboard_Screenshot`）一眼就能看出这几处不对。另外字号、行距、缩进的值分散在
`docx_utils` 与 `doc_render` 里各写一份，改一档字号要翻两个文件。

**改法**：

1. **新增 `services/doc_lexicon.py`（格式词表）**：中文号数（初号 42 → 八号 5）、
   中英字体成对表、行距（单倍 / 1.15 / 1.25 / 1.5 / 1.75 / 双倍 / 固定值）、
   首行缩进（0–4 字符）、四级标题刻度（report / gongwen / thesis / compact）、
   页面预设、13 类文档的整套参数，全在这一份；`resolve_size` / `resolve_line` /
   `resolve_indent` / `resolve_align` 负责把「小四」「一点五倍」「两字符」翻成数值。
   `docx_utils` 与 `doc_render` 都从这里取，不再各写一份裸数字。
2. **正文首行缩进 2 字符**：写 `w:ind/@w:firstLineChars="200"`（Word 里「缩进 2 字符」
   就是它）并补 `w:firstLine` 兜底 WPS；存字符不存 pt——字号一改，缩进仍然是两格。
   预览同步：`blocks_to_html` 给正文段落加 `.doc-para`，CSS 给 `text-indent: 2em`，
   预览与下载一致。`compact` 等以信息密度为先的版式不缩进。
3. **大标题居中、宋体、全文最大**：`Preset.title_align="center"`，`title_font` 走
   `FONT_ROLES["title"]`；`Preset.__post_init__` 把 `title_size` 顶到
   「比所有小节与正文都大两档」，只调正文的人不会顺手把标题调小。
4. **正文默认宋体小四、节标题黑体**：`report` 版式正文 `FONT_BODY`（宋体 12pt）、
   一级黑体三号、二级黑体四号、三级宋体小四加粗；行距 1.5 倍。
5. **行距可整篇覆盖**：`generate_report(..., line_spacing="单倍" | "1.15" | "双倍" |
   "固定值28磅")`，不传跟版式走。
6. **一整句话被写成 `- ` 时退回段落**：一组条目全是完整句子（≥36 视觉字符且以句末
   标点收尾）说明作者在写段落，排成圆点会读成清单；混着短条目才仍当列表。
7. **`doc_lexicon` 随沙箱一起复制**：新增 `UTIL_SUPPORT`，不进提示词的库清单，但
   必须出现在脚本工作目录——少它 `docx_utils` 一 import 就 `ImportError`。

**度量**：后端 1675 passed / 42 skipped（新增 `tests/unit/test_doc_lexicon.py`）；
前端 59 文件 1277 passed；ruff / mypy / tsc / prettier / eslint 全绿。
实机验证：Word 导出样张确认 `Title` 宋体 22pt 居中、`Heading N` 黑体、正文段
`firstLineChars=200` + 1.5 倍行距；应用内预览与下载件同版式。

### 重构（2026-11-08 第八十七轮：文档版式按预览刻一套，正文交给模型自己写）

**背景**：用户给的参考稿（W45 老板版）是「一句话结论 → 一张进度表 → 一件要他拍板的事
→ 风险 → 下周承诺」，排版是黑标题、灰副标题、浅灰表头的无衬线商务风。
而 `doc.generate_report` 生成的是宋体 12pt + 蓝色 Calibri 标题 + 零间距，
正文固定六节，还带一行「生成时间 ｜ 模式 ｜ 来源」；没有素材时每节各写一句
「素材里没有…」，一份周报五句「没有」。同一个文件在预览里好看、下载下来难看。

**改法**：

1. **新增 `services/doc_render.py`（版式引擎）**：`parse_markdown()` 切块 →
   `DocxRenderer` 写 Word、`blocks_to_html()` 写预览，**一份 blocks 两条路**。
   版式三套（report 默认 / gongwen 公文 / compact 紧凑），字号刻度对齐 `.prose-docx`：
   标题 20pt、小节 15pt、三级 12.5pt、正文 10.5pt、行距 1.5。
   细节：标题用内置 `Title` / `Heading N` 样式（Word 导航窗格与 mammoth 才认得出）；
   一级标题自动编号（一、／（一）／1.／（1），原文自带编号则保留）；
   表格列宽按内容分（汉字算两格）而不是均分；表头浅灰底 + 跨页重复。
2. **`doc.generate_report` 支持 `body` / `subtitle` / `layout`**：`body` 收整篇 Markdown
   （`## ` 小节、`- `／`1. ` 列表、`| 表格 |`、`> 引用`、`**加粗**`），给了就按它排版；
   不给才退回六节骨架。工具描述、`system.md`、`TOOL_RULES` 都改成「真给人看的稿子
   必须自己写 body」。
3. **删掉正文里的机器信息**：docx / preview / txt / md / xlsx / pdf 都不再写
   「生成时间 ｜ 模式 ｜ 来源」。素材为空时给干净骨架 + 标题下一行「…框架 · 待补素材」，
   不再每节写「素材里没有…」。
4. **词表扩容**：`_HEADING_KEYS` 从 30 条到 90+ 条（本周完成／交付情况／下周承诺／
   行动项／执行摘要…）；`docx_utils` 补 `FONT_H4` / `FONT_QUOTE` / `FONT_CODE` /
   `PAGE_BRIEF` / `PAGE_MEMO` / `LINE_TIGHT` / `LINE_LOOSE` / `HEADING_SCALE` /
   `TABLE_STYLES` / `DOC_TYPES`（13 类文档 → 整套版式参数），`apply_headings` 支持
   `scale=`，`add_table_simple(style=)` 认同义词。新增 `doc-layout` 技能（骨架表、
   标题层级、字号行距、表格与列表规范、八条交付前自检）。
5. **思考过程不再报步数**：`ExecutionTrace` 去掉「共 N 步」，失败提示改「N 处没走通」；
   `PlanCard` 去掉「· N 步」。步数上限 24 → 60，硬顶 60 → 200（`.env` / `.env.example`
   同步）：它只防死循环，不是「做到第几步就交差」。
6. **演示产物与真产物对齐**：`mock-run.ts` 的 `MOCK_REPORT_HTML` 换成同一套版式
   （去掉蓝线装饰与「生成时间」），预览里的 `.doc-lead` 补样式。

**度量**：后端 1662 passed / 42 skipped（新增 `tests/unit/test_doc_render.py` 8 条 +
无素材/正文两条）；前端 59 文件 1277 passed；ruff / tsc / prettier 全绿。
实机验证：Word 导出的样张与参考稿版式一致；`?mock=1` 演示流思考过程只显示 `3/3`。

### 重构（2026-11-07 第八十六轮：删掉审批卡这一层，门控按「这一步会动什么」自己判）

**背景**：第八十五轮把默认档的弹卡收窄到「删了回不来」的动作，但卡本身还在。
实机用下来两条反馈都不满意：

1. **卡片在对话流里太糅杂**。工具流水、思考过程、方案卡之后又插一张带两个按钮的
   审批卡，一眼看过去不知道哪块是要动手的地方；而且「确认一下」这件事，用户每轮
   都要点一次，点久了只会闭眼点。
2. **拦下时挂着「脚本执行失败」的红字**。门控没放行，走的是
   `tool.finished(ok=False)`，前端一律画成失败；用户看到的是「这个软件跑个脚本
   老失败」，而真实情况是「它决定先不做」。观感和事实相反，这是最该修的一处。

**改法**：把「审批卡」整层拿掉，把「要不要动手」收回内核——要么按他的话办，
要么不做并说明；同时把门控与脚本执行结合得更细。

- `backend/app/tools/spec.py`：新增**效果分档** `EFFECT_READ` / `EFFECT_OUTPUT` /
  `EFFECT_DESTRUCTIVE` 与 `ToolSpec.effect_kind(args)`，取代原来的「写 / 不写」
  二元判断。**没声明效果的高风险工具按最严档（destructive）处理**——门控认不出
  这一步会动什么，就没资格替它担保。
- `backend/app/tools/builtin/code.py`：`_scan_script()` 改成返回
  `(writes, destructive)`，`_script_effect()` 据此给出三档。新增
  `_DESTRUCTIVE_CALLS` / `_DESTRUCTIVE_BARE`（`os.remove`、`shutil.rmtree`、
  `unlink`、`subprocess.*`…），且**先判 destructive 再判写**——`os.remove`
  同时出现在写词表里，顺序反了删除会被当成普通写盘。`run_python` 改为
  `effect=lambda args: _script_effect(...)`。
- `backend/app/tools/builtin/file.py` / `doc.py`：`file.delete` 声明
  `EFFECT_DESTRUCTIVE`，`doc.generate_report` 声明 `EFFECT_OUTPUT`。
- `backend/app/agents/policy.py`：`decide_write()` 重写为
  `decide_write(spec_risk, reading, *, message, effect, mode, continuing)`；
  新增 `MODE_BARS`（档位只调**放行线**，不再是「弹不弹卡」：
  谨慎 0.85 / 标准 0.72·0.75 / 放手 0）；新增 `REASON_CONTINUING`
  （本轮已有产物 → 接着改不再重新授权）、`REASON_DESTRUCTIVE`
  （动已有文件需 `MIN_DESTRUCTIVE_CONFIDENCE=0.85`）、`REASON_ALL_ALLOW`。
  删除 `should_ask_authorization()` / `ASKABLE_REASONS`。
- `backend/app/agents/real_engine.py`：**删掉整段审批流**——
  `_approval_flow` / `_ask_to_authorize` / `_approval_preview` / `_needs_approval` /
  `_wait_for_approval` 与全部审批状态位；门控调用改为带 `effect` 与
  `continuing`；`run.completed` 固定发 `approvals=[]`（字段保留，契约不改）；
  收尾文案里删掉卡片分支，补 `REASON_DESTRUCTIVE` 的说法。
- `backend/app/agents/mock_engine.py`：同步去掉审批挂起，直接
  `_call_tool(doc.generate_report)` → `artifact.ready` → `run.completed`。
- `backend/app/agents/engine_protocol.py`：删掉 `needs_approval()` 与
  `IRREVERSIBLE_TOOLS`；`approval_mode` 的定义从「要不要问」改成「信任档位」。

前端一并收敛「失败」的观感：

- `frontend/src/features/workbench/components/ChatStream.tsx`：删掉内联审批卡
  （`InlineApproval`）与「运行已暂停」提示条；`renderTraceItem(item, retried)`
  把「同一工具后面成功过」的那次失败标成已重试。
- `frontend/src/features/workbench/state/selectors.ts`：新增
  `selectRetriedIds(items)`（原 `ExecutionTrace.supersededIds` 挪到选择器层，
  顺带把 `ExecutionTrace` 的 react-refresh 告警消掉）。
- `frontend/src/features/runs/components/ToolCard.tsx`：新增 `retried`——
  失败描边由 `danger` 改 `warn`，状态写「已重试」，**错误详情收进展开层**，
  外层只留一句人话。
- `frontend/src/features/workbench/components/ExecutionTrace.tsx`：`×N 步失败`
  不再计入被重试覆盖的项——用户关心「东西做出来没有」，不是我们试了几次。
- 删除 `InlineApproval.tsx` / `ApprovalCard.tsx` / `ApprovalHistory.tsx` 及其测试；
  `Composer` / `WorkbenchPage` / `approval-modes.ts` 的档位文案改为
  「谨慎 / 标准 / 放手」，提示改成「拿不准就先不做」。

顺手收掉「这层没了但界面还在」的地方——它们比看起来更坑，因为按了不生效：

- `frontend/src/shared/lib/mock-run.ts`：本地演示流（`?mock=1`）原来还发
  `approval.required` 并等一个决议，卡没了以后没人能给出，演示会停在生成前。
  改成直接 `doc.generate_report → artifact.ready → run.completed`，
  `run.completed.approvals` 固定空数组。
- `frontend/src/features/settings/SettingsPage.tsx`：撤掉「审批与安全」页签。
  里面的「审批超时」「需要人工审批的工具」两个开关已经没有任何代码读了，
  点它等于按一个坏按钮。讲密钥的那段「安全提示」并进「模型与运行」。
- `frontend/src/features/audit/AuditPage.tsx`：「审批记录」卡片永远空着，
  删掉；`AuditDrawer` 的说明改成「运行摘要、耗用明细与产物清单」。

**测试**：重写 `backend/tests/unit/test_approval_modes.py` 为「效果 × 档位 ×
理解层」矩阵（9 条）；`test_real_engine.py` 新增
`test_delete_without_his_words_is_skipped_not_failed`（拦下是 skipped，
不是 failed）与 `test_continuation_still_writes_without_a_new_permission`；
`tests/helpers.py` 的 `approved_flow` 改成一次跑到底；删除
`tests/api/test_approval_failure.py`，`test_pipeline` 的「全流程一次跑完」
只断言事件顺序、`approvals == []`。`mock-run.test.ts` 的「审批通过 / 审批拒绝 /
审批阶段被 abort」三条改成「一次跑到底 / 生成中途 abort」，并显式断言
**不再出现 `approval.required`**。后端 `1652 passed, 42 skipped`，
前端 59 文件 `1277 passed`。

### 修复（2026-11-07 第八十五轮：默认档不再为写盘弹卡、审计页删掉两栏自用说明）

**背景**：实机用下来有两个反馈。

1. **每次生成都要点一次「现在做」**。第八十四轮把卡改成了人话，但没改「什么时候
   该弹」——默认档 `risky` 的名单里还点着 `code.run_python`，于是「标题改成深蓝」
   这种说得很清楚的话，也要先点一次按钮。点久了只会变成闭眼点，比不弹更糟。
2. **审计页混进了两栏只给自己看的东西**：「口径对照」那段（运行内 189 次 / 账本
   29 次，差额来自探测、标题、增强、失败重试……）和「调用账本 · 按用途」那张卡
   （主循环 / 意图理解 / 连通性探测）。这是开发者对账用的，用户在这里只需要知道
   「花了多少钱、花在哪」。

**改动**

- `backend/app/agents/engine_protocol.py`：`needs_approval()` 的 `risky` 档改成
  **只问删了回不来的动作**（新增 `IRREVERSIBLE_TOOLS = {file.delete}`），且不受
  配置名单影响。写盘要不要做，门控已经按「他这一轮到底让没让你产出文件」逐次判过，
  放行就意味着这句话本身就是授权——再弹一次卡等于同一件事问两遍。
  `always_ask` 档照旧逐步问（想全程盯着的人用这一档），`all_allow` 不变。
- `backend/app/agents/real_engine.py`：`_needs_approval()` 补上这段理由；行为不改。
- `backend/app/tools/builtin/code.py`：更新模块说明与 `run_python` 注册处注释
  （「必须命中审批规则」已不准确）。
- `frontend/src/shared/config/approval-modes.ts`：默认档说明改成「只问删除这类
  回不来的操作」，`always_ask` 的提示去掉「联网」（没有联网工具）。
- `frontend/src/features/audit/AuditPage.tsx`：删掉「口径对照」说明段和
  「调用账本 · 按用途」卡片，连带移除 `PURPOSE_LABEL`、`ledgerPurposes`。
  金额口径没有被丢掉——它原本就在「消费金额」卡的 hint 里（按官方价重算的估算值）
  和折线图下的 `price_note` 里。

**测试**：审批链路自身的用例（`test_pipeline` / `test_semantics_runs` /
`test_approval_failure` / `test_b3p` / `test_smoke` / `tests/helpers.start_run`）
原来靠默认档弹卡，现在显式传 `approval_mode="always_ask"`——它们测的是卡片怎么发、
批了怎么继续、拒了怎么收尾，本来就该在自己的档位上测。
`test_approval_modes.py` 的 `risky` 一行改写为「只问不可逆动作」，
`test_approval_mode_api.py` 新增「默认档不弹卡 / always_ask 仍弹卡」两条。

### 修复（2026-11-07 第八十四轮：卡片说人话、只读脚本不再惊动人）

**背景**：实机跑「你看着调一下吧，别太花哨」，弹出来的卡是「需要你确认 / 执行 Python /
高风险 / 即将执行 code.run_python / Agent 预审：建议看过脚本再批」。他刚把决定权交
出来，卡片却像在质疑这句话，而且整张卡没有一句是人话。

**根因有三层**：

1. **卡面是第三人称的技术描述**：`action` 只有工具名 `code.run_python`，界面把它翻成
   「执行 Python」；「我理解的是」只写在授权卡上，常规审批卡根本没有，他连自己在批
   什么都看不见。
2. **只读脚本也要审批**：门控已经按「这一次会不会写」区分了读写，审批却仍按工具名
   一刀切，于是 `os.listdir` 看一眼目录也要他点一次「批准」。
3. **授权转移的句式漏在词表外**：「你看着调一下吧」被判 `authorized/0.62`，没过放行线
   （0.72），又没被认成祈使句——既不放行、也不弹卡，界面上只剩一句「没有跑脚本」。

**改动**

- `backend/app/agents/intent.py`：`_HANDOVER_RE` 补「你看着调/改/弄/来/做/处理/安排」、
  「你拿主意 / 你说了算 / 你安排 / 你做主」、「看着来吧」。
- `backend/app/agents/real_engine.py`：
  - 新增 `_approval_preview(ctx, spec, args, *, kind)`，两种卡（授权 / 审批）共用；
    `preview` 带 `action`（人话动词）、`kind`、`authorized`、`intent`，`impact` 改成
    「会改动工作目录里的文件，同名产物会被覆盖」。
  - `_needs_approval(spec, args)`：声明了 `mutates` 的工具按这一次判断，只读不弹审批。
  - 审批卡的 `message` 不再出现工具名：已授权时「按你说的跑脚本，点一下就开始」，
    否则「这一步要跑脚本，确认后我再动」。
- `frontend/src/features/runs/components/ApprovalCard.tsx`：抬头分三档（要我现在做吗 /
  按你说的做这一步 / 需要你确认），角标由「高风险」换成「会写入文件」，主标题用
  `preview.action`，已授权时不再显示「Agent 预审」（那时问题不是风险，是确认），
  按钮改「现在做 / 先不做」。
- `policy.should_ask_authorization()` 保持只看句子：试过把「unsure + authorized」也
  纳入，实测会把「我想整理成摘要」问成「要我现在做吗」，已撤回。

**验证**：实机一条链路跑通——「你看着调一下吧，别太花哨」→ 卡（按你说的做这一步 /
会写入文件 / 跑脚本 / 我理解的是：…只动顶部「W45 周报」这一行…）→ 点「现在做」→
产出《W45周报(标题15pt深红).pdf》，¥0.03。后端 1713 passed / 42 skipped，前端
1284 passed，ruff / tsc / prettier 全绿。

**同轮发现并修掉的漏判**：「标题改成深绿」那次没弹审批直接落盘。查日志发现
`mutates=True` 但 `needs=False`——脚本用的是 `PdfWriter.write(out)` / `doc.build()`，
这两个落盘入口都不叫 `save`，词表里没有，于是被判成只读，门控和审批一起放行。
`tools/builtin/code.py` 补了 `write`（排除 `sys.stdout/stderr`）、`build`，以及
`_WRITE_CTORS`（`PdfWriter` / `PdfDocTemplate` / `Workbook` / `Presentation` 这类
「构造即写」的类；`Document()` 无参算写、`Document(path)` 算读）。用库里 80 段
历史脚本重算：「产出了文件却判成只读」由 1 条降到 0 条。

### 修复（2026-11-07 第八十三轮：被门控拦下时，把选择权交回用户）

**现象**：他说「你把标题改成红色」，卡片显示「没有跑脚本：他还在商量，没有拍板」。
既没做事，也没给他一个能点的入口——他只能再说一遍。

**为什么以前这样**：门控只认「他拍板了没有」。理解层判 `proposed`，门控就静默跳过，
把一句说明回给模型。这在"我还在琢磨"时是对的，但在"他已经明确下令"时是说不过去的：
指令就写在句子里，缺的只是「现在做」这一个确认。

**改法**：不猜、也不吞，问一句。

- `policy.should_ask_authorization(reason, message)`：只在
  `not_committed / unsure / long_message` 且 `order_verdict(message)` 命中时返回真。
  这里不拿祈使句去**授权**（它认不出范围：哪份文件、哪一段），只决定**要不要问**。
  `hold` / `retracted` 永远不弹卡——他已经说了「先别」，再问就是没听懂人话。
- `RealEngine._ask_to_authorize()`：复用审批通道（落库 + `approval.required` + 心跳），
  卡上写「要我现在跑脚本吗？」，`preview.intent` 摊开它理解的意图，批准就抬成
  `authorized` **并跳过本次审批**（同一件事问两遍，他只会觉得系统没记住他的话）。
- 答完的三种结局都不算失败：拒绝 → `authorization_declined` 并按「已跳过」记一条、
  本轮关闸；超时 → `authorization_timeout`、运行继续；通道坏 → 按没同意处理，不终止。
- 被拦下的卡片摘要统一改成第二人称（`_gate_card_note()`）："这一步先没动：还没听到
  你说动手"。不再出现 `reason_label()` 的第三人称（"他还在商量"），也不再有任何
  「失败」字样——这一步根本没跑，谈不上成败。
- `approval_mode=all_allow` 下不弹卡：那是他明确说过「别停下来问我」。

新增 3 条护栏：明确祈使句 → 只弹一张卡且批准后真的执行；拒绝 → 不算失败、不弹第二遍；
拦下摘要不含「失败」。另外两条旧用例换成商量句（祈使句现在走另一条路）。

### 修复（2026-11-07 第八十二轮：只读脚本不再被授权门控拦下）

**现象**：模型想量一下 PDF 里的标题字号，卡片显示「没有跑脚本：他还在商量，没有拍板」。

**根因不是理解层**：那个脚本是 `import pdf_utils` + `read_report` + 打印签名，一个字节都
不写。是门控按**工具名**判风险——`code.run_python` 注册成 `risk=high`（它能生成文件），
于是「读」也被算成「写」。同一个工具既读又写，按名字一刀切就必然误伤，而读被拦的代价
是模型连量个尺寸都要先跟用户要授权口径。

**改法**：把「这一步会不会写文件」下沉到**单次调用**。

- `ToolSpec` 新增 `mutates: Callable[[args], bool]`，`mutates_files(args)` 判不出来时
  按「会写」处理；默认仍由 `risk` 推出来，其余工具的语义一格没变。
- `code.run_python` 提供 `_script_mutates()`：AST 扫脚本，`open(..., "w"/"a"/"x")`、
  `Path.write_*`、`save()`、`to_excel()`、`make_pdf()`、`shutil.copy`、`os.remove`、
  `exec` 这类改动才算写；读报告、查签名、打印统计算读。语法错误、模式是算出来的，
  一律按写办。
- 这个谓词只影响**授权**，不影响审批：`run_python` 仍是 `risk=high`，「能不能跑代码」
  和「他让你产出文件了没有」是两个问题。

顺手把两处别的地方也收了：

- 输入框占位改成「正在做，有补充就说…」「等你确认，也可以先写下一条…」——原来那句
  「发送后会排进队列，跑完自动接着执行」把内部机制念给用户听。
- 工具描述里写明：只读脚本随时可以跑，会产出文件的才需要他已经同意动手。

验证：25 条正反例（含 `pdfplumber.open(路径)`、`Path.open("w")`、`str.replace` 这类
同形不同义的）零误判；用库里 42 段真实脚本交叉验证，「产出文件却判成只读」为 0。

### 修复（2026-11-07 第八十一轮：说「你生成吧」就该动手、脚本文件名对不上、文字不再整段蹦出）

三件事都来自同一晚的实测截图。

**一、用户说了「你生成吧」，它回「你说『就这样』我就出」**

理解层把这句话判成 `proposed`（还在商量），于是 `delivery=draft`，提示词要求
"最后问一句"，门控也在写工具前拦了一道——界面上就是「执行 Python 没有跑脚本：
他还在商量，没有拍板」。用户的原话是「我需要你生成的时候你按我的意思来执行就行，
不要非得按他的要求来」。

而 `commit_verdict("你生成吧")` 本来就是 True。「生成吧 / 出吧 / 就按这个」这类
短语逐条排除了否定、假设、引述、句尾疑问，是一张白名单；**是模型的犹豫把它盖住了**。

修法是加一道与 `apply_hold` 对称的校正 `apply_commit()`：

- `apply_hold` 往下压（他说「先别」），`apply_commit` 往上抬（他说「做吧」）；
- 抬档要两个前提：**有上文**（短句里的「这个」得有指代对象）+ `commit_verdict` 命中；
- 顺序是先压后抬：「先别生成吧」白名单不成立，压完就停住；「先别管格式，直接生成吧」
  会被抬回来——和判据里"明确指令优先于叫停"的约定一致。

顺带改了两处话术：`_authorization_note` 明令模型**不要索要确认口令**；
`READING_RULES` 里补上「你生成吧」这类带语气词的短命令 = 拍板，并单列一节
「不要向用户要口令」（只有缺一样不做会做错的信息才问）。

**二、脚本 `FileNotFoundError`，连撞两次**

对出来的真实脚本：产物登记名是 `W45周报(标题红色)(2).pdf`（仓库去重加的 `(2)`），
而 `out/` 里始终是 `W45周报(标题红色).pdf`。模型拿登记名回 `out/` 里读，必然找不到；
第二次换了个名字再猜，又找不到。

- `outputs` 每条加上 `workspace_file`（工作目录里的原名），工具描述同步说明 `(2)` 的来历；
- `files` 现在也能点名**本次运行刚生成的产物**（按登记名或原名都认），复制进 `in/`；
- 路径类失败时把 `in/`、`out/` 的真实文件名一起回给模型，别让它一个名字一个名字地猜。

**三、正文整段蹦出来**

`_stream_text` 分片之间是 `await asyncio.sleep(0)`——所有片子在同一帧发完，浏览器
合成一整块。改成 24ms/片（约 500 字/秒），并按 1.8 秒的总预算自动加速，长文不会
因为片数多而拖成"卡住"。

**四、顺手收紧两处观感**

- 被门控拦下 / 等不到审批的工具卡不再画成红色失败（`skipped` 单独一档，显示「已跳过」），
  `思考过程` 的「×N 步失败」也不再把"有意跳过"算进去——那不是故障，是我们替他把了道门。
- 输入框占位文案：「任务运行中：发送后会排进队列…」→「正在做；你接着说，这条做完就接上…」。

### 修复（2026-11-07 第八十轮：收尾不再用一句话糊住所有原因）

第七十九轮修的是「问句被吞」，这一轮修的是它的邻居：**这一轮确实没话说时，回的那句话
和真实原因对不上**。原兜底只看三件事——有产物、说过话、是不是聊天：

```python
if not self._emitted_text:
    if tool_ctx.artifact_ids: ...          # 报文件名
    elif last_text: final_text = last_text # ← 中途旁白被当成结论
    elif delivery == DELIVERY_CHAT: "这次没接上话，你再说一遍？"
    else: "这轮没能给出答复，麻烦重试一次。"
```

两个后果都在线上成立：

- **半句话冒充结论**。模型说「我先读一下这两份材料」然后被上限截断，`last_text`
  就是这句旁白，于是它成了这一轮唯一的回答。用户看到一句正常的话，以为事儿做完了。
- **该说明白的说成「故障」**。写操作被门控拦下（他还没拍板）、审批卡片根本没发出去，
  这两种都不是故障，重试一百次结果一样，但兜底让他「麻烦重试一次」。

改法是把判断从「有没有说过话」换成「为什么停」：`_closing_text()` 保留 `last_text`
（它说过的话照给），后面用 `_closing_note()` 追加一句原因；原因按**越具体越靠前**排：

| 情形 | 那句话讲什么 |
| --- | --- |
| 审批卡片没发出去 | 这一步要你先确认，但卡片没发出来 → 原话再发一次就行 |
| 门控没放行 | 按 `gate.reason` 分四句：先别动 / 已撤回 / 消息太长 / 还没到落盘那步 |
| 连续空转（`no_progress`） | 我在同一个动作上绕了几圈 → 请他说清哪份文件、哪一段 |
| 到上限 / 触顶（`max_steps`、`token_budget`） | 还没收尾，剩下的没做完 → 说一声「继续」 |

仍然一条铁律：**这些句子里不出现步数、上限、预算、token**（`test_max_steps_stop_reason`
与 `test_user_visible_budget_wording_stays_out_of_the_engine` 继续钉着）。

配套加了两个状态位：`_approval_unavailable`（累计，**不复位**——`_approval_failed`
会被下一次工具调用清掉，坏过一次就永远说不出来了）与 `_last_gate_reason`
（`_write_blocks` 只记次数，记不下原因）。

新增三条护栏：`test_step_stop_keeps_what_it_said_and_admits_it_is_unfinished`、
`test_blocked_write_says_why_it_did_not_land`、
`test_approval_unavailable_note_blames_the_card_not_the_user`。

**这一轮明确不改的两处**：`_emitted_text` 仍是布尔量（改判据会牵动所有收尾分支，
收益不抵风险）；thinking 决策行一条不删——每条都是模型真实的取舍，删掉等于替它编过程。

### 修复（2026-11-07 第七十九轮：追问被吞、调用账本落地、默认回 real）

**一、理解层问了一句，引擎一个字都没说**

线上现象：用户连发「改成红色」「你咋不做修改」「你咋不做修改」，三条都等不到回应，
直到「你好」才收到一条。看起来像卡死，实际每次调用都成功、都扣了钱。

从数据库里对出来的：那三条 run 都是 `completed`、有 2200 左右的 input tokens，
但 `run_events` 里**只有 `run.started` 和 `run.completed`，中间一条 `message.delta`
都没有**，`stop_reason=awaiting_user`。

根因在 `RealEngine.run()` 的早退分支：

```python
if reading.needs_confirm:
    yield EngineEvent(RUN_COMPLETED, ... stop_reason="awaiting_user")
    return          # ← reading.question 从没被发出去
```

理解层已经想好了「缺什么、该问什么」（`reading.question` 就有那句问话），
引擎也判了「先问一句、这一轮不动手」，最后**唯独没把这句话说出来**。
注释写的是「先问一句」，代码做到的是「沉默地问」——那等于没问。

修法是把这个分支接回正常的回复通道：`_stream_text(..., channel="reply")`，
问句进对话流、进 messages 表。另外补一句兜底：万一 `question` 为空，
用一句通用追问，**绝不允许什么都不说就结束**。

> 顺带解释一个反直觉的数据：失败的 run `input_tokens≈2200`、成功的 `≈6300`。
> 差的不是模型，是**有没有进主循环**——2200 是理解层那份短提示，6300 才带完整
> system prompt + 工具表。

新增两条护栏：`test_confirm_question_reaches_the_user`（问句必须出现在
`message.delta` 里，且不进主循环）、`test_every_normal_run_says_something`
（参数化：追问 / 闲聊两种路径，收尾时都必须有一条 `channel=reply` 的 `message.completed`）。

**二、`model_calls` 表：把 run 外的钱也记上**

上一轮把审计页的「请求次数」改成了运行内已记账的 153 次，解决了「拿运行数冒充请求数」。
但这仍然回答不了「为什么控制台是 1909 次」：

- 连通性探测、会话标题、提示词增强、技能起草 —— **不属于任何一次 run**；
- 限流重试、`max_tokens` 截断后的放大重试 —— 失败的请求也计费，但没有 usage 可记。

新增 `model_calls`（迁移 `0004`），逐条记录每次真正发出去的请求：

| 字段 | 为什么需要 |
|---|---|
| `run_id`（可空） | 空值本身就是事实：账本里有一半请求不属于任何运行 |
| `purpose` | engine / reading / probe / title / enhance / skill —— 回答「钱花在哪」 |
| `status` | `failed` 也计入次数（对面收了），金额记 0（没 usage，硬估只会更乱） |
| `request_id` | 拿去和供应商控制台逐条对 |
| `attempt` | 同一次逻辑调用的第几次请求（预算放大重试会发两次） |

记账点放在 **`ModelProvider.chat` 的每次 HTTP 回执**，不是 `ModelRouter`：截断重试
发生在 provider 内部，按上层记账会稳定地少算一半。用途通过 ContextVar 传递
（`core/call_journal.py`），所以 provider 不需要知道「这是主循环还是标题生成」；
`run_id/thread_id` 由 `RunService._produce` 在 task 入口绑定，并发会话不串账。

金额**写入时不算**：汇总时按现价重算（与 `UsageService` 同一口径），否则价格表改一次，
历史账就自相矛盾。失败行金额恒为 0。

`UsageOut` 新增 `ledger` 字段（`UsageLedgerOut`），与 runs 口径**并列**而不是替换：
「这次运行花了多少」和「这个 Key 一共发了多少请求」是两个问题，混成一个数只会继续
对不上。`ledger.since` 给最早一条记录的时间——**历史请求补不回来**，界面必须说清
账本从哪一刻开始完整。

审计页加「调用账本 · 按用途」卡片（横向占比条 + 失败次数 + tokens + 金额），
并把「口径差在哪」那段静态说明改成数据驱动：直接写出「运行内 N 次 / 账本 M 次 /
差额来自哪里 / 账本自何时起完整」。

**三、默认引擎改回 real**

`.env` 与 DB settings 两层同时改（DB 优先级更高，只改一边不生效）：
`ENGINE=mock → real`、`MOCK_MODE=true → false`。验证：`mode=real`、
`engine_effective=real`、`degraded=false`，真实请求能正常出结果。

**度量**：后端 `test_call_ledger.py` 新增 8 条、`test_real_engine.py` 57 → 62；
前端审计 11 条、tsc 干净；契约快照与 `schema.d.ts` 已重新生成。
真实链路验证：同一会话里 `probe`（无 run_id）/`reading`/`engine` 三种用途各记一条，
`/usage/summary` 返回的 `ledger.by_purpose` 与之一一对应。

### 变更（2026-11-07 第七十八轮：步数不再甩给用户、审计口径说清、开发默认回 mock）

**一、到步数上限时给用户发一句「你接着说」，是把自家预算变成用户的活**

`real_engine.py` 原来有两处往聊天流里注入预算台词：主循环触及 token 预算时
「本次运行已消耗 N tokens，超过预算…」，循环跑完档位步数时「这一轮到步数上限了…
还要接着改的地方你说一句，我继续」/「这轮步数用完了还没收尾」。用户要的是事情做完，
不是替我们数步数，更不是让他来推下一步。

改法不是换个委婉说法，是把停止线挪走：

- 两处注入全删；`stop_reason` 与结构化日志保留（`run_step_cap` / `run_token_budget`
  / `run_no_progress`，带 `skip=no_user_note`），排障照旧可查。
- 主循环改成跑全局上限 `_max_steps()`：默认 8 → **24**，硬顶 12 → **60**。
  `_max_steps_for()` 的分档步数降级为「起步预算」，跨过它只记一条
  `run_auto_continue` 日志，**自动续跑不打断**，直到模型给出不带工具的最终答复。
- 放开车之后必须有刹车：连续 4 步「同样的工具调用 + 同样的旁白」判空转，提前收尾
  （`no_progress`）。判据是**有没有新信息**，不是步数。
- 真一声不吭时，兜底文案从「你说下一步怎么走，我接着来」改成「这轮没能给出答复，
  麻烦重试一次」。
- `.env` 的 `MODEL_MAX_STEPS` 同步 8 → 24（它优先级高于代码默认值）。

> 与第七十六轮的取舍：那轮按用户要求做了「READ 档放宽、WRITE 档维持上限」。这轮
> 用户明确「压根不能有步数」，档位差异不再作为停止线，只留作日志与封顶计算。
> 真实模式放开步数会增加 token，所以默认给 24 而不是硬顶 60；切 mock 后不产生费用。

**二、审计页「API 请求次数」填的是运行数，跟官方账单差一个数量级**

实测数据库：70 次运行（56 真实 / 14 mock），运行内记账的真实请求 **153 次**、
1,104,835 tokens、按现价重算 ¥0.43；DeepSeek 控制台当日 1,909 次请求、
4,039,120 tokens、¥2.72。三个数三个口径，直接对比没有意义：

- 审计按 **run 聚合**，只含运行内**成功**的调用；官方按 **API Key 发出的每一次请求**
  计，还包括连通性探测（`probe_chain` 的 ping）、会话标题、提示词增强、技能起草这些
  run 外调用，以及超时重试。
- 原来卡片写「API 请求次数」却填 `usage.runs`，是标签与数据不符；「按模型」里的
  「请求 N 次」同样是运行数。
- 时间范围也不同：审计是「近 30 天」，控制台那张图是「当日」。

改动：`UsageOut` 新增 `calls`（运行内已记账请求数），`UsageService` 从
`run.extra.usage.calls` 汇总；前端卡片改成「已记账请求」并显示 `calls`，hint 给出
运行数与 mock 数；「按模型」改成「运行 N 次」；金额卡标注「非账单金额」；指标卡下
加一条口径说明。`pricing_note()` 固定报**闲时基准价**并说明高峰翻倍（以前按「当前
时段」报单价，用来描述历史区间是错的）。契约快照与前端生成类型同步重新导出。

> **没做的**：全量调用账本（把探测 / run 外调用 / 失败重试也持久化成一张表）。那才能
> 让未来的数字真正贴近账单，但要加表 + 迁移，而且**历史请求补不回来**——已发生的
> ¥0.43 vs ¥2.72 不会因为改代码变一致。

**三、开发阶段默认回 mock**

`config.py` 的默认 `mock_mode=True` 一直被 `.env` 和 **DB settings 表**双重覆盖成 real
（`engine=real` / `mock_mode=false`），所以每次启动都在真实调 DeepSeek。两层都改回 mock：
`.env` 的 `ENGINE=mock` / `MOCK_MODE=true`，以及 DB 里同名的两行。设置页仍可随时临时
切回真实模型（热生效，不用重启）。

**度量**：后端全量 **1687 passed, 42 skipped**（`test_real_engine.py` 57 → 59：
新增 2 条 + 扩展 1 条；`test_pricing.py` 8 → 9）、前端 **1284 passed**；
ruff check/format、契约快照 `--check`、前端 tsc 全绿。顺带修了 `test_core.py` 里
读本机 `.env` 断言「默认档」的脆弱用例——改配置不该让归一化测试变红。

### 变更（2026-11-07 第七十七轮：意图层补「直接下令」维度——记目标，不开门）

**问题**：用户问「是不是该把词表的文字密度提高，让命中率更高」。先用
`tests/data/utterances.jsonl` 量了一遍：45 条 `authorized` 里 `commit_verdict`
只认出 7 条（16%），误判 0。把 38 条漏判逐条铺开，**没有一条是"少了一个词"**：
它们主要是直接下令（「把标题居中」「删掉第二段」「把这三份合并成一个文件」），
而 `_STRONG_COMMIT` 收的全是**决策陈述**（就按这个 / 直接生成 / 落盘）。
这是少了一整个维度，不是密度不够——往词表里加 5 个最常见的词只能打捞 7/38，
且那 5 个词是照着这批语料挑的，换一批就废。

**加的是句式，不是词**：`_IMPERATIVE_RE` 收两种有限句式——处置式
（`把 X 怎么样`）与动宾式（`改成 / 删掉 / 读一下 / 合并成 …`）。实测在 38 条
漏判上覆盖 17 条，加词那条路是 7 条。

**但补法不是把 `commit_verdict` 加宽**。「把这份材料整理成周报」被判 False
是 `test_commit_verdict_table` 里有意写下的立场：它只是"描述要做的事"，
没说"就做"。真正的答案是**第二个问题**：新增 `order_verdict()` 问
「他有没有让我做」，与 `commit_verdict` 的「他决定了没有」并列。

**用途只有一处，而且不给权限**：`fallback_reading`（理解模型不可用时）把
`order_verdict` 的命中写进 `goal`，`commitment` 仍然封着。理由是既有的
`test_fallback_never_guesses` 早就写清了——祈使句缺的不是语气，是**范围**
（哪份文件、哪一段），判断范围是否唯一是理解层的活，兜底没人替他确认，
放行就是对着猜出来的文件动手。我第一版直接把 fallback 判成 authorized，
正是被这条用例挡下来的。

**顺带修好三处**（都是加规则时自己踩出来的）：

1. 语料里「这几份材料我想整理成摘要，你觉得先动哪份」被 `整理成` 命中判成下令
   ——现在是真误判。加一道：整句在征询（`advice_verdict`）时不算下令，
   征询会笼罩整个句子，不看动作词落在哪。
2. 「把标题居中**吧**，如果领导同意的话」的条件从句没拦住：短语本身不含语气词，
   `_clauses_after` 把「吧」当成了下一个分句，真正的条件句退到第二格看不见。
   现在把紧跟的语气词一起吃掉再查。
3. 「你看着办吧」被判成**征询**——`_ADVICE_RE` 里收了「你看着办」。那是把决定权
   交出来，属于授权；征询会压掉拍板信号，一句授权被拖成一轮反问。摘掉，
   改由 `_HANDOVER_RE` 认（「你看着办 / 随便哪个都行 / 听你的」）。
   另 `_POST_DEFER_RE` 补「先放放 / 搁一搁 / 往后放」，「把标题居中这事儿先放放」
   不再算下令。

**度量**（`tests/data/utterances.jsonl`，114 条）：

| | 召回 | 误判 |
|---|---|---|
| `commit_verdict`（写盘判据，未改） | 7/45 = 16% | 0 |
| `order_verdict`（记目标用） | 24/45 = 53% | 0 |

兜底场景在 45 条真授权上「记住目标」从 7 条升到 24 条，**实际放行写盘仍是 7 条**，
非授权被放行仍是 0 条。另跑 22 条对抗样本（条件、疑问、引述、否定、叫停、
意愿表达）全对。

**度量**：后端 1677 → **1684 passed**（新增 `test_intent.py` 5 条、
`test_reading.py` 1 条）；ruff check + format 干净。

> 说明：这轮提升的是**兜底场景下的诉求命中**（理解模型挂了时，模型知道
> 用户要什么，而不是反问一句）。日常链路由理解层读上下文，不经过这两个函数
> ——那条路上的命中率在 `reading.py` 的提示词与判据，不在词表里。

### 修复（2026-11-07 第七十六轮：兜底叠两把钥匙、提示词收成两段式、步数按只读/写分开）

**现象**：线上仍能见到四类错误行为——文件乱生成、卡死、提示词冲突、逻辑逃逸。
逐个定位到三处结构问题。

**一、兜底只看一句话就补文件**

`_reliability_fallback()` 原来只判「话里有没有动手指令或模型有没有承诺」。
一句话够不上「他确实要交付」：`就按这个格式改标题` 含 `就按这个`；
`先别生成吧` 的一小部分也已经靠位置检查挡掉，但挡不干净。反过来，
把 `authorized` 当唯一凭据也不成立——「跑个脚本统计字数」同样判成 authorized，
于是补出一份周报。

改成**两把钥匙同时转到底**：`marker`（命中的动手指令/承诺）**且**
`reading.commitment == authorized`。`proposed` 直接跳过——他还在商量，
兜底补动作等于替他拍板；`none` 同理。`hold`（先别/我只是问问）与
`model_refused`（模型说做不了）仍在前面拦一道。

同时把日志补成可复盘的：每次都带 `marker`（命中的短语**原文**）与
`skip`（`no_marker` / `hold` / `proposed` / `no_commit` / `model_refused`），
事件名按 skip 分列；`core/logging.py` 的 `_EXTRA_KEYS` 增加 `marker` / `skip`，
JSON 日志里可以直接筛 `marker=直接生成`，不用全文检索 message。
为此 `intent.standing_phrase()` 把「命中的短语」作为一等返回值
（从 evidence 里反抠引号很脆——短语本身就可能带引号）。

**二、提示词拼接：稳定段与易变段混在一起**

`_initial_messages()` 一次到底地拼十几段，每轮变化的（素材依据、路由规范、
历史要点、授权状态）散落在中间。后果有两个，正好对应线上看到的两种症状：
缓存前缀每轮作废；以及**规则互相冲突**——中间插一句「本轮有素材」之后，
后面又接「用户要文件就落盘」，模型看到的是两句打架的话，只能挑一句执行，
表现就是行为忽左忽右。

拆成两个函数，边界即规则：

- `_stable_system(ctx, delivery)`：人设 + 本档规则，只放「按档位固定」的内容。
- `_turn_tail(ctx, delivery, reading)`：**system 的最后一节**，只放每轮会变的
  内容，顺序固定（依据 → 路由规范 → 历史要点 → 授权状态）。
  函数上写了强约束：只许往里追加，禁止挪回稳定段，也禁止在它之后再拼东西。

配套两处：

- `reading.restate` 注入前过 `_clip_restate()`（`RESTATE_PROMPT_LIMIT = 120`，
  超长补「…」）。它是第二道闸——`reading.GOAL_MAX_CHARS` 只在解析时裁，
  而 `TurnReading` 也能由测试、旧调用方、确定性兜底直接构造。
- 商量档对 `TOOL_RULES` 做**局部覆盖**：`DRAFT_TOOL_OVERRIDE` 紧跟在
  `TOOL_RULES` 之后，明写「本回合禁止调用任何写文件工具，即使需求提到产出文件，
  仅输出方案文本」。只切档不改工具约定是不够的——那一大段里「用户要文件就调
  doc_generate_report」还在生效，模型读到「周报」两个字就照那条办。

**三、步数不区分只读与写**

`read` 与 `draft` 原来共用 `min(3 + 份数//2, 6, max_steps)`：只读档被压到 6 步，
比交付档（8 步）还紧。方向反了——只读不落盘、不动用户文件，多跑几步只花几毛
钱 token；而它跑不完的代价是模型拿前两份的内容把第三份「补」出来，
「没读到」写成「没有」，从成稿里根本看不出来。

现在：`read` = `2 + 2×份数`（封顶 `model_max_steps`）、`draft` = `3 + 份数`
（同封顶）、`deliver` 维持全局上限。只读档的上限不再低于写档。

**度量**：后端 1669 → **1678 passed**。新增用例 9 条：proposed 不补 / none
不补 / 两把钥匙齐了才补 / 日志带 marker 原文 / 稳定段边界 / system 逐字可复现 /
复述截断 / 只读档不紧于写档 / 商量档覆盖生效；另有 `standing_phrase` 直测 1 条。
ruff check + format 干净。

**主动变保守的一处**：`proposed` 档现在完全不做兜底。以前「他已经说了方向、
模型也确实漏交付」这种情况会补一份；现在改成把方案说出来等他点头。
理由是这一档补错的概率高于漏补——漏补他再说一句就行，补错要删文件、还要解释。

### 修复（2026-11-07 第七十五轮：审批通道故障不许终止运行 + 门控/意图层六处补漏）

**现象一（实测）**：跑真机时审批端口自己抛异常，整轮运行直接没了——用户看到一句
「服务内部错误」，前面读过的素材、写好的草稿全丢。原因是 `_approval_flow` 里
`approval_gate.create()` 与 `pending.result()` 都没有保护：异常从 `run()` 的异步
生成器里冒出去，被 `run_service` 兜成 `INTERNAL`。审批是个**外部依赖**（落库 +
内存事件 + 前端卡片），任何一环坏都不该有权力终止一轮工作。

**做法**：审批故障一律降级成「没得到同意」，而不是「运行失败」。

- `create()` 失败 / 端口未接入 / 返回对象没有 id → `tool.finished(ok=False,
  error.code=APPROVAL_UNAVAILABLE)`，工具不执行，运行继续，模型收到一句
  「审批通道暂时不可用，这一步没有执行，不要换工具重试」。
- `wait()` 失败 → 同上。`_wait_for_approval` 的返回值从 `(decision, heartbeat)`
  扩成 `(decision, heartbeat, failed)`：超时（产品行为，仍 `run.failed`）与故障
  （意外，不终止）从此分开。取消后的任务现在会 `await` 一次，不再留下
  "Task exception was never retrieved" 冒充事故。
- `ApprovalService.wait()` 同样不许抛：`repo.get()` 炸了按「没有决议」返回；
  `timed_out` 标记写在 `except TimeoutError` 里，**它自己失败会盖掉真正的超时结局**
  ——现在吞掉只记日志（标记是给审计看的，不是流程用的）。顺手删了只写不读、
  还会无限增长的 `_timed_out` 集合。
- `mock_engine` 是同一条等待链，一并加固（演示模式最容易撞上它）。

**现象二**：门控只看理解层给的 `commitment`。模型读错一次，它答「已授权」就照写。
可有些话是**白纸黑字**的：「先别生成吧，我就是想问问」「我点头了再落盘」「算了」。

**做法**：`decide_write()` 加三道只做减法的否决——`hold` / `retracted` /
`long_message`，全是「否决」不带「授予」。放行一次的代价是一份没人要的文件，
多问一句的代价是半句话。另外三处硬化：

- 认不出的 `spec_risk`（`High`、空串、`medium`）一律按 high 办。以前 `!= "high"`
  就放行，一个拼写错误就能把门拆了。
- 消息超过 1200 字（三倍分析窗口）时，授权的把握门槛从 0.72 抬到 0.85。
  400 字只是开头被切掉一点，理解层读的是全文；到三倍窗口就是「整篇材料 + 一句话」，
  「这份材料想整理成周报」很容易被读成「他要我整理」。
- 拦到上限（`MAX_BLOCKS_PER_RUN`）后本轮写工具整体关掉（`_write_disabled`）：
  模型不会因为一句"别再试"就停手，它会换个工具名再来。拦下时还会发一张
  `tool.finished(ok=False)` 卡——以前只回模型一句话、不发事件，界面上什么都没发生，
  用户看着"它说要生成"然后凭空开始讲方案，既不知道被拦了也不知道为什么。
  卡上的话用 `policy.reason_label()` 翻成给用户看的说法（模型拿到的 `hint` 是
  "下一步怎么做"，受众不同，不能互相顶替）。

**现象三**：意图层四个句法漏洞，方向都是**把"不要"读成"要"**。

1. **截断就认拍板**。分析窗口被截断时以前只扣 0.05 把握度（0.9→0.85，照样越过门控
   的 0.72）。可窗口里看到的「生成吧」可能落在一个「如果……就……」里，而「如果」
   正好在被丢掉的开头——引述、否定同理。现在 `truncated=True` 直接不认拍板
   （`phrase_stands` 同理），代价是"长材料 + 拍板"交给理解层读全文判断，它本来
   也更该做这个判断。
2. **受益标记全文搜索**。「这个方案你觉得行吗？顺便帮我改下标题」被判成请求——
   隔着一个分句的「帮我」把真征询否掉了。改成 `_near_clause()` 就近匹配：同一分句、
   12 字以内。同时区分**请求**与**征询**：「给我个建议」「帮我拿个主意」要求的是
   判断本身，仍是征询。
3. **拍板之后的软反悔看不见**。「生成吧，先不弄了」「改成横向吧，回头再说」里
   拍板短语完整、位置正确，只有后面那个分句说了实话。`_blocker` 现在往后看
   一到两个分句，查延迟（先等等 / 回头再说 / 等我确认）与否定（先不弄了 /
   不做了 / 别改了）。「不用问了」「别再问了」刻意不收——那是把拦路的东西拿开。
4. **弱匹配分不清主句与前件**。「改成横向吧，如果领导同意的话」动作、语气词、
   位置全对，意思是"等同意再改"。弱匹配（正则拼的）现在额外查所在分句与紧邻
   下一分句有没有条件标记（如果/要是/只要/的话）；表内短语是人挑过的，配上条件
   读起来就是假设，前缀检查已经够用。

**度量**：后端 1639 → **1669 passed**（新增 `test_approval_service.py` 5 条、
`tests/api/test_approval_failure.py` 2 条端到端：从 SSE 上看确实没有 `run.failed(INTERNAL)`；
引擎侧 4 条：create 失败 / wait 失败 / 端口未接入 / 撞门关闸；门控 8 条：hold 否决、
撤回否决、拍板优先、低风险不连坐、长消息抬门槛、短消息不动、未知风险按 high、
reason_label；意图层 4 组：截断不认拍板、就近受益、软反悔、条件从句）。
`tests/data/utterances.jsonl` 上 114 条真实说法跑 `commit_verdict`：**误判拍板 0 条**
（危险项为 0），45 条 authorized 里确定性层认出 7 条（它只做信号，不做法官）。
ruff check / format 干净。

**已知代价**：长消息（>400 字）不再由确定性层放行——这是「截断不认拍板」的直接
后果，也是这一轮唯一一处**主动选择变保守**的地方。

### 新增（2026-11-07 第七十四轮：素材检索，把「没读到」从猜变成查）

**现象**：以前素材只有一种用法——整块塞进上下文，超过 24000 字从头截掉。一份三万字的
报告，模型只看到前三分之一，它的反应不是「我没读完」，而是把剩下的用通顺的话补上。
这类幻觉最难发现：语气和真读到一模一样，用户手上没有原文，无从核对。更糟的是
`material_notice` 写着「如需完整内容可再次调用 file_read 并指定 files 分文件读取」——
单份文件本身就超限时，再读一次还是同一个开头，这句提示等于没给出口。

**做法**：新增 `app/domain/rag.py`（纯标准库，零第三方依赖）配一个 `file.search` 工具，
把「取内容」从一次性变成按需。

- **切块**：标题与空行感知。换小节必断块（一块横跨两节，命中后注入的上下文自相矛盾）；
  短尾只在本节内合并（「库存」里混进「下一步」比不合并更糟）；多级编号整段剥掉
  （「2.1 库存」→「库存」，不是「1 库存」）。编号 S1…Sn 全局连续——它同时是引用 `[S3]`
  和补读坐标 `block_ids=["S3"]`，断号会让模型照着写一个翻不到的编号。
- **检索**：BM25 + 中文 bigram，不分词——分词要词典、要维护、要处理新词，而 bigram 对
  检索更宽容（「退款手续费」与「退款」共享「退款」，只是 idf 低一点）。不引向量库有两个
  原因：离线环境装不了 faiss/numpy/sentence-transformers（pptx 那轮已经踩过）；业务问句
  是关键词密集型的，「退款率」和「退货比例」语义近却常常该分开——**召回得准**才是降幻觉
  最要紧的一步，而不是召回得多。
- **两维分档**：coverage（这一块把查询讲全了没有）+ support（查询里的词有多少是素材认识的）。
  只看 coverage 会被「命中一个词就满分」骗过去：问「营收和员工餐补」，营收那一块 coverage
  是 1.0，可餐补素材里根本没有，模型拿到 strong 就敢顺着往下编。support 只把 strong 降成
  weak，不降到 none——概述类提问（「帮我看看这个项目整体怎么样」）天生词少又泛，判 none
  等于告诉模型「素材里没有」，可素材里全都有。
- **match=none 不注入片段**：检索不到就空手回去，另外附一份素材小节清单让它换词再试。
  给几段「沾边」的文字，比什么都不给更容易被当成依据。

**工具与提示词**：

- `file.search`（low）：`query` / `files` / `top_k`，返回 `match` 档位 + 带编号的片段。
  索引按素材清单缓存在 `ToolContext`，一轮里查十几次不重建；缓存只在「覆盖了这次要搜的
  文件」时才用——上一轮只读过 A，直接拿它当全量会把 B 漏掉，还查不出是漏了。
- `file.read` 超长时改为「分节目录 + 前 N 块 + 还剩几块」，并给两条出路（`file_search`
  检索 / `block_ids` 补读）。`ctx.material_text` 仍是全文——产物要靠它抽句子，注入给模型
  的才是裁剪版，两者以前是一份，所以只能二选一。
- `RAG_RULES`（仅在有素材时注入）：逐句标 `[S3]`；只写片段里出现过的数字与专名；`match=none`
  要明说没提；追问先补全指代再检索（「那华南呢」直接搜三个字必然命中不了，模型会当成
  素材没写）。
- 片段走独立注入通道（8000 字），不走 4000 字的通用回执截断：片段是已经选过的高相关内容，
  按通用上限截掉后面几条，等于让模型只看第一条依据就下结论。

**落地校验**（只报告，不阻断）：

- `doc.generate_report` 成文后回查正文数字能否在素材里找到，写进 `extra["unverified_numbers"]`
  与工具回执摘要，模型在收尾时能看到。
- 引擎收尾对答复跑同一次回查，命中就记 `grounding_unverified` 日志（不改答复）。
- 只管数字，因为数字是唯一能机器判定的那类幻觉：「略有下降」被写成「显著下降」判不了，
  但「提升 12%」的 12 有没有出处是确定的事实。只报告不阻断，是因为 `1.2 万` 与 `12000`
  这类等价表述会被误报，硬拦会把正常交付打回。

**度量**：后端 1611 → **1639 passed**（新增 `tests/unit/test_rag.py` 28 条：切块边界 /
编号连续 / 短块合并范围 / 检索命中 / 两维分档 / 数字回查的等价写法与序号排除 / 工具层 /
索引缓存覆盖不全）。其中 12 条是**真实材料的档位回归集**——短句里词挨得紧、bigram 噪声少，
测不出真实文档上的分档漂移；这套集子在 3000 字材料上锁住了 8 个 strong、3 个 weak、2 个 none
的判定。ruff check / format 干净；前端 `tsc -b` 干净、`format.test.ts` 21 passed。

**没做的**：向量检索。真需要语义召回时换 `Index.search` 的实现即可，上层接口不变；
但按现在这批业务问句的实测，换它不会更准——只会多一个离线装不上的依赖。

### 调整（2026-11-07 第七十三轮：格式矩阵收成一张表，pptx 补齐全链路）

**现象**：「支持哪些格式」这件事在代码里有五份清单——`doc.py` 的 `OUTPUT_FORMATS`、
工具描述里手写的「还支持 md」、`security.py` 的上传白名单、`code.py` 的 `UTIL_MODULES`、
提示词里手抄的工具库清单。五份各说一套，最直接的后果不是难看，是**模型照着描述承诺，
实现里那行永远走不到**：`if output_format not in OUTPUT_FORMATS` 会先把 md 静默降级成 docx；
`parsing.py` 里写好了 `_parse_csv`，白名单却拒收 csv。

**做法**：新增 `app/domain/formats.py`，一张 `FORMATS` 表。每行同时回答五个问题——
能不能上传、能不能产出、沙箱用哪个库、那个库先用哪些函数、登记成什么产物类型。
其余模块只允许从这张表派生：`OUTPUT_FORMATS` / `UPLOAD_EXTS` / `UTIL_MODULES` /
`ALLOWED_MIME` / `OOXML_ROOTS` / 接口文档里的枚举提示串，全是算出来的，不再手抄。

放在 `domain` 层不是随手一放：`core/security.py` 要用它校验白名单，而
`services/__init__.py` 反过来 import `core.security`——这张表只要落在 `services` 包里
就是一个循环导入（第一版确实这么炸的）。它本身也只描述「一种格式是什么」，不碰 IO。

**pptx 补齐五处**：`services/pptx_utils.py` 手写 OOXML（离线装不了 python-pptx，
生成端只做「标题 + 要点」这一种最稳的版式）；`doc.generate_report` 的产物分支
（一节超过 6 条要点拆续页，宁可多一页）；上传白名单与 magic 校验（靠 `ppt/` 目录
区分改后缀）；`parsing._parse_pptx` 按页读文字、读不到就说读不到；`doc.analyze_material`
的体检分支；前端菜单、图标（新 `IconSlides`）、accept。pptx 产物同时落一份文本预览，
因为应用内预览不了幻灯片。

**三个必须成对的细节**（这轮的主要工作量）：

- **产物格式 ↔ 上传白名单 ↔ 沙箱工具库**：同一张表派生。`ALLOWED_MIME` 由每行的
  `content_type` 加浏览器别名算出；OOXML 校验按 `ooxml_root` 查目录，改后缀骗白名单
  会在这一步被拦；`code.run_python` 复制哪几个 `*_utils.py` 也由表决定。
- **工具描述 ↔ 提示词 ↔ 前端菜单**：工具描述用 `util_index()` 生成，提示词用
  `util_bullets()` 生成，展示名用 `FORMAT_LABELS`（`Word 文档（docx）`，与前端
  `OUTPUT_FORMAT_COMPACT` 逐字对应）。前端 `UPLOAD_ACCEPT` 只剩一份，此前 Composer
  与 WorkbenchPage 各写了一遍 `.docx,.txt,.pdf,.xlsx`。新增一种格式要做的事变成
  「表里加一行 → 前端两个数组各加一项 → 补图标」，漏一步类型检查会当场报出来。
- **权限门控 ↔ 子智能体**：`doc_agent` 在内部**直接调 handler**，不经过
  `_run_single_tool` 那道门，等于绕过 `policy.decide_write`（当前它没被主链路调用，
  所以不是活漏洞，但接线那天就是）。把这一轮的 `reading` 放进 `ToolContext`，
  子智能体在动手前自己过同一个 `decide_write`；没有 reading 时按不放行处理。

**顺带修的两处语义**：md 从「只读」改成「能传不能产」——项目目录里的 README.md
是真实素材，`DOC_EXTS = UPLOAD_EXTS` 把它收进来之后，再在白名单拒收就自相矛盾；
csv 同样「能传不能产」（把报告输出成 csv 没有意义）。另外 `mock-run.ts` 漏了
`ThinkingKind` 的导入，`tsc -b` 一直是红的，补上；`scripts/record-demo.mjs` 的
`return` 写在 `finally` 里会吞掉异常，改成 if/else。

**度量**：后端 1596 → **1611 passed**（新增 `tests/unit/test_formats.py` 15 条：
表自洽 / 派生清单 / 工具库函数真实存在 / pptx 生成→上传校验→解析→登记产物 /
子智能体门控），ruff check 与 format 干净；前端 **1284 passed**、`tsc -b` 干净、
`eslint src scripts` 干净。pptx 在真机 PowerPoint 里打开并导出 PNG 逐页核对过
（中文、缩进、超长要点折行都正常）。

### 修复（2026-11-07 第七十二轮：说「先别生成，我就想问问」仍被补了一份 docx）

**现象**：线程里有素材，用户说「先别生成吧，我就是想问问周报该怎么写」。
模型答得完全正确——只讲骨架和方法，不落盘。但回复结束后，引擎的**可靠性兜底**
又替它补了一份没人要的 docx。答得越对，越会出事。

**根因不在意图层，在兜底的判据**。`_reliability_fallback` 判断"他是不是要一份文档"
用的是 `keyword in message`：那句话里有「生成吧」，于是命中 `EXPLICIT_BUILD_MARKERS`。
一个纯子串检查看不出「生成吧」前面站着「先别」。

两处都修，因为错在两个地方：

- **词法**：新增 `phrase_stands(message, markers)`——短语必须"站得住"才算数。
  沿用 `commit_verdict` 的同一套闸门（同分句否定、条件从句、转述、句尾疑问），
  但返回值是"这个短语是不是一句有效指令"，不是"他拍板了没"。兜底改用它。
- **语义**：新增 `hold_verdict` / `hold_of`，认出三类"这一轮别动手"：
  明确叫停（先别 / 暂时别 / 先放着）、推后到确认之后（我点头了再 / 等我确认了再）、
  自述只问（我就是想问问 / 我只是打听一下 / 我还想搞清楚）。
  `apply_hold()` 在 `read_turn` 的三个出口（零成本短路、模型判定、退兜底）全部生效，
  **只往下压、不授予任何权限**——判错的代价只能是多问一句。

两个必须成对的细节：

- `hold` 不吞掉窄指令。「这个先不用改，改标题就行」第一版被判成叫停，
  是这轮唯一自己引入的误伤——评价集里表现为"保守 +1"。判据仍是位置：
  叫停后面跟着「……就行 / ……就好」，那是在**指定**做什么，不是停手。
- `commit_verdict` 也要认得"推迟"。以前「先给方案，我点头了再落盘」因为含「落盘」
  直接判拍板；现在命中 `_DEFER_RE` 就是否——条件没满足，话不算数。

同一轮清掉 `PROMISE_MARKERS` 里的三个虚词（「这就 / 马上 / 现在给你」）：
模型正常收尾的「这就要看你想给谁看了」就能命中，然后内核替它补文件。
换成「我这就给你做 / 我现在就生成」这类带主语的整句。

**度量**：评估集 107 → 114 条（新增 7 条覆盖叫停 / 只问 / 推后 / 转述叫停 /
叫停与窄指令并存），真实模型 **109/114（95.6%）**，危险 0、已兜住 0；
确定性层 114 条误判 0。顺手修了两条标注缺陷：「我说的是给老板看」标着要动手
却没有 `history`（模型无从知道上一轮已经在改），「这就要看你想给谁看了」
是对话性回应却标了 explore。
真实链路两连：带素材说「先别生成吧，我就是想问问」→ 零工具零产物、正文给骨架 + 示例；
说「行，那就按这个结构，直接生成一份周报」→ 正常出 docx。
后端 1596 passed（+14）、ruff check 与 format 全干净。

### 调整（2026-11-07 第七十一轮：词表横排、评估集补密度，挖出两个判定缺口）

**判断**：「行数不是指标，能一眼看全才是指标」。六张词表原来一个词一行，
占了 200 多行——不是有人手写的，是 `ruff format` 的产物：只要带尾逗号，
格式化器就认定"作者要竖排"，每次保存都摊得更长。改成隐式字符串拼接 +
`_words()` 之后，一行十来个词，改词就是改一行文字，格式化器也不会动它。

同一轮把评估集从 70 条补到 107 条。补的不是数量，是**此前一条样本都没有的
句式**：寒暄变体、撤回梯度（取消 / 暂缓 / 叫停）、条件从句、转述与二次转述、
疑问尾、说完反悔、长材料 + 尾部指令、礼貌请求 vs 征询、甩手授权、一句话两件事、
中英混、指代不唯一、催促、复述要求。

补样本立刻换来两个真发现：

1. **表里的词被自己的闸门关掉**。「不用问了」「别再问了」在 `_STRONG_COMMIT`
   里，但否定闸看到「不」「别」就拦——词在表里，却永远判不出拍板。修法是让
   否定闸只作用于**正则拼出来的弱匹配**：弱匹配里出现「不」几乎必然是否句
   （「这样改不太好吧」），表内短语是人挑过的，「不用问了」带「不」恰恰是
   "别问了、直接做"。
2. **疑问标记不在句尾**。中文常常不打问号：「按这个来会不会太快」
   「就按这个是不是更好」。只看句尾问号，会把这些问句当成决定。新增
   `_QUESTION_MARKER_RE` 检查短语**之后**有没有疑问标记——判据仍然是位置。

护栏也跟着换了一条：「评估集漏判不超过 30 条」这个数不成立，它随样本量上涨，
加一条祈使句就挤占一格配额，最后调的是配额不是判据。改成
`_MUST_CATCH`（写死在测试里的十条明确拍板，不从表里读，才能发现表被删空）
+ `test_every_phrase_in_the_table_can_stand_alone`（表内每条都要能单独判出
拍板，正是它抓到了上面第 1 点）。

度量：确定性层在 107 条上**误判 0 / 漏判 38**；真实模型评估 99/107（92.5%），
危险 0、已兜住 2、保守 1、档位 5。后端 1582 passed，`ruff check` 与
`ruff format --check` 全干净（顺手清掉前几轮留下的 15 个文件的格式债）。

**留了一条明确的结构性张力没动**：`commitment` 一个字段同时表达「能不能动手」
和「能不能落盘」。按提示词的现行口径「让你读一份材料也是动手」，
「这几份材料你帮我看看，我还没想好怎么弄」应记 `authorized`（读可以），
但它的真实语义是"别写"。模型在同类句子上两次判反，说明这是字段划得粗，
不是模型不稳。要不要把两件事拆成两个字段，是产品级决定，等拍板。

### 调整（2026-11-07 第七十轮：write 拆成「给方案」和「交付」，复核时挖出一个门控漏洞）

**判断**：三档（chat / explore / direct）说的是「他要话还是要结果」，但真正决定
怎么招呼他的还有第二个维度——**拍板没有**。两个维度交叉出四种处境，用同一套
提示词招呼它们是矛盾的：

`direct + proposed`（「我想弄成一份周报，你看行吗」）以前落到 write 档，拿到的
system 里一边写着「用户要文件就调 doc_generate_report，不能只在回复里给文本」，
一边写着「他还在商量，这一轮不要生成」。同一份提示词让模型自己赌，赌错就是
一份没人要的 docx——评估里行为发飘，一半是这个原因。

所以把 write 再切一刀：

| 交付形态 | 条件 | 提示词 | 步数 |
|---|---|---|---|
| `chat` | 只是在说话 | 读工具三行说明 + 说话方式 | 2（有素材 3）|
| `read` | 在问、在评价 | 工具约定 + 回答方式 | 3 + 素材数/2，封顶 6 |
| `draft` | 方向明确、没拍板 | 工具约定 + **给方案不落盘**（新增）| 同上 |
| `deliver` | 拍板了 | 工具约定 + 交付约定 + 产物格式 + 收尾 | 全局上限 |

`draft` 档的新提示词只要求一件事：把方案做实在——做成什么样、为什么不是另一种、
代价是什么、拿不准的给默认值，最后问一句。**不注入产物格式**，也不给
「必须交文件」的规矩，矛盾从源头上消失。

**改的同时补了三处别的**：

- **字段上限从"压扁"改成"天花板"**。`goal` 40→120、`question` 80→120、
  `basis` 60→160、`scope` 6→12，`missing` 单独拆出 160。40 字会把
  「把 W44 和 W45 合并，退款单独成节，口径按订单数」截成半句，条件一丢，
  下一轮它就得重问。**prompt 里那句「不超过 30 字」也一并删了**——只放宽代码
  没用，模型照着 prompt 自己就压扁了，截断根本不触发。新增断言
  `test_prompt_no_longer_asks_for_30_char_brief` 防只改一半。
- **把握度门槛**：`CONFIDENCE_FLOOR` 0.65→0.75，`MIN_AUTHORIZED_CONFIDENCE`
  0.5→0.72。0.6–0.7 是模型"我在两档之间犹豫"的分数段，拿它当动手依据不成立；
  但也不拉满，0.9 会让每句明确指令都得先反问一遍。authorized 门槛比 FLOOR 低
  三分是因为它有"说出口的那句话"作凭据，可以比纯语气的判断松一点。
- **步数按素材厚度放宽**：三份材料只给三步，它读完两份、第三步必须开口，
  第三份就只能编。1 份→3 步、3 份→4 步、5 份→5 步，封顶 6。这不是多花几步的问题，
  是"没读到"会不会被当成"没有"的问题。

**复核时挖出一个真实漏洞**（本轮最重要的产出）：

`policy.decide_write` 里「明确指令本身就含授权」那条分支只看
`stance == direct and confidence >= FLOOR`，**没有检查 commitment**。于是
`direct + proposed`（「我想弄成一份周报，你看行吗」）只要模型给的把握度过线，
就直接放行写盘——一句话里既承认"在问"又照样落盘，等于门控没装。补上
`commitment == proposed` 的提前拦截，并加了 `test_delivery_does_not_grant_permission`
钉住它。

评估口径也跟着改：`eval_reading.py` 现在拿真实 `decide_write("high", reading)` 过一遍，
把"读错但门控拦住"单列成 `已兜住`，不再和 `危险`（读错**且会落盘**）混在一起。
兜底越有用、指标越难看，最后没人愿意修真问题——这一栏就是为了避免这个。

**度量**：四次评估 68 / 67 / 66 / 68（70 条），**危险恒为 0**。期间抓到一次
「这几份材料你帮我看看，我还没想好怎么弄」被判成 authorized（conf=0.62）——
按旧门槛 0.5 它会直接落盘，按新门槛 0.72 被拦下，属于"读错但没出事"。

**真实链路**：「我想把这几份材料弄成一份周报，你看行吗」→ 只 `file.list`、零产物、
七段结构 + 取舍 + 代价 + 两个默认值 + 一句问话；「直接生成一份周报，就按你上面
说的结构」→ 正常产出，并交代"骨架不是成品、哪些没替你编"。

**测试**：+20（后端 1577 passed），ruff 干净。

### 调整（2026-11-07 第六十九轮：确定性信号层从「删词表」升级到「看句法位置」）

**判断**：上一轮把 `intent.py` 的关键词表删到只剩三件事，方向是对的——判断依据在
句内齐了才做，齐不了就交出去。但它只做到了「删」，没做到「准」。逐条查下来有三类
**会真出错**的缺陷，补词是补不好的：

1. **剥词法是 `str.replace`**。「行」会把「行业报告」咬成「业报告」，「hi」会把
   「history」咬成「story」。这次结论侥幸没翻车，换个句子就会。
2. **残余不做容忍**。「好了」「行吧」「就这样吧」「早上好呀」一律被判成"不是"，
   因为它们不知道该把句尾的「了/吧/呀」当语气词。
3. **没有句法位置**。「先别生成吧」「不要直接生成」「如果按这个来」
   「他说按这个来」——全部命中拍板短语。前三条会**直接写到盘上**。

**做法**：不再加动作词，而是加了「看词站在什么位置」的能力。分四层：

- **文本整形**（`shape_of`）：NFKC 归一（全角问号/字母）、剔零宽与双向控制字符、
  标点**换成空格而不是删掉**（删掉会把「不，要」粘成「不要」）。产出三种视图：
  `text` 留给句法、`stem` 留给词法（空格是拉丁词的天然边界）、`compact` 只回答
  「有没有内容」。纯 emoji 因此等同于空消息。
- **最大匹配词法**（`_Lexicon`）：每个字符只被整词消费一次，绝不跨词咬进实词；
  纯拉丁段只做整段匹配。残余再交给语气词表容忍（剥三轮，剥与折叠互相露出对方）。
- **句法位置判定**（`_blocker`）：四道闸——词组内部带否定、同分句里的否定
  （裸「不」也算，但排掉「不错/不然/不但」，因为「刚才那个不生成吧」是真否句）、
  前缀里的条件从句、前缀里的转述，外加**说完之后的反悔**（「生成吧——不对，等等」）。
- **判定带凭据**（`Verdict`）：每条判断返回 `value + confidence + evidence`。
  布尔值答不了「为什么判成聊天」，`policy.py` 也需要把握度，评估脚本要靠 evidence
  定位是哪条判据偏了。新增 `explain()` 把整条判定链摊开。

**顺带修的**：
- `fallback_reading` 的置信度不再写死 0.8，改用 `commit_verdict().confidence`
  （「直接生成」0.9 / 「……吧」0.72），让 `policy.py` 的门槛真正起作用。
- 修正 `deterministic_reading` 里与代码不符的注释（它从未短路 `bare_confirmation`，
  也不该短路——「好」只有结合上一轮才知道授权了什么）。
- 评估集里 `刚才那个文件也看一下`、`就按你说的，合成一份吧` 两条标注「承接上一轮」
  却没给 `history`，模型只能判 proposed。补上上下文，让样本测的是它声称要测的能力。

**度量**：`eval_reading.py` 连跑三次，全对 67 / 66 / 69（70 条），**危险恒为 0**。
抖动集中在 stance（档位），说明软判断会漂、硬门控不漂——这正是
`reading 猜 + policy 兜` 这套分层想要的形态。确定性层单独用评估集反查：
70 条里误判授权 0 条，漏判 28 条（全部是祈使句和短确认，需要语境，本就该留给模型）。

**测试**：新增 `tests/unit/test_intent.py` 68 条，按「三类历史 bug」组织，每条断言
对应一种真实错法。其中两条是**方向性护栏**，读 `tests/data/utterances.jsonl`：
误判授权必须为 0（守「一份没人要的 docx」的入口），漏判不得超过 30 条
（守「越改越保守，兜底永远不授权」的反向事故）。后端 1557 passed，ruff 干净。

### 调整（2026-11-07 第六十八轮：输出不再设上限、docs 目录规整）

**判断**：上一轮只是把上限从 2000 提到 8000，仍然是内核在替模型决定「你能想多久」。
用户要求彻底不限制——`max_tokens` 是**上限不是花费**，按实际输出计费，卡紧省不下钱，
只会毁答案。这一轮把开关做成「默认不限制」。

- **单次输出上限：默认不限制**（`MODEL_MAX_TOKENS=0`）。请求里**不带** `max_tokens` 字段，
  由供应商按模型自身的输出上限决定；填正整数仍当硬顶用（限流/成本兜底场景），
  且不再被 32000 这种魔数二次裁剪。
- **不限制时取消「放大预算重试」**。以前被截断会放大 3 倍再要一次；没设上限时再被截断
  只可能是模型自身上限到了，重试结果一样，只会白等一轮还多付一次调用。
- **整轮预算 200k → 1M**（`TOKEN_BUDGET_PER_RUN`、`model_token_budget`）。它只防跑飞、
  不参与「想得够不够」；设成 deepseek-flash 的上下文大小（1M），永远先于上下文溢出触发。
- 涉及：`providers/base.py`（`max_tokens: int | None`，`None` = 不发字段）、
  `model_router.py`（三层签名放开）、`real_engine._max_output_tokens()`（返回 `None`）、
  `core/config.py`、`.env`（加 `MODEL_MAX_TOKENS=0` 与说明）。

**docs 目录规整**：新增 [docs/README.md](docs/README.md) 作为总索引，按用途分七类，
并明确「活文档 vs 快照」的判定规则（带日期后缀的是一次性证据，不要更新）。
`docs/tech.zip`（与 `docs/tech/` 重复的打包产物，78KB）移出到 `.backup/`。
`KNOWN_ISSUES.md` 刷新日期并补入第六十六/六十七轮后的真实链路状态；README 里过期的
「前端覆盖率 8.61%」改为已闭环的 72.05%。

### 调整（2026-11-07 第六十七轮：放开 token 上限、收窄产物提示）

**判断**：`max_tokens` 是上限而不是花费，按实际输出计费，卡得紧几乎不省钱，却会实实在在地毁掉答案。
用户提的「不要各层级都设 token 限制，限制太死思考不到位」是对的，而且有两条实测依据。

- **单次输出上限 2000 → 8000，硬顶 4000 → 32000**（`_max_output_tokens`、`model_max_tokens`）。
  `deepseek-flash` 默认开 thinking，推理内容也走这个额度：2000 时一次带推理的工具调用会先把额度
  花在 reasoning 上、正文变成空串（日志 `正文为空但 finish_reason=length`），再靠 provider 层放大到
  6000 重试——白等 30 秒还多付一次调用。
- **`file.read` 正文观察上限 7000 → 24000 字**。两万字的报告原来只能看到开头三分之一，后面靠猜。
- **工具观察截断 1800 → 4000 字**。此前一个 `doc.analyze_material` 的结构摘要就能占满，
  模型看不到第三份材料的细节，「没读到」被误当成「没有」。
- 保留 `TOKEN_BUDGET_PER_RUN = 200000` 与 `MAX_STEPS_HARD_LIMIT`：它们防的是失控，不参与「想得够不够」。

**产物卡片悬浮提示收窄**：只留「文件名 + 类型 · 大小 · 时间」。去掉「源自 a.docx、b.docx…」的
素材列表和「生成这份文件用了 N tokens」——素材一多提示会撑到四五步高，挡住用户想确认的那一行；
tokens 在行内右侧本来就有。

**产物仓库不加删除按钮**：产物中心已有完整链路（勾选 → 移入回收站 → 恢复 / 彻底删除），
侧栏窄栏 hover 已放三个图标，再加一个会挤掉文件名，且删除是高风险动作，常显反而增加误触。
结论见 `docs/release-checklist.md` 之外无需额外开发。

**新增 `docs/release-checklist.md`**：记录上线前必须做、但现在不该动的项，首条就是 mock 下线
（隐藏设置页开关、强制 `MOCK_MODE=false`、供应商全挂时不再降级 mock 而是明示失败；保留代码供
测试与离线演示用）。

### 重构（2026-11-07 第六十六轮：把「判断」和「权限」拆开，判错不再出事故）

**现象**：「用户还在商量，文件已经生成了」。上一轮把判断从关键词换成了模型，仍然会漏——
因为**判断结果直接等于能不能写文件**：只要判成 act，`doc.generate_report` 就出现在工具清单里，
模型一调就落盘。判断不可能永远对，把「猜得准」当安全前提，本身就不成立。

**根因**：一条链上混了两件事——「他想干什么」（认识问题）和「准不准他干」（授权问题）。
两者绑在一起时，判错一次就是硬故障：判成聊天 → 连文件都读不到；判成派活 → 多一份没人要的 docx。

**改动**：

- **`intent.py` 从意图分类器降级成确定性信号**。删掉动作词表（`WRITE_INTENT_KEYWORDS` /
  `READ_INTENT_KEYWORDS`）和长度阈值（`CHAT_MESSAGE_MAX_CHARS = 60`）。只留三件判断依据在句内
  就齐了的事：空句、整句寒暄（剥词判断，不是找词）、纯确认（「行 / 就这个」）。
  `intent_of()` **永不返回 write**——兜底站便宜的那一边。
- **`reading.py` 增加 `commitment`**（none / proposed / authorized），并改写判据：
  不再问「句子里有没有动作词」，而问「他拍板了没有」。四个 authorized 依据：拍板短语、
  上轮有方案时的短确认、对象范围结果唯一的祈使句、祈使式的纠正。
  特别写明**评价不是指令**——「这版太长了」是描述问题，不是授权重做（评估集实测就错在这）。
- **新增 `policy.py`，写权限门控**。工具不再按意图裁剪（能力全给），高风险写工具在**执行前**
  按「是否已授权 + 风险等级 + 置信度」判断：低风险（写计划）直接放行；高风险（生成文档、跑脚本、
  删文件）必须 authorized；authorized 但置信度 < 0.5 也要拦（实测误判集中在 0.5 上下）。
  被拦时不报错，回给模型一句说明，让它改成「先讲打算 + 问一句」。同一轮拦 2 次就收手。
- **工具可见性不再是权限边界**。`_tools_for()` 一律返回全部工具。判错成「只是聊天」也能读到文件；
  判错成「要动手」也落不了盘。system 末尾加一行授权状态，让模型不用试探就知道边界。
- **`max_tokens` 400 → 800**。实测 400 会在 `missing` / `basis` 中途截断 JSON，
  解析失败后静默退到保守兜底——表现是「用户说得很清楚，它却一直在问」，约 6% 的请求命中。
- **新增评估集**：`backend/tests/data/utterances.jsonl`（70 条真实说法）+ `backend/scripts/eval_reading.py`。
  输出 stance / commitment 准确率，并把错误分成**危险（误生成）/ 保守（多问一句）/ 档位（话风）**三类，
  危险错误非零即退出码 1。这是「覆盖率」唯一能量出来的方式——加词只能让这次对，加样本才知道下次错在哪。
  当前基线：70 条全对 69 条，危险 0，保守 0。

**实测**（真实模型，两条素材）：

| 输入 | 结果 |
|---|---|
| 这份周报想改成给老板看的版本，怎么改好？ | 读 1 次，810 字，给 A/B/C 三个方向 + 问「要不要按 B 出稿」，**无产物** |
| 就按 B 出稿，直接生成 docx | 读 + 两段脚本，产出《工作周报（老板版）.docx》，398 字交代三处未确认数据 |
| 这两份周报合成一份更合适 | 读 1 次，620 字，两个方案 + 问「退款回调这周做了没有」，**无产物** |
| 你好 | 零工具，66 字，接住上一轮的悬念 |

### 重构（2026-11-07 第六十五轮：意图判定从关键词表改成「模型读一遍」）

**现象**：工具和模型档位由一张关键词表决定，人的说法一变形就判错，而且**判错会同时关掉工具和档位**。
「再把 old_weekly.docx 也读出来」里没有词表里的动作词，被判成聊天，连 `file.read` 都不给——
它只能回一句「我这轮没法读文件」。反过来，「这个表按月份拆开会清楚很多」这种评价句其实是派活，
词表只觉得他在闲聊。

**根因**：关键词把**语法特征**当成了**意图**。补词只能救下一次，救不了语气、省略、指代和上下文。

**改动**（新增 `backend/app/agents/reading.py`）：

- 每轮先用一次轻量调用（几百 token）读这句话，输出结构化理解：
  `mode`（talk / inspect / act）、`restate`（用第二人称复述他要的结果）、`scope`（涉及哪些文件）、
  `missing`（动手还缺什么）、`question`（真要问的那一句）、`confident`。
- 三档语义改成**只决定能不能写**，不再决定能不能读：talk / inspect 都挂只读工具，
  只有 act 才把写盘工具摆出来。talk 的步数 1 → 2，判错时至少还能读。
- **判错往宽了兜**：理解调用异常、超时、输出不合 JSON、`mode` 非法，一律退到关键词兜底；
  兜底只决定大致档位，**不触发反问**（没读懂就别装懂）。
- `confident=false` 且 `missing` 非空时，这一轮不动手，直接把 `question` 问出来
  （`stop_reason="awaiting_user"`，不产生 `tool.*` / `artifact.*`）。猜错要白干一轮还附赠一份
  没人要的文件，问一句只要半句话。
- `restate` 贴在用户消息末尾作为目标锚点：system 那两三千字规则容易把目标冲淡，
  而原话里往往混着背景和情绪，复述才是该交付的东西。
- `intent_of()` 降级为兜底，不再出现在主路径上；mock 引擎改用 `fallback_reading()`。

**顺带（信息密度）**：`system.md` 与 `REPLY_RULES` 去掉「全文 120 字左右」的一刀切——
它让「交付一份文档」和「解释一个判断」都只能写 120 字，结果是把依据和口径一起砍掉。
改成可执行的删句标准（删掉之后他要做的事不变，就删）+ 一条「结论依据的关键事实必须写在回复里」。
`system.md` 版本 2.0.0 → 2.1.0。

**澄清（模型档位）**：官方 API 现在只有 `deepseek-flash`（= DeepSeek-V4.1-Flash-1017）与
`deepseek-v4-pro` 两个 `model` 取值，`deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 停止服务。
因此「换个小模型」并不是这套回答变薄的原因；且 thinking 模式下 `temperature` 不生效。
`MODEL_NAME=deepseek-flash` 保持不变。

**验证**：后端 1483 passed / 42 skipped，ruff 干净。真实模型四条：
「这份周报讲了什么」→ 一次 `file.read`、351 字、主动指出两份周报的口径对不上；
「old_weekly.docx 那段退款的原话」→ 无动作词仍能 `file.read` 取原句（旧逻辑下这句判聊天）；
「你好」→ 零工具、70 字、接住上一轮的悬念；「两份合成一份给老板看更合适」→ 读 + 生成，
并在回复里交代两处取舍（不替「退款回调」编状态、不把两周指标混算）。

### 重构（2026-11-07 第六十四轮：思考从「每轮一段」改成「决策点一句话」）

**现象**：拆掉流水线之后，思考区仍然是定式的——每轮开工都先摊开一段推演，读起来像模板在演。
根因是那段推演本来就是个**固定环节**：模型动手前说的第一段话整段当思考，且不管这句话里
有没有真的判断。

**语义改了**（`docs/events.md` 3.13）：`thinking.*` 现在只在三种场合出现，一条一句话（≤64 字）：

| kind | 什么时候 |
|---|---|
| `decision` | 它在两个方向里挑了一个，或决定先停 |
| `ask` | 它停下来等你补一句话 |
| `error` | 某一步没成，得换法子 |

- 新增 `decision_line()`：从动手前那句话里挑「真的在拿主意」的句子（问句 / 给方向 / 说没把握 /
  要确认）；没有就返回空，那句话压成一行进 **process 旁白**，不占思考区。
- 工具失败时补一句人话（`tool_failure_line`，工具名翻成动词 + 原因 + 接下来怎么变）；
  用户拒绝写盘时说一句「你按住了这一步，我就不动了」。
- mock 引擎同步：删掉四段式 `THINKING_TEMPLATE`、审批后的二次思考、「读完了 N 份 M 段」的体检报告
  式长文，只在选模板时给一句理由。

**前端**：`ThinkingBlock` 从卡片改成一行淡字（错误用告警色，问句用品牌色图标），
不再有「正在思考 / 已思考 3.2 秒 / 点击展开」；决策行不再折进「思考过程」那一行，
直接摊在对话里（`full` / `brief` 都显示，`off` 才收走）。

**顺手**：`providers/base.py` 加 `strip_tool_markup()`——deepseek-flash 偶尔把工具调用写成正文里的
DSML 标记，实测吐到对话里是一段乱码；归一化时切掉，切空了就当空回复重试。

**验证**：真实模型三条链路——「你好」零思考零工具；「有哪些进展」零思考、只读一次；
「按你说的直接生成 docx」零思考、两步产出文件。后端 1467 passed，前端 1276 passed。

### 修复（2026-11-07 同一轮：关掉预览后焦点环与「预览」气泡残留）

**现象**：产物仓库里点开预览再关掉，那一行的眼睛按钮上留一圈黑框，整条悬浮操作条也一直挂着，
鼠标早就不在那儿了还会冒出「预览」字样。

**根因**是一条链：`Modal` 卸载时无条件 `previous.focus()`——鼠标关闭时这次调用已经脱离用户手势，
Chrome 一律判成 `:focus-visible`，于是按钮上留焦点环、依赖 `group-has-[:focus-visible]` 的操作条
常显；同时 `Tooltip` 绑的是 `onFocus={show}`，焦点一回去就弹气泡。

**改法**：`Modal` 只在键盘路径（Esc / Tab+Enter）还原焦点；`Tooltip` 只在键盘聚焦时弹
（模块级记最近一次输入是键鼠，不用 `:focus-visible`——那个伪类没法在 jsdom 里复现），
按下就收起（`onPointerDown={hide}`）；`ArtifactActions` 的焦点环换成品牌色，不再是浏览器默认黑框；
`tokens.css` 再兜一层 `button:focus:not(:focus-visible) { outline: none }`，
以后别的浮层再引入「关闭后还原焦点」也不会把这道残影带回来。

**验证**：vitest 1276 passed，`tsc` 干净。

### 重构（2026-11-07 第六十三轮：引擎从「流水线」改成「回合」）

**背景**：用户的原话是「会话太单一，想做成两个合作者在商讨方案那样」。复盘下来，问题不在
提示词措辞，而在内核替模型做了太多决定：`intent.py` 按关键词把一句话分成 chat/read/write；
`plan_steps_for()` 在模型开口之前就按关键词挑好 4 步计划；`_compose_thought()` 每轮另跑一次
固定四维度、固定 360 token 的「思考」调用；`_reliability_fallback()` 只要消息里有「整理 /
报告 / 摘要」且没产物，就强制补一份 docx。于是无论问什么，界面都是同一张计划表、同一段思考、
同一份文件的流水线。

**改动**

- **意图判定先看「是不是在问意见」**（`agents/intent.py`）：新增 `_ADVICE_RE`
  （怎么改 / 要不要 / 是不是 / 你觉得 / 哪个好 …），命中就落到「商量」档而不是「派活」。
  「这份周报我想改成给老板看的版本，怎么改好？」以前命中「改成」直接开工，现在只读材料、
  给方向、不动文件。句尾的「行吗 / 可以吗」不算征询——那是客气，该直接做。
- **删掉内核的步骤模板**（`agents/real_engine.py`）：`PLAN_FORMAT / PLAN_DOC / PLAN_EXTRACT /
  PLAN_CODE / PLAN_ANSWER` 与 `plan_steps_for()` 整块删除。计划只在模型自己调用
  `todo_write` 时出现，进度也只由它更新；`_advance_plan()` 按工具名猜进度（读一次文件就
  勾掉一步）随之删掉，`_mark_plan_done()` 不再把 pending 一律标 completed——那是化妆。
- **思考不再单独跑一次模型调用**：删掉 `_compose_thought()`（固定 system、固定四维度、
  固定 360 token，产出必然同构）。动手前的第一句旁白直接作为 `thinking.*` 下发，和它接下来
  真正做的事是同一段推理；模型一声不吭直接动手时不显示思考区——没有「想」比编一段想更像人。
- **兜底不再替用户决定**：`_reliability_fallback()` 的触发条件从「任务含文档意图」收成
  「明确命令（直接生成 / 就按第二个 / 别再问）或模型自己承诺了却停住」。商量到一半被塞一份
  docx 是最伤信任的错，宁可让用户多说一句「做吧」。
- **提示词换人格**（`prompts/system.md` 1.5.4 → 2.0.0）：开头从「目标不是聊天，而是把任务做完
  并交付文件」改成「一起把事定下来，再把它做完」；新增「商量」一节（先说判断、再给 2–3 个方向、
  等对方挑）；交付类 120 字、商量类不压字数。引擎侧配一段所有意图共用的 `CONSULT_RULES`。
- **收尾话术不再报运行数字**：「已达到最大步数 8」改成「这一轮到步数上限了，文件已经产出…」；
  空回复按「有产物 → 报文件名 / 说过话 → 那句就是回答 / 一声不吭 → 直说」三档。

**验证**：后端 1462 passed / 42 skipped，ruff 干净；新增 5 条用例（问意见不算派活、
商量轮拿不到写盘工具、第一段旁白进 thinking、沉默时不出 thinking、模型没写 todo 就没有计划）。
真实 DeepSeek 连跑三条：「你好」→ 只有 run.started / message.delta / completed，零工具零计划；
「这份周报我想改成给老板看的版本，怎么改好？」→ 只 file.read 一次，给出三种改法和缺的信息，
未产文件；「就按第一个来，直接生成 docx」→ file.read + doc.generate_report 一次成稿。

### 优化（2026-10-30 第六十二轮：浮层去黑，产物行的操作条内化「添加到对话框」）

**背景**：两处观感问题。一是浅色界面里还留着几块纯黑浮层——加号菜单整块 `bg-black`
（还专门配了一套 `menu-on-dark` 亮色令牌），hover 气泡是 `#101828` 的实心黑，图表提示
是 `bg-ink`；手指划过按钮就跳出一块黑胶布，和周围的白卡片完全不是一个世界。二是产物行
只有预览 / 下载两颗小图标，「把上周那份稿子拿回来再改一版」只能自己去文件管理器翻出来
重传。

**改动**

- **浮层不再压黑**：`Tooltip` 两种形态（单行标签 / 多行富内容）统一成「白色卡片 + 细描边
  + 2px 背景模糊」，浅色主题文字走 `#1f2937`，深色主题保留 `#2b303a`；加号菜单从
  `bg-black` 回到 `bg-surface`，`.menu-on-dark` 那一段就地换令牌的样式整块删掉；柱状图 /
  面积图的 hover 气泡、`BarChart` 的数值提示同步换色。这样浅色下所有浮层都只靠投影和描边
  分层，不再有「突然掉下一块黑方块」。
- **产物行有了悬浮操作条**（新组件 `features/artifacts/components/ArtifactActions.tsx`）：
  预览 / 添加到对话框 / 下载三件事收进一条 90px 的胶囊，平时不占位；hover（或键盘
  focus）时右侧「大小 + 格式」原地让位给操作条——位置固定、行高与文件名字段宽度都不变，
  鼠标顺着列表往下扫不会看到按钮「跳出来又缩回去」。行本身加了三处轻量反馈：左侧 2px
  品牌色竖条从中间长出来、极浅的品牌色底、类型图块轻抬 0.5px 并托起一层阴影
  （`.artifact-row / --card / __tile`，见 `tokens.css`）。
- **「添加到对话框」是真动作**：`WorkbenchPage.addArtifactToChat()` 取回产物文件 →
  走和手动选文件同一条素材上传链路 → 输入框上方出现素材条，下一轮的工具就能读到它的正文
  （只塞一句「见附件」是读不到的）。成功后按钮图标变勾停留 1.6 秒、状态栏补一句
  「接着说想怎么改」；格式不在后端白名单里（md / csv 等）时就地说清楚，不做假成功。
  右栏「产物仓库」的每一行同样有这颗按钮——它才是翻旧稿最常用的入口。
- **两处排版修正**：产物行的「6.48 MB + DOCX」在 88px 的槽位里会折成两行（实测），槽位
  放宽到 96px 并加 `whitespace-nowrap`；文件名提示不再二次截断，改成 `break-all` 换行，
  长文件名在气泡里能读全。

**验证**：vitest 1245 passed（新增 4 条：操作条三个动作都在、添加到对话框成功变勾 /
返回失败不假装成功 / 没接线时不出按钮）；`tsc -b`、`eslint`、`prettier` 干净；Playwright
39 passed；浅色与深色两套主题各截图核对（产物行悬停、加号菜单与二级面板、右栏操作条），
并实点一次「添加到对话框」确认素材条与提示都出现、随后清理掉测试产生的重复素材。

> 注：`e2e` 第一次跑挂在 5173 上——本机另一个应用占着这个端口，`reuseExistingServer`
> 直接复用了它（页面快照是「资源库 / 自动化 / 评测」另一套导航），39 条全红全是环境问题；
> 换到 5174 后全绿，`playwright.config.ts` 已还原。

### 新增（2026-10-30 第六十一轮：外观可控字重与字体，审批项说人话）

**背景**：设置页还有四处「不像给用户做的」——审批工具列一排 `code.run_python`；
外观只有主题与缩放两行，字重和字形都没得选；关于页塞着暂时用不上的意见反馈卡片。

**改动**

- **审批工具用中文名**：`执行 Python` / `生成文档` / `删除产物`，技术名与工具说明
  挪进 `title`（悬停可见，排查时仍能对着日志找）。名称来自 `shared/lib/format` 的
  `toolLabel()`，没有新增翻译表；届时新增工具只需补一行。
- **外观新增三项**（均写 localStorage，刷新后仍在）：
  - 字体大小：滑杆右侧带「小 / 默认 / 大」刻度，刻度按真实百分比定位（默认 90% 在 33% 处），
    不是硬拉三等分；
  - 字体粗细：300~600（细 / 常规 / 粗），写 `--ui-font-weight`；`tokens.css` 末尾把
    `.font-medium / .font-semibold / .font-bold` 改成「基准 + 一档」，所以调粗细不会把
    标题与按钮之间的层级抹平（基准 400 时与 Tailwind 原值完全一致，界面零变化）；
  - 字体样式：默认 / 微软雅黑 / 思源黑体 / 宋体 / 楷体 / 行楷，下拉选项按各自字族渲染
    （不用选完才知道字形），选中即改写 `--font-sans`，整个界面跟着变；
  - 「恢复默认外观」一键把主题、字号、字重、字体样式一起复位。
- **下线意见反馈卡片**（设置 → 关于）：组件与测试保留在 `components/FeedbackCard.tsx`，
  需要时把 import 与一行 `<FeedbackCard />` 加回去即可。
- **窄屏顶栏**：390px 下 `品牌名 + 页面标题 + 返回首页 + 主题 + 刷新 + 保存` 会把顶栏顶出
  屏幕（实测 `scrollWidth 416 > 390`）；窄屏收掉品牌名与「返回首页」（logo 仍可回工作台）。

**验证**：vitest 1230 passed（新增 `theme.test.ts` 6 条）；e2e 39 passed（新增设置页一条，
断言中文工具名、字号/字重滑杆写对 CSS 变量、字体样式选中后 `--font-sans` 含 `KaiTi`、
恢复默认清空内联变量）；`tsc` / `eslint` 干净。

### 修复（2026-10-30 第六十轮：产物预览的排版诊断、统一规范与响应式）

**背景**：预览 Word / Markdown / 表格时界面像「把文字堆上去」——正文偏小发虚、
层次分不清、纸面与弹窗边缘挤在一起，窄窗口下还会溢出。

**诊断（改动前实测）**

| 现象 | 根因 |
| --- | --- |
| 正文只有 12.6px、标题 18px | 文档排版写了 rem，被「外观 · 基准字号」（默认 90%）连坐缩放，还成了分数像素（发虚） |
| 字号层级看不出主次 | 标题/正文/注释各写各的值，没有统一刻度，二级列表留白随 |
| 纸面几乎贴住弹窗边框 | 弹窗宽（54rem→778px）与纸宽（46rem→662px）都被同一个缩放系数压小，桌面留白只剩 7px |
| 宽表格挤成竖条 | 表格与文档共用 46rem 纸宽，没有单独的容器策略 |
| 窄窗口内容溢出 | 没有断点约定，靠组件各自 Tailwind 类硬撑 |

**规范（落在 `frontend/src/styles/tokens.css`，改文档版式只动那一段）**

- **`.doc-paper`**：阅读容器。宽度 ≤720px（一行 40~45 个汉字）、居中；留白窄屏 22/18、
  ≥640px 36/40；表格换 `--doc-table-width`（880px）并允许纸内横向滚动。
- **`.prose-docx`**：文档内部版式。**一律 px，不吃界面缩放**——
  字号四档 + 注释一档：正文 15 / 小标题 16 / 段落标题 18 / 文档标题 22 / 注释 12；
  行高统一整数（正文 27，标题 24~30）；垂直节奏六档：6 / 14 / 8+22 / 10+28 / 28。
- **颜色**只用语义令牌：标题 `ink`、正文 `ink-soft`、注释 `muted` / `faint`、链接 `brand-strong`。

**改动清单**

- `styles/tokens.css`：把旧的 rem 版式表换成上面这套 px 版式表 + `.doc-paper`；
  新增 `--color-doc-page` / `--color-doc-backdrop` 一对「纸与桌面」底色（深浅主题都保持
  纸比桌面亮一档，不再复用 surface 导致纸变成凹坑）。
- `features/artifacts/components/ArtifactPreviewModal.tsx`：正文容器改用 `.doc-paper` /
  `.doc-paper--table`（组件不再自己写宽度与留白）；类型图块固定 36px；
  页脚按钮统一叫「用系统程序打开」（原来这里写「用 WPS 打开」，空态却写「用系统程序打开」，
  同一动作两个名字，且 macOS/Linux 上叫 WPS 是错的）；标题栏补 `data-testid` 便于断言。
- `shared/ui/primitives.tsx`：
  - `Modal` 支持 `subtitle` / `leading` / `padded`，并在出现副标题时按
    「标题 15px > 界面正文 13px > 副信息 12px」给固定像素（原来标题只有 11.7px，比正文还小）；
  - `size="lg"` 固定 900px：给纸留出桌面留白；
  - `Tooltip` 增加 `enabled`：弹窗打开后行上的提示气泡不再浮到预览正文上面；
- `features/artifacts/ArtifactCard.tsx`：预览打开时关掉这一行的 hover 提示。
- `features/artifacts/**`：预览正文调用处改用统一的纸容器；测试随之前进。

**交互整合**

- 模型相关设置只留一个控件组（原来的「用量」「模型」两个图标按钮合成一个
  「模型与用量」胶囊：上半是模型列表，下半是近 7 天用量）。
  注：本产品没有「模型强度」这一维度的设置，无法合并；要做需要先有后端参数。
- 技能从输入框工具条上的独立胶囊，内化到「+」菜单里作为二级面板，
  与「产物格式」共用同一套悬停展开交互；工具条上不再单挂一个胶囊。

**验证**：vitest 1222 passed（新增 1 条「纸容器」断言）；e2e 38 passed（
技能/模型/浮层让位三条用例随交互改写）；1440/1180/1024/820/390 五个宽度实测：
文档无横向溢出、正文 15px/27px、纸面留白充足，390 下表格与代码块在纸内横向滚动、
页面本身不产生横向滚动条。

**补充（同日，看完用户截图后按图复核再修的五处）**

- **Markdown 竖线表格**：`renderMarkdown` 以前没有表格分支，`| 现象 | 根因 |` 与
  `| --- | --- |` 只能当正文渲染，读者看到的是两行裸竖线。新增表头/表体识别，
  产出 `<table>`（沿用已有的表头底色与斑马纹）。配一条回归测试。
- **行内代码被从词中间折断**：`` `rounded-panel` `` 默认会在连字符后折行，
  上一行结尾剩 `rounded-`、下一行开头是 `panel`，像打错字。给行内 `code` 加
  `white-space: nowrap`，`pre code` 单独还原为可换行。
- **Word 报告头部的机器信息**：`生成时间：… | 模式：… | 来源：…` 原来与正文同字号同色，
  读起来像正文第一句，把「摘要」往下推。`markDocxMeta()` 把这一段收成 `.doc-meta` 注释块，
  与纯文本预览的处理对齐（同样配了测试）。
- **窄屏「模型与用量」面板整块溢出屏幕**：面板 `right-0` 死贴触发按钮右缘，
  手机上触发按钮离右边缘很远，390 宽时面板左边被切掉 86px（模型名只剩 `mock`、`en`、`n`）。
  改为窄屏挂在触发点中线上（`max-sm:left-1/2 -translate-x-1/2`），实测 37→373 完整落在视口内。
- **另两处响应式挤压**：mock 提示条在窄屏把链接改成独占一行（原来链接插在折行文字右边，
  中间挖出一个缺口）；首页大标题加 `text-wrap: pretty`，不再出现「档」这种单字占一行；
  底部「演示模式…」的圆点改为顶对齐，折行时不再跑到第二行开头像个列表符号。


### 新增（2026-10-29 第五十九轮：桌面端下载完，能看见文件在哪、也能从原处找回）

**背景**：用户删掉桌面端之后找不到安装文件——浏览器自己下载的东西只有「下载」目录里
一个名字，页面既拿不到真实路径，事后也没有任何地方能找回。

**改动**

- 新增 `backend/app/api/v1/desktop.py`：
  - `GET /desktop/package`：可交付状态 + **上次保存的位置**（每次都现算 `exists`，
    被删/被移走会带上原因）；
  - `POST /desktop/package/download`：把安装包复制到目标目录（默认系统下载目录），
    成功才写记录；失败/目录不可用会**清空记录**并在响应里说明原因；
  - `POST /desktop/package/reveal`：在资源管理器里定位文件（文件没了就打开所在目录）；
  - `POST /desktop/package/open`：拉起安装包 / 桌面端本身，等于「重新安装 / 再打开」。
  - 记录落在 `data/desktop_package.json`（与数据库同级，原子写），只认这份记录里的路径，
    不接受前端传任意路径过来。
- 前端 `DesktopAppCard` 的安装弹窗多了「安装包已存到本机」区块：完整路径（可选中、
  可复制）、`复制路径`、`在文件管理器中打开`；文件失效时区块转为警示色，写清
  「已经不在这个位置了（可能被删除或移动）」并给 `重新下载`；文件还在时页脚多一个
  `打开安装包`。右栏入口那行小字也直接显示「安装包在「Downloads」文件夹」。
- 服务端没有可交付安装包时（老部署 / 未配下载地址）自动退回原来的下载链接方式，不出现
  假路径。
- `contracts/openapi.v1.json` 重新导出，`npm run gen:api` 同步类型；顺带补上
  `settings/api.ts` 里 mock 健康响应缺的 `git_sha_live`（上一轮改契约时漏的）。

**验证**：后端新增 11 条接口测试（保存/失效/目录消失/无包/定位/打开/幂等）；
前端新增 6 条组件测试；真机（8000 端口）走通：下载 → 显示
`C:\Users\16650\Downloads\Office Agent.exe` → 复制到剪贴板 → 刷新后仍在 →
把文件改名后提示失效并可「重新下载」恢复。

### 修复（2026-10-29 第五十八轮：旧构建提示认错了人——分清「界面没重建」和「进程没重启」）

**现象**：界面弹出「这个窗口跑的是旧版界面 · 前端构建 8195a64，服务端已经是 1daa671」，
让人去 `npm run build`。可实际上前端是最新的，**后端是一个 10-28 19:28 启动、
加载着 1daa671 代码的老进程**（跨了一整天的提交还在跑）。照着提示做当然没用。

**根因**：`/api/v1/health` 只报一个 `git_sha`，而它是**进程启动那一刻的快照**；
前端只能判断「两边 sha 相不相等」，无法知道是界面落后还是进程落后，于是默认
把锅甩给界面。

**改动**

- 后端 `health()` 增加 `git_sha_live`：每次请求现读仓库 HEAD。`git_sha` 保持「进程载入的
  版本」语义不变，两个字段一对比就能看出进程是不是老的（`schemas.HealthOut` 同步，
  `contracts/openapi.v1.json` 重新导出）；
- 前端 `build-info.ts`：`isStaleBuild`（布尔）换成 `classifyBuildMismatch`，返回
  `frontend | backend | both` 三态；界面与仓库一致、进程落后 → `backend`；
  老后端不报 `git_sha_live` 时退回原来的保守判断，不会突然不提示；
- `StaleBuildBanner` 按三态换文案与按钮：界面旧 → 「重新 `npm run build`」+ 刷新；
  进程旧 → 「关掉启动窗口再双击启动器」+「重新检查」（不再让人白重建）；
  两边都旧 → 先说清两件事，再给刷新；
- 设置 → 关于的「前端构建」徽标同步：落后于仓库 / 后端进程仍是 X。

**验证**：用 Playwright 拦 `/health` 造三种不一致（前端旧 / 后端旧 / 两边旧）+ 一种一致：
文案与按钮各自正确，一致时不出提示条；vitest 1207 passed；后端 unit 309 passed；
e2e 38 passed；`export_openapi.py --check` 一致。

### 修复（2026-10-29 第五十七轮：收起态不再渲染会话条目）

**问题**：左栏收起成 52px 图标条后，会话条目仍以一列「文件图标 + 竖向滚动条」渲染。
图标分不清是哪个会话，滚动条还把这条窄条切出一条灰边——纯属多余内容。

**改动**

- `features/sessions/components/SessionList.tsx` 收起分支删掉会话图标块（含它与导航之间的
  那条分组分隔线），只留 品牌 / 新建 / 展开 / 导航图标；不留占位、不留空块；
- 展开态的结构、文案、样式、交互一律未动（会话搜索、批量清理、⋮ 菜单、分页原样）；
- 收起/展开的过渡仍由 `WorkbenchPage` 外层 `transition-[width]` 承担，切换只是 DOM 换一套，
  没有额外动画与布局位移。

**取舍**：收起态不再提供「图标直达某条会话」的快捷入口，要先展开再选——这与收起态本身
「只留导航、靠悬停浮层解释」的定位一致。

**测试**：`SessionList.test.tsx` 新增收起态 2 条（无 `session-list`、无会话标题、无滚动容器；
展开态照旧）；e2e 收起用例补断言收起态侧栏内不存在 `overflow-y: auto/scroll` 容器。

### 修复（2026-10-29 第五十六轮：本地看到旧界面 / 文字发虚的排查与防护）

**问题**：本地跑起来看到的界面比预览旧一版（底部还挂着已删掉的身份卡、项目区没有折叠箭头），
观感上像「清晰度、尺寸、裁剪都坏了」。根因不是样式，是**跑的产物不是这份代码**。

**1. 构建指纹（让「旧构建」自己暴露）**

- `vite.config.ts` 注入 `__BUILD_ID__ = <git 短 sha>-<构建时间>`，首屏在控制台打一行；
- 新增 `shared/lib/build-info.ts`：拿 `/api/v1/health` 的 `git_sha` 与前端构建比对，
  不一致时广播 `office-agent:stale-build`；`dev` / `nogit` / 后端 `mock` 一律不报（避免误报）；
- 新增 `shared/ui/StaleBuildBanner.tsx`：顶部提示「这个窗口跑的是旧版界面」+ 两边 sha + 刷新按钮；
- 设置 → 关于新增「前端构建」一行，落后于后端时带黄色标记。

**2. 缓存不再留住旧外壳**

- `static_site.py`：`/assets/*` 改用 `ImmutableStaticFiles`（`max-age=31536000, immutable`）；
  `sw.js`、manifest、图标改为 `no-cache`（原来 sw.js 命中 1 小时缓存，等于「装成桌面端后停在旧版本」）；
- `public/sw.js` 的 `VERSION` 改由构建注入（原来是写死的 `v3`，每次构建字节相同 → 浏览器认为 SW 没变）。

**3. 启动器不再拿旧产物凑合**

- `scripts/launch.py`：`ensure_frontend` 会比较 `src/`、`public/`、`vite.config.ts` 等与
  `dist/index.html` 的 mtime，源码更新过就自动重建；`--check` 会显示「比源码旧（启动时会自动重建）」。

**4. 打包版也能报出版本**

- `packaging/office_agent.spec` 打包时生成 `build_info.json`（git sha + 构建时间）带进 exe；
  `core/utils.detect_git_sha()` 在冻结态读它（原来直接返回空串，「关于」里只剩 `0.2.0 ·`）；

**5. 高分屏 / 缩放说明与图标**

- 补 `icons/icon-256.png` 并写进 manifest：Windows 任务栏/开始菜单按 256 取图，缺这一档会插值发糊；
- 设置 → 外观的缩放说明改正（原来写成「100% 最紧凑」，实际是 100% 最大），并写明
  100% 时字号落在整数像素最锐利、85~95% 更紧凑但在 125%/150% 缩放下会略发虚。

### 变更（2026-10-29 第五十五轮：左栏高度重分配，会话列表占满剩余空间）

**1. 项目区改成可折叠，标题行常驻**

- 标题行（`项目 N` + 折叠箭头 + 添加按钮）永远在，折叠只是收纳内容；`添加项目` 始终点得到。
- 内容用 `grid-rows 0fr/1fr` 过渡展开收起（不需要预先知道内容高度，动画不跳），
  收起时补 `aria-hidden + inert`，项目行退出 Tab 顺序。
- 项目列表上限从固定 `9.5rem` 改成 `min(9.5rem, 24vh)`，再多项目也只占这么高、内部滚动，不裁内容。
- 行内边距 `py-1.5 → py-1`，空状态按钮 `py-2 → py-1.5`。

**2. 矮窗口自动收起项目区**

- 窗口矮于 720px：项目区默认收起，把高度让给会话列表；用户手点过折叠按钮就记住偏好
  （`oa:rail-projects-open`），此后按用户的来，窗口再变矮也不会把用户展开的项目收回去。

**3. 会话列表：唯一的弹性块**

- 会话列 `flex-1 + min-h-[7rem] + min-h-0`，剩余高度全归它，内部 `overflow-y-auto` 自己滚。
- 导航行 `h-9 → h-8`（6 项省 24px）、会话列上边距 `mt-3 → mt-2`，省下的高度也归会话列表。
- aside 从 `overflow-hidden` 改成 `overflow-x-hidden overflow-y-auto`：极端矮窗口下放不下 7rem
  会话区时整栏滚动兜底，而不是把列表裁掉一截。

实测（同一批会话）：660px 高窗口可见行 6 → 8；520px 高 2 → 4；各类高度 `asideOverflow` 均为 0
（除「矮窗口 + 手动展开 + 6 个项目」这种极端组合，此时整栏滚动 34px，无裁剪）。

### 变更（2026-10-29 第五十四轮：删掉左栏身份卡与设置里的「运行时」，空间还给会话区）

**1. 左栏底部身份卡移除**

- 「本机 · 演示环境 / 产物仅写入本地目录 / MVP」那张卡删掉：它既不提供操作，又常驻占掉
  左栏最后一屏高度。面板底部现在就是会话列表本身（列表滚动区补了 `pb-2`，末行不会贴着圆角）。

**2. 空出来的空间分给会话区**

- 左栏：会话列表从「列表 + 底部卡」变成整列铺满，同样的窗口高度能多显示约两行会话，
  长列表滚动时也不会再被一张卡挤掉可视范围。
- 对话区：消息列 `48.75rem → 52rem`、输入区与用量/后台任务条 `51.25rem → 54.5rem`，
  大窗口下正文不再是一条窄柱；两者仍保持「输入区比消息列宽 2.5rem、内部左右各 1.5rem 内缩」
  的关系，文字左右边界继续对齐。
- 窄窗口不变：三段都是 `max-w` + `mx-auto`，宽度只在大屏才生效；720 / 900 / 1080 / 1440
  四档实测 `scrollWidth == clientWidth`，没有横向溢出。

**3. 设置页的「运行时」整块删除**

- 导航里 `运行时` 一项、对应的设置面板（Python 脚本 / 工作目录 / 限制 / 环境隔离 / 审批
  五行只读信息）以及 `SectionKey`、`IconTerminal` 导入一并删除；
  分组变成「功能：模型与运行、审批与安全」——不再留下点进去空一屏的死入口。
- 面板里原本只是「展示」的运行时常量与审批勾选状态仍可在「审批与安全」里看到与修改，
  后端 `code.run_python` 的运行时能力不受影响（删的是设置页的只读展示）。

### 变更（2026-10-29 第五十三轮：加号面板瘦身 —— 去重、悬停展开、纯黑底）

**1. 删掉面板内部的「审批策略」**

- 加号右边的胶囊本来就是审批策略的常驻入口，面板里再抄一份（还带三行说明）既占高度，
  又让人怀疑「两边是不是不一样」。现在面板只保留一份入口：胶囊。
  面板里那一组的 props、图标、说明文案一并删除，状态仍由外层同一份 `approvalMode` 持有，
  审批功能一行没少。

**2. 产物格式收成一行，悬停才展开**

- 新增 `ComposerMenuGroup`：折叠时是一行「图标 + 分组名 + 当前值 + 箭头」，
  指针移上去才在右侧弹出二级面板选四项；选完即收起，箭头会给出轻微位移反馈。
- 交互细节：鼠标从行移到二级面板要跨 6px 间隙，留 160ms 宽容时间，不会「一移就没了」；
  触屏点一下也能开、键盘 Tab 到该行同样展开（`aria-haspopup` / `aria-expanded` 齐备）；
  Esc 逐层退出（先收二级面板，再收整张菜单）；展开时按视口边缘自动内收，贴着屏幕也不裁切。
- 面板高度从 ~650px（含审批三行）降到 183px，只剩五行；
  `max-h + overflow-y-auto` 一并去掉——面板不再需要滚动，二级面板也不会被容器裁掉。
- 当前值用新的 `OUTPUT_FORMAT_COMPACT`（Word 文档 / PDF 文档 / Excel 表格 / 纯文本）：
  完整标签带后缀括号，会把左侧分组名挤成「产物…」。

**3. 面板底色改成纯黑**

- 面板 `bg-black`（#000000），去掉原来偏亮的灰黑底。纯黑底上沿主题令牌会读不出字，
  所以在 `tokens.css` 新增 `.menu-on-dark`：就地换一套亮色令牌（文字、描边、悬停底色、品牌蓝），
  子元素继续写语义类，浅色/深色主题下都保持可读。二级面板用 #0b0c0e 比纯黑亮一档，
  靠明度差 + 描边分层。

### 修复（2026-10-29 第五十二轮：下载只能一次 / 恢复卡片式外壳 / 圆角统一调柔）

**1. 同一份产物只能下载一次 —— 改成每次点击都重新取一份文件**

- 原因不是后端（连发三次请求都是 200 + 完整 37 KB），而是前端的取文件方式：
  `window.open(下载地址)` 对着「附件」响应会顺手留下一个空白标签页，连点几次就被浏览器
  按弹窗拦掉——用户看到的就是「第二次点击没反应」；而 `<a href download>` 能否重复落盘
  取决于各家浏览器的缓存去重策略，前端既控制不了也给不出反馈。
- 新增 `shared/lib/download.ts` 的 `saveRemoteFile()`：`fetch(cache:'no-store')` → Blob →
  **每次新建** objectURL → 点一下 `a[download]` → 1 秒后 `revokeObjectURL`。
  每次点击都是「一个新文件」，点几次就落盘几次；objectURL 用完即回收，不会把整份文件
  长期挂在内存里，也不会出现「第二次指向已失效地址」。
- 四个入口统一走它：对话交付卡（由 `<a>` 改成按钮，下载中显示「保存中」）、产物中心列表、
  右栏产物行、预览弹窗。成功给「已开始下载《文件名》」，失败给具体原因，不再静默。

**2. 恢复卡片式布局**

- 外壳回到 `p-2.5 + gap-2.5` 的卡片式：左栏、对话区、右栏各自是 `rounded-panel + 描边 + 投影`
  的独立卡片，间距与内边距回到上一版口径；`--spacing-rail` 回到 16.5rem。
- `.window-inset-top` 恢复「标题栏高度 - 外壳 10px」的让位写法，窗口按钮不会压住面板内容。

**3. 圆角统一调柔**

- token 收成五档：`xs 6px`（复选框/行内代码）、`chip 8px`（类型角标）、`control 10px`
  （按钮/输入框/菜单行/提示气泡）、`card 14px`、`panel 16px`。
- 原来散落各处的 `rounded-[4px]/[5px]/[6px]/[7px]/[10px]` 全部换成语义 token，
  卡片、按钮、标签、输入框的圆角从此只有一个来源；结构与配色一个没动。

### 变更（2026-10-29 第五十一轮：输入区入口收拢到加号 + 增强提示词）

**1. 「文档类型」不再是独立入口，收进加号菜单**

- 加号菜单新增分组「产物格式」：四项（docx / pdf / xlsx / txt）各带类型图标、
  当前项打勾、与首个素材同格式的那项标「同素材」。选中即写入 `outputFormat` 并收起菜单，
  走的是和「添加文件 / 审计用量」完全一致的菜单项路径（同样的行高、hover、图标尺寸）。
- 底部工具栏删除独立的产物格式下拉（`aria-label="产物格式"` 的那颗胶囊不再存在），
  工具栏从「+ / 格式 / 审批 / 技能」变成「+ / 审批 / 技能」，入口不再重复。

**2. 审批策略也进菜单，但加号右边保留一颗胶囊**

- 菜单新增分组「审批策略」：三项各带一句说明（始终询问 / 按需确认 / 全部允许），当前项打勾。
- 加号右侧保留紧凑胶囊并**紧贴加号**：这是安全设置，用户需要一眼看到「Agent 现在能自己
  干到什么程度」，完全藏进菜单会让人不敢发任务。两处读写同一份 `approvalMode`，不会各说各话。
- 菜单加了 `max-h` + 滚动，小屏展开不会被窗口边缘截断。

**3. 新增「增强提示词」**

- 后端 `POST /api/v1/prompts/enhance`：把一句需求补成「任务 / 输出格式 / 篇幅 / 要求」，
  真实模型改写时保留原意、不新增事实；**没配模型 / 超时 / 模型回了废稿**时退回本地规则版，
  并在 `source`（model | rules）与 `note` 里说清来源——按钮不能变成报错入口。
- 前端输入区右侧星形按钮：hover 提示「增强提示词」、请求中显示环形进度并置 `aria-busy`、
  空输入把焦点送回输入框、失败保留原文并说明原因、成功后替换文本并聚焦。
- 提示条新增 `tone`：成功用品牌色 info，不再复用警告黄（「已增强」画成警告色会让人以为出错）。
- 校验：`text` 1–4000 字（全空白 400、超长 400），`output_format` 只作改写提示，不改变产物。

**4. 测试与契约**

- 后端 +24 条（增强器单元 16：清洗/规则/两种来源/失败降级；接口语义 8：空白/超长/坏 JSON/多余字段），
  全量 `1324 passed / 42 skipped`。
- 前端 +10 条（菜单 5：选项/切换/同素材/审批/独立入口已移除；增强 5：空输入/成功/规则兜底/失败/加载态），
  全量 `1171 passed`；tsc / eslint / prettier 干净。
- `contracts/openapi.v1.json` 与 `frontend/src/shared/api/generated/schema.d.ts` 重新生成
  （54 条路径 / 66 个操作）。

**5. 涉及文件**

- 后端：`api/v1/prompts.py`（新）、`services/prompt_enhancer.py`（新）、
  `api/v1/router.py`、`api/v1/schemas.py`、`tests/unit/test_prompt_enhancer.py`（新）、
  `tests/api/test_semantics_prompts.py`（新）。
- 前端：`features/workbench/components/Composer.tsx`（菜单重写 + 增强按钮）、
  `features/workbench/api/prompts.ts`（新）、`components/Composer.test.tsx`、
  `components/EmptyState.tsx`（文案改成「在输入框左侧的 + 里改选」）。
- 契约：`contracts/openapi.v1.json`、`frontend/src/shared/api/generated/schema.d.ts`。

### 变更（2026-10-28 第五十轮：交付形态改成单文件 exe）

**1. 别再发 248 MB 的整仓 zip：改成 37 MB 的单文件 exe**

- 新增 `make exe`（`packaging/office_agent.spec`，PyInstaller `--onefile`），
  产物 `dist/Office Agent.exe`：双击即用，**对方不用装 Python，也不用装 Node**。
- 体积对比：整仓 zip **248.6 MB**（里面躺着 310 MB 的 `frontend/node_modules` 和 199 MB 的 `.venv`）
  → exe **36.6 MB**（只带运行时真正 import 到的依赖 + 1 MB 的前端构建产物）。
- 不加 UPX：省不了多少体积，反而常见杀软误报。

**2. 打包安全：资源根与数据根拆开（核心改动）**

- 新增 `backend/app/core/paths.py`：`RESOURCE_ROOT`（只读资源：前端 dist、提示词、技能库、
  迁移脚本）与 `DATA_ROOT`（可写数据：SQLite、上传、产物、模板、`.env`）。
  源码态两者都是仓库根（行为不变）；打包态资源根 = exe 解压目录，数据根 =
  `%LOCALAPPDATA%\Office Agent`（`OA_DATA_DIR` / `--data-dir` 可覆盖）。
- 不拆的后果很隐蔽：`--onefile` 每次启动解压、退出即删，数据写进去就是
  「今天用得好好的，明天打开全没了」，而且没有任何报错。
- 连带调整：`config.resolve_path`（资源）/ `resolve_data_path`（数据）分工，
  `build_database_url`、`uploads/artifacts/trash/templates/feedback`、`.env` 落数据根；
  `Settings.frontend_dist_path` 仍走资源根。`project_service.project_root`、
  `ModelService.workdir()` 跟数据根走；打包态跳过 `git rev-parse`（少 fork 一个进程）。

**3. 打包入口 `scripts/app_entry.py`**

- 与 `scripts/launch.py` 分工明确：后者给「拿到源码的人」（建 venv / 装依赖 / 构建前端），
  前者给「只拿到一个 exe 的人」——只做：备好数据目录与 `.env`、挑空闲端口、
  等服务真能访问了再开浏览器、起服务。
- 参数：`--port` / `--no-browser` / `--data-dir` / `--show-data-dir`；
  已在运行时不再起第二个进程（与启动脚本一致）。

**4. 测试与文档**

- 新增 `backend/tests/unit/test_paths.py` 8 条，把「打包态数据根 ≠ 解压目录」钉成测试
  （含 `OA_DATA_DIR` 覆盖、Settings 各路径归属、入口首次复制 `.env` 且第二次不覆盖）。
- README 新增「给别人一台电脑用：打包成一个 exe」小节与 `make exe` 命令表；
  Makefile 新增 `exe` 目标（前端未构建时先构建，缺 PyInstaller 时自动装）。
- 后端全量：`1300 passed / 42 skipped`（新增 8 条）；ruff check + format 通过。

**5. 顺手修一条时红时绿的用例**

- `test_pin_moves_thread_to_top` 原断言「取消置顶后它就不在第一」：排序是
  `pinned DESC, updated_at DESC, id DESC`，而 `updated_at` 只到秒、`id` 是随机 uuid——
  同一秒内的先后由随机 id 决定，于是全量跑三次里红了两次。
- 改成确定性写法：另建一条会话，跨秒后再更新它（时间戳严格更晚），断言这条排第一、
  被取消置顶的那条仍在列表里。连跑三次全绿。

### 变更（2026-10-28 第四十九轮：收尾答复收成一张结论卡）

**1. 收尾答复有了硬约束，不再「把过程也写一遍」**

- `real_engine.py` 新增 `REPLY_RULES`，作为系统消息的**最后一段**下发（越贴近生成位置越管用）：
  固定「结论 / 依据 / 下一步」三段、全文约 120 字、依据最多 3 条且每条 ≤25 字。
- 明令禁止：复述素材内容与原文、列读过哪些文件、报字数/耗时/步骤数/token、
  解释自己的思路、写「我不能编造」这类自我说明、列 1/2/3 多选菜单。
- 附一条合格示例；`system.md` 同步到同一套说法（v1.4.0 → v1.5.0），避免两处口径不一致。
- 实测（真实 deepseek，素材与需求不匹配的会议纪要任务）：**194 字 → 119 字**，
  原文摘抄与"本轮已生成…"的自我总结都消失了。

**2. 兜底补生成不再与结论互相打脸**

- 模型已明确说「无法 / 做不了 / 缺少要素」时，内核不再补 `doc.generate_report`：
  结论说「本轮没有产出文件」、下面又冒出一份文件，用户只会觉得前面那段是白说的。
  新增 `MODEL_REFUSAL_MARKERS` 与 `_model_refused()`，跳过时记 `kernel_fallback_skipped_refused`。
- 兜底说明改成先补生成、再说话，于是能带上文件名，且只讲结果：
  「已补生成《观秋_会议纪要.docx》，可在产物中心下载。」——原来那句
  「模型未产出文档，内核按任务要求自动补生成 TXT 产物」是运行日志，不该出现在结论区。

**3. 测试**

- `tests/unit/test_real_engine.py` 增 6 条：约束排在系统消息末尾、约束含硬指标、
  `system.md` 与本约束口径一致且版本为 1.5.0、兜底说明只说结果并带文件名、
  模型拒绝时不再补生成。

### 变更（2026-10-28 第四十八轮：2461 条用例的接口测试矩阵）

**1. 新增后端接口矩阵 `backend/tests/api/`（977 条）**

- 覆盖运行时 OpenAPI 的 53 条路径 / 65 个操作，分四层：
  协议层（310，路由/错误体/trace/坏输入/方法不允许）、
  语义层（191，会话·上传·运行·审批·产物·设置·模型·模板·技能·存储·项目）、
  模糊层（476，畸形 id / body / query，只断言不 5xx）。
- 进程内 `TestClient`，单条 3–5ms；一份 session 级种子（8 轮真实 mock 运行产出的产物）。
- 安全阀：技能目录复制到临时区并在收尾比对仓库目录；会拉起系统窗口或写 `.env`
  的端点标记为 `ext`，只打错误路径。
- 新增接口只需在 `tests/api/matrix.py` 的 `OPS` 加一行，四组用例自动派生。

**2. 前端补 HTTP 错误矩阵 `src/shared/lib/api.matrix.test.ts`（80 条）**

- 状态码 × 响应体形态的笛卡尔积：9 个 4xx × 5 种 body、4 个 5xx × 5 种 body，
  外加取值优先级（标准体 / detail / HTML / 空体）、2xx 边界、连通性广播、请求构造。

**3. 矩阵跑出来后修掉的缺陷**

- **坏 JSON 请求体 500 → 400**：`RequestValidationError.errors()` 的 `input` 是原始 bytes，
  直接塞进 JSONResponse 会 `TypeError`，于是「格式写错」被报成「服务内部错误」。
  新增 `_jsonable()` 做安全转换。
- **全空白「技能想法」不再生成垃圾技能**：`idea` 入口 `strip()` 后为空直接 400。
- **项目文件列表补上 `.md`**：接口描述一直写着支持 md，实现里漏了。

### 变更（2026-10-28 第四十七轮：全站底色收成一层 + 桌面端顶部不再空一条）

**1. 页面之间不再「换一层底色」**

- `--color-shell` 与 `--color-canvas` 同值（深色 `#101317` / 浅色 `#f3f5f9`）：
  工作台外壳、子页面底色、窗口最外沿是同一个色，从工作台切到审计/设置时整扇窗口不变色。
- 子页面顶栏（`PageShell` / `PlaceholderPage` / `ProjectPage`）从 `bg-surface`
  改回 `bg-canvas`：标题栏区 → 顶栏 → 内容区连成一片，只剩一条 1px 描边分隔。
  上一版顶栏比页面亮一档，最大化窗口里会看到「顶部一条亮带 + 下面更暗」的拼接感。
- `theme-color`（PWA 标题栏/状态栏、`manifest.theme_color`）统一改成页面底色。
  它以前是更深的壳色，装上桌面端后屏幕上沿会多出一条「另一套配色」的横带。
- 面板层级不再靠底色深浅，改由 `border-line` + `shadow-panel` 承担。

**2. 桌面端顶部空隙**

- 工作台外壳不再整体下移一个标题栏高度，改成四边同样的 10px；窗口按钮那一条
  交给各面板内部的 `.window-inset-top`（`max(--titlebar-h - 10px, 0)`）。
  面板因此**贴到窗口顶沿**，标题栏下面那条空档消失，而面板里的按钮/标题
  仍落在 — □ ✕ 下沿之下（网页态 `--titlebar-h` 为 0，规则自动失效）。
- 左栏顶部内边距 `pt-2.5 → pt-2`；`ProjectPage` / `PlaceholderPage` 补上标题栏让位
  （这两页原来没有，桌面端里顶栏按钮会钻到窗口按钮底下）。

**3. 顺手修掉的回归**

- 供应商显示名只对 deepseek 改成 `deepseek harness`；qwen / glm / openai 恢复
  「通义千问 / 智谱 GLM / OpenAI」（上一轮误把所有显示名都压成了小写标识，
  「去充值」菜单也跟着变成 `qwen`，e2e 里 `/DeepSeek/` 断言因此失败）。

### 变更（2026-10-28 第四十六轮：让模型替你写技能 + 新增 WorkBuddy 供应商）

**1. 导入技能多一条「说一句就让模型写」的捷径**

- 新增 `POST /api/v1/skills/draft`：`{idea}` → 一份**可直接导入**的 SKILL.md
  （`markdown/name/title/description/triggers/model/source/note`）。接口不落盘，
  前端把它当本地文件走既有的 `/skills/import`，所以「模型写的」和「手写的」是同一条入库路径。
- 后端 `services/skill_drafter.py` 负责脏活：剥掉 ``` 围栏、按 `key: value` 解析 frontmatter、
  补齐 `name/title/description/triggers`、过滤非法的 `category/icon`、同名自动加 `-2` 后缀、
  正文压在 8000 字内。模型没配上（演示模式 / 无 Key / 调用失败 / 返回空）时降级成本地骨架
  （`source=local` + 一句人话说明），不让入口整块消失。
- 「做一个自己的技能」弹窗顶部加一块蓝色捷径：一句话输入 + 「让模型写一张」→ 就地预览
  （标题、生成模型、正文、建议）→「就用这张」才写盘。原来的三步流程原样保留。

**2. 新增 WorkBuddy 模型供应商（接口地址由用户自带）**

- `workbuddy` 进 `PROVIDER_FACTORIES` / `DEFAULT_MODELS`（占位 `workbuddy-chat`）/
  `API_KEY_ENV`（`WORKBUDDY_API_KEY`）/ `_KNOWN_PROVIDERS`，字段 `workbuddy_api_key`、
  `workbuddy_base_url` 同步进 `.env.example`。
- **故意不写默认 Base URL**：接口地址按账号给，写死一个猜来的域名只会让「测试连接」永远失败。
  `PROVIDER_DEFAULTS["workbuddy"] = ""`，且 `provider_base_url()` 不再把未知供应商回落到 OpenAI。
- 模型列表新增「接口」一栏：显示当前地址，空着就写「接口地址待填」并给「填接口」；
  新增 `EndpointModal`（地址只收 http(s) 绝对地址、可改模型名、保存走已有的 `POST /models`）。
  地址没填时点「添加 Key」会先看到黄色提醒，而不是保存后吃一个 400。
- 缺地址时的 `POST /models/{id}/test` 返回 `ok=false` +「还没填接口地址…」，不抛 400；
  `configured` 同时要求 Key 与地址，`real_model_configured` 也补上地址判断。

**3. 修掉「改完地址要重启才生效」**

- provider 实例构造时把 base_url 拍成快照并缓存。新增 `ModelRouter.reset_providers()`，
  `SettingsService._apply()`（设置保存、启动时套用 DB 覆盖都会走）末尾调用它，
  同时清空探测缓存与熔断状态——它们描述的是旧地址的健康状况。

**4. 供应商显示名**

- 界面统一走 `providerLabel()`：`deepseek` 显示为 **deepseek harness**（标识与配置键不变），
  WorkBuddy 显示为 `WorkBuddy`。`PROVIDER_CONSOLES`（「去充值」菜单的数据源）不收录 WorkBuddy
  ——它没有可跳的开放平台页，`KeyRefModal` 改为显示「Key 由你的账号提供」。

**契约与测试**

- `contracts/openapi.v1.json` 重导（**53 路径 / 65 操作**），`schema.d.ts` 重生成；
  `docs/api.md` 补 `/skills/draft` 与 WorkBuddy 段落。
- 新增 `tests/unit/test_skill_drafter.py`（10 条，含「模型输出必须能被真实 import 落盘」）、
  `tests/integration/test_skills_draft_api.py`（4 条）、`test_model_router.py` 的缓存刷新回归；
  前端新增 `ModelListCard.test.tsx` / `EndpointModal.test.tsx` 与 `SkillImportGuide` 的草稿用例。

### 修复（2026-10-28 第四十五轮：桌面端右上角被 — □ ✕ 压住）

- **根因一（让位失效）**：`applyTitlebarInset()` 量不到高度时写死内联 `--titlebar-h: 0px`。
  内联样式优先级高于样式表，把 tokens.css 里 `env(titlebar-area-height)` 的兜底永久压住；
  而个别 Chromium 在 overlay 刚生效时 `getTitlebarAreaRect().height` 正是 0。
  现在改成：量到正数才写内联，量不到就删掉属性，交给 CSS 的 `env()`。
  同时 `--titlebar-h` 的默认值从 `0px` 换成 `env(titlebar-area-height, 0px)`——
  JS 只负责「量得更准」，不再是唯一来源；overlay 模式下再兜一层 `max(…, 32px)`。
- **根因二（浮层没让位）**：右栏抽屉 / 弹窗 / 审计弹窗都是 `fixed inset-0`，坐标相对窗口
  而不是外壳，于是面板顶边和「本次会话」一行直接钻到窗口按钮底下（窄窗口最明显）。
  三处容器都加上 `padding-top: calc(var(--titlebar-h) + 原有内边距)`；遮罩背景仍铺满整屏。
- 回归：单测锁「量到 0 时必须清掉内联变量」；e2e 锁窄窗口抽屉与弹窗的顶部位置。

### 变更（2026-10-28 第四十四轮：服务断开时界面自己说清楚）

- **背景**：用户关掉黑窗口后发现桌面端还能用，以为两者独立。真实原因是当时还有另一个
  `launch.py --no-browser` 进程在跑（12:22:56 起）。桌面图标只是浏览器窗口，服务一停，
  任何请求都失败，但界面只会弹一句「无法连接后端」，看起来像 bug。
- 新增 `shared/lib/backend-status.ts`：HTTP 层被动上报在线/离线（收到任何响应就算在线，
  fetch 直接失败才算离线；**超时和主动取消都不上报**——长任务慢不等于服务没开）。
- 新增 `ServiceDownBanner`（挂在 `App` 里、全站生效）：顶部一条提示「本机服务已断开，
  这个窗口暂时用不了 / 桌面图标只是个窗口，真正干活的服务要在后台跑 / 双击
  `启动 Office Agent.cmd`，等出现「启动完成，可以用了」再点重试」，带「重试」按钮
  （`GET /health` 确认恢复后自动消失，不用刷新）。只占顶部一条，不遮住已加载的内容。

### 文档（2026-10-28 第四十三轮：说清「黑窗口能不能关」）

- README「双击启动」补一张对照表：窗口写「启动完成，可以用了」= 服务本体，关掉等于退出程序；
  写「已经在运行，不用再开一个」= 只是探测窗口，关掉无影响。
- 点明桌面图标（含安装出来的窗口）是浏览器窗口，指向 `http://127.0.0.1:8000`、不含服务端：
  服务停了它就是「无法访问此网站」，重启电脑后需要重新双击一次启动器。

### 变更（2026-10-28 第四十二轮：双击真的能启动——修掉「点了没反应」）

- **根因**：上一轮的 `.cmd` 靠 `where py` / `where python` 找 Python。这台电脑没有 `py`
  启动器，`where python` 命中的是 Microsoft Store 的转发存根
  （`python.exe → AppInstallerPythonRedirector.exe`）：它不打印任何东西、直接返回 9009，
  于是批处理只剩 `pause` 的「Press any key to continue . . .」——看起来就是双击没反应。
- **修法**：按「不依赖 PATH」的顺序找，每个候选都要真能 `import sys` 才算数：
  项目自带 `.venv\Scripts\python.exe` → `py -3` → PATH 里的 `python`（`find /i "WindowsApps"`
  跳过商店存根）→ `%LocalAppData%\Programs\Python`、`%ProgramFiles%`、`%ProgramFiles(x86)%`
  下的 `Python3*`。找不到才提示装 Python，并按任意键才关窗口。
- **中文提示不再塞进批处理**：改成 `scripts/messages/{no-python,crashed,no-launcher}.txt`
  （UTF-8 无 BOM），批处理用 `type` 打印、`pause >nul` 静音等待。批处理保持纯 ASCII
  （cmd.exe 按字节读文件，混中文会把下一行读坏），文案改动不用碰脚本。
- **地址一定看得见**：启动完成后打印「浏览器地址：http://127.0.0.1:端口」，并把同一个地址
  写进窗口标题栏（`SetConsoleTitleW`）；端口被占自动往后换时，显示的是**实际用的**端口。
  「已经在运行」也走同一条提示，不再一闪而过。
- **不再闪退**：`die()` 与未捕获异常都会打印原因、等按键，并以退出码 2 告诉批处理
  「已经等过」，避免连按两次。
- 顺带：`.command` 也优先用 `.venv/bin/python`；新增 `test_launcher_scripts.py` 11 条
  （ASCII / CRLF / LF / 查找顺序 / 跳过商店存根 / 提示文件编码 / `die()` 返回码与等待）。

### 变更（2026-10-27 第四十一轮：一键启动 + 单端口托管）

- **双击就能用**：仓库根新增「启动 Office Agent.cmd」（Windows）与「启动 Office Agent.command」
  （macOS），逻辑都在 `scripts/launch.py`。依次做四件事：查 Python 版本 → 备 `.venv` →
  装依赖（已装则跳过）→ 确认 `frontend/dist`（没有就用 npm 构建一次）→ 起服务、等真能访问再开浏览器。
  失败时给「哪一步、为什么、怎么办」，不是黑框一闪。
- **单端口托管**：新增 `core/static_site.py` 与 `SERVE_FRONTEND` 开关（默认关闭）。打开后由 FastAPI
  直接端出 `frontend/dist`，用户只访问 `127.0.0.1:8000`，**不需要 Node、不需要开两个终端**。
  规则：`/assets` 走 StaticFiles（带 ETag）；其它 GET 先找同名文件、找不到回 `index.html`
  （BrowserRouter 刷新 `/settings` 不 404）；`/api/*` 一律不接管（未知接口仍是 JSON 404）；
  解析后必须仍在 dist 内（`/../.env` 只会拿到首页）；入口 HTML `no-cache`。
- **端口冲突自己处理**：占用时自动往后找（最多 20 个）；已经在跑就直接开浏览器，不起第二个进程。
- **`--check` 体检**：`python scripts/launch.py --check` 逐项报告 Python / 依赖 / 界面产物 / Node / 端口，
  不启动服务——排错时不用猜。`make start` 与 README「只想用、不改代码」一节同步补上。
- 契约不变：静态路由 `include_in_schema=False`，`contracts/openapi.v1.json` 保持 52 路径 / 64 操作。
- 测试：`test_frontend_static.py` 6 条（根路径给界面、子路由不 404、静态文件与 ETag、接口不被兜底吞掉、
  目录穿越拿不到仓库文件、不开开关时根路径仍是 JSON）。

### 变更（2026-10-27 第四十轮：导入技能说人话、独立窗口标题栏融进外壳、设置页意见反馈）

- **「导入技能」改成照着做就行的三步**：原来的引导上来就是 `title / description / triggers /
  category / icon` 五个字段的含义，用户得先懂 frontmatter 才能动手。现在用「一张便签」的比喻开头，
  第 2 步直接给一份带高亮与旁注的示例文件（只标三处要改的行、外加「怎么做」的步骤），
  `category / icon` 收进「进阶（可以不看）」折叠区；主按钮「选文件导入」跟着第 3 步走，
  不再藏在底部工具条里。弹窗从 380px 加宽到 520px（`Modal size="md"`），正文超过窗口高度时自己滚，
  标题与底部按钮始终在。
- **输入框的技能弹层不再直接弹系统文件框**：和三处入口统一走同一个引导（`onImportGuide`），
  弹层自己先收起再开引导，避免两个浮层叠着。文案也从「导入 SKILL.md」改成「导入技能」。
- **独立窗口的标题栏融进外壳**：以 `standalone` 打开时，浏览器会画一条自己的标题栏（图标 + 名字 +
  窗口按钮），它在外壳的卡片面板之外、配色也不归界面管，看着像「网页被塞进了套子」。
  现在 manifest 声明 `display_override: ["window-controls-overlay", "standalone"]`，
  由 `shared/lib/titlebar.ts` 量出 `env` 之外的真实标题栏高度写进 `--titlebar-h`
  （监听 `geometrychange`，拖到另一块屏/改缩放会跟着变），工作台与 `PageShell` 的 `padding-top`
  吃这个变量，外壳底色一路铺到窗口最上沿，窗口按钮直接浮在壳色上；顶上补一条
  `.titlebar-drag-band`（`app-region: drag`）保住拖窗口。网页态变量是 0，布局与之前完全一致；
  不支持 overlay 的浏览器回落 `standalone`，老版本 Chromium 由
  `@media (display-mode: window-controls-overlay)` + `env(titlebar-area-height)` 兜底。
  `isStandalone()` 同时认 overlay 模式，装好的人不会再看到「安装桌面端」。
- **设置 → 关于 → 意见反馈**（新接口 `POST /api/v1/feedback`）：写一段话 + 选类型（遇到问题 /
  想要新功能 / 其他）+ 可选联系方式，勾选是否附带版本、引擎、窗口形态等环境信息（不含文档内容）。
  后端**不发信、不联网**：先写一条本机存档 `data/feedback/feedback.jsonl`，再把标题与正文拼成
  `mailto:` 链接交给系统邮件程序；开发者邮箱用 `FEEDBACK_EMAIL` 配置（默认留空 = 只存档，
  界面退化成「复制内容自己发」）。正文编码后超过 1900 字符会自动收短并置 `truncated=true`
  （存档里保留全文），避免邮件程序悄悄截断半句话。
- 契约：`contracts/openapi.v1.json` 重导（52 路径 / 64 操作），`schema.d.ts` 重生成。
- 测试：`titlebar` 单测 6 条（高度边界 / 封顶 / geometrychange / 无能力时不写内联变量）、
  `FeedbackCard` 5 条（空内容禁用 / 类型与内容透传 / 勾掉环境信息 / 复制到剪贴板 / 后端报错可见）、
  `test_feedback_service.py` 9 条 + `test_feedback_api.py` 3 条（存档、mailto 编码、超长收短、
  空内容拒绝、多条追加）；e2e 把「不声明 WCO」改成「声明 WCO 就必须自己让位」（断言
  `--titlebar-h` 与 `padding-top` 联动、拖拽区 `app-region: drag`），技能弹层用例改走引导弹窗。
  前端 1062 条单测、后端 332 条、e2e 35 条全绿。

### 变更（2026-10-26 第二十八轮：比赛版 UI 基础层——AI 语义令牌、Toast、焦点管理）

按 `competition-ui-style-plan-2026-10-25.md` 的提示词 1 落地，只动基础层，不改业务功能。

- **AI / 工具语义令牌**：新增 `--color-ai`（AI 产出：回复/思考/推荐）与 `--color-tool`（工具调用这类中性过程）
  两族（含 soft / line，深色各一套），分别对齐 brand 与 accent，保持「一个主强调 + 一个副强调」。
  顺手补了 `--color-accent-line`，把 Badge 紫色描边写死的 `#ddd6fe` 收进令牌（深色下不再是一圈突兀亮紫）。
- **动效常量**：`:root` 新增 `--dur-feedback`(160ms) / `--dur-enter`(220ms) / `--ease-out`，
  `.rise-in`、`.card-lift`、`.composer-glow` 里写死的时长全部改走变量。
- **prefers-reduced-motion**：末尾统一的 media 块把两个时长压到 1ms、循环动画停掉（caret / shimmer）、
  卡片悬浮位移取消——系统开了「减少动态效果」，全站动效一次关闭，不用逐个组件改。实测 `--dur-feedback`
  在 reduced 下由 160ms 变 1ms。
- **Toast 轻提示**（新增 `shared/ui/Toast.tsx` + `toast-context.ts`）：portal + fixed 挂 body、容器常驻
  （aria-live 区域必须先在 DOM 里，读屏才会播报）、危险提示用 `role=alert`、默认 3.2s 自动消失、
  同屏最多 3 条、卸载清计时器；没有 Provider 时 `useToast()` 静默降级，单独渲染组件不会崩。
  宿主挂在 `app/providers.tsx`，首个真实用法是「复制会话标题」——以前点了完全没反馈，现在成功/被拒都有提示。
- **Modal 升级为 Dialog 语义**：打开时焦点进弹窗容器（不是头部「关闭」，否则念不出标题、回车易误关），
  Tab / Shift+Tab 在弹窗内循环不外泄，关闭后焦点还给触发元素。不再另造一个 Dialog 组件。
- **图标**：补 `IconMic`（语音输入）、`IconVolume`（朗读）、`IconOptions`（多方案），共 54 个。
- 测试：Toast 8 条（aria-live 常驻 / 自动消失 / duration=0 常驻 / alert 语义 / 最多 3 条 / 卸载清计时器 /
  无 Provider 降级）、Modal 焦点 2 条、e2e 新增「复制标题弹轻提示」。

### 变更（2026-10-25 第二十七轮：产物中心只留产物、默认深色背景、导航提示缩短）

- **产物中心只列产物，不再混上传素材**：以前上传的 `cet4成绩.pdf` 和生成的 `cet4成绩.pdf` 并排躺在同一页，
  名字一模一样却一个是原料一个是成品，用户根本分不清。现在 `GET /artifacts`（含 `/artifacts/trash`）
  默认排除 `type=upload`，要连素材一起看带 `include_uploads=true`（或直接 `type=upload`，工作台取素材走的就是这条）。
  过滤下推到 SQL（`type != 'upload'`），总数与分页一起准，不是前端筛完再凑数；类型下拉也去掉「上传文件」。
- **默认深色背景**：以前没存过偏好时跟随系统，系统浅色就整个白底。现在没存过偏好一律按深色起步
  （顶栏/设置页改过就听本地的）。`index.html` 里加了一段首屏前执行的脚本 + 底色样式，
  先把 `html.dark` 与 `#141416` 定下来，避免 JS/CSS 到位前白闪一下；`html` 也铺了 `--color-canvas`，
  拖到顶/底的越界回弹不再漏白；`color-scheme` 改成 `dark light`，滚动条等原生控件跟着主题走。
- **「插件与技能」导航提示缩短**：从 24 字的长句收到「查看插件、添加技能」——
  气泡宽度只有 300px、超了会截断，条目本身已经写着「插件与技能」，没必要再复述一遍。
- 测试：后端 302 通过 / 1 跳过（新增 1 条：素材默认不进产物列表、`include_uploads` 与 `type=upload` 仍可查、
  回收站同口径）；前端 60 条产物用例（新增类型下拉无「上传文件」）；契约重导至 51 路径 / 63 操作。

### 变更（2026-10-25 第二十六轮：会话批量清理、输入框光晕、导航提示文案）

- **左栏「最近会话」支持批量清理**：标题行多了常驻的垃圾桶图标（不藏 hover——26 个会话逐个点 ⋮ 删太累），
  点进去进**选择模式**：整行变复选框、行首显示勾选态，标题行变成「已选 N / 本页 M」，
  底部出现「删除选中（N）」+「全选本页」+「选中全部 N 个」。
  选中集合**跨页保留**，所以「整个清理」是一次性的事：全选本页 → 翻页再全选 → 一次提交。
  删除必须点两次（第一次只把按钮变成「确认删除 N 个」并加红环），Esc 退出选择模式；
  选择模式下 Ctrl+D 不再删当前会话（「删的」和「选的」会打架）。
- **新增 `POST /threads/bulk-delete`**：`thread_ids`（1–200 个）→ `{deleted}`。
  仓储层一条 `UPDATE ... WHERE id IN (...)` 搞定，不逐条 `get`；不存在/已删的 ID 忽略不报错（重复调用幂等），
  空数组 400。逐个 DELETE 要发 N 次、中途失败会留下半删状态，所以走批量接口。
  前端按 200 个一批切块，「选中全部」按 100/页（后端分页上限）翻完全部页取 ID，最多 20 页防死循环。
- **输入框外缘光晕加强**：以前 hover 只是描边从 `line-strong` 变 `brand-line`（两个浅灰蓝，差一眼看不出来）。
  现在抽成 `.composer-glow`：hover 时描边用品牌色 + 4px 柔光环 + 外发光，聚焦时再加一档（5px / 26%）；
  用 `color-mix` 取品牌色透明度，深色主题同样成立。
- **「插件与技能」导航提示重写**：原来是「插件（工具能力）与技能（做法包），内置规范包一览」——
  两个括号夹名词、结尾一个「一览」，读着别扭也不说能干什么。改成「查看已启用的插件、添加技能，内置规范包也在这里」。
- 测试：后端 301 通过 / 1 跳过（新增批量删除 2 条：混合不存在 ID 只计真正删掉的、空数组 400）；
  前端 932 通过 / 42 文件（`SessionList` 新增 4 条：选择模式、全选本页 + 二次确认、跨页全选、空选禁用与 Esc 退出）；
  Playwright 22 条、tsc / eslint / prettier / ruff 干净；契约重导至 51 路径 / 63 操作。

### 变更（2026-10-25 第二十五轮：脚本真接进主链路、文档不再编造、右栏换成「本次素材」）

这一轮全部来自评审截图：**说的要和做的一致**。之前「接了 Python 脚本」只停在嘴上——思考过程里说要读素材，
成文时却套固定模板，产出里塞「完成了本周既定任务的梳理与交付」这种素材里没有的句子。现在按四件事改到位：

- **新增真跑脚本的工具 `doc.analyze_material`**（`backend/app/tools/builtin/analyze.py`，risk=low，只读不进审批规则）：
  起 `sys.executable -c` 子进程，用 python-docx / openpyxl / pypdf 读素材本体，返回**段落数、正文字数、
  标题层级、内嵌图片、表格、图注**与周报信号（`本周/进展/下周/计划` 是否出现在全文）；环境变量走白名单、
  带超时与输出截断，用 `OA_JSON:` 前缀回传。摘要会如实念数：「python 脚本解析完成：1 份素材 / 正文 7 段 / 246 字」。
- **mock 主链路真的调用了它**：`thinking(方法) → message → file.list → file.read → doc.analyze_material →
  thinking(为什么用这个模板) → brief → plan → 审批 → doc.generate_report → artifact.ready`。
  结构体检结果经 `ToolContext.material_facts` 传给成文工具（不塞进事件入参，避免工具卡体积爆炸）。
- **模板按素材自适应**：命中周报信号（含「本周/进展/下周/计划」）才用 `weekly`；否则落到 **`summary`「素材摘要」模板**
  （摘要 / 要点 / 素材构成 / 来源引用）。随笔类素材现在生成的是「素材摘要」，不会再顶着一个「工作周报」的壳子。
- **成文不再编造**：删掉 `doc.py` 里所有凑数句，素材里没有就直说「素材里没有『本周进展』这类内容，建议补充工作记录后再生成周报」；
  「关键数据」章节写的是脚本量出来的真实结构（份数/段数/字数/图片/表格/图注）；图注行（`图1 …` / `照片《…》`）不再混进要点与引用；
  摘要句先去标点再做子串去重，不会同一句念两遍。实测随笔素材产出 5 个章节 100% 来自原文或脚本统计。
- **右栏删掉「本次运行」，换成「本次素材」**：耗时 / tokens / 花费 / 模型那块没人看（`RunDockStatus` / `LastRunInfo` /
  `toLastRun` 整套 dead code 一并删除）。现在底部固定本轮素材列表（文件名 + 字数 + 解析状态），标题右侧是合计字数。
  `selectMaterials(state)` 优先读输入区的 uploads，消息发出后回落到时间线里最近一条 `file.list` 的输出；
  `GET /threads/{id}` 追加 **`uploads`** 字段（只追加不改语义），切回历史会话也能直接恢复素材列表。
- **技能页排版对齐插件页**：删掉精选大卡、分类小标题那一整套特殊结构，两个 tab 共用同一节奏——
  一行「标题 + 数量 + 右侧统计」+ 一片 `auto-fill minmax(340px,1fr)` 网格，条目一律「图标 + 标题 + 两行说明 + 右侧动作」。
  带角标的技能也直接平铺在列表里，不再另占一块。
- 顺带：删掉临时截图脚本 `frontend/e2e/tmp-shot.spec.ts` 与一次性素材 `data/走观秋.docx`；
  `docs/api.md` 的 paths/ops 计数从写死的 32/40 修到实际的 **50 / 62**，并补 tools 清单与 `uploads` 示例。
- 契约与测试：`contracts/openapi.v1.json` 重导 + `schema.d.ts` 重生成；新增 `analyze` 工具单测（只读不审批、图注过滤、
  脚本统计进「关键数据」、summary 模板用原文不用默认值）、集成测试（随笔素材先 analyze 再 generate、产物不得出现「本周进展」/
  「关键数据」章节、必须出现原文词、不得出现旧编造句）、`selectors` 3 条、`SkillsPage` / `RightPanel` / e2e 断言改写。
  后端 299 通过 / 1 跳过，前端 925 通过 / 42 文件，Playwright 22 条全过，ruff / tsc / eslint / prettier 干净。

### 变更（2026-10-25 第二十四轮：技能页升级成「插件与技能」扩展页）

- **一级 tab：插件 / 技能**：导航与页面标题改成「插件与技能」（左栏短标签仍是「技能」）。
  插件 tab 读运行时真实注册的工具（`GET /api/v1/tools`），按前缀归成 5 个能看懂的插件
  （文档生成 / 脚本加工 / 素材读取 / 产物清理 / 任务计划），卡片上直接标工具数与风险等级
  （含高风险工具就写「执行前需确认」）。工具是随应用发布、常驻启用的，所以只读、不放假按钮；
  后端以后加工具，这里自动多出一组，不用改前端。
- **去掉「已添加」整块区域**：技能库和已添加合成一片商店式列表（图标 + 标题 + 两行说明 +
  右侧动作，auto-fill 三列），省下一整块高度。已添加的行就地显示「已添加 ✓」，旁边是
  电源键（启用/停用）与移除（hover 出现，软删，技能库里随时能加回来）。
- **添加按钮自己说结果**：点「添加」后按钮就地变「已添加」，计数与系统提示词字数同步刷新，
  不再靠页头横幅确认。
- **内置规范包入口上移到工具条**（搜索框右侧的「内置规范包 7」按钮）：之前缩在列表最末尾，
  用户根本注意不到；点开仍是弹窗阅读器（左目录 / 右正文）。
- **精选位不再和列表重复**：带角标的两位占精选卡，列表里自动去掉这两条；一筛选就都回到列表。
- **切 tab 清空筛选**：两个 tab 的分类与搜索对象不同，切过去自动回到「全部」+ 空关键词。
- **右栏产物空态删掉「可以先让我做这些」三条示例**：那是输入框的活儿，放在产物栏里既占高度
  又抢注意力；现在只留图标 + 一句说明。`RightPanel` 的 `onUseSuggestion` 入参一并移除。
- 顺带：
  - 新增 `IconPuzzle` / `IconPower`（图标清单断言 49 → 51）；
  - 修掉一条脆断言：`test_api` 原本要求 `skills[0] == "weekly-report"`，界面上装过任何技能就挂，
    改成「包含 weekly-report 即可」（和上一轮 `test_health` 同类问题）；
  - `skills` 目录被界面测试装进去的 4 份副本已清掉，恢复成只有 `weekly-report`。
- 测试：`SkillsPage` 12 条（两个 tab、添加/启停、搜索与分类、精选不重复、插件分组与搜索、
  规范包入口位置与阅读器）、`RightPanel` 空态改断言；e2e 改 2 条（右栏空态、扩展页 tab 与插件列表）。
  前端 925 通过 / 42 文件，Playwright 22 条全过，后端 293 通过 / 1 跳过，ruff 干净。

### 新增（2026-10-25 第二十三轮：右栏从「产物独占」改成产物 + 本次运行两块）

- **右栏底部固定「本次运行」**：状态徽标（未开始 / 运行中 / 等待审批 / 已完成 / 失败 /
  审批被拒 / 已停止）+ 耗时、用量 tokens、工具调用次数、花费、模型，可折叠。产物列表只吃
  剩余高度——产物再多也不会把整栏占满，产物为 0 时也不至于只剩一片空白。
- **切到历史会话不再显示「未开始」**：选会话时顺带从审计（`/threads/{id}/audit` 的 `runs`）
  还原最近一次运行的用量（`toLastRun`，取 `started_at` 最新的一条），工具调用次数在历史里
  数不出来就显示「—」，不拿 0 冒充。
- **产物空态重做**：垂直居中的一小块（图标 + 一行说明 + 「可以先让我做这些」三条示例），
  点示例直接把文案填进输入框并聚焦、光标落末尾（只填不发，用户还能改）。原来是一行灰字贴在
  顶部、下面空一大片。
- **产物区底部加「查看全部产物 ›」**：右侧只列本次会话，跨会话去产物中心。
- 测试：`RightPanel` 8 条（空态示例回调、历史运行还原、折叠、审计入口）；e2e +1
  （右栏空态示例点了回填、底部「本次运行」常驻）。前端 912 通过 / 42 文件，Playwright 22 条全过。
- 顺带修掉一条脆断言：`test_health` 原本要求 `skills == ["weekly-report"]`，
  技能库装上任何技能后它必挂；改成「包含 weekly-report 即可」。

### 修复（2026-10-25 第二十二轮：规范包改弹窗阅读、PDF 预览不再自动下载、弹窗关闭键靠右）

- **内置规范包从「页面内两列铺开」改成弹窗阅读器**：入口仍是技能列表下面一行小字，点开后是
  左目录 + 右正文（用共享 Markdown 渲染，标题/列表/代码块都正常）。之前 7 段一起铺在页面上，
  一片细碎文字既看不清也把技能列表挤下去；现在页面保持干净。正文开头若与标题同名（`## 同名`）
  会自动去重，避免弹窗里出现两遍大标题。
- **PDF 预览不再自动下载**：`GET /artifacts/{id}/download` 增加 `inline` 参数（默认 false 保持
  「下载」语义），预览 iframe 改走 `?inline=1`，把 `Content-Disposition` 换成 `inline`，
  浏览器才会用内置阅读器打开。顺带在 `download_target` 里按扩展名兜底 Content-Type——
  上传时浏览器给的 `application/octet-stream` 会让 PDF 认不出来。
- **弹窗关闭键推到标题栏最右侧**：`IconButton` 带 tooltip 时会多包一层 span 做气泡锚点，
  `ml-auto` 传在按钮上推不开外层，所以关闭键一直贴在标题后面。新增 `wrapperClassName`
  给这层包装用，Modal 与审计抽屉的关闭键都改成 `wrapperClassName="ml-auto"`（实测距右边缘 15px）。
- 顺带：`Markdown` 组件从 `features/workbench/components` 移到 `shared/ui`，技能页与对话流共用一份。
- 契约与文档：`contracts/openapi.v1.json` 重导（50 路径 / 62 操作，download 多一个 `inline` 查询参数）；
  `docs/api.md` 补下载接口的 `inline=1` 说明。
- 测试：后端 +3（规范包 body 与 chars 一致、inline/attachment 两种 disposition、媒体类型兜底），
  前端规范包 3 条改写成弹窗断言（目录 + 正文 + 切换 + 关闭），PDF 预览断言 `?inline=1`。

### 新增（2026-10-25 第二十一轮：技能页改成技能商店，内置技能库可一键添加）

- **技能页按「技能商店」重排**：搜索框 + 分类筛选（全部 / 办公文档 / 表格数据 / 会议协作 /
  内容写作 / 文件处理）+ 两张精选位（必备精选、新功能推荐）+「已添加」+「技能库」两片网格。
  卡片是圆形分类色块图标 + 名称 + 描述 + 触发词，底部「分类 · 字数」和操作按钮，一屏能扫完。
- **新增内置技能库（后端 `app/skills_catalog/`）**：5 个贴合办公场景的技能——会议纪要、项目复盘、
  数据速览、文档质检、先立提纲；`SKILL.md` frontmatter 增加 `title/category/icon/badge` 四个
  展示字段（缺省回落 name / 空串）。
- **技能库里的技能「添加前不占提示词」**：新增 `GET /api/v1/skills/catalog` 与
  `POST /api/v1/skills/catalog/{skill_id}/install`（复制目录到 `app/skills/` 并默认启用；
  不存在 404、已添加 409）。实测加一个 591 字的技能，提示词从 1360 → 1972 字，不加就一直是 1360。
- **添加/启用/停用都是按钮**；移除技能的二次确认收成 ✓ / ✕ 两个图标（tooltip 说明），
  不再写「删除这个技能？」。输入框技能弹层同步显示展示名（周报写作），便于和技能页对上。
- `backend/app/skills/.trash/`（删除技能时的回收站）加进 `.gitignore`，删技能不再弄脏工作区。
- 契约与文档：`contracts/openapi.v1.json` 重导至 **50 条路径 / 62 个操作**；`docs/api.md` 补两条
  技能库接口与 `/skills` 新字段；`backend/README.md`、`README.md` 扩展点 E4 同步。
- 测试：后端 +3（技能库列表含元信息与 installed 标记 / 安装后进提示词 / 未知与重复安装报错），
  前端 `SkillsPage` 重写为 8 条（分区、分类筛选、搜索、添加、精选位、启停、规范包），
  e2e +1（技能页两片分区 + 搜索空态）。

### 变更（2026-10-25 第二十轮：删除确认去掉红字，只留带提示的图标）

- **会话 ⋮ → 删除、项目 ⋮ → 移除的确认条不再有「删除？」「移除？」红字**：这两个词只是把
  本来就明显的动作又说一遍，还把浮层撑宽、压住会话标题。现在确认态只有 ✓ / ✕（会话）和
  垃圾桶 / ✕（项目），含义由各自的 hover 提示说明（确认删除会话 / 取消删除、确认移除项目 / 取消移除）。
- **顺手修掉一个一直存在的颜色 bug**：`IconButton` 基类写死 `text-muted`，外部再传
  `text-danger` 只是同权重覆盖，最终谁生效看 Tailwind 产出顺序——实测危险图标一直是灰的，
  之前靠红字撑着才没被看出来。现在 `IconButton` 增加 `tone="danger"`，红字去掉后确认键仍然是红的
  （hover 走 `danger-soft` 底色）。
- 测试：会话用例改为断言确认态只有「确认删除会话 / 取消删除」两个图标按钮、没有「删除？」文字；
  Ctrl+D 直接删的用例同步改成断言不出现确认按钮。

### 变更（2026-10-25 第十九轮：顶栏去掉「审计」按钮）

- **顶栏那个「审计」按钮删了**：它跟主题切换、右栏开关挤在右上角，而它要打开的又是「这一次会话
  的审计记录」——本身就是上下文动作，挂在右栏标题的「本次会话」旁边才对。现在顶栏右侧只剩
  主题切换 + 右栏开关两个图标。
- 审计入口收敛为两处：右栏「产物 / 本次会话」旁的小盾牌（未选会话时置灰），以及左栏「更多 ›
  审计用量」（跨会话的总览页）。
- `StatusBar` 随之去掉 `auditEnabled` / `canAudit` / `onOpenAudit` 三个 props，不再为一个按钮
  拉三条属性穿透；测试改成断言顶栏没有「审计」按钮、右栏入口仍在。

### 新增（2026-10-25 第十八轮：内置规范包改成一行文字入口，不再单占卡片）

- **规范包不再是一张卡片、也不占网格里的一格**：上一版给了它和技能同款的外壳，收起时右侧空半格、
  展开时又横跨整行，都占地方。现在它就是技能列表下面一行小字——「内置规范包 7 段 · 每轮按需求
  自动匹配 1–2 段，不常驻 ›」，想看明细点这行字即可（像「查看详情」），再点收起。
- 明细也不再套框：两列铺开，每条是「标题 + 触发词 + 字数」，收起后整块只剩那一行。
- 测试：`SkillsPage` 第一条改为断言规范包入口不在网格里、也没有 `article` 外壳；折叠/展开用例不变。

### 新增（2026-10-25 第十七轮：输入框锁定状态的提示提亮）

- **锁定态（任务运行中 / 等待审批）的提示语不再是最淡的灰**：这两句其实是在告诉用户
  「现在能写，但会排队」/「先去确认审批」，用 `faint` 灰几乎读不出来。现在按状态着色——
  运行中用品牌色（深蓝 / 暗色下亮蓝）、等待审批用警示色（琥珀），一眼能分清是「状态说明」
  还是普通占位文案。
- **空闲态占位提示也从 `faint` 抬到 `muted`**：对比度不低于正文的辅助信息，不用凑近看。
- 底部「演示环境：产物只写入本地目录，不外发」同样提亮一档（`faint` → `muted`）。
- 去掉 textarea 的 `disabled:opacity-70`：真禁用时整体降透明度会把提示压得更暗，与「提示要看得清」相反。

### 新增（2026-10-25 第十六轮：右栏产物行再收成单行、空态不再铺大框）

- **产物行只留「图标 + 文件名」**：上一版虽然改了列表，但第二行的「类型 · 大小 · 时间」仍把行高
  撑到 40px，一屏放不下几个文件。现在一行 36px——类型色块图标 + 文件名（超长省略号）+
  有运行用量时右侧的 tokens；类型/大小/时间/花费全部收进 hover 提示，需要时看一眼，不占版面。
  预览/下载仍是 hover 浮出的图标按钮，不占行宽。
- **空态不再是一个占满整栏的虚线大框**：没有产物时就一行灰字「暂无产物，文档生成完成后会出现在
  这里」，像空列表而不是「没加载出来的区域」。
- 测试：`ArtifactCard` 改为断言「列表里只有文件名、元信息在 title 里」；`RightPanel` 断言空态是
  一行 `<p>`、不带虚线框。

### 新增（2026-10-25 第十五轮：技能改卡片网格，一个技能不再横占整行）

- **一个技能不再占满整行**：原来是「一行一条、横着铺满 1200px」，一个技能就吃掉半屏宽度。
  改成和右栏产物同量级的卡片（实测约 300px 宽），用 `auto-fill` 网格铺开——1280 宽一行四张，
  窗口变窄自动减列；技能只会越装越多，多到十几个也只是往下长，不再是又长又空的列表。
- 卡片按窄宽度重排：图标 + 名称（超长省略号截断，不挤掉徽标）+ 启用状态；描述最多两行；
  触发词只露前 3 个（其余折成 +N）；底部「提示词 N 字 + 启用/停用」用 `mt-auto` 贴底，
  同一行卡片操作区对齐。
- 删除确认收进卡片内：底部临时换成「删除这个技能？ 删除 / 取消」，不再额外撑出一行按钮。
- 内置规范包仍是同一片网格里的同款卡片（折叠时只占一格）；展开时横跨整行列明细，双列排布。
- 测试：`SkillsPage.test.tsx` 第一条改为断言网格布局（`auto-fill`、技能卡是网格直接子项、
  规范包在同一网格里）。
- **会话菜单的「删除」不再标 Ctrl+D 提示**（用户反馈：这行提示没用）。快捷键本身仍可用
  （按 Ctrl+D 仍是直接删、不弹确认），只是菜单里不再标；置顶 / 重命名两项的提示保留。

### 新增（2026-10-25 第十四轮：产物区改紧凑列表、技能与规范包同框、弹出菜单不再被裁切）

- **右栏产物改成文件列表**：原来一个产物一张大卡（类型徽标一行、预览按钮一行、tokens 一行），
  四个文件就要滚屏。现在一行一个文件——类型色块图标 + 文件名（tokens 靠右）+ 一行灰色元信息；
  预览/下载是 hover 时浮在右侧的图标按钮，**不占行宽**，文件名能用满整栏；单击文件名同样能预览。
- **技能与内置规范包同框**：规范包不再单独成一节，收进技能卡片的同一个框里（框内分隔线分段、
  默认折叠）。列表项铺满整行，「只有 1 个技能时右边空半屏」的问题一并消失。
- **启用/停用改成按钮**：技能行的复选框换成「启用 / 停用」按钮——复选框只表达「当前是什么」，
  按钮直接表达「点了会怎样」；删除仍是 hover 出现的垃圾桶 + 二次确认。
- **修：弹出菜单被列表容器裁切**（用户反馈的 bug）。项目 ⋮ 与会话 ⋮ 菜单原来是行内的
  `absolute top-7 right-0`，落在 `overflow-y-auto` 的列表里，靠近底部就只剩半行（「打开项目」被切）。
  新增 `shared/ui/FloatingMenu`：portal 到 body + `fixed` 定位，下方放不下自动向上翻，
  水平按按钮右边缘对齐并夹进视口，滚动/改窗口大小时跟随重算。项目菜单、会话菜单都改用它。
- **修：菜单打开时不再弹 hover 气泡**。`IconButton` 新增 `tip` 开关，菜单展开时关掉——
  以前「项目操作 / 更多操作」的深色气泡会压在刚弹出来的菜单上，两条浮层叠在一起。
- **Ctrl+D 直接删会话**：以前按完只弹「删除？✓✕」，等于按了没删。现在快捷键直接删；
  鼠标走菜单点「删除」仍保留一次确认（那条路径更容易误点）。
- 测试：新增 `FloatingMenu.test.tsx`（portal / 外部点击 / Esc / 向上翻）、`SessionList.test.tsx`
  （Ctrl+D 直删、菜单删除仍需确认、菜单挂在 body、焦点在输入框时不抢键）、`SkillsPage.test.tsx`
  （同框、按钮启停、规范包折叠）；`ArtifactCard` 保持原有 7 条断言全绿；e2e 新增
  「会话 ⋮ 菜单一次显示全（不被列表容器裁切）」。
- 文档：`docs/demo.md` 演示脚本同步（素材四类格式、审批期间输入可用、右栏只放产物）。

### 新增（2026-10-25 第十三轮：输入框任务队列，跑完自动接着执行）

- **运行中也能继续写**：以前任务一开跑输入框就锁死，用户写好的下一句只能先存到别处。
  现在 `streaming` / `waiting_approval` 期间照常输入、照常提交——消息进前端队列，
  出现在输入框上方的「N 条任务排队中」卡片里，当前任务一结束就按顺序自动发起下一条。
- 队列卡片（`QueuedMessages`）：序号 + 两行正文 + 随任务走的素材名；右侧可**编辑**（正文与素材
  一起拿回输入框）与**删除**（已上传的素材顺手软删，不会留在会话素材里）。
- 运行中主按钮从「发送」变「排队」（时钟图标），旁边独立一个「停止」：停止只停当前这条，
  队列不跟着一起丢。停止后队列**自动暂停**（避免刚停就又自己跑起来），卡片上给「继续执行」，
  再写一条新消息也会解除暂停。
- 队列项记着入队时的 `thread_id`：换会话不丢队列、也不会把别的会话的任务发到当前会话；
  会话被删时它的排队任务一并清掉。
- 素材归属跟着消息走：入队时素材从输入区摘到队列项上，下一条消息不会误带上去。
- 状态层新增 `queue` / `queuePaused` 与 `queue/add|remove|returnUploads|pause|resume` 六个 action；
  `selectInputDisabled` 改名为 `selectRunBusy`（它描述的是「跑着」，不再是「输入禁用」）。
- 测试：新增 `queue.test.ts`（7 条 reducer 规则）与 useWorkbench 队列用例 5 条
  （入队、自动接续、编辑回填、删除清素材、停止后暂停）；Composer 新增 4 条；
  e2e 新增「运行中发的任务排进队列，跑完自动接着执行」（含「审批没过时队列不抢跑」）。
- 文档：`docs/api.md` 第 4 节补「4.1 任务队列」——含「刷新即清空（纯内存）」这条已知取舍。

### 新增（2026-10-25 第十二轮：审批内联 + 三档权限、技能搬输入框、会话自动命名、真思考过程）

- **审批搬进对话流，右栏只留产物**：原先审批卡挂在右栏，与产物混在一块，分不清哪块是产物、哪块是审批。
  现在 pending 审批以警示色区块内联渲染在对话流里（`InlineApproval`，标题「需要你确认 N 项」），
  下方跟折叠的已处理摘要（`ApprovalHistory`）；右栏重写为纯「产物」区（标题 + 计数 Badge + 审计入口，
  无运行记录时审计按钮禁用）。产物与审计两部分在视觉上一眼可分。
- **审批策略三档**：`always_ask`（始终询问）/ `risky`（按需确认，默认）/ `all_allow`（全部允许）。
  判定统一收敛到 `engine_protocol.needs_approval(mode, tool_name, risk, approval_tools)`，真引擎与
  mock 引擎共用；非法值一律回落到 `risky`（宁可多问一句，不会静默放行）。
  输入框工具条新增「审批策略」下拉（带盾牌图标），选择持久化到 localStorage，随运行请求
  `approval_mode` 一起发出。
- **技能从左栏搬到输入框，且可增删改**：左栏不再显示技能摘要（`SkillsRail` / `useSkillSummary` 删除），
  改为输入框左侧的「技能」圆角按钮，点开是 `w-22rem` 的柔和圆角弹层（`rounded-2xl`、无锐角）：
  复选框启停、hover 显示删除（二次确认）、底部「导入 SKILL.md」。技能页同步升级为
  卡片式启停 + 删除 + 顶部导入，「内置规范包」默认折叠（对用户用处不大，但保留可查）。
- **技能后端补齐导入/删除**：新增 `POST /api/v1/skills/import`（multipart，201，同名 409）与
  `DELETE /api/v1/skills/{skill_id}`（文件挪进 `app/skills/.trash/` 可恢复）；导入做 200KB / UTF-8 /
  frontmatter name 校验与 slug 防路径逃逸，删除后即时重建提示词。
- **会话自动命名**：新会话先用规则式 `derive_thread_title`（去掉「麻烦你帮我 / 请帮我 / 帮我」等客套前缀
  并削掉句末标点，避免尾空格），运行结束后再由模型 `suggest_title` 优化（24 字以内、3 秒超时、
  拒绝解释性回复与引号序号前缀），失败就保留规则标题；只对「自动标题」生效，用户手改过的不覆盖。
- **真实思考过程**：真引擎开场先调模型写 4–6 行推理（`_compose_thought`，带素材名与目标格式，
  `ModelUnavailableError` 或异常回退到固定模板），再分片下发 `thinking.delta`
  （分片间隔 35ms，像真在想，不再一闪而过）；`thinking.completed` 新增 `elapsed_ms`，
  前端折叠行显示「已思考 X.X 秒」。mock 引擎的思考文本同步改成 4 行结构化 + 耗时。
- **md / csv 整体下线**：产物格式与上传白名单收敛为 `docx / pdf / xlsx / txt` 四类
  （`SUPPORTED_UPLOAD_EXTS`、MIME 表、`OUTPUT_FORMATS`、`ACCEPT`、类型筛选下拉、项目扫描
  `DOC_EXTS`、工具提示词全部同步），`docs/markdown-knowledge-base-2026-10-25.md` 一并删除。
- **素材移除真正落库**：此前点「移除」只清前端状态，重进会话服务端又读回来。现在 `removeUpload`
  先调 `DELETE /api/v1/files/{id}`（软删进 `data/trash`），失败提示并保留素材，成功才清本地。
- **输入框交互收口**：外层容器加 hover 边框高亮；文件卡片去掉多余的 `cursor-help` 与文件名悬浮提示
  （只在真正出错时挂 Tooltip）。
- **测试**：后端新增 `test_approval_modes.py`（判定矩阵 5 条）、`test_skills_manage.py`（导入/重名/
  坏载荷/slug 逃逸/删除进 trash/越权路径/启停 7 条）、`test_title_suggester.py`（8 条）、
  `test_approval_mode_api.py`（all_allow 不问、默认问、非法值回落 3 条）；前端新增
  `approval-modes.test.ts`（4 条）、`SkillsMenu.test.tsx`（7 条），重写 `RightPanel.test.tsx`（4 条），
  并补充审批内联、审批策略下拉、素材删除落库等用例。
- **文档/契约**：`docs/api.md` 同步支持格式四类、`/skills` 增补导入删除、`waiting_approval` 改
  「对话流内联审批卡」；`docs/events.md` 补 `thinking.completed.elapsed_ms`；
  重新导出 `contracts/openapi.v1.json`，**补回第十/十一轮漏同步的路径**
  （`/projects*`、`/artifacts/trash`、`/artifacts/{id}/{open,purge,restore}`、`/storage/*`、
  `/prompt-packs`、`/skills/import`），快照由 34 paths/42 ops 更新为 48 paths/60 ops。

### 新增（2026-10-25 第十一轮：pdf / xlsx / md / txt 知识库与四套工具库）

- 新增 `pdf_utils.py`：`read_report`（页数/加密/元数据/每页文本量/扫描件判定）、`extract_pages`、
  `merge_pdfs` / `split_pdf`（按页数或区间）/ `rotate_pages` / `watermark`，以及 `make_pdf`
  生成中文 PDF（STSong-Light、四种版式预设、页码页脚、`& < >` 自动转义、表格与项目符号）。
- 新增 `xlsx_utils.py`：`read_report`（sheet/行列/表头/空值率/公式/合并区）、`sheet_records`
  （跳过整行空白、重复表头加后缀）、`write_table` / `append_records` / `write_csv` /
  `read_csv_records`（utf-8-sig → gb18030 自动识别）、`style_header` / `autofit_columns` /
  `freeze_header` / `add_autofilter` / `apply_number_format` / `add_total_row`（SUM 公式）/
  `group_sum`。
- 新增 `text_utils.py`：`read_text` 自动识别 UTF-8 / GBK / UTF-16 并剥离 BOM、`write_text` 统一 LF、
  `heading_tree`（标出标题跳级）、`normalize_markdown`（补标题空格、补表格分隔行、收拢空行）、
  `md_table`、`split_by_heading`、`txt_stats` / `txt_wrap`、`md_to_docx`（标题/列表/表格/加粗）。
- `code.run_python` 工作目录从「只有 docx_utils」扩展为四套工具库；工具描述与 Agent 提示词
  按扩展名给出对应库的函数名，并要求「扫描件不要假装读到文本」「合计用 SUM 公式可复算」。
- `doc.generate_report` 的 pdf / xlsx 产物改用上面两套库：PDF 有页码与统一版式，xlsx 表头加粗、
  冻结首行、筛选与列宽一步到位（原来是一列文本灌进去）。
- 参照 docx 知识库补齐三份文档：`docs/pdf-knowledge-base-2026-10-25.md`、
  `xlsx-knowledge-base-2026-10-25.md`、`txt-knowledge-base-2026-10-25.md`——能力边界（不能做的写明）、
  版式/格式预设、场景库、函数表、Agent 提示词、常见坑、交付校验清单。Markdown 那份已随
  「md/csv 下线」一并删除（见「第十二轮」）。
- 新增 24 条测试：`test_pdf_utils.py`（真实 pypdf 读回页数/旋转角/页脚，扫描件与空文档判定）、
  `test_xlsx_utils.py`（断言落在 openpyxl 对象：加粗、冻结、筛选、数字格式、SUM 公式）、
  `test_text_utils.py`（三种编码、CRLF 归一、Markdown 规范化、md→docx 结构）。
- 修 `docx_utils.set_font`：`bold` 默认改为 `None`（不传不覆盖），此前 `apply_body` 会把脚本里
  设好的加粗全部抹掉。

### 新增（2026-10-25 第十轮：左栏加项目区、技能区与「更多」菜单，技能页做成真的）

- 左栏从「最近会话独占」改成四段：新建会话 → 项目 → 最近会话（限高滚动）→ 技能摘要 → 底部导航。
  项目区、技能区常驻，谁也不会把别人挤没。
- 新增「项目」能力：把自己的文档文件夹登记成项目（`POST /api/v1/projects`），左栏可直接选，
  选中后输入框出现项目徽标，本轮任务会把项目里的文档作为素材交给 Agent；点项目名进项目页
  看全部文件（文件名/类型/大小/修改时间、按名筛选、勾选后「用选中的 N 个文件开始」）。
- 项目在服务层做校验：只接受存在的目录、重复添加给 409、最多 20 个、不允许程序目录与上传/产物目录；
  扫描只读、限深度 3 / 400 个文件、跳过隐藏目录与符号链接；目录被移走时标 `missing` 提示重新指定，
  不让整块界面报错。
- 运行接入：`POST /threads/{id}/runs/stream` 新增 `project_id` / `project_files`，服务端把项目文档
  搬进会话素材（单文件 30MB、最多 10 个，解析失败的单个文件跳过并记日志），Agent 只看到「素材」，
  不直接放开用户磁盘路径。
- 底部导航按参考软件分级：产物 / 技能 / 设置 三个常用入口 + 「更多」弹出菜单（审计用量、知识库），
  不再是 5 格平铺挤成小字。
- `/skills` 从占位页做成真页面：技能列表（说明、触发词、提示词字数、启停开关即时生效）+ 内置规范包
  一览（7 段、各段触发词与字数）+ 手动安装位置说明；左栏技能区显示「N/M 启用 · 提示词 X 字」。
- 新增 `GET /api/v1/prompt-packs`：暴露内置提示词包清单。
- 前端新增 `features/projects`、`features/skills` 两个 feature（含 index.ts 入口，满足模块边界规则），
  新增项目接口与项目区组件 9 条测试。

### 新增（2026-10-25 第十轮：Agent 提示词合集按需路由）

- 把 `docs/agent-prompts-2026-10-25.md` 里的 7 段提示词拆成 `backend/app/prompts/packs/*.md`
  （文档决策 / 前端评审 / 数据提取 / 表格处理 / 文档比对 / 批量模板 / 信息整理），首行注释声明
  id、标题、触发词。
- 新增 `PromptPackService`：按本轮用户消息的关键词打分，最多注入 2 段、总字符上限 4200，
  在 `RunContext.prompt_extra` 里传给真引擎拼进 system prompt；不常驻、不互相干扰。
  改 md 文件后按 mtime 自动重载，不用重启。
- 新增 5 条路由测试：7 段全部加载、七类典型说法各命中对应包、最多 2 段、空消息不注入、字符预算。

### 新增（2026-10-25 文档操作知识库落地）

- 新增 `backend/app/services/docx_utils.py`：把知识库里的样式预设与常用操作固化成函数——
  页面预设（默认 / 紧凑 / 公文 / 论文 / 简历 / 信函）、字体预设（正文宋体小四、公文仿宋三号、
  标题黑体、表格五号）、`set_page` / `set_para` / `apply_body` / `apply_headings` /
  `add_table_simple`（三线表 / 全框线 / 无框线，表头跨页重复）/ `replace_text`（含跨 run 替换，
  覆盖正文 + 表格 + 页眉页脚）/ `add_page_number` / `backup` / `read_report`。
- `code.run_python` 每次运行会把 `docx_utils.py` 复制进工作目录，脚本直接
  `from docx_utils import *`；工具描述与 Agent 提示词同步说明「优先用这套函数，别现场拼 XML」，
  并写入四条改动纪律（先读后改、留备份、最小改动、打印改动摘要）。
- 修掉知识库示例里几个会静默出错的地方：`run.font.color.rgb = None` 并不会保持黑色、
  字符间距要写 `w:spacing/@w:val`（1/20 pt）而不是 rPr 属性、三线表边框要 `w:val="nil"`
  而不是 `sz=0`（sz=0 在 Word 里仍会画细线）、`set_para` 里 line 参数的两个分支等价。
- 新增 15 条 `test_docx_utils.py`：断言落在 XML 层（`w:eastAsia`、`w:tblBorders`、`w:tblHeader`），
  并包含一条「按典型脚本骨架真跑一次」的端到端用例。
- 新增示例素材 `data/samples/meeting_notes.docx`；知识库原件归档到 `docs/`。

### 变更（2026-10-25 第九轮：会话不再自动新建、目录选择器、审批分级、模板下线）

**上传素材不再偷偷建会话**

- 以前选文件就 `ensureThread()`，用户每传一次就被塞一个新会话；现在改成「先暂存、发送时才上传」：
  没有会话时文件只进输入框（状态「待发送」），点发送或回车才建会话 + 上传 + 开跑。
  建会话从此只有两个用户动作能触发：点「新建会话」、或是第一次发送任务。

**存储目录：点着选，不用手打路径**

- 新增 `GET /api/v1/storage/browse`（只列子目录、过滤隐藏/系统 junction、读不到就退回可用上级）
  与 `POST /api/v1/storage/browse/mkdir`（就地新建文件夹）。
- 设置页「上传目录 / 产物目录」原来要手打绝对路径、还并排放着「打开」和「修改」两个近义按钮；
  现在路径整行可点（直接开资源管理器），右侧只留「更改位置」（开目录选择器）和「恢复默认」。

**审批分级：只有高风险才拦人**

- 默认审批范围从 `doc.generate_report,file.delete,code.run_python` 收窄为 `code.run_python,file.delete`
  —— 生成文档写的是产物目录、可覆盖可重跑，不该每次都打断人。
- mock 引擎跟着规则走：没被列进审批规则的动作直接执行，不再伪造一次审批。
- 审批卡新增「Agent 预审」建议行：按动作类型给一句结论 + 理由（建议批准 / 建议先看一眼清单 / 建议看过脚本再批），
  用户扫一眼就能决定是否通过。

**模板整块下线，左栏换成图标坞**

- 左栏「模板」区、空状态里的「或从模板开始」、`shared/config/templates` 的入口一并移除（自定义模板本地存储也不再被读）。
- 底部导航从 4 格改 5 格：产物 / 用量 / 设置 / 技能 / 知识库，标签改用短标签避免 12px 下被截断。
- 新增「技能」占位入口（`/skills`）：先把位置留出来，后续接 GitHub 等来源的技能导入。

**会话与产物的小修补**

- 删除最近会话后，左栏计数（`sessionsMeta.total`）实时减一，不用刷新页面。
- 会话 ⋮ 菜单补「复制标题」，并把 Ctrl+Shift+P / Ctrl+Shift+R / Ctrl+D 真的绑上（焦点在输入框里不拦）。
- 产物列表卡片去掉单条「删除」，删除统一走勾选后的「删除选中」，避免误点。
- 审批区已处理的记录收进折叠组，不再一长串堆在待办下面。

### 变更（2026-10-25 第八轮：输入框附件卡更有层次）

- 附件卡（`Composer` 的 `UploadChip`）原来用「近白底 + 浅灰描边」，贴在白色输入框上几乎看不出边界；
  改为 `surface-sunken` 底 + `line-strong` 描边 + 轻阴影 + 8px 圆角，与输入框拉开一档对比，
  深色主题下同样成立（#2a2a2e 底 / #3d3d43 边）。
- 左侧状态图标加白色圆底：解析完成绿、上传中蓝、失败红，扫一眼就能分辨状态。
- 类型徽标（PDF / DOCX / XLSX…）改为品牌浅蓝底 + 品牌色文字 + 细描边；文件名提到 medium 字重，
  大小用等宽数字，信息层级从「一片灰字」变成「状态 → 类型 → 名称 → 大小」。
- 附件之间间距 6 → 8px；悬停时底色再深一档、描边转品牌色，鼠标经过有明确反馈。

### 变更（2026-10-25 第七轮：执行过程折叠、审批按钮、产物卡消耗）

**执行过程默认折叠为一行的摘要**

- 新增 `ExecutionTrace`：把连续的「执行计划 / 工具调用 / 子智能体 / 思考」合成一组，
  默认只显示一行——`执行过程 · 3/3 已完成 · 全部步骤已完成`（运行中显示「正在：xxx」，
  失败时显示「N 步失败」）。点开才逐条展开，看入参/出参。
- 单独一条中间过程不再套分组（工具调用本身就是一行流水）；消息仍然打断分组。

**审批卡：两个按钮同一行**

- 「批准并继续」占主宽 +「拒绝」靠右，取代原来的两块通栏按钮；卡片内边距、
  说明行距同步收紧，右栏 4:6 分割下「拒绝」不会再被面板裁掉一半。
- 右栏待审批时审批区临时让到 5 : 5，产物区仍多于一半，保证按钮完整可见。

**产物生成后自动清空附件**

- `run.completed` 且产出了产物时清空输入框上的附件（之前会一直挂着，像还要再点一次）。

**产物卡：去掉 SHA256，改显示消耗**

- 右栏产物卡不再显示 `SHA256 bff2391ce058…` 和「加载校验信息」——用户看不懂这串字符；
  改成显示这次运行消耗的 `441 tokens`（悬停可看花费），并把「预览」做成带文字按钮。
- `run.completed` 会把 tokens / 花费写到该轮产物上（`ArtifactItem.tokens / cost_cny`）。

**运行摘要与导航间距**

- 运行结束那一行补上消耗与模型：`✓ 运行完成 · 产物 1 个 · 共消耗 441 tokens · ¥0.0033 · 演示模型`
  （演示模式下不暴露 `mock-scripted` 这种内部名字）。
- 顶部导航四个入口间距 `gap-2 → gap-3.5`，不再挤成一排。

### 变更（2026-10-25 第六轮：对话流瘦身、后台并行任务、回收站多选）

**后台任务：切走会话也不中断**

- 以前切会话 / 新建会话会 `abort` 正在跑的事件流，任务直接死掉；现在改为「摘成后台任务」：
  流继续消费，只是不再往当前会话的界面写事件（每条流有独立 key，`emit` 只在前台时 dispatch）。
- 输入框上方新增「N 个后台任务运行中」胶囊（`BackgroundTasksBar`），点开可看任务名、耗时、
  状态（执行中 / 等你审批），能「回到会话」或「停止」（停止 = 断流 + 调 `POST /runs/{id}/cancel`）。
- 后台任务跑完：撤掉胶囊；若用户正停在该会话就重新拉一次详情（消息 / 产物 / 审批），
  否则弹一条完成提示。
- 顺手修掉一个竞态：刷新后「恢复上次会话」的异步结果可能盖掉用户刚点的「新建会话」。

**对话流瘦身（工具调用不再刷屏）**

- `PlanCard`、`ToolCard`、`SubagentCard` 全部从「图标方块 + 标题 + 徽标 + 耗时」的卡片
  改成**单行流水**（图标 + 中文动作名 + 一行摘要 + 结果 + 耗时），点开才展开入参/出参。
  执行计划默认收起，只留「2/3 已完成 · 正在：xxx」和一条 2px 进度线。
- `RunSummaryCard` 删掉 tokens / 成本 / 耗时三栏与 `run_id`，收成一行：
  「✓ 运行完成 · 产物 1 个 · 已消耗 ¥0.0033 · 查看审计记录」。
- 对话条目间距 `gap-5 → gap-3`，一屏能看到更多上下文。

**审批卡：只标生成的文档类型**

- 主区只剩「生成文档 + 类型徽标（PDF / DOCX）」和一句说明；动作、标题、格式、影响范围、
  技术编号全部收进「查看详情」，默认收起。批准 / 拒绝仍是两块通栏大按钮。

**输入区**

- 删掉附件下方「453 字 · 预览：……」那块大段文字（附件 chip 里已经有文件名与字数）。
- 只加了附件没写需求时点「发送」：不再静默，给出「已添加 1 个素材，请再写一句需求…」
  或「请先输入需求，再点发送」，并把焦点送回输入框、给输入框加一圈琥珀色描边；
  开始输入即消失。有附件时占位文案也换成「已添加素材，说说想让我做什么？」。

**右栏与产物中心**

- 审批 / 产物各自成为独立面板（边框 + 表头底色 + 表头右侧状态），4 : 6 比例不变，
  两块边界一眼能分清；空状态在面板内垂直居中。
- 产物卡 hover 换成统一 `.card-lift`：上浮 2px + 品牌色描边 + 5px 柔光 + 加深投影
  （`shadow-[...]` 多条阴影的任意值写法在 Tailwind 里不生效，改为写进 `tokens.css`）。
- 回收站支持多选：每张卡带复选框 + 「全选本页」+「恢复选中」/「彻底删除」（逐条调用，
  失败只报数）；彻底删除仍需二次确认。
- `PageShell` 内容区 1100 → 1280px（顶栏两侧余白本来就多），产物网格更舒展。

**文案**

- 成功类提示不再挂 `trace: tr_xxx`（只有错误提示保留，便于查日志）。
- 「后端未连接（/api）…?mock=1」改成「还没连上本地服务，暂时发不出任务。确认程序已启动后
  点「重试」，也可以先用演示模式看看效果。」

### 变更（2026-10-25 第五轮：产物中心、预览与文案可读性）

**说明性小字统一放大一号（只动小字，不动正文）**

- `--text-caption` 11px → 12px、`--text-mini` 12px → 13px，行高同步上调。
  90% 基准下这两档原来只有 9.9 / 10.8px，屏幕上看��吃力；正文（13/14）与标题保持原样。
- 间距整体松一档：`PageShell` 内容区 `py-5 → py-6`、说明文案 `mb-3 → mb-4`、
  产物卡片栅格 `gap-2 → gap-3`、卡片内边距 `p-3 → p-3.5`、筛选条 `mb-4 → mb-5`。

**产物中心：只按类型查找，误删可回收**

- 去掉「会话」筛选，只留「类型」——按会话的 ID 找文件对用户没有意义。
- 卡片不再显示 `th_xxx / r_xxx` 这类内部编号，只保留「创建于」。
- 新增「全部产物 / 回收站」视图切换：删除改为软删（文件挪进 `data/trash/`），
  回收站里可「恢复」或「彻底删除」；对应 `GET /artifacts/trash`、
  `POST /artifacts/{id}/restore`、`DELETE /artifacts/{id}/purge`（见 `docs/api.md`）。
- 回收站条数单独拉取，读失败不影响主列表。

**预览：能看清、也看得懂**

- 预览弹窗宽度 380px → 860px（`Modal` 新增 `size="lg"`），正文 12px → 13px。
- txt：按结构还原——`【小标题】` 变标题、`- ` 变列表、开头的「生成时间 / 模式 / 来源」
  收进一条弱化的元信息行，不再是一整块等宽文字。
- csv：解析成表格（首行表头）；上传的 .txt / .md / .csv 之前一律「暂不支持预览」，
  现在按扩展名还原真实类型再预览，同时支持 html（sandbox 隔离）。
- 「用 WPS 打开」走 `POST /artifacts/{id}/open`，装了 WPS 就用 WPS 打开原文件。

**右栏与设置**

- 右栏只剩「审批 + 产物」，高度按 4 : 6 分配（`flex-[4]` / `flex-[6]`），两块各自内部滚动。
- 产物目录 / 上传目录可改：新增 `PUT /storage/paths`，路径写到本地 overrides 文件，
  不改 `.env`；「打开」按钮从竖排改横排（`whitespace-nowrap`）。

**hover 反馈与文案**

- Tooltip 更醒目：13px + 中等字重、内边距加大、加一圈描边；顶部导航也补上同名提示。
- 设置页 / 导航提示 / 空状态里「前端、后端、mock、环境变量」等说法改成用户能懂的话，
  例如「模型、审批与界面设置」「演示模式（不联网）：产物只保存在本机目录，不会外发」。

**审计页**

- 每日消费从面积图改成柱状图：框架高度固定，柱高只按数值相对大小变化，不再无限撑大。
- 「去充值」不再写死 DeepSeek：hover 弹出供应商选择框（圆角面板，列出用过的供应商在前），
  选中后跳对应开放平台；弹层用 portal 渲染，不会被下方卡片遮住。

### 变更（2026-10-25 第四轮：交互反馈与设置页存储目录）

**hover / 禁用态：任何可交互元素都要有看得见的反馈**

- 新增 `--color-surface-hover`（浅 `#e9edf3` / 深 `#2c2c31`）：全站 18 处 `hover:bg-surface-sunken`
  统一换成它，鼠标划过时底色对比更明显；左栏模板行/会话行/底部导航、右栏空状态虚线框、
  产物卡片、设置分区导航、下拉触发器全部覆盖。
- 新增 `--color-brand-solid` / `--color-brand-solid-hover`：主按钮不再用「文字用 brand」当底色
  （深色下 brand 被提亮，按钮会变成浅白蓝）。实色按钮的 hover 现在是加深而不是提亮。
- 新增 `--color-tooltip` / `--color-tooltip-ink`：Tooltip 原来用 `bg-ink text-surface`，
  暗色主题下 `ink` 是浅色 → 气泡变成一块白底，已修正。
- 发送按钮不再用 `disabled` 表达「还没写内容」：常亮可点，空内容时点它把焦点送回输入框；
  只有运行中/等审批才真正 disable。新增 `Composer.test.tsx` 锁住这条规则。

**页面骨架：导航位置固定**

- `PageShell` 的页面导航改为绝对居中（≥1024 用居中版、768–1023 用行内版），
  各页右侧动作按钮（刷新/保存/导出）宽度不同也不会再把导航推来推去。
- 左栏宽度 `--spacing-rail` 13.75rem → 16.5rem（相对右栏 20rem 不再明显偏窄）。
- 设置页左侧分区导航字号 `text-mini` → `text-regular`，选中态改品牌色。

**设置页：存储目录真的能访问**

- 新增 `GET /storage/paths`、`POST /storage/reveal`（见 `docs/api.md` 1.7.1）：
  返回绝对路径 + 文件数，并能唤起系统文件管理器；只允许 uploads / artifacts 两个固定目录。
- 设置页「数据与路径」：上传目录/产物目录改为「绝对路径 + 打开按钮」，
  删除对用户无意义的「数据库」一行；两个目录的打开失败原因会显示在区块顶部。
- 「保存设置」不再因为「没有改动」而禁用，永远可点（无改动时相当于再保存一次）。
- `GET /settings` 的 `upload_dir` / `artifact_dir` 改为返回绝对路径。

**工作台：回到首页不再自动变成新会话**

- 新增 `state/last-thread.ts`：记住最近打开的会话（`oa:last-thread`），
  回到 `/` 时恢复该会话；只有用户点「新建会话」或删掉当前会话才清记录。
- 挂载时不再有任何自动建线程行为；恢复失败（会话已删/后端重置）静默回到空状态。
  新增 3 条单测锁住「恢复 / 记录失效 / 新建后不恢复」。

**其他**

- 右栏审批 / 产物列表统一限高（`max-h-[13.5rem]`）内部滚动，条目再多也不把框架顶长。
- 模型面板改为单行紧凑布局（每行「模型名 供应商 + 已配置/未配置」），高度从约 440px 降到 ~167px。
- 审计按钮 tooltip 文案改为「查看本次运行的审计记录 / 查看审计用量（先选择一个会话）」。

### 变更（2026-10-24 第三轮：产物格式收敛到 5 种，页面基准缩到 90%）

**产物格式去掉 csv / html**

- 后端 `doc.py` 的 `OUTPUT_FORMATS` 只保留 docx / pdf / xlsx / md / txt，
  连带删除 `render_csv` / `render_html_file` 与不再需要的 `csv` / `io` 导入；
  DOCX 预览用的 `render_preview_html` 保留（那是预览，不是产物格式）。
- 前端 `shared/config/output-formats.ts` 同步收敛，下拉只剩 5 项；
  上传 `.csv` 素材仍可解析，只是产物默认回落到 docx。
- 契约快照与生成类型重新导出；`RunRequestIn.output_format` 的说明文本、`docs/api.md`、
  两个 README 的格式清单同步。
- 新增用例：`POST /runs/stream` 传 `output_format=csv|html` 必须 400，且报错文案里不再列出这两个格式。

**整页缩到 90% 基准（对齐浏览器 90% 缩放的观感）**

- `tokens.css` 增加 `html { font-size: 90% }`：Tailwind 的字号/间距/圆角全走 rem，
  改一处即整体缩小，字距与留白比例不变。
- 布局里写死的 px 也换成 rem，避免「字小了、容器没小」：`--spacing-rail` 220px→13.75rem、
  `--spacing-panel` 320px→20rem，以及会话流/输入区/空状态/导航/快捷气泡的
  `max-w-[780px]`、`max-w-[820px]`、`max-w-[460px]`、`min-h-[44px]`、`w-[128px]` 等。
- 右栏「窄面板转下拉」阈值随之从 300px 调到 270px，否则默认宽度（288px）会被误判成窄面板、
  把三个区块收进下拉。

**空状态首屏不再被裁切**

- 垂直节奏改为随视口高度伸缩（`clamp(...vh...)`）：矮窗口自动压缩，高窗口保持原留白。
- `max-height: 700px` 时图标与标题并排、隐藏与输入区重复的底部说明，省下约 60px。
- 空状态不再自动滚到底（原先 `scrollTop = scrollHeight` 会把图标和标题顶出可视区）；
  内容用 `my-auto` 居中——空间富余时居中，空间不足时自动退化为顶部对齐。
- 实测 1080×545：内容 319px / 可视 319px（改前 463/309，溢出 154px）；
  1280×860：上下各余 104px。

### 变更（2026-10-24 第二轮：下线发邮件能力，审批前移到写盘）

邮件在本产品里始终只是「演示高风险动作」的载体：既没有真实投递价值，又拖着一整套
连接器抽象（`MailConnector` / mock / imap）与配置项（`MAIL_TO` / `OUTBOX_DIR`）。
本轮整体删除，并把审批演示换到语义更自然的位置。

**删除**

- 工具层：`tools/builtin/mail.py`（`mail.draft` / `mail.send`）。
- 连接器层：`connectors/`（`base.py` / `registry.py` / `mail_mock.py` / `mail_imap.py`）
  与 `infra/mail/` 整目录下线；`domain/ports.py` 的 `MailConnector` 协议、
  `ToolContext.mail`、`RunContext.mail` 一并移除。
- 配置层：`MAIL_TO` / `OUTBOX_DIR` 环境变量与 `Settings.outbox_path`、设置页「邮件草稿收件人」
  字段、`SettingsOut/UpdateIn.mail_to`、`settings_service` 白名单与 env 提示。
- 文档与脚本：README 架构图/目录树/扩展点（12→11）、`docs/api.md`、`docs/events.md`、
  `docs/demo.md`、`docs/acceptance.md`（#22 标记为已随能力下线移除）、
  `docs/adr/0002-mock-first.md`、`docker-compose.yml`、`Makefile`、`.env.example`。

**审批演示改到「写入产物目录」**

- `doc.generate_report` 的 `risk` 由 `low` 提到 `high`，默认 `APPROVAL_RULES` 改为
  `doc.generate_report,file.delete`：调用顺序由「先生成 → 再审批发信」改为
  **「先审批 → 批准后才写盘」**，拒绝时零写入、零产物。
- mock / real 引擎同步改流程：`approval.required(doc.generate_report)` 前置，
  计划模板 4 步减为 3 步；拒绝分支只发 `tool.finished(skipped=true)`，不再产出 `artifact.ready`。
- 前端时间线、审批卡预览（新增「标题 / 格式」两行）、工具中文名映射
  （`mail.*` → `doc.generate_report` / `file.delete`）与全部文案同步。
- smoke 用例 smoke-06/07、后端 `test_pipeline` / `test_tools` / `test_real_engine*`
  按新事件顺序重写。

**验证**

- 后端 190 passed / 1 skipped，ruff 干净；前端 30 文件 / 792 用例通过，
  `tsc -b`、eslint、prettier 干净；Playwright 13/13。

### 修复（2026-10-24）

- **产物批量删除返回 405**：不是代码缺陷，而是 8000 端口上跑的后端进程来自主检出
  `E:/opencode/office-agent-mvp`，该仓库停在旧提交、没有 `POST /artifacts/batch-delete`，
  请求被 `GET /artifacts/{artifact_id}` 部分匹配成 405。已把 `master` 快进合并到本分支
  （`git merge --ff-only`），重启后端即生效。

### 优化（2026-10-24）

- **产物格式选择器改为自绘下拉**：原生 `<select>` 的展开弹层由 Windows/Chromium 系统绘制，
  选项高亮是直角深灰块、CSS 无法圆角化。改为 `button` + `createPortal` 的 listbox
  （`OutputFormatSelect.tsx`）：面板 `rounded-2xl`、选项 `rounded-xl` 圆角浅底 + 品牌色勾选，
  带 `aria-haspopup/expanded`、方向键/Esc/Enter 键盘导航、空间不足自动上翻、滚动/缩放收起；
  原本挂在触发器上的 hover 说明改为弹层底部一行提示，避免与展开的列表互相遮挡。
- **左栏底部导航提示改用统一气泡**：4 个导航项原先用原生 `title`（系统绘制的方角提示），
  改为复用 `Tooltip`（深色圆角小卡片、`side="top"`、未上线项追加「（即将上线）」）。

### 评审整改（code-review-suggestions-2026-10-24）

本轮按评审文档逐条整改，本节记录已完成项；未完成项见 `KNOWN_ISSUES.md`。

**P0 / P1**

- **P0-1 认证缺失**：compose 端口改为回环绑定（`127.0.0.1:8000` / `127.0.0.1:8080`）；
  新增可选 API Token 中间件（`X-API-Token`，默认关闭，纯 ASGI 实现以免缓冲 SSE）。
- **P0-2 SSE 被缓冲**：Nginx 改为 envsubst 模板，用一条正则 location 覆盖
  `/api` 与 `/api/v1` 两个前缀下的三个 SSE 端点（此前只有旧别名路径生效，
  前端实际走的 `/api/v1/...` 仍被缓冲 120s）。
- **P1-3 SSRF**：新增 `core/net_guard.py`，出站 URL 做 DNS 解析 + 私网黑名单 + 域名白名单。
- **P1-4 压缩炸弹**：上传改为「解压后总大小 / 条目数 / 压缩比」三重限制，PDF 页数与解析文本长度上限。
- **P1-5 file.delete**：补齐此前配置里声明但未实现的高风险工具（软删到回收站 + 审批门禁）。
- **P1-6 依赖锁**：pip-tools 生成 `deploy/requirements.lock.txt`（36 个包全 `==` 锁定），
  新增 `scripts/check_requirements_sync.py` 校验三处依赖清单一致（已发现并修掉 `pyyaml` 漏声明）。
- **P1-7 前端覆盖率**：**8.61% → 72.05%**（28 个测试文件 / 774 条用例），
  超过 DoD 第 13 条的 60% 目标；`vitest.config.ts` 门槛已从 40% 提到 **60%**（四项同时卡），CI 强制校验。
  补测重点：workbench reducer（90%）、`useWorkbench` 控制器（97%）、`sse.ts`（98%）、
  `mock-run` 事件脚本（78%）、五个 feature 的 `api.ts`、`primitives.tsx` / `Icons.tsx` /
  `AreaChart.tsx`、工作台全部展示组件（气泡/思考块/流容器/状态栏/空态/运行摘要/用量卡/快捷入口）、
  产物卡与 docx 预览弹窗（含 mammoth 失败、pdf/xlsx 引导下载、HTML 清洗）。

**P2**

- 生产环境关闭 `/docs` `/redoc` `openapi.json`；补齐安全响应头（CSP / Referrer-Policy / Permissions-Policy）。
- 上传大小限制由 `MAX_UPLOAD_MB` 经 envsubst 注入 Nginx，前端 `MAX_UPLOAD_BYTES` 与后端默认值对齐。
- `APP_ENV` 此前被静默忽略（字段名不匹配），改为 `AliasChoices` 兼容；`.env.example` 清理幻影变量。
- 模型 `temperature` / token 预算改为可配置；`.gitignore` 补齐测试残留目录。
- **P2-12 启动命令统一**：Makefile 的 `api` / `mock-api` 改为仓库根执行
  `python -m uvicorn backend.app.main:app`，与 README、Dockerfile `CMD`、`tests/conftest.py` 完全一致
  （此前 Makefile 走 `cd backend && app.main:app`，三处写法并存，文档与实现容易漂移）。
- **P2-15 分页下推 SQL**：`/threads`、`/runs`、`/artifacts` 三个列表接口此前是
  `list(limit=1000/2000)` + 内存过滤切片，超过上限的数据永远翻不到，且每次翻页都把整段历史读进内存。
  现在改为 `COUNT(*)` 取总数 + `LIMIT/OFFSET` 只取当前页，`status` / `type` / 关键词过滤全部下推到 SQL；
  排序补 `id` 作为兜底，翻页不再出现重复或漏项。审计导出改成按 200 为一批迭代线程与 run，
  去掉原先 `1000 线程 × 500 runs` 的截断与一次性载入。
- **P2-16 工作区残留**：已核实 `git status` 洁净（此前记录的 ` D tmpmopmgbv4` 删除项已不在工作区），
  CI 的「工作区洁净」断言可正常使用。
- **P2-14 前端大文件拆分（行为不变）**：
  - `state/workbench.ts` 1005 → 392 行，按职责拆成 `types.ts`（状态/action/初始态）、
    `helpers.ts`（timeline 与收尾纯函数）、`run-events.ts`（SSE 事件分支）、
    `selectors.ts`（派生查询）；入口用 `export *` 保持原有导入路径与 API 不变。
  - `useWorkbench.ts` 780 → 680 行，把 6 个「后端 DTO → 视图模型」纯映射
    （标题摘要 / 运行模式归一 / 历史消息 / 产物素材 / 审批记录 / 错误信息）抽到 `state/mappers.ts`，
    并补 8 条直测（此前这些分支埋在 hook 里只能间接覆盖）。
  - `SettingsPage.tsx` 733 → 498 行，抽出 `components/KeyRefModal.tsx`（添加 Key 弹窗）、
    `components/ModelListCard.tsx`（模型与 Key 状态列表）、`keys.ts`（默认环境变量名 + 掩码）。
  - 验证：`tsc -b` / eslint 干净，Playwright 13/13（含设置页保存、添加 Key 两条）。

### 新增

- **产物中心支持多选批量删除**：每张产物卡新增勾选框，「全选本页 / 已选 N 项 / 删除选中」
  常驻筛选栏；选择集只覆盖当前页，翻页或切换筛选自动清空（避免误删看不见的项）。
  配套新增 `POST /api/v1/artifacts/batch-delete`（单次上限 200、自动去重、**部分成功**语义：
  失败的 ID 逐条返回原因，不阻断其余；仍是软删入 `data/trash`，保留审计记录）。

### 修复

- 设置页「添加 Key」只能登记环境变量名、无法粘贴供应商 Key → 新增
  `PUT /api/v1/models/{id}/key`，可直接粘贴 Key（落本机 `.env`，权限 600，响应仅回掩码）。
- 顶栏 hover 提示被视口裁切 / 贴边只露一半 → Tooltip 改为 portal + `fixed` 定位，
  按实测宽度二次夹取，空间不足自动翻面，滚动/缩放时收起。
- 右栏无用的「素材」区块移除，只保留审批与产物。
- 切换会话时详情加载失败的提示看不见 → `thread/selected` 会用初始状态重建（notice 归 null），
  原先「先 notify 再 dispatch」导致错误提示刚发出就被抹掉；改为先 dispatch 再 notify。
- **`.gitignore` 误吞源码目录**（本轮排查发现的历史遗留问题）：`artifacts/` 规则没有前导 `/`，
  git 会匹配任意层级的同名目录，导致 `frontend/src/features/artifacts/`（整个产物中心 feature，
  含页面、卡片、api 层）**从未入库**。已将 `outbox/` `uploads/` `artifacts/` 三条运行时目录规则
  锚定为 `/outbox/` `/uploads/` `/artifacts/`；`data/artifacts/` 仍由 `data/*` 正常忽略。

## [0.2.0] - 2026-10-23

V2.1 标准化版本（B0–B5 分批落地）。本版目标：从「毛胚」升级为
「可日常自用、可持续演进的标准骨架」——规范可执行、契约可校验、扩展可证明。

### Added（B0 工程地基）

- 仓库根规范文件：`.editorconfig`、`.pre-commit-config.yaml`、`LICENSE`（MIT）、
  `CONTRIBUTING.md`、`CODEOWNERS`、`CHANGELOG.md`。
- `.github/`：PR 模板、Bug/Feature Issue 模板、Issue 模板配置。
- CI 六道门禁骨架：`backend-lint`、`backend-test`、`frontend-quality`、
  `contract`、`build`、`security`（文件未就绪时输出明确错误，不空跑成功）。
- `.env.example` 增加多模型供应商变量（DeepSeek / 通义千问 / GLM，仅占位与引用，
  不含真实 Key）、模型路由/步数/日志/特性开关配置。
- `.gitignore` 加固：测试残留目录（`oam_*`、`pip-*`、`pytest-of-*`）、覆盖率、
  构建产物、contracts 生成临时文件。
- `Makefile` 增加 `setup` / `dev` / `test` / `verify` / `docker` 目标。
- `README` 增加「V2.1 架构与开发规范」骨架与目标目录树。
- 测试进程清理 `NO_PROXY`（Windows `[::1]` 导致 httpx `Invalid port` 的环境问题）。

### Added（B1 后端分层与契约）

- `backend/app/` 分层（api / core / domain / services / agents / tools / infra）。
- SQLAlchemy 2.0 + Alembic 数据层，8 张表迁移。
- `/api/v1` 版本化接口与 OpenAPI / 事件 JSON Schema 快照入库。

### Added（B2 前端标准化）

- `frontend/src/features/` 目录、ESLint/Prettier、生成式类型、Vitest/RTL 测试骨架。

### Added（B3 基础功能 P0 / B4 内核升级）

- 设置中心、会话管理、运行管理、产物中心、上传增强、模板/技能、审计与用量、错误体验。
- ModelProvider 多供应商路由、真实 ReAct 循环、工具 schema 化、断线重连。

### Added（B5 测试/验收/文档）

- 契约快照：`scripts/export_openapi.py` + `contracts/openapi.v1.json`（32 paths / 40 ops）+
  `contracts/events.v1.schema.json`（12 类事件，JSON Schema draft-07），CI `contract` 门禁（diff 为空 + 前端生成类型一致性）。
- 根目录 30 条黑盒 smoke（`tests/`）：health/旧接口兼容、会话 CRUD/搜索/分页、6 格式上传与非法类型、
  SSE 批准/拒绝/取消/超时、断线重放（JSON + Last-Event-ID SSE）、产物中心（列表/筛选/删除/重新生成）、
  设置热更新、模型探测（脱敏）、模板、审计与用量导出、旧 `/api` 全链路。
- 真实模型 smoke（`tests/test_real_smoke.py`，默认跳过）：真实 DeepSeek 单次运行 PASS（含 approval + DOCX，
  tokens≈14.8k / 成本≈¥0.036；证据 `backend/tests/evidence/real_deepseek*.json`）。
- Playwright 6 条（`frontend/e2e/smoke.spec.ts`，B3 5 条 + QA 新增审计导出 1 条）。
- `docs/api.md` 升级为 V2.1 实际契约（v1 + 旧别名）；`docs/events.md` 升级 v1.1（tool.started /
  run.cancelled / 心跳 / Last-Event-ID / run.completed 扩展字段）；`docs/demo.md` 扩为 8 分钟脚本；
  `docs/acceptance.md` 按 DoD 30 条如实勾选；ADR 0004（monorepo 布局）、0005（模型路由）。
- `Makefile` 增加 `setup/api/mock-api/smoke/e2e/coverage/lint/contract/build/security/verify/clean` 等真实目标；
  `scripts/check_commit_msg.py`（Conventional Commits，pre-commit commit-msg 钩子）。
- `deploy/requirements.api.txt` 同步 pyproject 依赖；`Dockerfile.api` 适配 `backend.app.main:app`；
  compose 增加 `ENGINE` 与多供应商 Key 注入；CI 增加 smoke 步骤与 nightly Playwright job。

### Verified（本版实测证据）

- 后端：`pytest` → **117 passed, 1 skipped**；覆盖率 **84.70%**（门槛 70%；core 88%）。
- 30 条 smoke：**30 passed, 1 skipped**（直连 mock 8004；真实模型用例默认跳过）。
- 真实模型 smoke：**1 passed**（8000 真实 DeepSeek；artifact + approval + DOCX 校验）。
- 前端：`vitest` 25 passed；**覆盖率 8.61%（未达 60% 目标，如实记录）**；eslint/prettier/tsc 0 error。
- Playwright：**6 passed**（本机 Chrome，8000 + 5173）。
- 后端 lint：ruff check / ruff format --check / mypy 全部通过；bandit 无 medium/high 问题。
- Alembic：SQLite 从零执行 `upgrade head` 成功（0001→0002，8 张业务表 + alembic_version）。

### Known Issues（详见 KNOWN_ISSUES.md）

- 本机无 Docker：镜像/Compose 未实测（仅静态校验）；无 GNU make（Makefile 命令以原始命令等价执行）。
- `backend/pyproject.toml` 缺 `uv.lock`：依赖版本仍不可完全复现（pyyaml 已由 Lead 补入依赖）。
- 前端生成类型已与契约快照同步（task-14 重新生成，归一化 banner 后 diff 为空）；
  `pip-audit` 本机因缓存目录权限无法运行（CI 执行）。
- Playwright E2E 依赖本机 Chrome（`channel: 'chrome'`），CI 侧跑在 nightly。

## [0.1.0] - 2026-10-22

### Added

- V2.0 毛胚版首版交付：FastAPI + 进程内确定性 mock Agent + React 工作台。
- 主链路：建会话 → 上传素材 → SSE 事件流（计划/工具/审批/产物）→ 审批批准/拒绝 →
  DOCX 产物下载 → 审计。
- mock 模式（无 Key、断网可演示）、mock 邮件发件箱（绝不真实外发）、审批挂起与超时。
- 10 条黑盒 smoke、Docker Compose（web + api）、Nginx 反代（SSE 不缓冲）、
  PostgreSQL 迁移脚本、导出/样例脚本、ADR 0001–0003、KNOWN_ISSUES。

[Unreleased]: https://example.com/office-agent-mvp/compare/v0.1.0...HEAD
[0.2.0]: https://example.com/office-agent-mvp/releases/tag/v0.2.0
[0.1.0]: https://example.com/office-agent-mvp/releases/tag/v0.1.0
