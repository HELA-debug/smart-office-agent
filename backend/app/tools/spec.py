"""工具抽象：ToolSpec + ToolContext + 注册表。

新增工具 = 写一个函数 + 一行 @tool 装饰器，不改主流程。
工具只依赖 domain 端口与注入的上下文，禁止自行建 DB/HTTP 连接。
"""

from __future__ import annotations

import inspect
import re
import types
import typing
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from ..core.config import Settings
from ..domain.entities import Artifact, UploadInfo
from ..domain.enums import Risk
from ..domain.ports import ArtifactRepository, FileStorage

_PY_TO_JSON: dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass
class ToolContext:
    """一次运行内共享的可变上下文（工具通过它取数、登记产物、更新计划）。"""

    thread_id: str
    run_id: str
    trace_id: str
    settings: Settings
    artifacts: ArtifactRepository
    storage: FileStorage
    mode: str = "mock"
    degraded: bool = False
    uploads: list[UploadInfo] = field(default_factory=list)
    material_text: str = ""
    material_sources: list[dict[str, Any]] = field(default_factory=list)
    """素材原文：`[{filename, text, chars, path}]`。"""
    rag_index: Any = None
    """素材的分块检索索引（`services.rag.Index`）。

    一次运行里可能检索十几次，每次重建索引都要把几万字重新切词；按素材清单
    缓存一份即可。素材在本轮不会变（上传发生在运行之前），所以缓存键用
    「文件名 + 字数」就够，不必逐字节比对。
    """
    rag_key: str = ""
    material_facts: dict[str, Any] = field(default_factory=dict)
    """脚本体检出来的素材结构（doc.analyze_material）：份数/段数/字数/图片/图注。"""
    todos: list[dict[str, Any]] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    llm_text: str = ""
    reading: Any = None
    """本轮的理解结论（`agents.reading.TurnReading`）。

    类型写 Any 是为了不让工具层反向依赖 agents 层；用到它的只有子智能体：
    它们在内部直接调 handler，绕开了引擎的写权限门控，得自己按同一套
    `policy.decide_write` 过一遍。引擎主链路不用它——那边在 `_run_single_tool`
    里已经拦过了。
    """
    message: str = ""
    """他这一轮的原话。子智能体过门控时要用：`policy.decide_write` 会拿它查
    「先别 / 我点头了再 / 算了」这类确定性否决，没有原文就只剩理解层的结论。"""
    doc_style: dict[str, Any] = field(default_factory=dict)
    """这一轮用户在「文档格式」里点的那几项（字体 / 字号 / 字形 / 行距 / 缩进 / 对齐）。

    用户点了就以它为准，没点的那几项留空、继续跟版式预设走——所以在生成文档时
    只覆盖真正给了值的字段，不能用默认值把预设整个顶掉。空字典 = 全部由 Agent 判断。"""

    def find_uploads(self, names: list[str] | None = None) -> list[UploadInfo]:
        if not names:
            return list(self.uploads)
        wanted = {name.strip() for name in names if name and name.strip()}
        return [upload for upload in self.uploads if upload.filename in wanted]

    def register_artifact(self, artifact: Artifact) -> Artifact:
        self.artifact_ids.append(artifact.id)
        return artifact


#: 一次调用的**效果分级**。门控以前只问「会不会写」，于是「往产物目录写一份新
#: PDF」和「删掉你的素材」被算成一件事，同一个门槛；现在分三档，判据才精细得起来。
#:
#: - `read`：只读。数页数、量字号、看一眼目录——随时可以跑，不该惊动他。
#: - `output`：只往产物目录写新文件。这是他本来就要的结果，授权只取决于
#:   「他这一轮是不是让你动手」，不取决于「写」这个动作本身。
#: - `destructive`：会动到已有文件（删除 / 改名 / 覆盖 / 执行外部命令）。
#:   这里才需要更强的凭据：一句「你看着弄」不足以担保「删掉那份旧稿」。
EFFECT_READ = "read"
EFFECT_OUTPUT = "output"
EFFECT_DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: Risk
    schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]] = field(repr=False)
    #: 这一次调用会不会改动用户的文件——授权门控只问这一件事。
    #:
    #: 默认由 `risk` 推出来（高风险 = 会写），但有些工具**一次调用里既能读也能写**：
    #: `code.run_python` 跑一段打印 PDF 页数的脚本，和跑一段生成 PDF 的脚本，
    #: 是两件事。按工具名一刀切，读也被当成写——线上就发生过模型只想量一下标题
    #: 字号，卡片却写「他还在商量，没有拍板」，一步都没跑成。
    mutates: Callable[[dict[str, Any]], bool] | None = field(default=None, repr=False)
    #: 更细的效果：返回 `EFFECT_READ` / `EFFECT_OUTPUT` / `EFFECT_DESTRUCTIVE`。
    #: 给了它就按它判，`mutates` 退成兜底（两者都缺省 = 高风险一律按会写处理）。
    effect: Callable[[dict[str, Any]], str] | None = field(default=None, repr=False)

    @property
    def requires_approval_default(self) -> bool:
        return self.risk == Risk.HIGH

    def effect_kind(self, args: dict[str, Any]) -> str:
        """这一次调用落在哪一档。

        判不出来的方向要选对：**按最严的那一档办**。门控认不出这一步会动什么，
        就没资格替它担保。
        """
        if self.risk != Risk.HIGH:
            return EFFECT_READ
        if self.effect is not None:
            try:
                value = str(self.effect(args) or "")
            except Exception:  # 分类器自己炸了，别把门拆了
                return EFFECT_DESTRUCTIVE
            if value in (EFFECT_READ, EFFECT_OUTPUT, EFFECT_DESTRUCTIVE):
                return value
            return EFFECT_DESTRUCTIVE
        if self.mutates is None:
            # 没声明效果的高风险工具：不知道它会不会动已有文件，就按会动办。
            # 想告诉门控「我只是往产物目录写新文件」的工具，必须自己声明。
            return EFFECT_DESTRUCTIVE
        try:
            return EFFECT_OUTPUT if self.mutates(args) else EFFECT_READ
        except Exception:
            return EFFECT_DESTRUCTIVE

    def mutates_files(self, args: dict[str, Any]) -> bool:
        """这一步要不要「他说过要动手」这道授权。

        判不出来时按「会写」处理：门控认不出这一步的性质，就没资格替它担保。
        """
        return self.effect_kind(args) != EFFECT_READ


