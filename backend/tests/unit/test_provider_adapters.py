"""Provider 适配单测：httpx.MockTransport 验证鉴权/请求/响应解析/错误分类。

不访问网络、不读取真实 Key；所有供应商请求都被 MockTransport 拦截。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from app.core.config import Settings
from app.providers import (
    DeepSeekProvider,
    ErrorCategory,
    GLMProvider,
    ProviderError,
    ProviderResult,
    QwenProvider,
)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "mock_mode": False,
        "model_provider": "deepseek",
        "model_name": "deepseek-chat",
        "model_fallback_chain": "deepseek,qwen,glm,mock",
        "deepseek_api_key": "sk-test-deepseek",
        "qwen_api_key": "",
        "glm_api_key": "",
        "openai_api_key": "",
        "openai_base_url": "",
    }
    base.update(overrides)
    return Settings(**base)


def make_provider(
    cls: type[DeepSeekProvider] | type[QwenProvider] | type[GLMProvider],
    handler: Any,
    settings: Settings | None = None,
) -> Any:
    settings = settings or make_settings()

    def factory(_settings: Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False, timeout=5.0
        )

    return cls(settings, http_client_factory=factory)


def completion(
    *,
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
    model: str = "deepseek-chat",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def test_deepseek_request_shape_and_tool_call_parsing() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=completion(
                content="我先读取素材。",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "file_read",
                            "arguments": '{"files": ["周报素材.txt"]}',
                        },
                    }
                ],
            ),
        )

    provider = make_provider(DeepSeekProvider, handler)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "file_read",
                "description": "读取素材",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    result: ProviderResult = asyncio.run(
        provider.chat([{"role": "user", "content": "生成周报"}], tools=tools, max_tokens=256)
    )

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test-deepseek"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["tools"] == tools
    assert result.text == "我先读取素材。"
    assert result.prompt_tokens == 11 and result.completion_tokens == 7
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "file_read"
    assert call.arguments == {"files": ["周报素材.txt"]}
    assert call.id == "call_1"


def test_leaked_tool_markup_is_stripped_from_text() -> None:
    """正文里泄漏的工具标记要切掉。

    deepseek-flash 偶尔把工具调用写成正文里的 DSML 标记，而不是结构化 tool_calls：
    那段既不能执行、也不该给人看，原样吐进对话就是一段乱码（真实会话里出现过）。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=completion(
                content=(
                    "先把 old_weekly.docx 读出来再合并。\n\n"
                    '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="file_read">\n'
                    "</｜｜DSML｜｜ calls>"
                )
            ),
        )

    provider = make_provider(DeepSeekProvider, handler)
    result = asyncio.run(provider.chat([{"role": "user", "content": "读一下"}], max_tokens=256))

    assert result.text == "先把 old_weekly.docx 读出来再合并。"
    # 标记被切掉，但「它想读一份文件」这件事没丢：调用被捞回来了
    assert [call.name for call in result.tool_calls] == ["file_read"]


