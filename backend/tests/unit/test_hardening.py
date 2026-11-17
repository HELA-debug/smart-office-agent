"""安全加固单元测试：SSRF 出站校验、解压炸弹防护、API Token 中间件。

对应审查项 P0-1（API 认证）、P1-3（base_url SSRF）、P1-4（压缩炸弹）。
"""

from __future__ import annotations

import io
import zipfile

import pytest
from app.core.config import Settings
from app.core.net_guard import UnsafeUrlError, validate_outbound_url
from app.core.security import (
    UploadLimits,
    UploadValidationError,
    check_zip_bomb,
    validate_upload,
)
from fastapi.testclient import TestClient

# ---------------------------------------------------------------- SSRF


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "http://localhost:11434/v1",
        "http://10.0.0.5/v1",
        "http://192.168.1.10/v1",
        "http://172.16.3.4/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]:8000/v1",
        "http://0.0.0.0:8000/v1",
    ],
)
def test_ssrf_blocks_internal_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.deepseek.com/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://8.8.8.8/v1",
    ],
)
def test_ssrf_allows_public_targets(url: str) -> None:
    # resolve=False：只做静态判定，避免测试依赖 DNS
    assert validate_outbound_url(url, resolve=False)


def test_ssrf_rejects_non_http_schemes() -> None:
    for url in ("file:///etc/passwd", "gopher://x", "ftp://example.com", ""):
        with pytest.raises(UnsafeUrlError):
            validate_outbound_url(url, resolve=False)


def test_ssrf_allowlist_only_permits_listed_hosts() -> None:
    allow = {"api.deepseek.com"}
    assert validate_outbound_url("https://api.deepseek.com/v1", allowlist=allow)
    # 子域允许
    assert validate_outbound_url("https://beta.api.deepseek.com/v1", allowlist=allow)
    with pytest.raises(UnsafeUrlError, match="不在允许列表"):
        validate_outbound_url("https://evil.example.com/v1", allowlist=allow)


def test_ssrf_unresolvable_host_is_rejected() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https://this-host-should-not-exist.invalid/v1")


# ---------------------------------------------------------------- 压缩炸弹


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_zip_bomb_rejects_too_many_entries() -> None:
    data = _zip_bytes({f"word/f{i}.xml": b"x" for i in range(30)})
    limits = UploadLimits(max_archive_entries=10, max_uncompressed_bytes=10**9)
    with pytest.raises(UploadValidationError) as exc:
        check_zip_bomb(data, limits=limits)
    assert exc.value.reason == "too_many_entries"


def test_zip_bomb_rejects_oversized_uncompressed_total() -> None:
    data = _zip_bytes({"word/document.xml": b"a" * (2 * 1024 * 1024)})
    limits = UploadLimits(max_uncompressed_bytes=1024 * 1024)
    with pytest.raises(UploadValidationError) as exc:
        check_zip_bomb(data, limits=limits)
    assert exc.value.reason == "zip_bomb"


def test_zip_bomb_rejects_extreme_compression_ratio() -> None:
    # 2MB 全零压缩后只有几 KB，压缩比远超阈值
    data = _zip_bytes({"word/document.xml": b"\0" * (2 * 1024 * 1024)})
    limits = UploadLimits(max_uncompressed_bytes=100 * 1024 * 1024, max_compression_ratio=200)
    with pytest.raises(UploadValidationError) as exc:
        check_zip_bomb(data, limits=limits)
    assert exc.value.reason == "zip_bomb"


def test_zip_bomb_accepts_normal_docx_size() -> None:
    data = _zip_bytes({"word/document.xml": b"<w:document>" + b"text" * 1000})
    check_zip_bomb(data)  # 不抛异常即通过


def test_validate_upload_uses_limits_for_ooxml() -> None:
    data = _zip_bytes({"word/document.xml": b"a" * (2 * 1024 * 1024)})
    limits = UploadLimits(max_uncompressed_bytes=1024 * 1024)
    with pytest.raises(UploadValidationError):
        validate_upload("报告.docx", None, data, limits=limits)


def test_validate_upload_rejects_non_ooxml_zip() -> None:
    data = _zip_bytes({"xl/workbook.xml": b"x"})
    with pytest.raises(UploadValidationError):
        validate_upload("报告.docx", None, data)


def test_parsed_text_is_truncated_to_limit() -> None:
    from app.infra.parsing import parse_bytes

    text = ("你好" * 50).encode("utf-8")
    result = parse_bytes(text, ".txt", UploadLimits(max_parsed_chars=20))
    assert "已截断" in result
    assert len(result) < 200


# ---------------------------------------------------------------- API Token


class _AppFactory:
    """按需构造带独立 SQLite 的 app（复用同一临时目录，避免每个用例都建库）。"""

    def __init__(self, root) -> None:
        self.root = root
        self._apps: dict[str, object] = {}

    def get(self, token: str):
        from app.main import create_app

        if token not in self._apps:
            safe = token or "public"
            self._apps[token] = create_app(
                Settings(
                    engine="mock",
                    model_provider="mock",
                    model_name="mock-scripted",
                    model_fallback_chain="mock",
                    mock_mode=True,
                    mock_model_speed=0,
                    api_token=token,
                    approval_rules="file.delete",
                    serve_frontend=False,
                    database_url=f"sqlite:///{self.root / f'app-{safe}.db'}",
                    upload_dir=str(self.root / f"uploads-{safe}"),
                    artifact_dir=str(self.root / f"artifacts-{safe}"),
                    trash_dir=str(self.root / f"trash-{safe}"),
                    templates_file=str(self.root / f"templates-{safe}.json"),
                    auto_migrate=True,
                    log_level="WARNING",
                    log_format="text",
                )
            )
        return self._apps[token]


@pytest.fixture(scope="module")
def app_factory(tmp_path_factory: pytest.TempPathFactory) -> _AppFactory:
    return _AppFactory(tmp_path_factory.mktemp("auth-hardening"))


def test_auth_disabled_by_default(app_factory: _AppFactory) -> None:
    with TestClient(app_factory.get("")) as client:
        response = client.get("/api/v1/tools")
        assert response.status_code == 200


def test_auth_enabled_requires_token(app_factory: _AppFactory) -> None:
    with TestClient(app_factory.get("secret-token")) as client:
        # 无 token → 401 且是统一错误体
        blocked = client.get("/api/v1/tools")
        assert blocked.status_code == 401
        body = blocked.json()
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert "trace_id" in body
        assert blocked.headers.get("X-Trace-ID")

        # 错误 token → 401
        assert client.get("/api/v1/tools", headers={"X-API-Token": "wrong"}).status_code == 401

        # 正确 token → 200
        allowed = client.get("/api/v1/tools", headers={"X-API-Token": "secret-token"})
        assert allowed.status_code == 200


def test_auth_keeps_health_public(app_factory: _AppFactory) -> None:
    """容器 healthcheck 不能要求 token，否则编排永远不健康。"""
    with TestClient(app_factory.get("secret-token")) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/").status_code == 200


def test_auth_allows_cors_preflight(app_factory: _AppFactory) -> None:
    with TestClient(app_factory.get("secret-token")) as client:
        response = client.options(
            "/api/v1/tools",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
