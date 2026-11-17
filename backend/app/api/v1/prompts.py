"""提示词增强接口：输入框右侧那颗星形按钮按的就是这里。

一行需求（「把这材料整理成周报」）往往缺三样东西：要什么结构、多长、哪些不能编。
用户在输入框里补这些很啰嗦，交给模型一句话改写好再让人微调更省事。

约定：
- 不落库、不改会话：返回的文本由前端替换进输入框，用户不满意可以再点或直接改；
- 一定会返回可用文本：没配模型 / 模型超时都退回本地规则版，只在 ``source`` 与
  ``note`` 里说清楚来源，不让按钮变成报错入口。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...core.errors import AppError, ErrorCode
from ...services.prompt_enhancer import (
    MAX_INPUT_CHARS,
    enhance_prompt,
)
from ..deps import ContainerDep
from .schemas import PromptEnhanceIn, PromptEnhanceOut

router = APIRouter(tags=["prompts"])


@router.post(
    "/prompts/enhance",
    response_model=PromptEnhanceOut,
    summary="增强提示词：把一句话需求补成可执行的指令（没模型时按本地规则补全）",
    responses={400: {"description": "没写需求（全是空白）"}},
)
async def enhance(
    body: PromptEnhanceIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    """空文本在入口就拒掉：把空白喂给模型只会换回一句「请描述你的需求」。"""
    text = body.text.strip()
    if not text:
        raise AppError(ErrorCode.BAD_REQUEST, "先写一句需求，再点增强")
    if len(text) > MAX_INPUT_CHARS:
        raise AppError(
            ErrorCode.BAD_REQUEST,
            f"需求太长了（{len(text)} 字），先精简到 {MAX_INPUT_CHARS} 字以内再增强",
        )

    result = await enhance_prompt(
        container.runtime.router,
        container.settings,
        text,
        output_format=body.output_format,
    )
    return {"trace_id": request.state.trace_id, **result}