def test_text_that_is_only_tool_markup_recovers_the_call() -> None:
    """整段都是标记时，把调用捞回来接着跑——总比把整次运行降级成「模型不可用」强。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=completion(
                content=(
                    "<｜｜DSML｜｜ calls>\n"
                    '<｜｜DSML｜｜ invoke name="file_read">\n'
                    '<｜｜DSML｜｜ parameter name="files" string="false">'
                    '["old_weekly.docx"]</｜｜DSML｜｜ parameter>\n'
                    "</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>"
                )
            ),
        )

    provider = make_provider(DeepSeekProvider, handler)
    result = asyncio.run(provider.chat([{"role": "user", "content": "读一下"}], max_tokens=256))

    assert result.text == ""
    assert [call.name for call in result.tool_calls] == ["file_read"]
    assert result.tool_calls[0].arguments == {"files": ["old_weekly.docx"]}


def test_providers_use_official_openai_compatible_base_urls() -> None:
    settings = make_settings(qwen_api_key="sk-qwen", glm_api_key="sk-glm")
    deepseek = DeepSeekProvider(settings)
    qwen = QwenProvider(settings)
    glm = GLMProvider(settings)
    assert deepseek.base_url == "https://api.deepseek.com/v1"
    assert qwen.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert glm.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert qwen.model == "qwen-plus"
    assert glm.model == "glm-4-plus"
    # 主供应商的模型名可配
    primary_qwen = QwenProvider(
        make_settings(model_provider="qwen", model_name="qwen-max", qwen_api_key="sk-qwen")
    )
    assert primary_qwen.model == "qwen-max"


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, ErrorCategory.AUTH),
        (403, ErrorCategory.AUTH),
        (429, ErrorCategory.RATE_LIMIT),
        (500, ErrorCategory.SERVER),
        (503, ErrorCategory.SERVER),
        (400, ErrorCategory.BAD_FORMAT),
    ],
)
def test_error_classification_by_status(status: int, category: ErrorCategory) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    provider = make_provider(DeepSeekProvider, handler)
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    error = excinfo.value
    assert error.category == category
    assert error.status_code == status
    assert error.retryable is (category in (ErrorCategory.RATE_LIMIT,))


def test_timeout_and_network_errors_are_classified() -> None:
    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timeout")

    def network_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ProviderError) as timeout_error:
        asyncio.run(
            make_provider(DeepSeekProvider, timeout_handler).chat(
                [{"role": "user", "content": "hi"}]
            )
        )
    assert timeout_error.value.category == ErrorCategory.TIMEOUT
    assert timeout_error.value.retryable is True

    with pytest.raises(ProviderError) as network_error:
        asyncio.run(
            make_provider(DeepSeekProvider, network_handler).chat(
                [{"role": "user", "content": "hi"}]
            )
        )
    assert network_error.value.category == ErrorCategory.NETWORK


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"message": {"role": "assistant", "content": ""}}]},
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "x",
                        "tool_calls": [
                            {"id": "c", "function": {"name": "f", "arguments": "not-json"}}
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": "not-a-dict"}]},
    ],
)
def test_bad_format_responses_are_classified(body: dict[str, Any]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = make_provider(DeepSeekProvider, handler)
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    assert excinfo.value.category == ErrorCategory.BAD_FORMAT


def test_unconfigured_provider_raises_and_probe_returns_reason() -> None:
    provider = DeepSeekProvider(make_settings(deepseek_api_key="", openai_api_key=""))
    assert provider.configured is False
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    assert excinfo.value.category == ErrorCategory.UNCONFIGURED
    ok, reason = asyncio.run(provider.probe())
    assert ok is False
    assert "未配置" in reason


def test_probe_success_and_api_key_never_exposed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=completion(content="ok", prompt_tokens=1, completion_tokens=1)
        )

    provider = make_provider(DeepSeekProvider, handler)
    ok, reason = asyncio.run(provider.probe())
    assert ok is True and reason == ""
    described = provider.describe()
    assert described["api_key_ref"] == "env:DEEPSEEK_API_KEY"
    assert "sk-test-deepseek" not in json.dumps(described, ensure_ascii=False)
    assert "sk-test-deepseek" not in json.dumps(
        provider._error_from_response(httpx.Response(401, text="bad key")).public(),
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    ("provider_cls", "key_field", "expected_base"),
    [
        (QwenProvider, "qwen_api_key", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        (GLMProvider, "glm_api_key", "https://open.bigmodel.cn/api/paas/v4"),
    ],
)
def test_qwen_glm_smoke_with_openai_compatible_mock(
    provider_cls: Any, key_field: str, expected_base: str
) -> None:
    """千问 / GLM 的 Provider 实现必须可运行（同一 OpenAI 兼容适配层）。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=completion(
                content="完成",
                tool_calls=[
                    {
                        "id": "call_q",
                        "type": "function",
                        "function": {"name": "file_read", "arguments": "{}"},
                    }
                ],
            ),
        )

    settings = make_settings(**{key_field: "sk-fake"})
    provider = make_provider(provider_cls, handler, settings)
    assert provider.configured is True
    result = asyncio.run(provider.chat([{"role": "user", "content": "写周报"}]))
    assert captured["url"] == f"{expected_base}/chat/completions"
    assert captured["payload"]["model"] in ("qwen-plus", "glm-4-plus")
    assert result.text == "完成"
    assert result.tool_calls[0].arguments == {}


