"""sing-box engine implementation.

Manages sing-box binary discovery, config generation, and process lifecycle.
"""
import ipaddress
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from ..server_model import ProxyProtocol
from .base import ProxyEngine, EngineType
from . import common

log = logging.getLogger("engine.singbox")

SINGBOX_VERSION = "v1.11.8"
RELEASE_BASE_URL = "https://github.com/SagerNet/sing-box/releases/download"
_VERSION_MARKER = ".singbox-version"

_TARGET_MAP = {
    ("windows", "amd64"): "windows-amd64",
    ("windows", "x86_64"): "windows-amd64",
    ("windows", "arm64"): "windows-arm64",
    ("windows", "aarch64"): "windows-arm64",
    ("linux", "amd64"): "linux-amd64",
    ("linux", "x86_64"): "linux-amd64",
    ("linux", "arm64"): "linux-arm64",
    ("linux", "aarch64"): "linux-arm64",
    ("darwin", "amd64"): "darwin-amd64",
    ("darwin", "x86_64"): "darwin-amd64",
    ("darwin", "arm64"): "darwin-arm64",
    ("darwin", "aarch64"): "darwin-arm64",
}

_PROFILE = common.InstallProfile(
    engine_name="sing-box",
    version=SINGBOX_VERSION,
    release_base_url=RELEASE_BASE_URL,
    marker_name=_VERSION_MARKER,
    temp_prefix=".singbox-",
    target_map=_TARGET_MAP,
    archive_name=lambda version, target: f"sing-box-{version}-{target}.zip",
)


def _detect_target():
    return common._detect_target(_TARGET_MAP)


def _binary_name():
    return common._binary_name("sing-box")


def _find_binary() -> Path | None:
    return common._find_binary("sing-box")


def _check_usable(path) -> "CheckResult":
    return common._check_usable(path, "sing-box")


def _download(url, dest, progress_cb=None):
    return common._download(url, dest, progress_cb=progress_cb)


def _install(progress_cb=None):
    return common._install(_PROFILE, progress_cb=progress_cb)


def _build_singbox_transport(server) -> dict | None:
    """Build sing-box transport config from a Server object."""
    transport_type = getattr(server, "transport", "tcp") or "tcp"
    if transport_type == "tcp":
        return None

    if transport_type == "ws":
        transport: dict = {"type": "ws"}
        path = getattr(server, "path", "") or ""
        if path:
            transport["path"] = path
        host_header = getattr(server, "host_header", "") or getattr(server, "server_name", "") or ""
        if host_header:
            transport["headers"] = {"Host": host_header}
        return transport

    if transport_type == "grpc":
        transport = {"type": "grpc"}
        service = getattr(server, "path", "") or ""
        if service:
            transport["service_name"] = service
        return transport

    if transport_type == "xhttp":
        transport_type = "http"

    return {"type": transport_type}


def _build_singbox_vless_outbound(server) -> dict:
    """Build a sing-box VLESS outbound dict."""
    outbound: dict = {
        "type": "vless",
        "tag": "proxy",
        "server": server.host,
        "server_port": int(server.port),
        "uuid": getattr(server, "uuid", ""),
    }

    transport_type = getattr(server, "transport", "tcp") or "tcp"
    flow = getattr(server, "flow", "") or ""
    if flow and transport_type == "tcp":
        outbound["flow"] = flow

    security = getattr(server, "security", "none") or "none"
    if security != "none":
        tls: dict = {"enabled": True}
        sni = getattr(server, "server_name", "") or ""
        if sni:
            tls["server_name"] = sni
        fp = getattr(server, "fingerprint", "") or "chrome"
        tls["utls"] = {"enabled": True, "fingerprint": fp}
        if getattr(server, "allow_insecure", False) or getattr(server, "insecure", False):
            tls["insecure"] = True
        if security == "reality":
            pbk = getattr(server, "public_key", "") or ""
            sid = getattr(server, "short_id", "") or ""
            tls["reality"] = {"enabled": True, "public_key": pbk, "short_id": sid}
        outbound["tls"] = tls

    transport = _build_singbox_transport(server)
    if transport:
        outbound["transport"] = transport

    return outbound


