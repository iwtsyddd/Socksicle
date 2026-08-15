"""Xray-core engine implementation.

Manages xray binary discovery, config generation, and process lifecycle.
"""
import logging
from pathlib import Path

from ..server_model import ProxyProtocol
from .base import ProxyEngine, EngineType
from . import common

log = logging.getLogger("engine.xray")

XRAY_VERSION = "v25.4.3"
RELEASE_BASE_URL = "https://github.com/XTLS/Xray-core/releases/download"
_VERSION_MARKER = ".xray-version"

_TARGET_MAP = {
    ("windows", "amd64"): "windows-64",
    ("windows", "x86_64"): "windows-64",
    ("windows", "arm64"): "windows-arm64-v8a",
    ("windows", "aarch64"): "windows-arm64-v8a",
    ("linux", "amd64"): "linux-64",
    ("linux", "x86_64"): "linux-64",
    ("linux", "arm64"): "linux-arm64-v8a",
    ("linux", "aarch64"): "linux-arm64-v8a",
    ("darwin", "amd64"): "macos-64",
    ("darwin", "x86_64"): "macos-64",
    ("darwin", "arm64"): "macos-arm64-v8a",
    ("darwin", "aarch64"): "macos-arm64-v8a",
}

_PROFILE = common.InstallProfile(
    engine_name="xray",
    version=XRAY_VERSION,
    release_base_url=RELEASE_BASE_URL,
    marker_name=_VERSION_MARKER,
    temp_prefix=".xray-",
    target_map=_TARGET_MAP,
    archive_name=lambda version, target: f"xray-{target}.zip",
)


def _detect_target():
    return common._detect_target(_TARGET_MAP)


def _binary_name():
    return common._binary_name("xray")


def _find_binary() -> Path | None:
    return common._find_binary("xray")


def _check_usable(path) -> "CheckResult":
    return common._check_usable(path, "xray")


def _download(url, dest, progress_cb=None):
    return common._download(url, dest, progress_cb=progress_cb)


def _install(progress_cb=None):
    return common._install(_PROFILE, progress_cb=progress_cb)


def _build_xray_stream_settings(server) -> dict:
    """Build streamSettings for VLESS/VMess outbounds."""
    stream = {"network": server.transport or "tcp"}

    security = getattr(server, 'security', 'none')
    fp = getattr(server, 'fingerprint', 'chrome')
    sni = getattr(server, 'server_name', '') or getattr(server, 'host', '')
    host_header = getattr(server, 'host_header', '')
    path = getattr(server, 'path', '')
    transport = getattr(server, 'transport', 'tcp')

    if security == 'tls':
        stream["security"] = "tls"
        tls_settings = {}
        if sni:
            tls_settings["serverName"] = sni
        if fp:
            tls_settings["fingerprint"] = fp
        stream["tlsSettings"] = tls_settings
    elif security == 'reality':
        stream["security"] = "reality"
        reality_settings = {}
        if sni:
            reality_settings["serverName"] = sni
        if fp:
            reality_settings["fingerprint"] = fp
        pbk = getattr(server, 'public_key', '')
        sid = getattr(server, 'short_id', '')
        if pbk:
            reality_settings["publicKey"] = pbk
        if sid:
            reality_settings["shortId"] = sid
        stream["realitySettings"] = reality_settings

    if transport == 'ws':
        ws_settings = {}
        if path:
            ws_settings["path"] = path
        if host_header:
            ws_settings["headers"] = {"Host": host_header}
        stream["wsSettings"] = ws_settings
    elif transport == 'grpc':
        grpc_settings = {}
        if path:
            grpc_settings["serviceName"] = path
        stream["grpcSettings"] = grpc_settings
    elif transport == 'xhttp':
        xhttp_settings = {}
        if path:
            xhttp_settings["path"] = path
        if host_header:
            xhttp_settings["host"] = [host_header]
        stream["xhttpSettings"] = xhttp_settings

    return stream


def _build_xray_vless_outbound(server) -> dict:
    """Generate outbound dict for a VLESS server."""
    from utils.server_model import ProxyProtocol
    settings = {
        "vnext": [{
            "address": server.host,
            "port": server.port,
            "users": [{
                "id": server.uuid,
                "encryption": getattr(server, 'encryption', 'none'),
                "flow": getattr(server, 'flow', ''),
            }]
        }]
    }
    return {
        "tag": "proxy",
        "protocol": "vless",
        "settings": settings,
        "streamSettings": _build_xray_stream_settings(server),
    }


def _build_xray_vmess_outbound(server) -> dict:
    """Generate outbound dict for a VMess server."""
    settings = {
        "vnext": [{
            "address": server.host,
            "port": server.port,
            "users": [{
                "id": server.uuid,
                "alterId": getattr(server, 'alter_id', 0),
                "security": getattr(server, 'vmess_security', 'auto'),
            }]
        }]
    }
    return {
        "tag": "proxy",
        "protocol": "vmess",
        "settings": settings,
        "streamSettings": _build_xray_stream_settings(server),
    }


def _build_xray_ss_outbound(server) -> dict:
    """Generate outbound dict for a Shadowsocks server."""
    return {
        "tag": "proxy",
        "protocol": "shadowsocks",
        "settings": {
            "servers": [{
                "address": server.host,
                "port": server.port,
                "method": server.method,
                "password": server.password,
            }]
        },
        "streamSettings": {"network": "tcp"},
    }


_XRAY_OUTBOUND_BUILDERS = {
    ProxyProtocol.SHADOWSOCKS: _build_xray_ss_outbound,
    ProxyProtocol.VLESS: _build_xray_vless_outbound,
    ProxyProtocol.VMESS: _build_xray_vmess_outbound,
}


def _generate_config(server, local_port) -> dict:
    """Generate xray JSON config for a single proxy server."""
    protocol = getattr(server, 'protocol', ProxyProtocol.SHADOWSOCKS)
    builder = _XRAY_OUTBOUND_BUILDERS.get(protocol)
    if builder is None:
        raise ValueError(f"Xray engine does not support protocol: {protocol}")
    outbound = builder(server)

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": int(local_port),
                "protocol": "socks",
                "settings": {"udp": True},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            }
        ],
        "outbounds": [
            outbound,
            {
                "tag": "direct",
                "protocol": "freedom"
            }
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": []
        }
    }


class XrayEngine(ProxyEngine):
    engine_type = EngineType.XRAY

    def __init__(self):
        super().__init__()

    def find_binary(self):
        return _find_binary()

    def check_usable(self, path):
        return _check_usable(path)

    def install(self, progress_cb=None):
        return _install(progress_cb=progress_cb)

    def build_config(self, server):
        return _generate_config(server, self.local_port)

    def build_args(self, server):
        return super().build_args(server, ["run", "-c"], "xray-")

    def version_args(self):
        return ["version"]

    def process_name(self):
        return "xray"


