"""代码工具：code.run_python（高风险，写盘的这一次要先过授权门控）。

为什么需要它：真实的文档加工经常是「拿 python-docx / pandas 改一遍」，
纯文本模板渲染覆盖不了。这里把一段 Python 脚本放进受控工作目录执行，
脚本可以向 `OA_OUTPUT_DIR` 写文件，执行完自动登记为产物。

安全边界（本地单用户 MVP 的取舍）：
- 写盘的脚本只有在「他这一轮确实让你产出文件」时才执行（见 `_script_mutates`
  与 `policy.decide_write`）；只读脚本（数页数、量字号）随时可以跑；
- 子进程环境变量白名单化：不带任何 API Key / token，避免脚本读到后端密钥；
- 固定工作目录 + 超时（默认 30s，上限 120s）+ 输出截断；
- 这不是内核级沙箱：脚本仍能访问本机文件系统，所以默认档位下写盘必须先过门控，
  always_ask 档位下每一步还要人工按一次。
"""

from __future__ import annotations

import ast
import contextlib
import difflib
import functools
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ...core.security import safe_filename
from ...core.utils import new_id, now_iso, sha256_file
from ...domain.entities import Artifact
from ...domain.enums import ArtifactType
from ...domain.formats import UTIL_MODULES, UTIL_SUPPORT, util_index
from ..spec import EFFECT_DESTRUCTIVE, EFFECT_OUTPUT, EFFECT_READ, ToolContext, tool

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
MAX_SCRIPT_CHARS = 20_000
MAX_OUTPUT_CHARS = 8_000
MAX_ARTIFACT_BYTES = 30 * 1024 * 1024

# 产物后缀 -> (产物类型, content-type)
_OUTPUT_TYPES: dict[str, tuple[ArtifactType, str]] = {
    ".docx": (
        ArtifactType.DOCX,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".pdf": (ArtifactType.PDF, "application/pdf"),
    ".xlsx": (
        ArtifactType.XLSX,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".md": (ArtifactType.TXT, "text/markdown; charset=utf-8"),
    ".txt": (ArtifactType.TXT, "text/plain; charset=utf-8"),
}

#: 中间稿 / 探针文件的特征。线上实况：一轮下来产物仓库里躺着 `_tmp_body.md`、
#: `_probe(2).pdf`——脚本拿它们中转正文、验证排版，写完就该扔，用户看到只会问
#: 「这些是什么」。所以它们进 `out/` 也不登记（脚本想攒稿，放 `$OA_RUN_DIR/tmp`）。
#:
#: 只认特别明确的：下划线 / 点开头（脚本作者的私有文件约定），以及名字里整段就是
#: tmp / temp / scratch / probe 的。`draft`、`backup`、`test` 不算——草案、备份、
#: 试算表有时真是要交付的东西。
_SCRATCH_PREFIXES = ("_", ".", "~$")
_SCRATCH_TOKENS = frozenset({"tmp", "temp", "scratch", "probe"})


def is_scratch_name(name: str) -> bool:
    """这个文件名是不是「中间稿 / 探针」——不该出现在产物仓库里。"""
    stem = Path(name).stem
    if not stem or stem.startswith(_SCRATCH_PREFIXES):
        return True
    # 只在 ASCII 词上切：中文文件名切不出来 token，自然不会误判
    tokens = re.split(r"[^a-z0-9]+", stem.lower())
    return any(token in _SCRATCH_TOKENS for token in tokens)


# 子进程可继承的环境变量：只留跑 Python 必需的，不含任何密钥/令牌
_ENV_ALLOWLIST = (    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
)


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原始 {len(text)} 字符）"


def _listing_hint(root: Path, outputs: Path) -> str:
    """路径类失败时，把 in/ 与 out/ 的真实文件名报给模型。

    线上连撞两次 FileNotFoundError 的那一轮，模型拿到的是「路径不存在」这种
    泛泛提示，只能换个名字再猜——它看不到目录里有什么。
    """

    def names(folder: Path) -> str:
        if not folder.is_dir():
            return "（空）"
        items = sorted(item.name for item in folder.iterdir() if item.is_file())
        return "、".join(items[:8]) if items else "（空）"

    return (
        f"目录里实际是：in/ 有 {names(root / 'in')}；out/ 有 {names(outputs)}。"
        "读回刚生成的文件要用 out/ 里的名字（产物登记名可能带 (2)，那是仓库去重）。"
    )


def _last_error_line(stderr: str) -> str:
    """取 traceback 的最后一句异常，而不是 `Traceback (most recent call last):`。

    摘要栏只放一行：`脚本执行失败（exit=1）：Traceback (most recent call last):`
    对用户和对模型都是废话——真正有用的是 `AttributeError: 'str' object has no attribute ...`。
    """
    for line in reversed((stderr or "").strip().splitlines()):
        text = line.strip()
        if not text:
            continue
        if text.startswith(("Traceback ", "During handling", "The above exception")):
            continue
        return text
    return ""


# 常见踩坑 -> 一句能照着改的提示。模型看得到这段，下一轮就不会再撞同一面墙。
_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("NameError", "is not defined"),
        "函数名不存在（不是格式不支持）：工具库只导出 __all__ 里的函数，先 "
        "`import docx_utils as u; print(u.__all__)` 拿到真实名单再写调用，不要凭印象拼函数名。",
    ),
    (
        ("has no attribute 'paragraphs'",),
        "docx_utils 的函数可以直接收文件路径（read_report(src)）；如果对象是 None，"
        "先确认路径来自 $OA_INPUT_DIR，而不是把 $OA_INPUTS 的 JSON 当路径。",
    ),
    (
        ("list index out of range",),
        "glob 没匹配到文件：素材目录是 $OA_INPUT_DIR（已把你指定的文件复制进去），"
        "$OA_INPUTS 是 JSON 清单、不是目录。",
    ),
    (
        ("No such file or directory", "FileNotFoundError"),
        "路径不存在：素材在 $OA_INPUT_DIR，产物写到 $OA_OUTPUT_DIR，不要用原始上传目录。"
        "要读回刚生成的产物，用上一次返回的 workspace_file（登记名可能带 (2)）。",
    ),
    (
        ("ModuleNotFoundError", "ImportError"),
        "依赖不可用：本机只保证 docx / openpyxl / pypdf / reportlab 与标准库，其余库请改用标准库实现。",
    ),
    (
        ("unexpected keyword argument", "positional argument"),
        "函数签名不符：不要猜参数名，docx_utils/xlsx_utils/pdf_utils/text_utils 里的函数"
        "可用 `import inspect; print(inspect.signature(函数名))` 先看一眼。",
    ),
    (
        ("PermissionError",),
        "文件被占用：用户可能正在 Word/WPS 里打开它，产物请写到 $OA_OUTPUT_DIR 换个文件名。",
    ),
    (
        ("UnicodeDecodeError",),
        "编码问题：读文本先用 text_utils.read_text(path)，它会自动探测编码。",
    ),
    (
        ("has no attribute 'footer'", "has no attribute 'header'"),
        "页眉页脚不在 Document 上：页码用 add_page_number(doc)（收 Document 或某个 section），"
        "要自己写页脚就是 doc.sections[0].footer。",
    ),
)


