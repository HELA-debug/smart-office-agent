"""部署配置静态校验（无需 Docker）。

守护两类容易回归的部署问题：
1. 所有 SSE 长连接端点都被 nginx 关掉缓冲（否则 Docker 下前端收不到增量事件）；
2. compose 端口只绑回环；安全响应头片段被每个 location 引用。

真正的 `nginx -t` / `docker compose up` 冒烟仍需在装有 Docker 的机器上跑
（见 KNOWN_ISSUES #1）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_DIR = PROJECT_ROOT / "deploy"

# 后端真实存在的 SSE 端点（路径片段 -> 说明）
SSE_ENDPOINTS = {
    "/api/v1/threads/{thread_id}/events/stream": "会话事件流（前端主链路）",
    "/api/v1/runs/{run_id}/events/stream": "运行事件流（Last-Event-ID 断线重放）",
    "/api/v1/artifacts/{artifact_id}/regenerate": "产物重新生成",
}


@pytest.fixture(scope="module")
def nginx_conf() -> str:
    """反代配置以模板形式存在（容器启动时由 envsubst 渲染）。"""
    return (DEPLOY_DIR / "nginx.conf.template").read_text(encoding="utf-8")


def _strip_comments(conf: str) -> str:
    """去掉 `#` 行注释（中文注释里出现 location 等关键字会干扰解析）。"""
    return "\n".join(line.split("#", 1)[0] for line in conf.splitlines())


def _parse_locations(conf: str) -> list[tuple[str, str]]:
    """提取 (location 匹配表达式, 块内容)。支持前缀匹配与 `~` 正则。"""
    blocks: list[tuple[str, str]] = []
    conf = _strip_comments(conf)
    pattern = re.compile(r"location\s+([^{]+?)\s*\{", re.MULTILINE)
    for match in pattern.finditer(conf):
        start = match.end()
        depth = 1
        index = start
        while index < len(conf) and depth:
            if conf[index] == "{":
                depth += 1
            elif conf[index] == "}":
                depth -= 1
            index += 1
        blocks.append((match.group(1).strip(), conf[start : index - 1]))
    return blocks


def _location_matches(expression: str, path: str) -> bool:
    """判断 nginx location 表达式是否覆盖给定路径（只处理本项目用到的两种写法）。"""
    if expression.startswith("~"):
        return bool(re.search(expression[1:].strip(), path))
    if expression.startswith("="):
        return expression[1:].strip() == path
    return path.startswith(expression)


def _resolve_includes(body: str) -> str:
    """把 include 展开成片段内容，便于断言 `proxy_buffering off` 等指令。

    容器内片段名为 /etc/nginx/conf.d/<name>.conf，仓库内对应 deploy/nginx-<name>.conf。
    """

    def replace(match: re.Match[str]) -> str:
        snippet = DEPLOY_DIR / f"nginx-{Path(match.group(1)).name}"
        return snippet.read_text(encoding="utf-8") if snippet.exists() else ""

    return re.sub(r"include\s+([^;]+);", replace, body)


def test_sse_conf_disables_buffering() -> None:
    sse = (DEPLOY_DIR / "nginx-sse.conf").read_text(encoding="utf-8")
    assert "proxy_buffering off" in sse
    assert "proxy_cache off" in sse
    assert "X-Accel-Buffering no" in sse
    # 读超时必须覆盖审批等待（默认 180s）
    timeout = int(re.search(r"proxy_read_timeout\s+(\d+)s", sse).group(1))
    assert timeout >= 300, f"SSE 读超时 {timeout}s 不足以覆盖审批等待 180s"


@pytest.mark.parametrize("path", sorted(SSE_ENDPOINTS))
def test_every_sse_endpoint_is_unbuffered(nginx_conf: str, path: str) -> None:
    """每条 SSE 端点都必须落在一个关闭缓冲的 location 里。"""
    for expression, body in _parse_locations(nginx_conf):
        if not _location_matches(expression, path):
            continue
        expanded = _resolve_includes(body)
        if "proxy_buffering off" in expanded:
            return
    pytest.fail(f"SSE 端点 {path}（{SSE_ENDPOINTS[path]}）未被关闭缓冲的 location 覆盖")


def test_sse_location_precedes_api_catch_all(nginx_conf: str) -> None:
    """nginx 正则 location 按书写顺序匹配：SSE 规则必须写在兜底 /api/ 之前。"""
    locations = [expression for expression, _ in _parse_locations(nginx_conf)]
    catch_all = next((i for i, item in enumerate(locations) if item == "/api/"), None)
    assert catch_all is not None, "缺少兜底 location /api/"
    sse_locations = [
        i for i, item in enumerate(locations) if item.startswith("~") and "stream" in item
    ]
    assert sse_locations, "未找到 SSE 正则 location"
    for index in sse_locations:
        assert index < catch_all, "正则 SSE location 必须位于兜底 /api/ 之前"


@pytest.mark.parametrize("path", sorted(SSE_ENDPOINTS))
def test_sse_endpoints_also_cover_legacy_api_prefix(path: str) -> None:
    """后端同时挂载 /api/v1 与旧 /api 别名，两条前缀都要被 SSE 规则覆盖。"""
    legacy = path.replace("/api/v1/", "/api/", 1)
    assert legacy != path, f"{path} 已是旧前缀"
    for expression, body in _parse_locations(
        (DEPLOY_DIR / "nginx.conf.template").read_text(encoding="utf-8")
    ):
        if _location_matches(expression, legacy) and "proxy_buffering off" in _resolve_includes(
            body
        ):
            return
    pytest.fail(f"旧别名路径 {legacy} 未被关闭缓冲的 location 覆盖")


def test_snippets_are_not_placed_in_conf_d() -> None:
    """conf.d/*.conf 会被顶层 nginx.conf 自动 include：

    把 `proxy_pass` 这类 location 级指令放进去会让 nginx 启动失败，
    因此片段必须落在 snippets/ 目录。
    """
    dockerfile = (PROJECT_ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "/etc/nginx/snippets/" in dockerfile
    for line in dockerfile.splitlines():
        if line.startswith("COPY deploy/nginx-"):
            assert "/etc/nginx/conf.d/" not in line, f"片段不应写入 conf.d：{line}"


def test_upload_limit_is_linked_with_backend() -> None:
    """nginx 的 client_max_body_size 必须与后端 MAX_UPLOAD_MB 用同一个变量。"""
    template = (DEPLOY_DIR / "nginx.conf.template").read_text(encoding="utf-8")
    assert "client_max_body_size ${NGINX_CLIENT_MAX_BODY_SIZE}" in template

    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "NGINX_CLIENT_MAX_BODY_SIZE" in compose
    assert "${MAX_UPLOAD_MB" in compose

    dockerfile = (PROJECT_ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    # 必须有默认值，否则 envsubst 渲染出空值会让 nginx 语法报错
    assert "NGINX_CLIENT_MAX_BODY_SIZE=20m" in dockerfile
    # 限定只替换 NGINX_ 前缀，避免 $host 等被误替换
    assert "NGINX_ENVSUBST_FILTER=NGINX_" in dockerfile


def test_security_header_snippet_is_complete() -> None:
    headers = (DEPLOY_DIR / "nginx-security-headers.conf").read_text(encoding="utf-8")
    for name in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Content-Security-Policy",
    ):
        assert name in headers, f"安全响应头片段缺少 {name}"


def test_every_location_includes_security_headers(nginx_conf: str) -> None:
    """add_header 不跨块继承：每个 location 都要 include 安全头片段。"""
    for expression, body in _parse_locations(nginx_conf):
        assert "security-headers.conf" in body, f"location {expression} 缺少安全响应头"


def test_compose_ports_bind_loopback_only() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    published = re.findall(r'-\s+"(\d+\.\d+\.\d+\.\d+)?:?(\d+):(\d+)"', compose)
    assert published, "未找到端口映射"
    for host, _host_port, _container_port in published:
        assert host == "127.0.0.1", f"端口 {host or '(所有网卡)'}:… 未绑回环，请改为 127.0.0.1"


def test_dockerfile_copies_nginx_snippets() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    for name in ("nginx-proxy-common.conf", "nginx-sse.conf", "nginx-security-headers.conf"):
        assert name in dockerfile, f"Dockerfile.web 未复制 {name}"
