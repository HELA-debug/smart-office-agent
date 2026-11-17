"""code.run_python 工具：高风险登记 + 真实执行 + 产物登记 + 环境变量脱敏。

这条链路是「让智能体用 Python 改文档」的基础：脚本在受控目录跑，
向 $OA_OUTPUT_DIR 写文件，执行完自动登记为可下载产物。
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.domain.entities import Artifact
from app.domain.enums import Risk
from app.tools.builtin import code as code_tools
from app.tools.registry import REGISTRY
from app.tools.spec import ToolContext


class FakeArtifactRepo:
    def __init__(self) -> None:
        self.items: list[Artifact] = []
        self.deleted: list[str] = []

    def add(self, artifact: Artifact) -> Artifact:
        self.items.append(artifact)
        return artifact

    def list(
        self,
        run_id: str | None = None,
        include_deleted: bool = False,
        limit: int = 200,
        **_kwargs: Any,
    ) -> list[Artifact]:
        rows = [
            item
            for item in self.items
            if (run_id is None or item.run_id == run_id)
            and (include_deleted or item.deleted_at is None)
        ]
        return rows[:limit]

    def soft_delete(
        self, artifact_id: str, deleted_at: str, extra: dict[str, Any] | None = None
    ) -> None:
        self.deleted.append(artifact_id)
        for item in self.items:
            if item.id == artifact_id:
                item.deleted_at = deleted_at
                if extra is not None:
                    item.extra.update(extra)

    def replace_file(self, artifact_id: str, *, size: int, sha256: str, created_at: str) -> None:
        for item in self.items:
            if item.id == artifact_id:
                item.size = size
                item.sha256 = sha256
                item.created_at = created_at
                item.deleted_at = None


class FakeStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def new_artifact_path(self, filename: str) -> Path:
        target = self.root / filename
        index = 1
        while target.exists():
            target = self.root / f"{Path(filename).stem}-{index}{Path(filename).suffix}"
            index += 1
        return target


def _context(tmp_path: Path) -> ToolContext:
    settings = Settings(
        artifact_dir=str(tmp_path / "artifacts"),
        upload_dir=str(tmp_path / "uploads"),
        approval_rules="code.run_python",
    )
    return ToolContext(
        thread_id="th_1",
        run_id="run_1",
        trace_id="tr_1",
        settings=settings,
        artifacts=FakeArtifactRepo(),  # type: ignore[arg-type]
        storage=FakeStorage(tmp_path / "artifacts"),  # type: ignore[arg-type]
    )


def test_registered_as_high_risk() -> None:
    spec = REGISTRY.get("code.run_python")
    assert spec is not None, "code.run_python 未注册"
    assert spec.risk == Risk.HIGH, "脚本执行必须走审批，不能是低风险"
    assert "code.run_python" in Settings().approval_tools


def test_runs_script_and_registers_output(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    result = code_tools.run_python(
        ctx,
        script=(
            "import os, pathlib\n"
            "out = pathlib.Path(os.environ['OA_OUTPUT_DIR'])\n"
            "(out / 'result.md').write_text('# 改好了\\n', encoding='utf-8')\n"
            "print('done')\n"
        ),
    )

    assert result["ok"] is True, result
    assert result["exit_code"] == 0
    assert "done" in result["stdout"]
    assert [item["filename"] for item in result["outputs"]] == ["result.md"]
    repo = ctx.artifacts
    assert isinstance(repo, FakeArtifactRepo)
    assert len(repo.items) == 1
    assert repo.items[0].filename == "result.md"
    assert repo.items[0].type == "txt"
    assert "1 个文件" in result["_summary"]


def test_scratch_names_are_recognised() -> None:
    """中间稿 / 探针的命名特征：下划线或点开头、名字里整段是 tmp/temp/probe/scratch。"""
    scratch = ["_tmp_body.md", "_probe(2).pdf", ".DS_Store", "~$报告.docx", "temp_table.xlsx", "probe.pdf"]
    keep = ["报告.md", "实验二_光照自适应调光_实验报告.pdf", "工作周报_2026-W47.docx", "draft.docx"]
    assert [name for name in scratch if not code_tools.is_scratch_name(name)] == []
    assert [name for name in keep if code_tools.is_scratch_name(name)] == []


def test_scratch_files_are_not_registered(tmp_path: Path) -> None:
    """中间稿留在 out/ 里给脚本自己用，但不进产物仓库。

    线上实况：一轮跑完，产物仓库里躺着 `_tmp_body.md`、`_probe(2).pdf`——
    中转正文和验证排版的副本次次都要占一个卡位，用户只会问「这些是什么」。
    """
    ctx = _context(tmp_path)
    result = code_tools.run_python(
        ctx,
        script=(
            "import os, pathlib\n"
            "out = pathlib.Path(os.environ['OA_OUTPUT_DIR'])\n"
            "(out / '报告.md').write_text('# 成品\\n', encoding='utf-8')\n"
            "(out / '_tmp_body.md').write_text('中转正文', encoding='utf-8')\n"
            "(out / '_probe.pdf').write_bytes(b'%PDF-1.4 stub')\n"
        ),
    )

    repo = ctx.artifacts
    assert isinstance(repo, FakeArtifactRepo)
    assert [item.filename for item in repo.items] == ["报告.md"]
    assert [item["filename"] for item in result["outputs"]] == ["报告.md"]
    # 文件本身还在 out/ 里：脚本下一步还要读它，只是不对外露面
    assert any("中间稿" in note for note in result.get("skipped", [])), result


def test_rewriting_same_file_reuses_one_artifact(tmp_path: Path) -> None:
    """同一轮里脚本重跑、再次写同名文件：覆盖上一版，不新增 `(2)` 副本。

    以前是「新建一条 + 把旧记录软删」，用户看到 `X.txt` 和 `X(2).txt` 并排，
    而界面上那张卡还指着已删的 id——点预览就是 404。
    """
    ctx = _context(tmp_path)
    first = code_tools.run_python(
        ctx,
        script=(
            "import os, pathlib\n"
            "out = pathlib.Path(os.environ['OA_OUTPUT_DIR'])\n"
            "(out / 'note.md').write_text('第一版', encoding='utf-8')\n"
        ),
    )
    second = code_tools.run_python(
        ctx,
        script=(
            "import os, pathlib\n"
            "out = pathlib.Path(os.environ['OA_OUTPUT_DIR'])\n"
            "(out / 'note.md').write_text('第二版，改长了一点', encoding='utf-8')\n"
        ),
    )

    repo = ctx.artifacts
    assert isinstance(repo, FakeArtifactRepo)
    assert len(repo.items) == 1, "同名重写不该多出一条记录"
    assert repo.deleted == [], "旧记录不能被软删（前端还拿着它的 id）"
    assert first["outputs"][0]["artifact_id"] == second["outputs"][0]["artifact_id"]
    assert repo.items[0].filename == "note.md"
    assert "第二版" in Path(repo.items[0].path).read_text(encoding="utf-8")
    assert repo.items[0].size == Path(repo.items[0].path).stat().st_size


def test_child_process_does_not_inherit_secrets(tmp_path: Path) -> None:
    os.environ["DEEPSEEK_API_KEY"] = "sk-should-not-leak"
    try:
        ctx = _context(tmp_path)
        result = code_tools.run_python(
            ctx,
            script="import os; print(os.environ.get('DEEPSEEK_API_KEY', 'missing'))",
        )
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)

    assert result["ok"] is True
    assert "sk-should-not-leak" not in result["stdout"]
    assert "missing" in result["stdout"]


def test_failed_script_reports_stderr(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    result = code_tools.run_python(ctx, script="raise SystemExit('boom')")

    assert result["ok"] is False
    assert result["exit_code"] != 0
    assert "脚本执行失败" in result["_summary"]


def test_failure_summary_is_the_real_exception_not_the_traceback_header(tmp_path: Path) -> None:
    """摘要要写 `AttributeError: ...`，而不是 `Traceback (most recent call last):`。
    前者能让人（和模型）一眼看出哪一步错了，后者只是噪音。"""
    ctx = _context(tmp_path)
    result = code_tools.run_python(ctx, script="print('x'.nosuchmethod())")

    assert result["ok"] is False
    assert "Traceback" not in result["_summary"]
    assert "AttributeError" in result["_summary"]


def test_failure_includes_actionable_hint_for_common_mistakes(tmp_path: Path) -> None:
    """把 $OA_INPUTS 当目录用是最高频的写法错误，失败时要直接告诉模型该用哪个变量。"""
    ctx = _context(tmp_path)
    result = code_tools.run_python(
        ctx,
        script=(
            "import glob, os\nsrc = glob.glob(os.path.join(os.environ['OA_INPUTS'], '*.docx'))[0]\n"
        ),
    )

    assert result["ok"] is False
    assert "OA_INPUT_DIR" in result.get("hint", "")


def test_input_dir_env_points_at_copied_material(tmp_path: Path) -> None:
    """$OA_INPUT_DIR 必须是「就是目录」的变量，脚本才能直接 glob。"""
    source = tmp_path / "素材.txt"
    source.write_text("原始内容", encoding="utf-8")
    ctx = _context(tmp_path)
    ctx.uploads = [
        type(
            "Upload",
            (),
            {
                "artifact_id": "up_1",
                "filename": "素材.txt",
                "path": str(source),
                "ext": "txt",
                "chars": 4,
                "text_path": "",
                "parsed": True,
            },
        )()
    ]

    result = code_tools.run_python(
        ctx,
        files=["素材.txt"],
        script=(
            "import glob, os, pathlib\n"
            "root = os.environ['OA_INPUT_DIR']\n"
            "print(sorted(p.name for p in pathlib.Path(root).iterdir()))\n"
            "print(glob.glob(os.path.join(root, '*.txt'))[0].endswith('素材.txt'))\n"
        ),
    )

    assert result["ok"] is True, result
    assert "['素材.txt']" in result["stdout"]
    assert "True" in result["stdout"]


def test_rejects_empty_or_oversized_script(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    empty = code_tools.run_python(ctx, script="   ")
    assert empty["ok"] is False
    assert "不能为空" in empty["error"]

    huge = code_tools.run_python(ctx, script="#" * (code_tools.MAX_SCRIPT_CHARS + 1))
    assert huge["ok"] is False
    assert "过长" in huge["error"]


def test_inputs_are_copied_into_workspace(tmp_path: Path) -> None:
    source = tmp_path / "素材.txt"
    source.write_text("原始内容", encoding="utf-8")
    ctx = _context(tmp_path)
    ctx.uploads = [
        type(
            "Upload",
            (),
            {
                "artifact_id": "up_1",
                "filename": "素材.txt",
                "path": str(source),
                "ext": "txt",
                "chars": 4,
                "text_path": "",
                "parsed": True,
            },
        )()
    ]

    result: dict[str, Any] = code_tools.run_python(
        ctx,
        files=["素材.txt"],
        script=(
            "import json, os, pathlib\n"
            "items = json.loads(os.environ['OA_INPUTS'])\n"
            "data = pathlib.Path(items[0]['path']).read_text(encoding='utf-8')\n"
            "print(len(items), data)\n"
        ),
    )

    assert result["ok"] is True
    assert "1 原始内容" in result["stdout"]


def test_failure_hint_points_at_real_function_names(tmp_path: Path) -> None:
    """函数名写错（历史上描述里写过一个不存在的 open_doc）时，不能只丢一句 NameError。

    这类错误看起来像「不支持这种格式」，实际只是名字不对；提示必须把模型引到
    `__all__` 这份真实名单上，下一轮才不会继续猜。
    """
    ctx = _context(tmp_path)
    result = code_tools.run_python(ctx, script="doc = open_doc('a.docx')")

    assert result["ok"] is False
    assert "NameError" in result["_summary"]
    hint = result.get("hint", "")
    assert "__all__" in hint
    # 光说「去查 __all__」还得猜一轮：直接把最接近的真实函数名递过去
    assert "ensure_doc" in hint


def test_description_only_names_functions_that_exist() -> None:
    """工具描述是模型唯一的 API 文档：描述里写一个不存在的函数，模型就会照着调用。

    所以描述里每个 `xxx_utils（a/b/c）` 的名字都必须真的在对应模块的导出里。
    这条用例把「描述漂移」挡在提交前，而不是等用户看到 NameError。
    """
    spec = REGISTRY.get("code.run_python")
    assert spec is not None
    groups = re.findall(
        r"(docx_utils|xlsx_utils|pdf_utils|text_utils)（([^）]*)）", spec.description
    )
    assert groups, "描述里应当按模块列出可用函数"

    checked = 0
    for module_name, body in groups:
        module = importlib.import_module(f"app.services.{module_name}")
        exported = set(getattr(module, "__all__", ()) or ())
        if not exported:
            exported = {name for name in dir(module) if not name.startswith("_")}
        for part in re.split(r"[、/]", body):
            name = part.strip().split("(")[0].strip()
            if not name.isidentifier() or name.isupper():
                continue
            checked += 1
            assert name in exported, f"{module_name} 没有 {name}：描述写错了，模型会照着调用"
    assert checked >= 10, "描述里的函数名太少，可能正则没匹配上"


def _write_script(text: str) -> str:
    """写一份同名产物的小脚本（同一次运行里跑两遍就是「改完再跑一次」）。"""
    return (
        "import os, pathlib\n"
        "out = pathlib.Path(os.environ['OA_OUTPUT_DIR']) / 'result.md'\n"
        f"out.write_text({text!r}, encoding='utf-8')\n"
    )


def test_rewrite_in_same_run_keeps_only_the_newest_version(tmp_path: Path) -> None:
    """改完再跑一遍：产物里不能还躺着上一版，也不该多出一份 `(2)` 副本。

    两条记录会引来两个麻烦：界面上的卡片还指着被软删的那条（点预览 404），
    以及 `result.md` / `result-1.md` 并排躺着，分不清哪份是刚改的。
    同一份交付物就在同一条记录上更新。
    """
    ctx = _context(tmp_path)
    first = code_tools.run_python(ctx, script=_write_script("# v1\n"))
    second = code_tools.run_python(ctx, script=_write_script("# v2\n"))

    repo = ctx.artifacts
    assert isinstance(repo, FakeArtifactRepo)
    assert len(repo.items) == 1
    assert repo.deleted == [], "旧版不该被软删——前端拿着它的 id"
    assert second["outputs"][0]["artifact_id"] == first["outputs"][0]["artifact_id"]
    assert Path(repo.items[0].path).read_text(encoding="utf-8") == "# v2\n"


def test_unchanged_output_is_not_registered_twice(tmp_path: Path) -> None:
    """内容没变就别再登记一份：产物中心不该为「又跑了一遍」多出一个同名文件。"""
    ctx = _context(tmp_path)
    code_tools.run_python(ctx, script=_write_script("# same\n"))
    again = code_tools.run_python(ctx, script=_write_script("# same\n"))

    repo = ctx.artifacts
    assert isinstance(repo, FakeArtifactRepo)
    assert len(repo.items) == 1
    assert again["outputs"] == []
    assert again["unchanged"] == ["result.md"]
    assert "没有变化" in again["_summary"]


def test_failed_script_does_not_register_half_written_output(tmp_path: Path) -> None:
    """脚本中途抛错时 out/ 里可能是写了一半的文件：登记了用户一下载就是「打不开」。"""
    ctx = _context(tmp_path)
    result = code_tools.run_python(
        ctx,
        script=(
            "import os, pathlib\n"
            "out = pathlib.Path(os.environ['OA_OUTPUT_DIR']) / 'result.md'\n"
            "out.write_text('half', encoding='utf-8')\n"
            "raise RuntimeError('boom')\n"
        ),
    )

    repo = ctx.artifacts
    assert isinstance(repo, FakeArtifactRepo)
    assert result["ok"] is False
    assert result["outputs"] == []
    assert result["skipped"] == ["result.md"]
    assert repo.items == []
    assert "没有登记" in result["_summary"]


def test_reported_filename_points_back_to_the_workspace_file(tmp_path: Path) -> None:
    """报给模型的 filename 必须能在 out/ 里找到同名文件。

    以前同名重写会被仓库改名成 `result-1.md`，而 out/ 里仍是 `result.md`，
    模型拿 filename 回去读就是 FileNotFoundError（线上撞过两次）。
    现在同一条记录上更新内容、不再改名，两个名字天然一致。
    """
    ctx = _context(tmp_path)
    first = code_tools.run_python(ctx, script=_write_script("# v1\n"))
    second = code_tools.run_python(ctx, script=_write_script("# v2\n"))

    assert first["outputs"][0]["filename"] == "result.md"
    assert second["outputs"][0]["filename"] == "result.md"
    assert second["outputs"][0]["workspace_file"] == "result.md"


def test_input_can_be_an_artifact_from_this_run(tmp_path: Path) -> None:
    """点名要读「刚生成的那份」时，它应该像素材一样被送进 in/。"""
    ctx = _context(tmp_path)
    produced = code_tools.run_python(ctx, script=_write_script("# v1\n"))
    name = produced["outputs"][0]["filename"]

    read_back = code_tools.run_python(
        ctx,
        script=(
            "import os, pathlib\n"
            "p = pathlib.Path(os.environ['OA_INPUT_DIR']) / 'result.md'\n"
            "print(p.read_text(encoding='utf-8'))\n"
        ),
        files=[name],
    )

    assert read_back["ok"] is True, read_back
    assert "v1" in read_back["stdout"]
    assert read_back.get("missing_inputs") is None


def test_missing_input_is_named_in_result(tmp_path: Path) -> None:
    """点名了不存在的素材时要直说是「文件没送去」，别让脚本去 glob 空目录后报 IndexError。"""
    ctx = _context(tmp_path)
    result = code_tools.run_python(ctx, files=["不存在.docx"], script="print('noop')")

    assert result["ok"] is True
    assert result["missing_inputs"] == ["不存在.docx"]
    assert "不存在.docx" in result["hint"]


def test_signature_mismatch_returns_real_signature(tmp_path: Path) -> None:
    """参数名写错时把真实签名递回去。

    历史现象：模型按「段落一把梭」的习惯写 `set_para(p, size=16, space_after=10)`，
    旧版 set_para 不认这些名字，一轮里连挂两次，用户只看到一片红。
    现在常见别名已经认了，剩下的写错也要一次改对——提示里必须带签名。
    """
    ctx = _context(tmp_path)
    result = code_tools.run_python(
        ctx,
        script=(
            "from docx import Document\n"
            "from docx_utils import *\n"
            "d = Document()\n"
            "p = d.add_paragraph('正文')\n"
            "set_para(p, spacing_after=10)\n"
        ),
    )

    assert result["ok"] is False
    hint = result.get("hint", "")
    assert "set_para" in hint
    assert "spacing_after" in hint
    # 签名本身要露出来，模型才能直接照着改
    assert "indent_pt" in hint


def test_script_mutates_separates_reading_from_writing() -> None:
    """授权门控只看「这一次会不会写文件」，这条判据就是它的唯一依据。

    判错的代价不对称：把读判成写，模型量个字号也要用户先拍板；把写判成读，
    是一份没人要的文件。所以读脚本要认得出来，写的脚本一个都不能漏。
    """
    read_only = [
        'from pypdf import PdfReader\nprint(len(PdfReader("a.pdf").pages))',
        'import pdfplumber\nwith pdfplumber.open("a.pdf") as pdf:\n    print(len(pdf.pages))',
        "import inspect, pdf_utils\nprint(inspect.signature(pdf_utils.make_pdf))",
        'import os\nfor name in os.listdir(os.environ["OA_OUTPUT_DIR"]):\n    print(name)',
        'print("a-b".replace("-", "_"))',
        'import re\nprint(re.compile("a").findall("aa"))',
        # 打印不是落盘：`sys.stdout.write` 天天出现在只读脚本里
        'import sys\nsys.stdout.write("done\\n")',
    ]
    writes = [
        'open("out/a.txt", "w").write("x")',
        'from pathlib import Path\nwith Path("out/a.txt").open("w") as f:\n    f.write("x")',
        'from pathlib import Path\nPath("out/a.txt").write_text("x")',
        'import pdf_utils\npdf_utils.make_pdf("out/a.pdf", title="t")',
        'from docx import Document\nDocument().save("out/a.docx")',
        'import shutil\nshutil.copy("a.pdf", "out/a.pdf")',
        'import os\nos.remove("out/a.pdf")',
        'exec("print(1)")',
        "def (",
        # 线上真实漏判：落盘入口叫 `write` / `build`，不叫 `save`
        'from pypdf import PdfWriter\nw = PdfWriter(clone_from="a.pdf")\nw.write("out/a.pdf")',
        'from reportlab.platypus import SimpleDocTemplate\ndoc = SimpleDocTemplate("out/a.pdf")\ndoc.build([])',
    ]

    missed = [script for script in read_only if code_tools._script_mutates(script)]
    assert not missed, f"只读脚本被判成写：{missed}"
    leaks = [script for script in writes if not code_tools._script_mutates(script)]
    assert not leaks, f"写脚本被判成读：{leaks}"