@functools.lru_cache(maxsize=1)
def _util_exports() -> dict[str, tuple[str, ...]]:
    """四个工具库导出的名字：AST 读 `__all__`，不执行脚本、不 import。"""
    base = Path(__file__).resolve().parents[2] / "services"
    exports: dict[str, tuple[str, ...]] = {}
    for module in UTIL_MODULES:
        path = base / f"{module}.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            ):
                continue
            with contextlib.suppress(ValueError, SyntaxError):
                names = ast.literal_eval(node.value)
                if isinstance(names, (list, tuple)):
                    exports[module] = tuple(str(name) for name in names)
            break
    return exports


def _closest_export(name: str) -> tuple[str, str] | None:
    """把猜错的名字对到真实函数上：open_doc → ensure_doc。"""
    best: tuple[float, str, str] | None = None
    for module, names in _util_exports().items():
        for candidate in difflib.get_close_matches(name, names, n=1, cutoff=0.55):
            score = difflib.SequenceMatcher(None, name, candidate).ratio()
            if best is None or score > best[0]:
                best = (score, module, candidate)
    return (best[1], best[2]) if best else None


def _signature_of(name: str) -> str:
    """拿到工具库里同名函数的真实签名；拿不到就返回空串。"""
    import importlib
    import inspect

    for module_name in UTIL_MODULES:
        try:
            module = importlib.import_module(f"app.services.{module_name}")
        except Exception:  # pragma: no cover - 依赖缺失时不该拖垮工具
            logger.debug("签名查询跳过模块 %s", module_name, exc_info=True)
            continue
        func = getattr(module, name, None)
        if callable(func):
            try:
                return f"{module_name}.{name}{inspect.signature(func)}"
            except (TypeError, ValueError):  # pragma: no cover
                return ""
    return ""