def _build_singbox_vmess_outbound(server) -> dict:
    """Build a sing-box VMess outbound dict."""
    outbound: dict = {
        "type": "vmess",
        "tag": "proxy",
        "server": server.host,
        "server_port": int(server.port),
        "uuid": getattr(server, "uuid", ""),
        "alter_id": int(getattr(server, "alter_id", 0)),
        "security": getattr(server, "vmess_security", "auto") or "auto",
    }

    security = getattr(server, "security", "none") or "none"
    if security != "none":
        tls = {"enabled": True}
        sni = getattr(server, "server_name", "") or ""
        if sni:
            tls["server_name"] = sni
        fp = getattr(server, "fingerprint", "") or "chrome"
        tls["utls"] = {"enabled": True, "fingerprint": fp}
        if getattr(server, "allow_insecure", False) or getattr(server, "insecure", False):
            tls["insecure"] = True
        outbound["tls"] = tls

    transport = _build_singbox_transport(server)
    if transport:
        outbound["transport"] = transport

    return outbound


def _build_singbox_ss_outbound(server) -> dict:
    """Build a sing-box Shadowsocks outbound dict."""
    return {
        "type": "shadowsocks",
        "tag": "proxy",
        "server": server.host,
        "server_port": int(server.port),
        "method": server.method,
        "password": server.password,
        "multiplex": {"enabled": False},
    }


def _build_singbox_hysteria2_outbound(server) -> dict:
    """Build a sing-box Hysteria 2 outbound dict."""
    outbound: dict = {
        "type": "hysteria2",
        "tag": "proxy",
        "server": server.host,
        "server_port": int(server.port),
    }

    password = getattr(server, "password", "") or ""
    if password:
        outbound["password"] = password

    ports = getattr(server, "ports", "") or ""
    if ports:
        outbound["server_ports"] = ports

    up_mbps = getattr(server, "up_mbps", 0)
    if up_mbps:
        try:
            outbound["up_mbps"] = int(up_mbps)
        except (ValueError, TypeError):
            pass

    down_mbps = getattr(server, "down_mbps", 0)
    if down_mbps:
        try:
            outbound["down_mbps"] = int(down_mbps)
        except (ValueError, TypeError):
            pass

    obfs_type = getattr(server, "obfs", "") or ""
    obfs_pass = getattr(server, "obfs_password", "") or ""
    if obfs_type or obfs_pass:
        obfs_dict: dict = {}
        if obfs_type:
            obfs_dict["type"] = obfs_type
        if obfs_pass:
            obfs_dict["password"] = obfs_pass
        outbound["obfs"] = obfs_dict

    tls: dict = {"enabled": True}
    sni = getattr(server, "server_name", "")
    if sni:
        tls["server_name"] = sni
    elif getattr(server, "host", ""):
        host = getattr(server, "host", "")
        # Only use host as SNI if it is a domain, not an IP address
        try:
            import ipaddress
            ipaddress.ip_address(host)
        except ValueError:
            tls["server_name"] = host

    insecure = getattr(server, "insecure", None)
    if insecure is None or bool(insecure):
        tls["insecure"] = True
    outbound["tls"] = tls

    return outbound


_SINGBOX_OUTBOUND_BUILDERS = {
    ProxyProtocol.SHADOWSOCKS: _build_singbox_ss_outbound,
    ProxyProtocol.VLESS: _build_singbox_vless_outbound,
    ProxyProtocol.VMESS: _build_singbox_vmess_outbound,
    ProxyProtocol.HYSTERIA2: _build_singbox_hysteria2_outbound,
}


