# 表格处理知识库（xlsx / csv）

> 项目：office-agent-mvp ｜ 对应工具库：`backend/app/services/xlsx_utils.py`
> 依赖：`openpyxl>=3.1`（xlsx 读写 + 格式）、标准库 `csv`（csv 读写）。
> 不引入 pandas：分组汇总用 dict 足够，多一个大依赖只为几行代码不划算。

---

## 〇、能力边界

| 能做 | 做法 |
|---|---|
| 体检：sheet 列表、行列数、表头、空值率、公式数、合并区 | `read_report` |
| 读成记录（list[dict]） | `sheet_records` / `read_csv_records` |
| 新建表、追加行 | `write_table` / `append_records` |
| 表头样式、列宽、冻结、筛选、千分位/百分比/日期格式 | `style_header` / `autofit_columns` / `freeze_header` / `add_autofilter` / `apply_number_format` |
| 合计行（SUM 公式） | `add_total_row` |
| 分组汇总 | `group_sum` |
| csv ↔ xlsx | `read_csv_records` / `write_csv` / `write_table` |

| 不能做 | 原因 / 替代 |
|---|---|
| 保留原表的图表、数据透视表、条件格式 | openpyxl 读得到部分，写回会丢。替代：只改数据区，格式由模板驱动 |
| 读 .xls（97-2003） | openpyxl 不支持。让用户另存为 .xlsx |
| 公式结果自动重算 | openpyxl 不计算；`data_only=True` 读到的是「上次 Excel 保存时的缓存值」 |
| 超大表（>50 万行） | 内存与耗时不可控。先按 sheet/区间拆分处理 |

---

## 一、铁律：先体检，后动手

```python
from xlsx_utils import *

report = read_report(path)
for sheet in report["sheets"]:
    print(sheet["name"], sheet["rows"], sheet["cols"], sheet["headers"][:8],
          sheet["blank_ratio"], sheet["formulas"], sheet["merged"])
```

必须向用户报：哪张 sheet、多少行多少列、表头是什么、空值比例、有没有公式/合并单元格。
「表头在第 2 行」「合并单元格跨 3 行」这类结构如果不先看清，清洗必然错位。

---

## 二、格式预设（统一用库里的默认值）

| 项 | 默认 | 说明 |
|---|---|---|
| 表头底纹 | `EEF1F6` | 浅灰蓝，打印不费墨 |
| 表头字号 | 加粗、居中、细边框 `B9C0CC` | `style_header` |
| 冻结 | `A2`（首行冻结） | `freeze_header` |
| 筛选 | `A1:<末列><末行>` | `add_autofilter` |
| 列宽 | 8–40，中文按 2 宽估算 | `autofit_columns` |
| 金额 | `¥#,##0.00` | `apply_number_format` |
| 百分比 | `0.0%` | 同上 |
| 日期 | `yyyy-mm-dd` | 同上 |
| 合计 | 末行 `=SUM(B2:Bn)` | `add_total_row` |

不要在一张表里同时出现「1200.5」「1,200.50」「¥1200.5」三种写法。

---

## 三、场景库

| 需求 | 做法 |
|---|---|
| 合并多张表的明细 | 逐表 `sheet_records` → `records_to_rows` → `write_table`（加「来源文件」列） |
| 按部门/月份汇总 | `group_sum(records, "部门", "金额")` |
| 去重（按订单号） | 读 records 后按 key 建 dict，保留首/末条需说明规则 |
| 补列头 | 表头行不是 1 时 `header_row=2`；空表头自动补「列N」 |
| 加合计行 | `add_total_row(ws, ["B", "D"])`，写公式保证可复算 |
| 金额列统一两位小数 | `apply_number_format(ws, "D", "¥#,##0.00")` |
| 导出 csv 给别的系统 | `write_csv(path, records, encoding="utf-8-sig")`（Excel 打开不乱码） |
| 读 GBK 的 csv | `read_csv_records(path)` 自动 utf-8-sig → gb18030 |
| 按模板批量填数 | 读模板 sheet 结构 → 逐行 `append_records` → 另存新文件（不动模板） |