def _hint_for(stderr: str) -> str:
    body = stderr or ""
    # 参数写错：把真实签名递过去，比让模型再猜一次便宜得多
    mismatch = re.search(r"TypeError: (\w+)\(\) got an unexpected keyword argument '([^']+)'", body)
    if mismatch is not None:
        func_name, bad_kw = mismatch.group(1), mismatch.group(2)
        signature = _signature_of(func_name)
        if signature:
            return (
                f"{func_name} 没有 {bad_kw} 这个参数；真实签名是 {signature}。"
                "按签名改一次，别再用同名参数硬试。"
            )
    # 名字写错是最常见的一类：光说「NameError」没有用，得把真实函数名递到眼前
    missing = re.search(r"NameError: name '([^']+)' is not defined", body)
    if missing is None:
        missing = re.search(r"module '[^']+' has no attribute '([^']+)'", body)
    if missing is not None:
        hit = _closest_export(missing.group(1))
        if hit is not None:
            module, candidate = hit
            return (
                f"{module} 里没有 {missing.group(1)}，最接近的是 {candidate}；"
                f"先 `import {module}; print({module}.__all__)` 看一眼真实名单再写。"
            )
    for needles, hint in _HINTS:
        if any(needle in body for needle in needles):
            return hint
    return ""


def _install_utils(root: Path) -> None:
    """把 *_utils.py 复制进工作目录，脚本可以直接 `from docx_utils import *`。

    以前模型每写一次脚本都要现场拼 `w:eastAsia`、边框 XML、openpyxl 样式对象，
    中文容易掉字体、格式容易写错；现在共用的预设与常用操作只有一份
    （app/services/*_utils.py），每次运行复制进工作目录即可，脚本不用关心路径。

    复制哪几个库由 `domain/formats.py` 的格式表决定（`UTIL_MODULES`）：
    加一种格式就在那张表里加一行，这里自动跟上，不用再改。
    `UTIL_SUPPORT` 是「不宣传但要跟着走」的模块（`doc_lexicon` / `slide_lexicon` /
    `sheet_lexicon` / `text_lexicon` 四份词表），少了它们 `from docx_utils import *`
    会直接 ImportError。
    """
    base = Path(__file__).resolve().parents[2] / "services"
    for name in (*UTIL_MODULES, *UTIL_SUPPORT):
        source = base / f"{name}.py"
        if not source.is_file():
            continue
        # 复制失败不影响脚本执行，脚本里自己 import 第三方库也能跑
        with contextlib.suppress(OSError):
            shutil.copy2(source, root / f"{name}.py")


def _workspace(ctx: ToolContext) -> Path:
    """每次运行独立目录：<artifact_dir>/../workspace/<run_id>/{main.py,in,out,tmp}。

    `tmp/` 是给中间稿留的：中转正文、试排版、核对页数的副本都该落在这里。
    out/ 里的每个文件都会登记成产物，中间稿混进去就成了用户眼里的「多余文档」。
    """
    root = ctx.settings.artifacts_path.parent / "workspace" / ctx.run_id
    (root / "in").mkdir(parents=True, exist_ok=True)
    (root / "out").mkdir(parents=True, exist_ok=True)
    (root / "tmp").mkdir(parents=True, exist_ok=True)
    _install_utils(root)
    return root


def _prepare_inputs(
    ctx: ToolContext, root: Path, files: list[str] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """把选中的素材复制到 in/，并返回清单（脚本按文件名读取即可）。

    同时回报「点名了但会话里没有」的文件：以前这种情况静默跳过，脚本 glob 空目录后
    报 `IndexError: list index out of range`，看起来像代码写错了，其实是文件没送去。
    """
    prepared: list[dict[str, Any]] = []
    uploads = ctx.find_uploads(files)
    missing: list[str] = []
    if files:
        found = {upload.filename for upload in uploads}
        missing = [name for name in files if name.strip() and name not in found]
    for upload in uploads:
        source = Path(upload.path)
        target = root / "in" / safe_filename(upload.filename)
        if source.exists():
            try:
                shutil.copy2(source, target)
            except OSError:
                target = source
        prepared.append(
            {
                "filename": upload.filename,
                "path": str(target),
                "ext": upload.ext,
                "chars": upload.chars,
            }
        )
    # 点名的文件也可能是**本次运行刚生成的产物**（"把刚生成的 PDF 读回来再核一遍"）。
    # 以前这种名字在 uploads 里找不到，就被算成 missing，脚本对着空目录跑。
    for name in list(missing):
        resolved = _artifact_as_input(ctx, root, name)
        if resolved is not None:
            prepared.append(resolved)
            missing.remove(name)
    return prepared, missing


def _artifact_as_input(ctx: ToolContext, root: Path, name: str) -> dict[str, Any] | None:
    """把本次运行的产物按名字复制进 in/，让它像素材一样能被脚本读到。

    认两个名字：登记名（可能带 `(2)`）和工作目录原名。返回 None 表示确实没有。
    """
    lister = getattr(ctx.artifacts, "list", None)
    if lister is None:
        return None
    try:
        rows = lister(run_id=ctx.run_id, include_deleted=False, limit=200)
    except Exception:  # 仓储读不到就当没有，不能让脚本因此不跑
        return None
    for row in rows:
        aliases = {str(getattr(row, "filename", "") or "")}
        aliases.add(str((getattr(row, "extra", None) or {}).get("workspace_file") or ""))
        if name not in aliases:
            continue
        source = Path(str(getattr(row, "path", "") or ""))
        if not source.is_file():
            continue
        target = root / "in" / safe_filename(source.name)
        try:
            shutil.copy2(source, target)
        except OSError:
            continue
        return {
            "filename": source.name,
            "path": str(target),
            "ext": source.suffix.lstrip(".").lower(),
            "chars": 0,
        }
    return None


def _child_env(
    root: Path, outputs: Path, inputs: list[dict[str, Any]], ctx: ToolContext
) -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "OA_RUN_DIR": str(root),
            # 素材目录单独给一个「就是路径」的变量：
            # OA_INPUTS 是 JSON 清单，模型常把它当目录丢进 os.path.join/glob，
            # 于是 glob 拿到一串 JSON 字符、什么也匹配不到，报 IndexError。
            "OA_INPUT_DIR": str(root / "in"),
            "OA_OUTPUT_DIR": str(outputs),
            "OA_TMP_DIR": str(root / "tmp"),
            "OA_ARTIFACT_DIR": str(ctx.settings.artifacts_path),
            "OA_UPLOAD_DIR": str(ctx.settings.uploads_path),
            "OA_INPUTS": json.dumps(inputs, ensure_ascii=False),
        }
    )
    return env


