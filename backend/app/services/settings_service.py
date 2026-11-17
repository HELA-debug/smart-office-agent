"""设置中心：env 默认值 + DB 覆盖（分层），保存后热更新运行时配置。

来源标记：db（设置表覆盖）> env（进程环境/.env）> default（字段默认值）。
密钥只返回 env 引用（env:DEEPSEEK_API_KEY），绝不返回明文。
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..core.config import Settings
from ..core.errors import AppError, ErrorCode
from ..core.utils import now_iso
from ..domain.entities import ModelConfigEntity, SettingItem
from ..domain.ports import ModelConfigRepository, SettingsRepository
from ..providers.base import API_KEY_ENV, resolve_api_key

# API 字段 -> Settings 属性 / 类型（白名单，白名单外一律拒绝）
_EDITABLE: dict[str, tuple[str | None, type]] = {
    "engine": ("engine", str),
    "model_provider": ("model_provider", str),
    "model_name": ("model_name", str),
    "fallback_chain": ("model_fallback_chain", list),
    "approval_rules": ("approval_rules", list),
    "mock_mode": ("mock_mode", bool),
    "max_upload_mb": ("max_upload_mb", int),
    "model_timeout_seconds": ("model_timeout_seconds", float),
    "approval_timeout_seconds": ("approval_timeout_seconds", int),
    "feature_flags": (None, dict),
}

_ENV_HINTS = {
    "engine": "ENGINE",
    "model_provider": "MODEL_PROVIDER",
    "model_name": "MODEL_NAME",
    "fallback_chain": "MODEL_FALLBACK_CHAIN",
    "approval_rules": "APPROVAL_RULES",
    "mock_mode": "MOCK_MODE",
    "max_upload_mb": "MAX_UPLOAD_MB",
    "model_timeout_seconds": "MODEL_TIMEOUT_SECONDS",
    "approval_timeout_seconds": "APPROVAL_TIMEOUT_SECONDS",
    "feature_flags": "FEATURE_FLAGS",
}

_PROVIDER_URL_FIELDS = {
    "deepseek": "deepseek_base_url",
    "qwen": "qwen_base_url",
    "glm": "glm_base_url",
    "openai": "openai_base_url",
    "workbuddy": "workbuddy_base_url",
}


class SettingsService:
    def __init__(
        self,
        repo: SettingsRepository,
        settings: Settings,
        model_configs: ModelConfigRepository | None = None,
    ):
        self.repo = repo
        self.settings = settings
        self.model_configs = model_configs
        self.runtime: Any = None

    # ---------- 装配 ----------
    def bind_runtime(self, runtime: Any) -> None:
        """main.py 装配完成后绑定运行时；随后应用 DB 覆盖（重启后仍生效）。"""
        self.runtime = runtime
        self.apply_persisted()

    # ---------- 读取 ----------
    def _overrides(self) -> dict[str, Any]:
        return {item.key: item.value for item in self.repo.list_all()}

    def _feature_flags(self, overrides: dict[str, Any]) -> dict[str, Any]:
        raw = overrides.get("feature_flags")
        if isinstance(raw, dict):
            return raw
        value = os.environ.get("FEATURE_FLAGS", "")
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}

    def _source(self, key: str, overrides: dict[str, Any]) -> str:
        if key in overrides:
            return "db"
        attr = _EDITABLE[key][0]
        field = attr or key
        if field in self.settings.model_fields_set:
            return "env"
        return "default"

    def _secret_refs(self) -> dict[str, dict[str, Any]]:
        """与 providers/base.resolve_api_key 一致的密钥状态；只展示 env 引用。"""
        refs: dict[str, dict[str, Any]] = {}
        for provider, env_name in API_KEY_ENV.items():
            entry: dict[str, Any] = {
                "configured": bool(resolve_api_key(self.settings, provider)),
                "ref": f"env:{env_name}",
            }
            if (
                provider == "deepseek"
                and not self.settings.deepseek_api_key
                and self.settings.openai_api_key
            ):
                entry["via"] = "env:OPENAI_API_KEY"
            refs[provider] = entry
        return refs

    def effective(self) -> dict[str, Any]:
        overrides = self._overrides()
        engine, mock_mode = self._switches(overrides)
        values: dict[str, Any] = {
            "engine": engine,
            "approval_rules": self.effective_approval_rules(overrides),
            "mock_mode": mock_mode,
            "model_provider": str(
                overrides.get("model_provider", self.settings.configured_provider)
            ),
            "model_name": str(overrides.get("model_name", self.settings.model_name)),
            "fallback_chain": self.effective_fallback_chain(overrides),
            "max_upload_mb": int(overrides.get("max_upload_mb", self.settings.max_upload_mb)),
            "model_timeout_seconds": float(
                overrides.get("model_timeout_seconds", self.settings.model_timeout_seconds)
            ),
            "approval_timeout_seconds": int(
                overrides.get("approval_timeout_seconds", self.settings.approval_timeout_seconds)
            ),
            "feature_flags": self._feature_flags(overrides),
        }
        return {
            **values,
            "sources": {key: self._source(key, overrides) for key in _EDITABLE},
            "env_hints": {key: _ENV_HINTS[key] for key in _EDITABLE if key in _ENV_HINTS},
            "secrets": self._secret_refs(),
            "database_url": self.settings.database_url.split("@")[-1],
            # 给界面看的是真实可访问的绝对路径（相对路径点不开也没法复制去用）
            "upload_dir": str(self.settings.uploads_path),
            "artifact_dir": str(self.settings.artifacts_path),
            "log_level": self.settings.log_level,
            "environment": self.settings.environment,
        }

    def effective_approval_rules(self, overrides: dict[str, Any] | None = None) -> list[str]:
        raw = (overrides or self._overrides()).get("approval_rules", self.settings.approval_rules)
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [item.strip() for item in str(raw).split(",") if item.strip()]

    def effective_fallback_chain(self, overrides: dict[str, Any] | None = None) -> list[str]:
        raw = (overrides or self._overrides()).get(
            "fallback_chain", self.settings.model_fallback_chain
        )
        if isinstance(raw, list):
            chain = [str(item).strip().lower() for item in raw if str(item).strip()]
        else:
            chain = [item.strip().lower() for item in str(raw).split(",") if item.strip()]
        return chain or ["mock"]

    def approval_rules(self) -> set[str]:
        return set(self.effective_approval_rules())

    def feature_flags(self) -> dict[str, Any]:
        return self._feature_flags(self._overrides())

    # ---------- 更新（热生效） ----------
    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        unknown = set(patch) - set(_EDITABLE)
        if unknown:
            raise AppError(
                ErrorCode.BAD_REQUEST,
                f"不支持修改的设置项：{', '.join(sorted(unknown))}",
                details={"editable": sorted(_EDITABLE)},
            )
        normalized: dict[str, Any] = {}
        for key, value in patch.items():
            expected = _EDITABLE[key][1]
            if expected is bool and not isinstance(value, bool):
                raise AppError(ErrorCode.BAD_REQUEST, f"{key} 必须是布尔值")
            if expected is str and not isinstance(value, str):
                raise AppError(ErrorCode.BAD_REQUEST, f"{key} 必须是字符串")
            if expected is int and not isinstance(value, int):
                raise AppError(ErrorCode.BAD_REQUEST, f"{key} 必须是整数")
            if expected is float and not isinstance(value, (int, float)):
                raise AppError(ErrorCode.BAD_REQUEST, f"{key} 必须是数字")
            if expected is list:
                if isinstance(value, str):
                    value = [item.strip() for item in value.split(",") if item.strip()]
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise AppError(ErrorCode.BAD_REQUEST, f"{key} 必须是字符串列表")
            if expected is dict and not isinstance(value, dict):
                raise AppError(ErrorCode.BAD_REQUEST, f"{key} 必须是对象")
            normalized[key] = value

        if "engine" in normalized and normalized["engine"] not in (
            "mock",
            "real",
            "deepagents",
        ):
            raise AppError(ErrorCode.BAD_REQUEST, "engine 只能是 mock / real / deepagents")
        if "model_provider" in normalized and not normalized["model_provider"]:
            raise AppError(ErrorCode.BAD_REQUEST, "model_provider 不能为空")
        if "fallback_chain" in normalized and not normalized["fallback_chain"]:
            raise AppError(ErrorCode.BAD_REQUEST, "fallback_chain 不能为空")
        if "max_upload_mb" in normalized and not 1 <= normalized["max_upload_mb"] <= 200:
            raise AppError(ErrorCode.BAD_REQUEST, "max_upload_mb 取值范围 1-200")

        # engine 与 mock_mode 是同一个开关的两种写法。以前两个都写进 DB、互不约束，
        # 于是出现过「engine=real + mock_mode=true」：设置页下拉写着「真实模型」，
        # 顶栏徽标写着「mock 连接器」，重启后真实模型永远不生效——两处各说各话。
        # 这里统一以 engine 为准，两个键一起落库，存进去就是一致的。
        if "engine" in normalized or "mock_mode" in normalized:
            engine, mock = self._switches(normalized)
            normalized["engine"] = engine
            normalized["mock_mode"] = mock

        for key, value in normalized.items():
            self.repo.upsert(
                SettingItem(
                    key=key,
                    value=value,
                    updated_at=now_iso(),
                    scope="global",
                    is_secret=False,
                )
            )
        self._apply(self._overrides())
        return self.effective()

    # ---------- 热更新 ----------
    def _switches(self, overrides: dict[str, Any]) -> tuple[str, bool]:
        """把「执行引擎」和「演示模式」归一成一对 (engine, mock_mode)。

        规则：engine 是权威值；只给 mock_mode（老客户端 / 直接调 API）时按它反推 engine。
        这样无论从哪个入口改，内存里的 settings 和返回给界面的值都不会互相打架。
        """
        if "engine" in overrides:
            engine = str(overrides["engine"]).strip().lower()
        elif "mock_mode" in overrides:
            engine = "mock" if bool(overrides["mock_mode"]) else "real"
        else:
            engine = self.settings.engine_kind
        if engine not in ("mock", "real", "deepagents"):
            engine = "real"
        return engine, engine == "mock"

    def apply_persisted(self) -> None:
        overrides = self._overrides()
        engine, mock = self._switches(overrides)
        self._apply(overrides)
        # DB 里可能留着历史矛盾（engine=real + mock_mode=true，界面两处各说各话的那种）：
        # 按 engine 修好后写回，否则每次启动都得纠一遍，下一次保存又会把矛盾带回去。
        mismatch = "engine" in overrides or "mock_mode" in overrides
        if mismatch and (overrides.get("engine") != engine or overrides.get("mock_mode") != mock):
            for key, value in (("engine", engine), ("mock_mode", mock)):
                self.repo.upsert(
                    SettingItem(
                        key=key,
                        value=value,
                        updated_at=now_iso(),
                        scope="global",
                        is_secret=False,
                    )
                )

    def _apply(self, overrides: dict[str, Any]) -> None:
        settings = self.settings
        if "engine" in overrides or "mock_mode" in overrides:
            # 只改一个也必须把另一个带上：mock_mode=true 会一票否决真实模型，
            # 两边不同步就是「设置里选了真实模型，实际还在跑 mock」。
            engine, mock = self._switches(overrides)
            settings.engine = engine
            settings.mock_mode = mock
        if "model_provider" in overrides:
            settings.model_provider = str(overrides["model_provider"])
        if "model_name" in overrides:
            settings.model_name = str(overrides["model_name"])
        if "approval_rules" in overrides:
            settings.approval_rules = ",".join(self.effective_approval_rules(overrides))
        if "fallback_chain" in overrides:
            settings.model_fallback_chain = ",".join(self.effective_fallback_chain(overrides))
        if "max_upload_mb" in overrides:
            settings.max_upload_mb = int(overrides["max_upload_mb"])
        if "model_timeout_seconds" in overrides:
            settings.model_timeout_seconds = float(overrides["model_timeout_seconds"])
        if "approval_timeout_seconds" in overrides:
            settings.approval_timeout_seconds = int(overrides["approval_timeout_seconds"])
        self._apply_model_configs(overrides)
        if self.runtime is not None:
            self.runtime.settings = settings
            self.runtime.approval_tools = self.runtime.tools.approval_tools(settings.approval_tools)
            self.runtime.router.settings = settings
            # 地址 / 模型 / 供应商都可能刚改过：让路由器丢掉旧实例，改完即生效（不用重启）。
            # provider 构造时把 base_url 拍成了快照，不清缓存就要重启才认新地址。
            self.runtime.router.reset_providers()
            self._clear_degrade()

    def _apply_model_configs(self, overrides: dict[str, Any]) -> None:
        """把模型登记里的 base_url 热应用到 Settings，供 B4 真实路由复用。"""
        if self.model_configs is None:
            return
        configs = [config for config in self.model_configs.list_all() if config.enabled]
        if not configs:
            return
        for config in configs:
            field = _PROVIDER_URL_FIELDS.get(config.provider)
            if field and config.base_url:
                setattr(self.settings, field, config.base_url.rstrip("/"))
        active = sorted(configs, key=lambda item: item.priority)
        current = self.settings.configured_provider
        for config in active:
            if config.provider != current:
                continue
            if config.model and "model_name" not in overrides:
                self.settings.model_name = config.model
            break

    # ---------- 模型引用辅助 ----------
    def provider_key_ref(self, provider: str) -> str:
        env_name = API_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")
        return f"env:{env_name}"

    def resolve_key_ref(self, ref: str) -> str:
        """解析 env:NAME 引用（只在服务端使用，返回值绝不外泄）。"""
        if not ref.startswith("env:"):
            return ""
        return os.environ.get(ref.split(":", 1)[1], "")

    def reset_router(self) -> None:
        """让模型路由器丢掉缓存实例（Key / 地址刚被清掉或改过后调用）。

        provider 构造时把 Key 拍成了快照：断开 Key 后不清缓存，路由器里
        那个实例还握着旧 Key 继续发请求——断开就白断、费用照扣。
        「上次探测失败」的结论也一起作废：见 `_clear_degrade`。
        """
        if self.runtime is not None:
            self.runtime.router.reset_providers()
            self._clear_degrade()

    def _clear_degrade(self) -> None:
        """配置刚变过：把「上次探测失败」的结论作废。

        `degraded` 只在**真实运行探测成功**时才复位，而 `/health` 只读它、不重新探测。
        于是出现过这样一条坑：用户换了新 Key、在设置页点「测试连接」也绿了，
        但设置页与顶栏还挂着旧 Key 的那条 401，写着「API Key 无效或已失效」，
        用户以为新 Key 根本没生效（实际下一次运行就是好的）。
        配置一变，旧结论就不该再被当成现状——真不能用的话，下一次运行会重新降级
        并给出新的原因，而不是把一条过期的报错永远挂在界面上。
        """
        if self.runtime is None:
            return
        self.runtime.degraded = False
        self.runtime.degraded_reason = ""

    @staticmethod
    def model_config_public(config: ModelConfigEntity | None) -> dict[str, Any]:
        if config is None:
            return {}
        return {
            "id": config.id,
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "api_key_ref": config.api_key_ref,
            "priority": config.priority,
            "enabled": config.enabled,
            "extra": {
                key: value
                for key, value in config.extra.items()
                if "key" not in key.lower() and "token" not in key.lower()
            },
        }