# OpenAI function name 只允许 [a-zA-Z0-9_-]；内部工具名用 `group.verb`，
# 暴露给模型 / OpenAI tools schema 时统一转成 `group_verb`，调用回来再映射。
_TOOL_API_NAME_RE = re.compile(r"[^0-9A-Za-z_-]")


def _json_type(annotation: Any) -> dict[str, Any]:
    if annotation in (inspect.Parameter.empty, Any):
        return {"type": "string"}
    origin = typing.get_origin(annotation)
    if origin in (list, tuple, set):
        args = typing.get_args(annotation)
        return {"type": "array", "items": _json_type(args[0]) if args else {"type": "string"}}
    if origin is dict:
        return {"type": "object"}
    if origin is typing.Union or origin is types.UnionType:
        union_args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _json_type(union_args[0]) if union_args else {"type": "string"}
    return {"type": _PY_TO_JSON.get(annotation, "string")}


def build_schema(handler: Callable[..., Any], *, required_all: bool = False) -> dict[str, Any]:
    """由函数签名自动生成 JSON Schema；跳过 ctx 与下划线私有参数。"""
    hints: dict[str, Any]
    try:
        hints = inspect.get_annotations(handler, eval_str=True)
    except Exception:
        hints = {}
    signature = inspect.signature(handler)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for index, (name, param) in enumerate(signature.parameters.items()):
        if index == 0 and name in ("ctx", "context"):
            continue
        if name.startswith("_"):
            continue
        annotation = hints.get(name, param.annotation)
        schema = _json_type(annotation)
        if param.default is inspect.Parameter.empty or required_all:
            required.append(name)
        else:
            if isinstance(param.default, (str, int, float, bool)) or param.default is None:
                schema = {**schema, "default": param.default}
        properties[name] = schema
    return {"type": "object", "properties": properties, "required": required}


def api_tool_name(name: str) -> str:
    """内部工具名 -> OpenAI function 名（`file.read` -> `file_read`）。"""
    return _TOOL_API_NAME_RE.sub("_", name.replace(".", "_"))


def openai_tool(spec: ToolSpec) -> dict[str, Any]:
    """由 ToolSpec 自动生成 OpenAI tools 中的一项（schema 复用 build_schema 结果）。"""
    description = spec.description
    if spec.risk == Risk.HIGH:
        description += "（高风险：执行前内核会核对这一步是否由他明确要求，没说就别硬做）"
    return {
        "type": "function",
        "function": {
            "name": api_tool_name(spec.name),
            "description": description,
            "parameters": spec.schema,
        },
    }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        risk: Risk | str = Risk.LOW,
        *,
        mutates: Callable[[dict[str, Any]], bool] | None = None,
        effect: Callable[[dict[str, Any]], str] | None = None,
    ) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
        pattern = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$")
        if not pattern.match(name):
            raise ValueError(f"工具名必须形如 group.verb：{name}")
        risk_value = Risk(risk) if isinstance(risk, str) else risk

        def decorator(handler: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                risk=risk_value,
                schema=build_schema(handler),
                handler=handler,
                mutates=mutates,
                effect=effect,
            )
            return handler

        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolSpec]:
        return [self._tools[name] for name in self.names()]

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "risk": spec.risk.value,
                "schema": spec.schema,
            }
            for spec in self.all()
        ]

    def approval_tools(self, rules: set[str]) -> list[str]:
        return [spec.name for spec in self.all() if spec.risk == Risk.HIGH and spec.name in rules]

    # ---------- 暴露给模型的 OpenAI tools ----------
    def openai_tools(self, only: Collection[str] | None = None) -> list[dict[str, Any]]:
        """自动生成 OpenAI tools 数组（供真实模型 function calling 使用）。

        `only` 给定时只导出这几件工具。工具不出现在上下文里，模型就不会顺手用它：
        一句「你好」看见 doc_generate_report，很容易理解成「那我把这批材料出一份文档」。
        """
        specs = self.all() if only is None else [s for s in self.all() if s.name in set(only)]
        return [openai_tool(spec) for spec in specs]

    def api_name_map(self) -> dict[str, str]:
        """OpenAI function 名 -> 内部工具名。"""
        return {api_tool_name(spec.name): spec.name for spec in self.all()}

    def resolve(self, name: str) -> ToolSpec | None:
        """解析模型返回的函数名：兼容 `file_read` / `file.read` 两种写法。"""
        spec = self.get(name)
        if spec is not None:
            return spec
        for candidate in self.all():
            if api_tool_name(candidate.name) == name:
                return candidate
        return None


# 全局注册表：builtin 模块导入即注册
REGISTRY = ToolRegistry()
tool = REGISTRY.register