def test_qwen_accepts_dashscope_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """密钥变量按计划书：千问读 DASHSCOPE_API_KEY（Settings 暂未声明该字段）。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
    provider = QwenProvider(make_settings(qwen_api_key=""))
    assert provider.configured is True
    assert provider.api_key_ref == "env:DASHSCOPE_API_KEY"


def _reasoning_only(**overrides: Any) -> dict[str, Any]:
    """推理模型在小 max_tokens 下的真实回执：正文空，只有 reasoning_content。"""
    payload: dict[str, Any] = {
        "id": "0f6d0c4a-1111-4c2b-9d67-1f0f1f2b3c4d",
        "model": "deepseek-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": "length",
                "message": {"role": "assistant", "content": "", "reasoning_content": "The"},
            }
        ],
        "usage": {
            "prompt_tokens": 6,
            "completion_tokens": 1,
            "total_tokens": 7,
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    }
    payload.update(overrides)
    return payload


def test_probe_accepts_reasoning_model_with_empty_content() -> None:
    """回归：探测曾经要求正文非空，deepseek-flash 必然探测失败。

    失败不是小事——runtime 会据此把整个引擎降级成 mock，用户以为在跟大模型对话，
    实际拿到的是本地脚本写的内容。这条用例守住「有合法回执就算通」。
    """
    provider = make_provider(
        DeepSeekProvider, lambda _request: httpx.Response(200, json=_reasoning_only())
    )
    ok, reason = asyncio.run(provider.probe())
    assert ok is True, reason


def test_probe_sends_enough_budget_for_reasoning_models() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_reasoning_only())

    provider = make_provider(DeepSeekProvider, handler)
    asyncio.run(provider.probe())
    # max_tokens=1 会被推理内容吃光，正文永远为空；给足预算也避免误判
    assert captured["payload"]["max_tokens"] >= 16


def test_probe_still_reports_bad_payload() -> None:
    """宽容正文不等于放弃体检：结构不对（没有 choices）仍然算不通。"""
    provider = make_provider(DeepSeekProvider, lambda _request: httpx.Response(200, json={}))
    ok, reason = asyncio.run(provider.probe())
    assert ok is False
    assert "choices" in reason


def test_chat_still_rejects_empty_content_by_default() -> None:
    """探测宽容，但正常对话不能：空正文就是空响应，得让上层看到错误。"""
    provider = make_provider(
        DeepSeekProvider, lambda _request: httpx.Response(200, json=_reasoning_only())
    )
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    assert excinfo.value.category == ErrorCategory.BAD_FORMAT


def test_empty_content_with_length_retries_with_bigger_budget() -> None:
    """推理模型把 max_tokens 花在 reasoning 上时，正文为空但调用是成功的。

    真实踩到的坑：deepseek-flash 默认带思考，输出预算 2000 时整段被思考占满，
    回执 content=""、finish_reason="length"。以前直接判「空内容」→ 引擎降级，
    界面上写「模型服务暂时不可用」，可钱已经扣了 —— 用户当然怀疑根本没调模型。
    """
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            body = completion(content="", completion_tokens=payload["max_tokens"])
            body["choices"][0]["finish_reason"] = "length"
            body["choices"][0]["message"]["reasoning_content"] = "先把思路想长一点…"
            return httpx.Response(200, json=body)
        return httpx.Response(200, json=completion(content="正文来了"))

    provider = make_provider(DeepSeekProvider, handler)
    result = asyncio.run(provider.chat([{"role": "user", "content": "写周报"}], max_tokens=800))

    assert [call["max_tokens"] for call in calls] == [800, 6000]
    assert result.text == "正文来了"


def test_empty_content_without_length_still_fails() -> None:
    """不是被预算截断却给空正文，那是真的坏回执，不能拿重试掩盖。"""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=completion(content=""))

    provider = make_provider(DeepSeekProvider, handler)
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.chat([{"role": "user", "content": "写周报"}], max_tokens=800))

    assert excinfo.value.category == ErrorCategory.BAD_FORMAT
    assert len(calls) == 1


def test_cache_hit_tokens_are_parsed_for_cost() -> None:
    """输入缓存命中/未命中要落库：官方按两档计价，差 50 倍。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = completion(content="ok", prompt_tokens=1000, completion_tokens=10)
        body["usage"].update({"prompt_cache_hit_tokens": 900, "prompt_cache_miss_tokens": 100})
        return httpx.Response(200, json=body)

    provider = make_provider(DeepSeekProvider, handler)
    result = asyncio.run(provider.chat([{"role": "user", "content": "ping"}], max_tokens=32))

    assert result.cache_hit_tokens == 900
    assert result.cache_miss_tokens == 100


