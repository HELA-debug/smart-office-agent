"""提示词增强接口的语义矩阵：能用的输入一定要拿到可用文本，不能用的当场说清楚。

接口是输入框上的一颗按钮，前端只做「替换文本 + 一句提示」，所以这里的错误必须是
前端能直接展示的 4xx/5xx 与 code，而不是内部堆栈。
"""

from __future__ import annotations

import pytest
from tests.api.matrix import MATRIX_PREFIX

ENHANCE = f"{MATRIX_PREFIX}/prompts/enhance"


def test_enhance_returns_usable_text(api_client):
    response = api_client.post(
        ENHANCE, json={"text": "把这份会议记录整理成周报", "output_format": "docx"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trace_id"]
    # 矩阵环境是 mock：没有可用模型时必须退回本地规则，而不是报错
    assert body["source"] == "rules"
    assert body["text"].startswith("任务：把这份会议记录整理成周报")
    assert "输出格式：Word 文档（docx）" in body["text"]
    assert body["note"]


def test_enhance_without_format_leaves_format_line_out(api_client):
    response = api_client.post(ENHANCE, json={"text": "整理成周报"})
    assert response.status_code == 200
    assert "输出格式：" not in response.json()["text"]


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_enhance_rejects_blank_text(api_client, blank: str):
    response = api_client.post(ENHANCE, json={"text": blank})
    # 校验失败统一映射成 400 + BAD_REQUEST（core/errors 的处理器），不能是 500
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_enhance_rejects_overlong_text(api_client):
    """超过 4000 字：模型改不动，也没必要为它烧 token，直接让用户先精简。"""
    response = api_client.post(ENHANCE, json={"text": "字" * 4001})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_enhance_ignores_unknown_fields(api_client):
    """前端换版本时多传一个字段不该把按钮打成 400。"""
    response = api_client.post(ENHANCE, json={"text": "整理成周报", "unknown_field": {"a": 1}})
    assert response.status_code == 200, response.text


def test_enhance_requires_json_body(api_client):
    response = api_client.post(
        ENHANCE, content=b"not-json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BAD_REQUEST"