def _build_singbox_dns_server(dns_target: str, tag="remote-dns", detour="proxy") -> dict:
    """Build a sing-box DNS server block for DoH, DoT, or standard UDP DNS."""
    if not dns_target or dns_target.strip().lower() == "default":
        return {
            "tag": tag,
            "type": "https",
            "server": "1.1.1.1",
            "path": "/dns-query",
            "detour": detour,
        }
    target = dns_target.strip()
    if target.startswith("https://"):
        from urllib.parse import urlparse
        p = urlparse(target)
        host = p.hostname or "1.1.1.1"
        path = p.path or "/dns-query"
        server_entry = {
            "tag": tag,
            "type": "https",
            "server": host,
            "path": path,
            "detour": detour,
        }
        if p.port:
            server_entry["server_port"] = p.port
        return server_entry
    elif target.startswith("tls://"):
        from urllib.parse import urlparse
        p = urlparse(target)
        host = p.hostname or "1.1.1.1"
        return {
            "tag": tag,
            "type": "tls",
            "server": host,
            "server_port": p.port or 853,
            "detour": detour,
        }
    else:
        clean = target.replace("udp://", "")
        if ":" in clean and not clean.startswith("["):
            host, port_s = clean.rsplit(":", 1)
            port = int(port_s)
        else:
            host = clean
            port = 53
        return {
            "tag": tag,
            "type": "udp",
            "server": host,
            "server_port": port,
            "detour": detour,
        }


def _generate_config(server, local_port, tun_mode=False, custom_dns=None) -> dict:
    """Generate sing-box JSON config for a single server."""
    protocol = getattr(server, "protocol", ProxyProtocol.SHADOWSOCKS)

    builder = _SINGBOX_OUTBOUND_BUILDERS.get(protocol)
    if builder is None:
        raise ValueError(f"sing-box engine does not support protocol: {protocol}")
    outbound = builder(server)

    server_host = getattr(server, "host", "") or ""
    server_rule = None
    server_ip_cidr = None
    if server_host:
        try:
            ip = ipaddress.ip_address(server_host)
            cidr = f"{server_host}/32" if ip.version == 4 else f"{server_host}/128"
            server_ip_cidr = cidr
            server_rule = {"ip_cidr": [cidr], "outbound": "direct"}
        except ValueError:
            server_rule = {"domain": [server_host], "outbound": "direct"}

    if tun_mode:
        tun_adapter_name = "socksicle-tun"
        outbound["domain_resolver"] = "local-dns"
        direct_outbound = {"type": "direct", "tag": "direct", "domain_resolver": "local-dns"}
        rules = [
            {"action": "sniff"},
            {"inbound": ["tun-in"], "protocol": "dns", "action": "hijack-dns"},
            {"port": 123, "outbound": "direct"},
        ]
        if server_rule:
            rules.append(server_rule)
        rules.append({"ip_is_private": True, "outbound": "direct"})

        tun_inbound: dict = {
            "type": "tun",
            "tag": "tun-in",
            "interface_name": tun_adapter_name,
            "address": [
                "172.19.0.1/30",
                "fdfe:dcba:9876::1/126",
            ],
            "auto_route": True,
            "strict_route": True,
            "route_address": [
                "0.0.0.0/1",
                "128.0.0.0/1",
                "::/1",
                "8000::/1",
            ],
            "stack": "mixed",
            "endpoint_independent_nat": True,
        }
        if server_ip_cidr:
            tun_inbound["route_exclude_address"] = [server_ip_cidr]

        dns_servers = []
        if custom_dns and custom_dns.strip() and custom_dns.strip().lower() != "default":
            dns_servers.append(_build_singbox_dns_server(custom_dns, "remote-dns", "proxy"))
            dns_servers.append({
                "tag": "remote-dns-fallback",
                "type": "https",
                "server": "1.1.1.1",
                "path": "/dns-query",
                "detour": "proxy",
            })
        else:
            dns_servers.extend([
                {
                    "tag": "remote-dns",
                    "type": "https",
                    "server": "1.1.1.1",
                    "path": "/dns-query",
                    "detour": "proxy",
                },
                {
                    "tag": "remote-dns-google",
                    "type": "https",
                    "server": "8.8.8.8",
                    "path": "/dns-query",
                    "detour": "proxy",
                },
            ])
        dns_servers.append({
            "tag": "local-dns",
            "type": "local",
            "detour": "direct",
        })

        config = {
            "log": {"level": "info", "timestamp": True},
            "dns": {
                "servers": dns_servers,
                "strategy": "prefer_ipv4",
                "reverse_mapping": True,
            },
            "inbounds": [
                tun_inbound,
                {
                    "type": "mixed",
                    "tag": "mixed-in",
                    "listen": "127.0.0.1",
                    "listen_port": int(local_port),
                },
            ],
            "outbounds": [
                outbound,
                direct_outbound,
            ],
            "route": {
                "default_domain_resolver": "remote-dns",
                "rules": rules,
                "auto_detect_interface": True,
                "final": "proxy",
            },
        }
    else:
        direct_outbound = {"type": "direct", "tag": "direct"}
        rules = [
            {"protocol": "dns", "outbound": "direct"},
            {"port": 123, "outbound": "direct"},
        ]
        if server_rule:
            rules.append(server_rule)
        rules.append({"ip_is_private": True, "outbound": "direct"})

        config = {
            "log": {"level": "info", "timestamp": True},
            "inbounds": [
                {
                    "type": "mixed",
                    "tag": "mixed-in",
                    "listen": "127.0.0.1",
                    "listen_port": int(local_port),
                }
            ],
            "outbounds": [
                outbound,
                direct_outbound
            ],
            "route": {
                "rules": rules,
                "final": "proxy"
            }
        }

    return config


