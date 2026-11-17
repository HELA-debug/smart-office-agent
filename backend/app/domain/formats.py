"""文档格式矩阵：产物格式、上传格式、沙箱工具库的唯一事实源。

**放在 domain 层是有原因的**：`core/security.py` 要用它校验上传白名单，
而 `services/__init__.py` 反过来会 import `core.security`——这张表只要落在
services 包里，就是一个循环导入。它本身也只描述「一种文档格式是什么」，
不碰 IO、不碰仓储，是纯领域词汇。


为什么要有这个文件。同一件「支持哪些格式」的事，以前散在五处：

- `tools/builtin/doc.py` 的 `OUTPUT_FORMATS`（docx / pdf / xlsx / txt）
- `doc.generate_report` 的工具描述里手写的「format 支持 docx/pdf/xlsx/md/txt」
- `core/security.py` 的 `SUPPORTED_UPLOAD_EXTS`（docx / txt / pdf / xlsx）
- `tools/builtin/code.py` 的 `UTIL_MODULES`（docx / pdf / xlsx / text）
- `agents/real_engine.py` 提示词里手抄的 utils 清单

五处各说一套，后果不是难看，是**模型照着描述承诺 md、实现里那行永远走不到**
（`if output_format not in OUTPUT_FORMATS` 会先把 md 降级成 docx）。
同样地，`parsing.py` 里写好了 `_parse_csv`，白名单却拒收 csv。

所以这里收成一张表。表里每一行同时回答五个问题：能不能当素材上传、
能不能当产物产出、沙箱里用哪个库处理它、那个库最该先用哪几个函数、
登记成什么产物类型。其余模块只允许从这里读，不再自己维护一份。

**「能传」和「能产」是两件事，这张表把它们分开**：

- md：「产物是 Markdown」对普通用户没有意义，所以 `can_output=False`；
  但项目目录里的 README.md、随手存的笔记都是常见素材，所以 `can_upload=True`。
- csv：用户给一张数据表是常事（`can_upload=True`），把报告输出成 csv 则没有意义
  （`can_output=False`）。

两边都只承诺做得到的事——这正是以前五处清单各说一套时最容易骗人的地方。
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ArtifactType


@dataclass(frozen=True)
class FormatSpec:
    """一种文档格式的全部身份信息。

    `utils` 是沙箱里处理该格式的函数库（`app/services/<utils>.py`，脚本运行时复制进
    工作目录）。为 None 表示没有专用库——不代表不能处理，只代表脚本得自己来。

    `utils_api` / `utils_note` 是给模型看的用法提示：前者列出最该先用的函数名，
    后者一句话说清这个库替它省掉什么手工活。提示词与工具描述都从这里取，
    免得再加一种格式时又漏掉一处。
    """

    key: str
    label: str
    artifact_type: str
    content_type: str
    utils: str | None = None
    utils_api: str = ""
    utils_note: str = ""
    #: OOXML 格式解压后的根目录（docx→word/、xlsx→xl/、pptx→ppt/），校验 magic 用。
    ooxml_root: str = ""
    can_upload: bool = True
    can_output: bool = True
    #: 给人看的中文名（Word 文档 / PPT 演示文稿）。`label` 是徽标用的短大写名（DOCX）；
    #: 前端 `OUTPUT_FORMAT_COMPACT` 与这里逐字对应，改一处就要改另一处。
    display: str = ""

    @property
    def ext(self) -> str:
        """上传白名单用的后缀（带点）。"""
        return f".{self.key}"

    @property
    def mime(self) -> str:
        """不带 charset 参数的 MIME，浏览器上报的值按它比对。"""
        return self.content_type.split(";", 1)[0].strip()


_DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

#: 全表。顺序即前端「产物格式」下拉的默认顺序：常用的在前。
FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec(
        "docx",
        "DOCX",
        ArtifactType.DOCX.value,
        _DOCX_TYPE,
        "docx_utils",
        "read_report/ensure_doc/set_page/apply_body/apply_headings/set_para/add_table_simple/"
        "replace_text/backup",
        "中文文档的版式与替换都在这一层，不要自己拼 w:eastAsia、表框线这类 XML",
        ooxml_root="word/",
        display="Word 文档",
    ),
    FormatSpec(
        "pdf",
        "PDF",
        ArtifactType.PDF.value,
        "application/pdf",
        "pdf_utils",
        "read_report/extract_pages/make_pdf/merge_pdfs/split_pdf/watermark",
        "页数、加密、是否扫描件先体检；扫描件不要假装读到了文本",
        display="PDF 文档",
    ),
    FormatSpec(
        "xlsx",
        "XLSX",
        ArtifactType.XLSX.value,
        _XLSX_TYPE,
        "xlsx_utils",
        "read_report/sheet_records/write_grid/write_table/render_table/append_records/group_sum",
        "表格体检、读写与分组汇总；课表/排班这类二维表用 write_grid（按行列摆格子），"
        "不要现场拼 openpyxl 样式对象",
        ooxml_root="xl/",
        display="Excel 表格",
    ),
    FormatSpec(
        "pptx",
        "PPTX",
        ArtifactType.PPTX.value,
        _PPTX_TYPE,
        "pptx_utils",
        "read_report/extract_slides/deck_text/write_deck/backup",
        "按页读要点、按页生成幻灯片；一页最多六条要点，宁可多一页",
        ooxml_root="ppt/",
        display="PPT 演示文稿",
    ),
    FormatSpec(
        "txt",
        "TXT",
        ArtifactType.TXT.value,
        "text/plain; charset=utf-8",
        "text_utils",
        "read_text/heading_tree/md_table/md_to_docx",
        "编码自动识别（UTF-8/GBK/UTF-16）、看结构、Markdown 重排成 Word",
        display="纯文本",
    ),
    # 能当素材，但不作为产物：产物菜单里没有 Markdown 这一项。
    FormatSpec(
        "md",
        "Markdown",
        ArtifactType.TXT.value,
        "text/markdown; charset=utf-8",
        "text_utils",
        can_output=False,
        display="Markdown",
    ),
    # 只入格式：能上传、能解析，但不作为产物。xlsx_utils 里也有 csv 的读写。
    FormatSpec(
        "csv",
        "CSV",
        ArtifactType.XLSX.value,
        "text/csv; charset=utf-8",
        "xlsx_utils",
        can_output=False,
        display="CSV 表格",
    ),
)

_BY_KEY: dict[str, FormatSpec] = {spec.key: spec for spec in FORMATS}


def spec_of(key: str) -> FormatSpec | None:
    """按格式名取行；不认识就返回 None（别抛——上游要能体面降级）。"""
    return _BY_KEY.get((key or "").strip().lower())


def is_output_format(key: str) -> bool:
    spec = spec_of(key)
    return bool(spec and spec.can_output)


def is_upload_format(key: str) -> bool:
    spec = spec_of(key)
    return bool(spec and spec.can_upload)


#: 产物格式表：`{key: {label, artifact_type, content_type}}`。
#: 保持 dict 形态是因为 `doc.generate_report` 与既有测试都按 `spec["label"]` 取值。
OUTPUT_FORMATS: dict[str, dict[str, str]] = {
    spec.key: {
        "label": spec.label,
        "artifact_type": spec.artifact_type,
        "content_type": spec.content_type,
    }
    for spec in FORMATS
    if spec.can_output
}

#: 产物格式名的有序元组，给前端契约与断言用。
OUTPUT_FORMAT_KEYS: tuple[str, ...] = tuple(OUTPUT_FORMATS)

#: 接口文档里的类型提示串（`docx | pdf | ... | upload`）。
#: upload 不是产物格式，但它也是合法产物类型（上传素材），所以拼在最后。
ARTIFACT_TYPE_HINT = " | ".join((*OUTPUT_FORMAT_KEYS, "upload"))

#: 接口文档里的产物格式提示串（`docx | pdf | ...`），不带 upload。
OUTPUT_FORMAT_HINT = " | ".join(OUTPUT_FORMAT_KEYS)

#: 中文展示名：`{key: "Word 文档"}`。与前端 `OUTPUT_FORMAT_COMPACT` 逐字一致。
FORMAT_DISPLAY: dict[str, str] = {
    spec.key: spec.display or spec.label for spec in FORMATS if spec.display
}

#: 带后缀的完整展示名：`{key: "Word 文档（docx）"}`，提示词里指代格式用这个。
FORMAT_LABELS: dict[str, str] = {
    spec.key: f"{spec.display}（{spec.key}）"
    for spec in FORMATS
    if spec.can_output and spec.display
}

#: 没指定格式时用什么。docx 是办公场景的默认交付物。
DEFAULT_OUTPUT_FORMAT = "docx"

#: 上传白名单（带点后缀）。
UPLOAD_EXTS: set[str] = {spec.ext for spec in FORMATS if spec.can_upload}

#: 上传格式名的有序元组。
UPLOAD_FORMAT_KEYS: tuple[str, ...] = tuple(spec.key for spec in FORMATS if spec.can_upload)

#: OOXML 扩展名 -> 解压后必须存在的根目录。上传时靠它区分「改后缀骗过白名单」。
OOXML_ROOTS: dict[str, str] = {spec.ext: spec.ooxml_root for spec in FORMATS if spec.ooxml_root}


def _util_guide() -> tuple[tuple[str, str, str], ...]:
    """按表的顺序整理出工具库说明，同一个库只留第一次出现的那行。

    md / csv 与 txt / xlsx 共用库，所以必须去重——否则提示词里同一个库出现两遍。
    """
    seen: dict[str, tuple[str, str, str]] = {}
    for spec in FORMATS:
        if spec.utils and spec.utils_api and spec.utils not in seen:
            seen[spec.utils] = (spec.utils, spec.utils_api, spec.utils_note)
    return tuple(seen.values())


#: `(库名, 常用函数, 一句话用途)`，顺序即提示词里的顺序。
UTIL_GUIDE = _util_guide()

#: 沙箱要复制进工作目录的库，按表顺序去重。
UTIL_MODULES: tuple[str, ...] = tuple(name for name, _, _ in UTIL_GUIDE)

#: 不对外宣传、但必须跟着复制的模块：每个 `*_utils` 的字号/格式/符号都从各自的
#: 词表取，少一个脚本一 import 就 ImportError。它们不进提示词的库清单。
#: `sheet_render` 是表格版式引擎（样式实现的那一半），`xlsx_utils` 依赖它。
UTIL_SUPPORT: tuple[str, ...] = (
    "doc_lexicon",
    "slide_lexicon",
    "sheet_lexicon",
    "sheet_render",
    "text_lexicon",
)


def util_index() -> str:
    """一行式工具库清单：`docx_utils（a/b/c）、xlsx_utils（…）`。给工具描述用。"""
    return "、".join(f"{name}（{api}）" for name, api, _ in UTIL_GUIDE)


def util_bullets() -> list[str]:
    """逐行的工具库用法，给提示词用（每行自己带 `- `）。"""
    return [f"- {name}（{api}）：{note}" for name, api, note in UTIL_GUIDE]


def output_format_label(key: str) -> str:
    """产物格式的展示名（docx -> DOCX）；不认识的原样返回。"""
    spec = spec_of(key)
    return spec.label if spec else (key or "").upper()


def describe_output_formats() -> str:
    """一句话列出产物格式，给提示词和工具描述用（避免各处手写清单）。"""
    return " / ".join(OUTPUT_FORMAT_KEYS)
