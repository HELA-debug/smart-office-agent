# PDF 处理知识库（Agent 直接可用版）

> 项目：office-agent-mvp ｜ 对应工具库：`backend/app/services/pdf_utils.py`
> 依赖：`pypdf>=5`（读/拼）、`reportlab>=4`（写）。运行时由 `code.run_python` 复制进工作目录。

---

## 〇、能力边界（先说不能做的）

| 能做 | 做法 |
|---|---|
| 读页数 / 元数据 / 是否加密 | `read_report` |
| 抽取文本（有文本层的 PDF） | `extract_pages` |
| 合并、按页拆分、旋转 | `merge_pdfs` / `split_pdf` / `rotate_pages` |
| 加水印、加页码 | `watermark` / `make_pdf(page_numbers=True)` |
| 生成中文 PDF（标题/正文/项目符号/表格） | `make_pdf` / `render_markdown_pdf` |

| 不能做（不许假装能做） | 原因与替代方案 |
|---|---|
| 扫描件文字提取 | 没有文本层，`extract_pages` 返回空串。要 OCR 得另装引擎；先告知用户「这份是扫描件，只能看到 0 字」 |
| PDF → docx 高保真还原 | 版面（分栏、页眉页脚、浮动图）无法可靠映射。替代：让用户选「按内容重排一版 Word」 |
| 修改 PDF 里的文字 | 不是流式格式。替代：重新生成一版 PDF |
| 读中文 CID 字体写出的文本 | reportlab 的 STSong-Light 提取出来是 CID 码，不是汉字。所以「自己生成的中文 PDF 再读回校验」不成立 |

---

## 一、版式预设（`PAGE_PRESETS`）

| 预设 | 纸张 | 页边距 | 正文字号 / 行距 | 适用 |
|---|---|---|---|---|
| `default` | A4 | 上下左右 2.54cm | 10.5pt / 18 | 通用报告 |
| `compact` | A4 | 2.0cm | 10pt / 16 | 内容多、压页数 |
| `gongwen` | A4 | 上 3.7 / 下 3.5 / 左 2.8 / 右 2.6cm | 15.5pt / 28 | 公文风格 |
| `letter` | Letter | 2.54cm | 11pt / 18 | 英文/海外 |

字号关系固定：`title = body + 8`、`h1 = body + 5`、`h2 = body + 2`，行距 `leading` 单独给。
改版式只改 preset，不要在脚本里手写字号（同一份文档出现 10.5/11/12 三种正文最显廉价）。

---

## 二、场景库（按需求路由）

| 需求 | 做法 |
|---|---|
| 看这份 PDF 讲了什么 | `read_report` → 若 `scanned=true` 直接说明「无文本层」→ 否则 `extract_pages` 分段读 |
| 两份合同合并成一份 | `merge_pdfs([a, b], out)`，页序即列表顺序 |
| 只留第 3-5 页 | `split_pdf(src, out_dir, ranges=[(3, 5)])` |
| 每 10 页拆一份 | `split_pdf(src, out_dir, every=10)` |
| 扫描页倒着 | `rotate_pages(src, out, pages=[2, 3], degrees=180)` |
| 加「内部资料」水印 | `watermark(src, out, "内部资料", opacity=0.12)` |
| Word 报告另存 PDF | 先生成 docx 再 `make_pdf`（不要指望 docx→pdf 自动转换） |
| 把 Markdown 排版成 PDF | `render_markdown_pdf(md_text, out)` |
| 批量给每份 PDF 加页码 | 逐份 `merge` 不可行（页码层），改为重新生成或接受无水印；批量请先说明限制 |

---

## 三、工具库函数表

```python
from pdf_utils import *

read_report(path)                  # -> {pages, encrypted, metadata, text_chars, empty_pages, scanned, per_page_chars}
extract_pages(path, pages=[1,2])   # -> [{page, chars, text}]（pages 1 起，缺省整篇）
merge_pdfs(paths, out_path)        # -> {out, files, pages}
split_pdf(path, out_dir, every=10) # -> [out...]；或 ranges=[(1,3),(4,6)]
rotate_pages(path, out_path, pages=[1], degrees=90)   # -> out
watermark(path, out_path, "内部", opacity=0.12)        # -> out
make_pdf(out, title, blocks, preset="default", page_numbers=True, footer_text="")
render_markdown_pdf(md_text, out, preset="default")
backup(src, out_dir)               # -> 副本路径（改前必备份）
```

