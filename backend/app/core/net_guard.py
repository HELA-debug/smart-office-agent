"""出站 URL 安全校验（SSRF 防护）。

模型 base_url 由用户在设置中心填写，且请求会带上供应商 API Key。
一旦服务被暴露，未校验的 base_url 等于「带凭据请求任意地址」的代理，
因此登记/调用前必须校验：

1. 只允许 http/https；
2. 主机名解析后的所有 IP 不得落在内网/本机/链路本地/保留地址段；
3. 若配置了域名白名单（MODEL_BASE_URL_ALLOWLIST），则只允许白名单域名。

说明：DNS 解析与连接之间存在 TOCTOU 窗口；这里的定位是拦住配置误填与
显而易见的滥用，真正的多租户隔离应由网络策略（出网白名单）承担。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# 禁止出网的目标网段（本机 / 私有 / 链路本地 / 保留 / 未指定）
_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # 云厂商元数据服务 169.254.169.254
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),  # 组播
    ipaddress.ip_network("240.0.0.0/4"),  # 保留
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 唯一本地
    ipaddress.ip_network("fe80::/10"),  # IPv6 链路本地
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped
)

# 无需解析即可判定的本机主机名
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "::1"})


class UnsafeUrlError(ValueError):
    """URL 不允许作为出站目标。"""

    def __init__(self, message: str, *, reason: str = "unsafe_url"):
        super().__init__(message)
        self.message = message
        self.reason = reason


def _is_blocked_ip(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return True
    # IPv4-mapped（::ffff:127.0.0.1）拆出内嵌 IPv4 再判一次
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None and any(mapped in net for net in _BLOCKED_NETWORKS):
        return True
    return any(address in net for net in _BLOCKED_NETWORKS)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def resolve_host(host: str) -> list[str]:
    """解析主机名为 IP 列表；解析失败返回空列表（交由调用方拒绝）。"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    # info[4] 是 (family, type, proto, canonname, sockaddr)，sockaddr[0] 才是 IP 字符串
    return [str(info[4][0]) for info in infos]


def validate_outbound_url(
    url: str,
    *,
    allowlist: set[str] | frozenset[str] | None = None,
    resolve: bool = True,
) -> str:
    """校验出站 URL 合法且目标不在内网段；返回归一化后的 URL。

    非法时抛 UnsafeUrlError。resolve=False 时只做静态校验（便于单测）。
    """
    raw = (url or "").strip()
    if not raw:
        raise UnsafeUrlError("地址不能为空")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"只允许 http/https 地址，当前为 {parsed.scheme or '（无协议）'}")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise UnsafeUrlError("地址缺少主机名")

    if allowlist:
        allowed = {item.strip().lower() for item in allowlist if item.strip()}
        if host not in allowed and not any(host.endswith(f".{item}") for item in allowed):
            raise UnsafeUrlError(
                f"域名 {host} 不在允许列表内（MODEL_BASE_URL_ALLOWLIST）",
                reason="host_not_allowed",
            )
        return raw.rstrip("/")

    # 主机名已经是字面 IP：直接判定，省一次 DNS
    if _is_ip_literal(host):
        if _is_blocked_ip(host):
            raise UnsafeUrlError("不允许指向内网/本机地址", reason="local_address")
        return raw.rstrip("/")
    if host in _LOCAL_HOSTNAMES:
        raise UnsafeUrlError("不允许指向本机地址", reason="local_address")

    if not resolve:
        return raw.rstrip("/")

    addresses = resolve_host(host)
    if not addresses:
        raise UnsafeUrlError(f"域名无法解析：{host}", reason="dns_failed")
    blocked = [item for item in addresses if _is_blocked_ip(item)]
    if blocked:
        raise UnsafeUrlError(f"域名 {host} 解析到内网地址，已拒绝", reason="local_address")
    return raw.rstrip("/")
