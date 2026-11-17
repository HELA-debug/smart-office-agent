"""供应商注册表：新增供应商只加一个类 + 一行注册，即可参与 fallback 链。

已实现（均为 OpenAI 兼容的 `/chat/completions`）：
- DeepSeek：https://api.deepseek.com/v1，默认 deepseek-flash（`deepseek-chat` 是官方会静默改写的旧别名）
- 通义千问：https://dashscope.aliyuncs.com/compatible-mode/v1，默认 qwen-plus
- 智谱 GLM：https://open.bigmodel.cn/api/paas/v4，默认 glm-4-plus
- OpenAI（兼容保留位）
- WorkBuddy：端点与模型名由用户填写（没有公共默认地址），默认占位 workbuddy-chat
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ..core.config import Settings
from .base import (
    API_KEY_ENV,
    DEFAULT_MODELS,
    HttpClientFactory,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderResult,
    ToolCall,
)

__all__ = [
    "API_KEY_ENV",
    "DEFAULT_MODELS",
    "DeepSeekProvider",
    "GLMProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "ProviderError",
    "ProviderResult",
    "QwenProvider",
    "ToolCall",
    "WorkBuddyProvider",
    "build_configured_providers",
    "build_provider",
    "provider_names",
]


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        super().__init__(
            settings,
            provider="deepseek",
            model=model,
            http_client_factory=http_client_factory or _default_factory,
        )


class QwenProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        super().__init__(
            settings,
            provider="qwen",
            model=model,
            http_client_factory=http_client_factory or _default_factory,
        )


class GLMProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        super().__init__(
            settings,
            provider="glm",
            model=model,
            http_client_factory=http_client_factory or _default_factory,
        )


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        super().__init__(
            settings,
            provider="openai",
            model=model,
            http_client_factory=http_client_factory or _default_factory,
        )


@dataclass(frozen=True)
class ProviderFactory:
    provider: str
    build: Callable[..., OpenAICompatibleProvider]


class WorkBuddyProvider(OpenAICompatibleProvider):
    """WorkBuddy：接口地址没有公共默认值，必须由用户在「设置接口」里填。

    未填地址时 `configured` 为 False，路由会直接跳过它（不发起任何请求），
    这样它出现在列表里也不会因为缺地址把整条 fallback 链拖慢。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        super().__init__(
            settings,
            provider="workbuddy",
            model=model,
            http_client_factory=http_client_factory or _default_factory,
        )


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "deepseek": ProviderFactory("deepseek", DeepSeekProvider),
    "qwen": ProviderFactory("qwen", QwenProvider),
    "glm": ProviderFactory("glm", GLMProvider),
    "openai": ProviderFactory("openai", OpenAIProvider),
    "workbuddy": ProviderFactory("workbuddy", WorkBuddyProvider),
}


def _default_factory(settings: Settings) -> httpx.AsyncClient:
    # 延迟导入避免循环依赖（infra 不应在模块加载期被 agents/providers 反向影响）
    from ..infra.http import build_http_client

    return build_http_client(settings)


def provider_names() -> list[str]:
    return list(PROVIDER_FACTORIES)


def build_provider(
    settings: Settings,
    name: str,
    *,
    model: str | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> OpenAICompatibleProvider:
    factory = PROVIDER_FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"未知模型供应商：{name}")
    return factory.build(
        settings,
        model=model,
        http_client_factory=http_client_factory or _default_factory,
    )


def build_configured_providers(
    settings: Settings,
    *,
    http_client_factory: HttpClientFactory | None = None,
) -> dict[str, OpenAICompatibleProvider]:
    """按"主供应商 + fallback 链"构建已配置（有 Key）的供应商实例。"""
    order: list[str] = []
    primary = settings.configured_provider
    if primary and primary != "mock":
        order.append(primary)
    for name in settings.fallback_chain:
        if name and name != "mock" and name not in order:
            order.append(name)
    providers: dict[str, OpenAICompatibleProvider] = {}
    for name in order:
        if name not in PROVIDER_FACTORIES:
            continue
        provider = build_provider(settings, name, http_client_factory=http_client_factory)
        if provider.configured:
            providers[name] = provider
    return providers