`make_pdf` 的 `blocks` 写法：

```python
blocks = [
    {"type": "h1", "text": "一、本周进展"},
    {"type": "p", "text": "完成 3 项，延期 1 项。"},        # 首行缩进
    {"type": "bullet", "text": "回款率 92%"},
    {"type": "table", "rows": [["项目", "进度"], ["A", "80%"]]},  # 第一行=表头
    {"type": "pagebreak"},
]
make_pdf("out.pdf", "周报", blocks, footer_text="内部资料")
```

- 标题用 `title=` 参数，不要在 blocks 里再写 h1，否则重复。
- 文本里的 `& < >` 已在库内转义，脚本里不用自己 `html.escape`。
- 表格列数不一致会挤成错位：先统一每行列数。

---

## 四、Agent 提示词（放进 system prompt 或工具描述）

```text
处理 PDF 时遵守：
1. 先 read_report：报页数、是否加密、每页文本量；scanned=true 时直接说明「扫描件没有文本层」，
   不要编造内容，也不要声称读到了文字。
2. 只读需要的页：extract_pages(path, pages=[...])；整篇超过 30 页时先给结构摘要再逐段处理。
3. 改动一律产出新文件：merge_pdfs / split_pdf / rotate_pages / watermark 都写 out_path，
   原文件只读；确需覆盖时先 backup。
4. 生成 PDF 用 make_pdf（中文已内置字体，页码默认开），不要现场写 reportlab 样式。
5. 交付前核对：页数、文件名、页脚页码；把「共 N 页 / 输出路径 / 做了什么」写在结论里。
6. PDF 不能直接改字、不能高保真转 Word：用户提这类需求时先说明限制，再给「重排一版」方案。
```

---

## 五、操作细节与常见坑（按踩坑频率）

1. **中文变方框/乱码**：reportlab 必须注册 `UnicodeCIDFont("STSong-Light")`；库里已做，别自己改成 DejaVuSans。
2. **Paragraph 解析标签报错**：正文含 `&`、`<`、`>` 会当 HTML 解析。库内已转义；若自己写 reportlab，必须转义。
3. **空文档 0 页**：没有任何 flowable 时 SimpleDocTemplate 不产页；库里补了一个空白段落。
4. **加密 PDF**：`is_encrypted=True` 但空口令能开的很常见（只加密权限）。口令错时 `decrypt` 抛异常，要如实告知用户。
5. **合并后书签/表单丢失**：`PdfWriter.add_page` 只搬页面内容，不搬 AcroForm 与 outline。需要保留表单时先说明。
6. **旋转角叠加**：`page.rotate()` 是相对当前角度累加；对已旋转 90° 的页再转 90° 等于 180°。
7. **页脚页码与内容重叠**：`gongwen` 预设下边距 3.5cm，页脚在 1.4cm 处，够用；`compact` 下内容满页时贴得近。
8. **扫描页混在文档里**：`read_report.empty_pages` 会列出来；不要因为「大部分有字」就说整份可读。
9. **水印透明度**：`opacity` 上限 0.6，超过会盖住正文；默认 0.12。
10. **文件名**：`split_pdf` 生成的 `stem_p1-3.pdf` 已语义化，不要改成 `out1.pdf`。

---

## 六、校验清单（交付前逐项）

- [ ] 页数与预期一致（合并/拆分后最易错）
- [ ] 文件能打开、大小 > 0（`make_pdf` 返回 `bytes` 字段）
- [ ] 中文正常（用 PDF 阅读器看，不要用 pypdf 文本反推）
- [ ] 页码/页脚位置正确，不与正文重叠
- [ ] 表格列数一致、无溢出页面
- [ ] 原始文件未被修改（只读；改动走 out_path）
- [ ] 结论里写清：共几页、输出路径、做了哪些操作

---

## 七、异常与边界处理

| 现象 | 判断 | 处理 |
|---|---|---|
| `PdfReadError` | 不是标准 PDF（改了后缀的图片/网页） | `safe_open_error(exc)` 转人话，要求用户换文件 |
| `FileNotFoundError` | 路径错/素材没登记 | 先 `file_list` 确认素材 |
| 文本几乎为空 | 扫描件或纯图片 PDF | 说明无文本层，询问是否只做页操作 |
| 页数 > 200 | 处理慢、内存高 | 先按区间拆分再处理，产物分文件 |
| 加密且有口令 | `decrypt` 失败 | 让用户提供无口令版本，不要尝试破解 |