def _previous_outputs(ctx: ToolContext) -> dict[str, Any]:
    """本次运行此前登记过的产物，按工作目录里的原文件名索引。

    同一个 run 里脚本可能跑两三遍（改完全心格式再跑一遍），拿它判断
    「这次产出的还是上次那份，还是真的改了」。
    """
    lister = getattr(ctx.artifacts, "list", None)
    if lister is None:
        return {}
    try:
        rows = lister(run_id=ctx.run_id, include_deleted=False, limit=200)
    except Exception:  # 仓储实现各异，读不到就当没有历史，不要因此让脚本结果作废
        return {}
    previous: dict[str, Any] = {}
    for row in rows:
        name = (getattr(row, "extra", None) or {}).get("workspace_file")
        if name:
            previous[str(name)] = row
    return previous


def _strip_proof_appendix(outputs: Path) -> None:
    """交付前摘掉「识别原文」这类对照附录（只动 .xlsx）。

    它是写稿人自己核对 OCR 结果用的：那一串流水文字行列本来就是错位的，
    摆在交付件里读者只会盯着它怀疑数据（用户 2026-11-10 明确要求删掉）。
    「核对说明」不在此列——那是结论（哪一格不确定、按什么规则复原的），要留。

    静默清理、不报错：清理失败不该让这一轮的脚本结果作废，产物原样登记即可。
    """
    from ...services import xlsx_utils  # 局部导入：openpyxl 不必在启动时就加载

    for item in sorted(outputs.iterdir()):
        if not item.is_file() or item.suffix.lower() != ".xlsx":
            continue
        with contextlib.suppress(Exception):
            removed = xlsx_utils.strip_proof_sheets(item)
            if removed:
                logger.info("已摘掉识别原文附录：%s（%s）", item.name, "、".join(removed))


