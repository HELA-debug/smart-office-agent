"""模型供应商适配层（ModelProvider 协议 + 注册表）。

- `base.py`：协议、错误分类、OpenAI 兼容实现
- `registry.py`：DeepSeek / 通义千问 / 智谱 GLM（+ OpenAI 兼容位）与工厂
"""

from __future__ import annotations

from .base import (
    API_KEY_ENV,
    DEFAULT_MODELS,
    ErrorCategory,
    HttpClientFactory,
    ModelProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderResult,
    ToolCall,
    provider_error_summary,
    resolve_api_key,
    resolve_base_url,
    resolve_model,
)
from .registry import (
    DeepSeekProvider,
    GLMProvider,
    OpenAIProvider,
    QwenProvider,
    build_configured_providers,
    build_provider,
    provider_names,
)

__all__ = [
    "API_KEY_ENV",
    "DEFAULT_MODELS",
    "DeepSeekProvider",
    "ErrorCategory",
    "GLMProvider",
    "HttpClientFactory",
    "ModelProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "ProviderError",
    "ProviderResult",
    "QwenProvider",
    "ToolCall",
    "build_configured_providers",
    "build_provider",
    "provider_error_summary",
    "provider_names",
    "resolve_api_key",
    "resolve_base_url",
    "resolve_model",
]
