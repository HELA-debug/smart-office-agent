"""模型管理：供应商登记（Key 只存 env 引用）+ 真实连通性探测。

不依赖 app.agents.*（B4 独占写域）：探测直接走 app.infra.http 的客户端工厂，
OpenAI 兼容 /chat/completions；返回结果与耗时，错误原因脱敏，绝不含 Key。
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from ..core import call_journal
from ..core.config import DATA_ROOT, Settings
from ..core.errors import AppError, ErrorCode
from ..core.net_guard import UnsafeUrlError, validate_outbound_url
from ..core.security import masked_secret
from ..core.utils import new_id, now_iso
from ..domain.entities import ModelConfigEntity
from ..domain.ports import ModelConfigRepository
from ..infra.http import build_http_client
from ..providers.base import API_KEY_ENV, resolve_api_key, resolve_model
from .settings_service import SettingsService

_KNOWN_PROVIDERS = ("deepseek", "qwen", "glm", "openai", "workbuddy")

# env 变量名规则（与前端输入校验保持一致）
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# 接口地址没填时的提示：别让用户对着「base_url 不安全」猜半天
_EMPTY_BASE_URL_HINT = (
    "还没填接口地址：点「设置接口」，把供应商给的 Base URL 填上（一般以 /v1 结尾）"
)


def _assert_safe_base_url(base_url: str, settings: Settings) -> None:
    """登记/调用前统一做 SSRF 校验：拒绝内网地址，避免「带 Key 请求任意地址」。

    base_url 会与供应商 Key 一起发出，属高风险输入，登记时与调用时都要校验
    （登记后环境变量仍可能被改动，故不能只校验一次）。
    """
    if not (base_url or "").strip():
        raise AppError(ErrorCode.BAD_REQUEST, _EMPTY_BASE_URL_HINT)
    try:
        validate_outbound_url(base_url, allowlist=settings.model_base_url_allowlist_hosts or None)
    except UnsafeUrlError as exc:
        raise AppError(ErrorCode.BAD_REQUEST, f"base_url 不安全：{exc.message}") from exc


class ModelService:
    def __init__(
        self,
        repo: ModelConfigRepository,
        settings: Settings,
        settings_service: SettingsService,
    ):
        self.repo = repo
        self.settings = settings
        self.settings_service = settings_service
        # 最近一次探测结果（按 config_id/provider 存内存，不落库、不含 Key）
        self._probe_status: dict[str, dict[str, Any]] = {}

    # ---------- 查询 ----------
    def _configured_provider_names(self) -> list[str]:
        """列出全部已知供应商（含未配置 Key 的），供设置/模型页统一展示。"""
        names: list[str] = []
        provider = self.settings.configured_provider
        if provider != "mock":
            names.append(provider)
        for item in self.settings.fallback_chain:
            if item != "mock" and item not in names:
                names.append(item)
        for item in _KNOWN_PROVIDERS:
            if item not in names:
                names.append(item)
        return names

    def _resolved_key(self, item: dict[str, Any]) -> str:
        """与 providers/base.resolve_api_key 一致；自定义 env:REF 仅按引用解析。"""
        ref = str(item.get("api_key_ref", ""))
        provider = str(item.get("provider", ""))
        standard_ref = f"env:{API_KEY_ENV.get(provider, '')}"
        if ref == standard_ref:
            return resolve_api_key(self.settings, provider)
        return self.settings_service.resolve_key_ref(ref)

    def list_models(self) -> list[dict[str, Any]]:
        """内置 env:* 供应商列表；若 model_configs 同 provider 已登记，则以登记值为准。"""
        configs = self.repo.list_all()
        registered = {
            config.provider: config for config in sorted(configs, key=lambda item: item.priority)
        }
        models: list[dict[str, Any]] = []
        for provider in self._configured_provider_names():
            key = f"env:{provider}"
            row: dict[str, Any] = {
                "id": key,
                "provider": provider,
                "base_url": self.settings.provider_base_url(provider),
                "model": resolve_model(self.settings, provider),
                "api_key_ref": f"env:{API_KEY_ENV.get(provider, provider.upper() + '_API_KEY')}",
                "configured": bool(resolve_api_key(self.settings, provider))
                and bool(self.settings.provider_base_url(provider)),
                "enabled": True,
                "priority": 0,
                "builtin": True,
                "last_probe": self._probe_status.get(key),
                "extra": {},
            }
            config = registered.get(provider)
            if config is not None:
                row.update(
                    {
                        "model": config.model or row["model"],
                        "base_url": config.base_url or row["base_url"],
                        "api_key_ref": config.api_key_ref,
                        "priority": config.priority,
                        "enabled": config.enabled,
                        "builtin": False,
                        "configured": bool(
                            self._resolved_key({**row, "api_key_ref": config.api_key_ref})
                        ),
                        "extra": {"registered_id": config.id},
                    }
                )
                row["last_probe"] = self._probe_status.get(config.id) or row["last_probe"]
            models.append(row)
        known = {f"env:{provider}" for provider in _KNOWN_PROVIDERS}
        for config in configs:
            if f"env:{config.provider}" in known:
                continue  # 已知 provider 已在 env:* 行内覆盖
            public = self.settings_service.model_config_public(config)
            public["configured"] = bool(self._resolved_key({**public, "provider": config.provider}))
            public["builtin"] = False
            public["last_probe"] = self._probe_status.get(config.id)
            models.append(public)
        return models

    def get_model(self, model_id: str) -> dict[str, Any]:
        for item in self.list_models():
            if item["id"] == model_id:
                return item
            if (item.get("extra") or {}).get("registered_id") == model_id:
                return item
        raise AppError(ErrorCode.NOT_FOUND, f"模型配置不存在：{model_id}")

    # ---------- 登记 ----------
    def upsert_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider", "")).strip().lower()
        if not provider:
            raise AppError(ErrorCode.BAD_REQUEST, "provider 不能为空")
        api_key_ref = str(
            payload.get("api_key_ref") or self.settings_service.provider_key_ref(provider)
        )
        if not api_key_ref.startswith("env:"):
            raise AppError(
                ErrorCode.BAD_REQUEST, "api_key_ref 只能是 env:NAME 形式（不存明文 Key）"
            )
        env_name = api_key_ref.split(":", 1)[1]
        if not env_name:
            raise AppError(ErrorCode.BAD_REQUEST, "api_key_ref 环境变量名不能为空")
        base_url = str(payload.get("base_url") or self.settings.provider_base_url(provider))
        _assert_safe_base_url(base_url, self.settings)
        model = str(payload.get("model") or resolve_model(self.settings, provider))
        priority = int(payload.get("priority", 100))
        enabled = bool(payload.get("enabled", True))

        existing = None
        requested_id = payload.get("id")
        if requested_id:
            existing = self.repo.get(str(requested_id))
        if existing is None:
            for config in self.repo.list_all():
                if config.provider == provider and config.model == model:
                    existing = config
                    break
        if existing is not None:
            config = ModelConfigEntity(
                id=existing.id,
                provider=provider,
                base_url=base_url,
                model=model,
                api_key_ref=api_key_ref,
                priority=priority,
                enabled=enabled,
                extra={**existing.extra, "env_present": env_name in os.environ},
            )
            self.repo.update(config)
        else:
            config = ModelConfigEntity(
                id=new_id("mc"),
                provider=provider,
                base_url=base_url,
                model=model,
                api_key_ref=api_key_ref,
                priority=priority,
                enabled=enabled,
                extra={"env_present": env_name in os.environ},
            )
            self.repo.add(config)
        self.settings_service.apply_persisted()
        public = self.get_model(config.id)
        return public

    # ---------- Key 写入 ----------
    def save_key(self, model_id: str, api_key: str, env_name: str | None = None) -> dict[str, Any]:
        """保存用户从供应商开放平台获取的 Key（写入进程环境 + 本地 .env）。

        - 明文只落本地 .env（已 gitignore）与服务端内存，接口只回显掩码；
        - 写盘失败（只读文件系统，如容器）不影响本次运行，返回 persisted=False；
        - 同时把 api_key_ref 定向到该 env 名，保证探测/调用取到同一份 Key。
        """
        item = self.get_model(model_id)
        provider = str(item["provider"])
        value = (api_key or "").strip()
        if not value:
            raise AppError(ErrorCode.BAD_REQUEST, "Key 不能为空")
        if len(value) < 8 or any(ch.isspace() for ch in value):
            raise AppError(ErrorCode.BAD_REQUEST, "Key 格式不正确（不能为空、含空格或过短）")
        ref_name = (
            (env_name or "").strip()
            or str(item.get("api_key_ref") or "").removeprefix("env:")
            or API_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")
        )
        if not _ENV_NAME_RE.match(ref_name):
            raise AppError(
                ErrorCode.BAD_REQUEST, "环境变量名只能是大写字母、数字与下划线，且以字母开头"
            )

        self.settings.apply_secret(ref_name, value)
        persisted = self.settings.persist_secret(ref_name, value)

        # 把登记的 Key 引用指向同一个 env 名（自定义 provider 也支持）
        payload = {
            "id": (item.get("extra") or {}).get("registered_id") or item.get("id"),
            "provider": provider,
            "base_url": item.get("base_url"),
            "model": item.get("model"),
            "api_key_ref": f"env:{ref_name}",
            "priority": int(item.get("priority", 100)),
            "enabled": bool(item.get("enabled", True)),
        }
        self.upsert_model(payload)
        return {
            "provider": provider,
            "api_key_ref": f"env:{ref_name}",
            "configured": True,
            "masked": masked_secret(value),
            "persisted": persisted,
        }

    # ---------- Key 断开 ----------
    def disconnect_key(self, model_id: str) -> dict[str, Any]:
        """断开某个模型的 Key：进程 env、Settings 字段、本地 .env 三处同清。

        场景是「项目要分享 / 部署给别人」：Key 留在 .env 里会跟着数据目录
        一起被拷走，别人拿它继续跑、费用记在原主头上。所以断开必须删得干干净净，
        不能只改内存状态。

        - env 名取登记的 api_key_ref（env:NAME）；没有登记就用该供应商的默认名；
        - 断开后该行回到「未配置」，但 base_url / 模型名等登记信息保留——
          换一把新 Key 就能重新接上，不该逼用户重填一遍地址；
        - .env 删行失败（只读文件系统）返回 persisted=False，由界面提示手动处理；
        - 顺带清掉这家的探测缓存，避免列表里还挂着一张「上次连接正常」的旧票。
        """
        item = self.get_model(model_id)
        provider = str(item["provider"])
        ref = str(item.get("api_key_ref") or "")
        env_name = ref.removeprefix("env:") or API_KEY_ENV.get(
            provider, f"{provider.upper()}_API_KEY"
        )
        persisted = self.settings.clear_secret(env_name)
        self._probe_status.pop(item.get("id"), None)
        self._probe_status.pop(f"env:{provider}", None)
        # 路由器里 provider 构造时把 Key 拍成了快照，不清缓存断开后还能继续用
        self.settings_service.reset_router()
        return {
            "provider": provider,
            "api_key_ref": f"env:{env_name}",
            "configured": False,
            "disconnected": True,
            "persisted": persisted,
        }

    # ---------- 账户余额 ----------
    async def balance(self, model_id: str) -> dict[str, Any]:
        """查供应商账户余额（目前 DeepSeek 有 /user/balance）。

        这是「界面上的 token 账单到底是不是这个账号花的」最直接的对账方式：
        拿同一把 Key 去问供应商还有多少钱，跟控制台一比对，账号对不对一目了然。
        """
        item = self.get_model(model_id)
        provider = str(item["provider"])
        base_url = str(item["base_url"] or "").rstrip("/")
        api_key = self._resolved_key(item)
        now = now_iso()
        result: dict[str, Any] = {
            "supported": provider == "deepseek",
            "provider": provider,
            "currency": "CNY",
            "checked_at": now,
        }
        if provider != "deepseek":
            result["reason"] = "该供应商没有公开的余额查询接口"
            return result
        if not base_url or not api_key:
            result["reason"] = "缺接口地址或 Key，无法查询"
            return result
        _assert_safe_base_url(base_url, self.settings)
        try:
            async with build_http_client(self.settings, timeout=8.0) as client:
                response = await client.get(
                    f"{base_url}/user/balance",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            result["reason"] = f"HTTP {exc.response.status_code}"
            return result
        except (httpx.HTTPError, ValueError) as exc:
            result["reason"] = f"查询失败：{type(exc).__name__}"
            return result
        infos = data.get("balance_infos") if isinstance(data, dict) else None
        info = infos[0] if isinstance(infos, list) and infos else {}
        if not isinstance(info, dict):
            info = {}

        def _amount(key: str) -> float | None:
            try:
                return float(info.get(key))
            except (TypeError, ValueError):
                return None

        result.update(
            total_balance=_amount("total_balance"),
            granted_balance=_amount("granted_balance"),
            topped_up_balance=_amount("topped_up_balance"),
            currency=str(info.get("currency") or "CNY"),
        )
        return result

    # ---------- 探测 ----------
    async def test_model(self, model_id: str) -> dict[str, Any]:
        item = self.get_model(model_id)
        provider = str(item["provider"])
        base_url = str(item["base_url"]).rstrip("/")
        model = str(item["model"])
        api_key = self._resolved_key(item)
        started = time.perf_counter()
        status: dict[str, Any] = {
            "ok": False,
            "provider": provider,
            "model": model,
            "api_key_ref": item["api_key_ref"],
            "latency_ms": 0,
        }
        # 先看「填没填」，再看「填得对不对」：缺地址/缺 Key 时直接返回人话原因，
        # 不抛 400——用户在列表里点一下「测试连接」，最想要的是原因而不是一个红色报错框。
        if not base_url:
            status["reason"] = _EMPTY_BASE_URL_HINT
            self._probe_status[model_id] = status
            return status
        if not api_key:
            status["reason"] = "环境变量中未找到 Key（仅返回引用，不回显明文）"
            self._probe_status[model_id] = status
            return status
        # 带 Key 发出请求，出网前再校验一次（登记后 base_url 仍可能被改动）
        _assert_safe_base_url(base_url, self.settings)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        try:
            async with build_http_client(self.settings, timeout=8.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
                data = response.json()
            returned = ((data.get("choices") or [{}])[0].get("model")) or model
            status.update(ok=True, returned_model=returned)
            _note_probe(
                provider,
                returned,
                started,
                request_id=str(data.get("id") or "") or None,
                usage=data.get("usage") or {},
            )
        except httpx.HTTPStatusError as exc:
            status["reason"] = f"HTTP {exc.response.status_code}"
            _note_probe(provider, model, started, error=f"http_{exc.response.status_code}")
        except (httpx.HTTPError, ValueError) as exc:
            status["reason"] = f"探测失败：{type(exc).__name__}"
            _note_probe(provider, model, started, error=type(exc).__name__)
        status["latency_ms"] = int((time.perf_counter() - started) * 1000)
        if status.get("ok"):
            # 探测通过 = 这套配置此刻真能用：把「上次失败」的降级结论与旧 provider 实例
            # 一起作废。否则用户换完 Key、这里已经显示「连接正常」，设置页和顶栏却还
            # 挂着旧 Key 的 401（/health 只读 degraded，不重新探测），看着像白换了。
            self.settings_service.reset_router()
        self._probe_status[model_id] = status
        return status

    @staticmethod
    def workdir() -> str:  # pragma: no cover - 仅用于调试
        return str(DATA_ROOT)


def _note_probe(
    provider: str,
    model: str,
    started: float,
    *,
    request_id: str | None = None,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """「测试连接」也会真的花一次钱，记进账本。

    它走内联 httpx 而不是 ModelRouter（要验的是用户刚填的这套配置，不是路由里
    已经生效的实例），所以记账得自己来。漏掉它，账本又会比控制台少一截——
    而按钮恰恰是「怀疑配置有问题」时最容易被反复点的地方。
    """
    usage = usage or {}
    call_journal.record(
        call_journal.entry_for(
            provider=provider,
            model=model,
            purpose="probe",
            status="failed" if error else "ok",
            request_id=request_id,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_hit_tokens=int(usage.get("prompt_cache_hit_tokens") or 0),
            cache_miss_tokens=int(usage.get("prompt_cache_miss_tokens") or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=error,
        )
    )