def _register_outputs(
    ctx: ToolContext, outputs: Path, previous: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """把 out/ 里新生成的文件登记为产物。

    四件事以前没做对，用户看到的就是「跑了但文件不对」：
    - 同名重写被当成「已存在」跳过，产物里躺着上一版；
    - 同名重写另起一条记录再把旧记录软删，产物列表变成 `X.txt` / `X(2).txt` 一串，
      而界面上那张卡还指着已删的 id——点预览就是 404；
    - 同一个文件内容没变也重新登记，产物越攒越多；
    - 脚本失败也登记，半成品 docx 一打开就是坏的。
    """
    _strip_proof_appendix(outputs)
    registered: list[dict[str, Any]] = []
    skipped: list[str] = []
    unchanged: list[str] = []
    for item in sorted(outputs.iterdir()):
        if not item.is_file():
            continue
        if is_scratch_name(item.name):
            # 中间稿 / 探针：文件留在 out/ 里给自己用，但不登记成产物
            skipped.append(f"{item.name}（中间稿）")
            continue
        ext = item.suffix.lower()
        if ext not in _OUTPUT_TYPES:
            skipped.append(item.name)
            continue
        if item.stat().st_size > MAX_ARTIFACT_BYTES:
            skipped.append(f"{item.name}（超过 30MB）")
            continue
        digest = sha256_file(item)
        before = previous.get(item.name)
        if before is not None and before.sha256 == digest:
            unchanged.append(item.name)
            continue
        artifact_type, content_type = _OUTPUT_TYPES[ext]
        if before is not None and _rewrite_in_place(ctx, before, item, digest):
            # 同一份文件被重写：覆盖上一版、沿用同一条记录。
            registered.append(
                {
                    "artifact_id": before.id,
                    "filename": before.filename,
                    "workspace_file": item.name,
                    "size": item.stat().st_size,
                    "format": artifact_type.value,
                }
            )
            continue
        target = ctx.storage.new_artifact_path(item.name)
        try:
            shutil.copy2(item, target)
        except OSError:
            skipped.append(item.name)
            continue
        artifact = Artifact(
            id=new_id("art"),
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            type=artifact_type.value,
            filename=target.name,
            path=str(target),
            size=target.stat().st_size,
            sha256=digest,
            content_type=content_type,
            created_at=now_iso(),
            extra={"source": "code.run_python", "workspace_file": item.name},
        )
        ctx.artifacts.add(artifact)
        ctx.register_artifact(artifact)
        if before is not None:
            # 仓储不支持原地替换（测试替身）：退回老做法，旧版收进回收站
            with contextlib.suppress(Exception):
                ctx.artifacts.soft_delete(
                    before.id, now_iso(), {"reason": "superseded", "replaced_by": artifact.id}
                )
        registered.append(
            {
                "artifact_id": artifact.id,
                "filename": artifact.filename,
                # 产物名可能被仓库去重成 `X(2).pdf`，而 out/ 里仍是 `X.pdf`。
                # 模型拿 filename 回头去 out/ 读会直接 FileNotFoundError（线上踩过两次），
                # 所以把工作目录里的真实名字一并给它。
                "workspace_file": item.name,
                "size": artifact.size,
                "format": artifact_type.value,
            }
        )
    return registered, skipped, unchanged


def _rewrite_in_place(ctx: ToolContext, before: Any, item: Path, digest: str) -> bool:
    """同一轮里同名文件被重写：覆盖原文件、沿用原记录（id 不变）。

    为什么不新建一条再把旧的软删：界面上那张卡拿着旧 id，记录一软删，预览就 404；
    用户还会看到 `X.txt` 和 `X(2).txt` 并排躺着，分不清哪份是刚改的。
    覆盖是这里唯一说得通的语义——同一个工作文件名，就是同一份交付物。
    """
    replacer = getattr(ctx.artifacts, "replace_file", None)
    if replacer is None:
        return False
    try:
        target = Path(before.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        replacer(before.id, size=target.stat().st_size, sha256=digest, created_at=now_iso())
    except Exception:
        return False
    if before.id not in ctx.artifact_ids:
        ctx.artifact_ids.append(before.id)
    return True


#: 会改动磁盘的调用名（函数名或最后一段方法名）。用来回答一个问题：
#: **这一段脚本会不会写文件**。写才需要「他说过要动手」，读不需要。
#:
#: 判错的代价不对称：把读判成写，是模型量个字号也要用户先拍板，一步都跑不动；
#: 把写判成读，是一份没人要的文件。所以这里只列**确定会写**的，判不出来一律
#: 按写处理（见 `_script_mutates` 的兜底）。
_WRITE_CALLS = frozenset(
    {
        # 内置工具库里的生成 / 备份函数
        "make_pdf",
        "render_markdown_pdf",
        "merge_pdfs",
        "split_pdf",
        "rotate_pages",
        "watermark",
        "write_deck",
        "write_table",
        "write_csv",
        "append_records",
        "md_to_docx",
        "backup",
        # 文件对象 / Path 的落盘方法
        "write_text",
        "write_bytes",
        "writelines",
        "writestr",
        "mkdir",
        "makedirs",
        "touch",
        "unlink",
        "rmdir",
        "removedirs",
        "rmtree",
        # 第三方库的保存入口
        "save",
        "save_as",
        "savefig",
        "to_excel",
        "to_csv",
        "to_json",
        "to_parquet",
        "to_pickle",
        "to_html",
        "to_docx",
        "to_xlsx",
    }
)

#: 这些类的**构造**本身就意味着要写文件：pypdf 的 `PdfWriter` 只有一个用途，
#: reportlab 的 `SimpleDocTemplate`/`BaseDocTemplate` 也是。它们的落盘方法常常
#: 是一个不叫 `save` 的名字（`writer.write(path)` / `doc.build(story)`），
#: 只盯方法名会漏——线上就漏过一次：脚本用 `PdfWriter.write()` 写出了 PDF，
#: 却被判成只读，既没过门控也没弹审批。
#:
#: `Document()` 在 python-docx 里要分两种：无参是新建（写），`Document(path)`
#: 是打开读。所以它不在这里，单独判。
_WRITE_CTORS = frozenset(
    {
        "PdfWriter",
        "PdfFileWriter",
        "SimpleDocTemplate",
        "BaseDocTemplate",
        "Workbook",
        "Presentation",
    }
)

#: 带模块前缀才认的（`copy.copy` / `str.replace` 和 `shutil.copy` / `Path.replace`
#: 同名不同事，只按最后一段判会把读脚本全判成写）。
_WRITE_DOTTED = frozenset(
    {
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
        "os.remove",
        "os.unlink",
        "os.rename",
        "os.replace",
        "os.makedirs",
        "os.mkdir",
        "os.rmdir",
        "os.removedirs",
        "os.link",
        "os.symlink",
        "os.truncate",
        "os.write",
        "json.dump",
        "pickle.dump",
    }
)

#: 能藏住任意写操作的调用。出现就按写处理：静态看不出它要干什么，
#: 就不该替它担保「这只是读」。
#:
#: `importlib.import_module` 故意不在里面：`import_module("pdfplumber")` 只是
#: 探一下库在不在，而真要靠它写文件，`make_pdf` / `save` 这些名字照样会露出来。
_DYNAMIC_CALLS = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "runpy.run_path",
        "os.system",
        "os.popen",
        "os.execv",
        "os.execve",
        "os.spawnl",
        "os.spawnv",
    }
)