---

## 四、工具库函数表

```python
read_report(path)                                   # -> {file, sheets:[...], active}
sheet_records(path, sheet=None, header_row=1)       # -> list[dict]（跳过整行空白、表头去重）
read_csv_records(path, encoding=None)               # -> list[dict]（编码自动识别）
records_to_rows(records, headers=None)              # -> (headers, rows)
write_table(path, rows, headers=None, sheet="Sheet1", number_formats={}, widths={})
append_records(path, records, sheet=None)           # -> {appended, ignored_columns}
write_csv(path, records, encoding="utf-8-sig")
style_header(ws) / autofit_columns(ws) / freeze_header(ws)
add_autofilter(ws, columns, last_row) / apply_number_format(ws, "B", "¥#,##0.00")
add_total_row(ws, ["B"], label="合计", label_column="A")
group_sum(records, "部门", "金额")                   # -> [{部门, 笔数, 金额}] 按合计倒序
backup(src, out_dir)
```

---

## 五、Agent 提示词

```text
处理表格时遵守：
1. 先 read_report 报告 sheet/行列/表头/空值率/公式/合并单元格，再动手；表头不在第 1 行要说明。
2. 读数据一律 sheet_records（跳过整行空白、重复表头自动加后缀），不要直接遍历单元格拼 list。
3. 写产物用 write_table：表头加粗+冻结+筛选+列宽一步到位；金额/百分比/日期用 apply_number_format。
4. 计算结果必须可复算：合计用 add_total_row 写 SUM 公式；分组合计用 group_sum 并说明口径。
5. 空值与异常（金额为负、日期 2026-13-40）单独列出来，不静默丢弃；去重与合并要说清匹配键与匹配率。
6. 只写新文件或 $OA_OUTPUT_DIR，不改原始表格；确需原地改先 backup 并告知用户。
7. 交付前抽样回算 3 条：明细之和 = 合计；同比/环比能对上；总行数与报告一致。
```

---

## 六、常见坑（实测）

1. **`data_only=True` 读到 None**：文件从没用 Excel 打开保存过，公式没有缓存值。要么用 `data_only=False` 读公式，要么让用户先用 Excel 打开另存。
2. **写入后格式全丢**：`load_workbook` 默认保留样式；如果新建 workbook 再逐格写，样式要自己加 —— 所以用 `write_table`。
3. **表头重复**：两张表都有「金额」，合并后后者覆盖前者。`sheet_records` 会给重复表头加 `_2` 后缀。
4. **日期变成数字**（如 45678）：单元格是 date 类型时 `number_format` 才生效；读出来是 datetime 时不要再 `str()` 拼「00:00:00」。
5. **合并单元格读成 None**：只有左上角有值，其余为空。汇总前要「向下填充」并说明。
6. **列宽 auto 后仍显示 ###**：数字列太窄，`autofit_columns` 按内容估宽，金额列建议再手动加 2。
7. **csv 用 utf-8 写、Excel 打开乱码**：改 `utf-8-sig`（带 BOM）。
8. **公式以 = 开头被当文本**：openpyxl 写入 `=SUM(...)` 会存为公式；想存文本要先加 `'`。
9. **删除行用 `ws.delete_rows` 后公式引用不自动调整**：先改数据再写合计。
10. **文件名**：语义化（`销售汇总_2026-10.xlsx`），不要 `output.xlsx`。

---

## 七、校验清单

- [ ] 总行数 = 明细行数（不含表头/合计）
- [ ] 合计 = 明细之和（抽样 3 行手算比对）
- [ ] 表头与原表一致，没有多出「列2」这类占位列
- [ ] 金额/日期格式统一，无 `###`
- [ ] 空值、异常值在报告里单独列出
- [ ] 原表未被修改（哈希或修改时间不变）
- [ ] 结论写清：产物路径、行数、口径、未处理项