def test_truncated_tool_arguments_retry_with_bigger_budget() -> None:
    """工具参数被 max_tokens 截断时，JSON 解析必然失败——但这不是坏回执，是预算不够。

    真实踩到的：模型把整段 Python 脚本塞进 code.run_python 的参数里，2000 的输出预算
    在脚本中间被切断，回执 arguments 缺右括号。以前整轮直接判「全部供应商不可用」。
    """
    calls: list[dict[str, Any]] = []
    good_args = json.dumps({"script": "print('ok')"})

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            body = completion(
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        # 被截断的 JSON：少了右括号
                        "function": {"name": "code.run_python", "arguments": '{"script": "print(1'},
                    }
                ],
                completion_tokens=payload["max_tokens"],
            )
            body["choices"][0]["finish_reason"] = "length"
            return httpx.Response(200, json=body)
        return httpx.Response(
            200,
            json=completion(
                tool_calls=[
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "code.run_python", "arguments": good_args},
                    }
                ]
            ),
        )

    provider = make_provider(DeepSeekProvider, handler)
    result = asyncio.run(provider.chat([{"role": "user", "content": "跑脚本"}], max_tokens=2000))

    assert [call["max_tokens"] for call in calls] == [2000, 6000]
    assert result.tool_calls[0].arguments == {"script": "print('ok')"}


def test_invalid_tool_arguments_without_truncation_still_fails() -> None:
    """没有 length 标记却给了坏 JSON：真坏回执，别拿重试掩盖。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=completion(
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "code.run_python", "arguments": "{not json"},
                    }
                ]
            ),
        )

    provider = make_provider(DeepSeekProvider, handler)
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.chat([{"role": "user", "content": "跑脚本"}], max_tokens=2000))
    assert excinfo.value.category == ErrorCategory.BAD_FORMAT


def test_default_call_sends_no_max_tokens_field() -> None:
    """默认不限制输出：请求里干脆不带 `max_tokens`，让供应商按模型自身上限走。

    以前固定发 800，推理模型会先把额度花在 reasoning 上、正文变空；
    而按实际输出计费，卡这个上限本来也省不下钱。
    """
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=completion(content="好"))

    provider = make_provider(DeepSeekProvider, handler)
    asyncio.run(provider.chat([{"role": "user", "content": "在吗"}]))

    assert "max_tokens" not in captured["payload"]


def test_explicit_max_tokens_is_still_honoured() -> None:
    """想设硬顶（限流/成本兜底）时照样生效，别把开关做死。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=completion(content="好"))

    provider = make_provider(DeepSeekProvider, handler)
    asyncio.run(provider.chat([{"role": "user", "content": "在吗"}], max_tokens=4096))

    assert captured["payload"]["max_tokens"] == 4096


def test_unbounded_call_does_not_retry_on_truncation() -> None:
    """不限制时没有「放大预算」这回事：再被截断只可能是模型上限到了。

    重试一次结果一样，只会白等一轮还多付一次调用，所以这里必须只发一次。
    """
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        body = completion(content="")
        body["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=body)

    provider = make_provider(DeepSeekProvider, handler)
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.chat([{"role": "user", "content": "写一段"}]))

    assert len(calls) == 1
    assert "max_tokens" not in calls[0]
    assert "未设输出上限" in excinfo.value.message