#: 这几个的签名是 `(file, mode)`，模式在第二个位置参数；其余 `.open(…)`
#: 是对象自己的方法（`Path.open("w")`），模式在第一个。
_OPENERS_MODE_ARG2 = frozenset(
    {
        "io.open",
        "codecs.open",
        "gzip.open",
        "bz2.open",
        "lzma.open",
        "tarfile.open",
        "ZipFile",
        "zipfile.ZipFile",
        "GzipFile",
        "gzip.GzipFile",
        "BZ2File",
        "bz2.BZ2File",
        "LZMAFile",
        "lzma.LZMAFile",
    }
)

#: 删了 / 改了收不回来的调用。它们和「写一份新文件」不是一回事：产物写多了只是
#: 多一个文件，删掉的原稿回不来。所以门控对这两类给不同的门槛——
#: 只要他说过「动手」，产物就可以写；要动已有文件，得是他明确让删/让改。
_DESTRUCTIVE_CALLS = frozenset(
    {
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.removedirs",
        "os.rename",
        "os.replace",
        "os.truncate",
        "shutil.rmtree",
        "shutil.move",
        "os.system",
        "os.popen",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.spawnl",
        "os.spawnv",
        "subprocess.run",
        "subprocess.call",
        "subprocess.Popen",
        "subprocess.check_output",
    }
)

#: 没有模块前缀也要认的不可逆动作（`path.unlink()` / `shutil.rmtree` 的裸写）。
_DESTRUCTIVE_BARE = frozenset({"unlink", "rmdir", "removedirs", "rmtree"})

_WRITE_MODE_CHARS = frozenset("wax+")

#: 合法的模式字符。用来把「模式」和「路径」分开：`pdfplumber.open("a.pdf")` 的
#: 第一个参数是路径，按「含 a 就算追加」的判法会被读成写。
_MODE_CHARS = frozenset("rwaxbt+U")


def _writes_mode(text: str) -> bool:
    """这个字符串像不像一个**写**模式。不像模式（比如路径）就不当模式看。"""
    mode = text.strip()
    if not mode or any(char not in _MODE_CHARS for char in mode):
        return False
    return any(char in _WRITE_MODE_CHARS for char in mode)