def _tun_device_check() -> tuple[bool, str]:
    """Check whether the Linux TUN device is present and usable.

    Returns (ok, message); on non-Linux platforms always ok.
    """
    if sys.platform == "win32":
        return True, ""
    if not os.path.exists("/dev/net/tun"):
        return False, (
            "TUN Mode requires the Linux /dev/net/tun device, which is "
            "missing on this system. Enable it (e.g. 'modprobe tun') and "
            "ensure the TUN kernel module is loaded, then try again."
        )
    return True, ""


class SingBoxEngine(ProxyEngine):
    engine_type = EngineType.SINGBOX

    def __init__(self):
        super().__init__()
        self.tun_mode = False
        self.custom_dns = None

    def _clean_stale_tun_adapter(self):
        """Clean any stale Wintun/socksicle network adapter on Windows."""
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["netsh", "interface", "delete", "interface", "name=socksicle-tun"],
                    capture_output=True,
                    timeout=1,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                )
            except Exception:
                pass

    def start(self, server):
        if self.tun_mode:
            self._clean_stale_tun_adapter()
            ok, reason = _tun_device_check()
            if not ok:
                log.error("TUN start blocked: %s", reason)
                self.statusChanged.emit(f"Connection failed: {reason}", True)
                return False
            if sys.platform.startswith("linux"):
                from ..platform_utils import check_tun_capabilities, grant_tun_capabilities
                binary = self.find_binary()
                if binary and not check_tun_capabilities(binary):
                    log.info("sing-box binary lacks TUN capabilities; requesting grant...")
                    granted = grant_tun_capabilities(binary)
                    if not granted or not check_tun_capabilities(binary):
                        reason = (
                            "TUN mode on Linux requires cap_net_admin capabilities on sing-box. "
                            "Authorization was declined or setcap failed."
                        )
                        log.error("TUN start blocked: %s", reason)
                        self.statusChanged.emit(f"Connection failed: {reason}", True)
                        return False
        return super().start(server)

    def teardown(self):
        super().teardown()
        if self.tun_mode:
            self._clean_stale_tun_adapter()

    def find_binary(self):
        return _find_binary()

    def check_usable(self, path):
        return _check_usable(path)

    def install(self, progress_cb=None):
        return _install(progress_cb=progress_cb)

    def build_config(self, server):
        return _generate_config(server, self.local_port, tun_mode=self.tun_mode, custom_dns=self.custom_dns)

    def build_args(self, server):
        return super().build_args(server, ["run", "-c"], "singbox-")

    def version_args(self):
        return ["version"]

    def process_name(self):
        return "sing-box (TUN)" if self.tun_mode else "sing-box"