def _dotted(node: ast.AST) -> str:
    """把 `shutil.copy` / `_out.mkdir` 还原成点号名；还原不出来给空串。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _open_writes(node: ast.Call, *, mode_is_arg2: bool) -> bool:
    """`open(p, "w")` / `Path.open("w")` 这类带模式参数的打开算不算写。

    两套签名要分开看：`open(file, mode)` 的模式在第二个位置参数，`Path.open(mode)`
    在第一个。还有第三种——`pdfplumber.open(path)` 的第一个参数是**路径**，不是
    模式：只有字面量且像模式的字符串才当模式看，否则「读一个 PDF」会被判成
    「写一个 PDF」。
    """
    mode: ast.AST | None = None
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        if mode_is_arg2:
            if len(node.args) < 2:
                return False  # 没给模式，默认只读
            mode = node.args[1]
            if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
                return True  # 模式是算出来的，不赌
        else:
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                return False
            mode = first
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return _writes_mode(mode.value)
    return True


def _scan_script(script: str) -> tuple[bool, bool]:
    """扫一遍脚本：`(会不会写文件, 有没有动已有文件的动作)`。

    只看调用点，不做数据流分析——够用，而且不假装比实际更聪明：脚本要产出
    文件，总得落在某一次 `open(..., "w")` / `save()` / `make_pdf()` 上。
    语法错误的脚本按「会写 + 不可逆」处理（它也跑不起来，但门控没资格替它担保）。
    """
    try:
        tree = ast.parse(script or "")
    except SyntaxError:
        return True, True

    writes = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        last = dotted.rsplit(".", 1)[-1]
        # 先判不可逆：`os.remove` 同时出现在写词表里，顺序反了就会被算成普通写。
        if dotted in _DYNAMIC_CALLS or dotted in _DESTRUCTIVE_CALLS or last in _DESTRUCTIVE_BARE:
            return True, True
        if last == "open" or dotted in _OPENERS_MODE_ARG2:
            # 裸 `open(...)` / `ZipFile(...)` 是 `(file, mode)`；`Path(...).open(...)`
            # 是 `(mode)`——两者靠「是不是模块级调用」分开。
            module_level = (
                isinstance(node.func, ast.Name) and node.func.id == "open"
            ) or dotted in _OPENERS_MODE_ARG2
            if _open_writes(node, mode_is_arg2=module_level):
                writes = True
            continue
        if last in _WRITE_CALLS or dotted in _WRITE_DOTTED:
            writes = True
            continue
        if last in _WRITE_CTORS:
            writes = True
            continue
        # python-docx：`Document()` 是新建（写），`Document(path)` 是打开来读。
        if last == "Document" and not node.args and not node.keywords:
            writes = True
            continue
        # `writer.write(out)`：pypdf 的落盘入口，方法名是 `write`，前面挂的是
        # 一个变量名（`writer` / `w` / `out`），静态看不出它是文件还是 stdout。
        # 放过它就等于放过「一份没人要的文件」；认错它只是多门一道。
        # `sys.stdout.write` / `sys.stderr.write` 是例外：那是打印，不是落盘。
        if last == "write" and not dotted.startswith(("sys.stdout", "sys.stderr")):
            writes = True
    return writes, False


def _script_mutates(script: str) -> bool:
    """这段脚本会不会改动文件。判不出来算「会」。"""
    writes, _destructive = _scan_script(script)
    return writes


def _script_effect(script: str) -> str:
    """这段脚本的**效果分档**，给门控用：读 / 写产物 / 动已有文件。

    分档的意义在于门槛不同：
    - 读：不看授权，随时跑（量个字号、数页数，不该先问一句）；
    - 写产物：他把活儿交给你了，产物就是他想要的结果；
    - 动已有文件：删除、改名、覆盖——这类得是他明确让做的那一件。
    """
    writes, destructive = _scan_script(script)
    if destructive:
        return EFFECT_DESTRUCTIVE
    return EFFECT_OUTPUT if writes else EFFECT_READ


@tool(
    "code.run_python",
    "在本机受控目录执行 Python 脚本，用于复杂的文档加工（如用 python-docx 改写段落、"
    "用 openpyxl 汇总表格、用 pypdf 合并拆分 PDF、按页重排 PPT）。"
    "素材已被复制到 $OA_INPUT_DIR（目录，`glob.glob($OA_INPUT_DIR + '/*.docx')` 即可）；"
    "$OA_INPUTS 是 JSON 清单（含 filename/path/ext/chars），不是目录，别拿它做路径拼接。"
    "产物写入 $OA_OUTPUT_DIR，执行后自动登记；登记名可能带 (2)（仓库去重），"
    "out/ 里仍是原名——要读回刚生成的文件，用返回值里的 workspace_file。"
    "中间稿（中转正文、试排版、核对页数的副本）写 $OA_TMP_DIR，别写 out/："
    "out/ 里每个文件都会登记成产物，写成 `_tmp_body.md` 这类也会被跳过，白写。"
    "工作目录已预置工具库，"
    "函数都接受「Document/Workbook/PdfReader 对象或文件路径」，可直接传路径："
    f"{util_index()}。"
    "docx 常用调用：set_page(doc, PAGE_DEFAULT 或 preset='gongwen')、"
    "add_page_number(doc, align='center')、add_table_simple(doc, header, rows)、"
    "replace_text(doc, old, new)、backup(src, out_dir)；"
    "段落字体可以一把设：set_para(p, size=16, bold=True, align='center', space_after=10)，"
    "set_font(run, font='Consolas', size=10)。"
    "按扩展名优先 `from <格式>_utils import *`，不要现场拼 XML 或样式对象；"
    "不确定函数名或签名，先 `import docx_utils; print(docx_utils.__all__)` / "
    "`inspect.signature(read_report)` 查一眼，别猜。"
    "只读脚本（只打印、不写 $OA_OUTPUT_DIR）随时可以跑，不用等用户拍板；"
    "会产出文件的脚本才需要他已经同意动手。",
    risk="high",
    # 门控按脚本内容分档：读 / 写产物 / 动已有文件（删除、改名、跑外部命令）。
    # 三档门槛不同，前端那张卡也就不会再出现「跑脚本失败」这种事——
    # 读和写产物根本不需要拦，只有第三档才需要他明确说过要删/要改。
    effect=lambda args: _script_effect(str(args.get("script") or "")),
)
def run_python(
    ctx: ToolContext,
    script: str,
    files: list[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    code = (script or "").strip()
    if not code:
        return {"ok": False, "error": "script 不能为空", "_summary": "没有可执行的 Python 脚本"}
    if len(code) > MAX_SCRIPT_CHARS:
        return {
            "ok": False,
            "error": f"脚本过长（{len(code)} 字符，上限 {MAX_SCRIPT_CHARS}）",
            "_summary": "脚本超过长度上限，未执行",
        }

    timeout = max(5, min(MAX_TIMEOUT, int(timeout_seconds or DEFAULT_TIMEOUT)))
    root = _workspace(ctx)
    inputs, missing_inputs = _prepare_inputs(ctx, root, files)
    outputs = root / "out"
    previous = _previous_outputs(ctx)

    script_path = root / "main.py"
    script_path.write_text(code, encoding="utf-8")

    started = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 - 脚本执行是本工具的目的，且必须经审批
            [sys.executable, str(script_path)],
            cwd=str(root),
            env=_child_env(root, outputs, inputs, ctx),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = f"执行超时（>{timeout}s），已终止子进程"
    except OSError as exc:  # 解释器不可用等
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(exc),
            "_summary": f"无法启动 Python 解释器：{exc}",
        }

    duration_ms = int((time.perf_counter() - started) * 1000)
    ok = exit_code == 0
    if ok:
        registered, skipped, unchanged = _register_outputs(ctx, outputs, previous)
        partial: list[str] = []
    else:
        # 脚本中途失败：out/ 里很可能是写了一半的 docx，登记了用户一下载就是「打不开」
        registered, unchanged = [], []
        partial = (
            [item.name for item in sorted(outputs.iterdir()) if item.is_file()]
            if outputs.exists()
            else []
        )
        skipped = list(partial)
    hint = "" if ok else _hint_for(stderr)
    if not ok and ("FileNotFoundError" in stderr or "No such file" in stderr):
        # 路径类报错最容易连撞三次：模型看不到目录里到底有什么，只能一个名字一个名字猜。
        # 直接把两个目录的真实内容摆给它，下一次就能改对。
        hint = (hint + " " if hint else "") + _listing_hint(root, outputs)
    if missing_inputs:
        # 点名要处理的文件不在会话里：脚本按空目录跑，报错会指向代码，其实是文件没送去
        note = "、".join(missing_inputs[:3])
        hint = (hint + " " if hint else "") + (
            f"点名要处理的素材不在会话里：{note}；"
            "先核对文件名（或干脆不传 files，默认处理全部素材），别让脚本去 glob 空目录。"
        )

    if registered:
        summary = f"脚本执行完成，产出 {len(registered)} 个文件：" + "、".join(
            item["filename"] for item in registered[:3]
        )
    elif not ok:
        reason = _last_error_line(stderr) or "无错误输出"
        timeout_note = "（执行超时）" if exit_code == -1 else ""
        summary = f"脚本执行失败{timeout_note}（exit={exit_code}）：{_clip(reason, 160).strip()}"
        if partial:
            summary += (
                f"；out/ 里这 {len(partial)} 个文件没有登记（可能是半成品），改好重跑会重新登记"
            )
    elif unchanged:
        summary = "脚本执行完成，产物内容没有变化（同名文件内容一致，不需要重新登记）"
    else:
        summary = "脚本执行完成，没有新增文件（如需落盘请写入 $OA_OUTPUT_DIR）"

    result: dict[str, Any] = {
        "ok": ok,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": _clip(stdout),
        "stderr": _clip(stderr),
        "outputs": registered,
        "skipped": skipped,
        "unchanged": unchanged,
        "workspace": str(root),
        "_summary": summary,
    }
    if missing_inputs:
        result["missing_inputs"] = missing_inputs
    if hint:
        # 放在非 _ 字段里：模型能直接读到，下一轮就不用靠猜
        result["hint"] = hint
    return result
