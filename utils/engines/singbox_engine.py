"""sing-box engine implementation.

Manages sing-box binary discovery, config generation, and process lifecycle.
"""
import logging
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
        host_header = getattr(server, "host_header", "") or ""
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

    flow = getattr(server, "flow", "") or ""
    if flow:
        outbound["flow"] = flow

    security = getattr(server, "security", "none") or "none"
    if security != "none":
        tls: dict = {"enabled": True}
        sni = getattr(server, "server_name", "") or ""
        if sni:
            tls["server_name"] = sni
        fp = getattr(server, "fingerprint", "") or ""
        if fp:
            tls["utls"] = {"enabled": True, "fingerprint": fp}
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
        fp = getattr(server, "fingerprint", "") or ""
        if fp:
            tls["utls"] = {"enabled": True, "fingerprint": fp}
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


_SINGBOX_OUTBOUND_BUILDERS = {
    ProxyProtocol.SHADOWSOCKS: _build_singbox_ss_outbound,
    ProxyProtocol.VLESS: _build_singbox_vless_outbound,
    ProxyProtocol.VMESS: _build_singbox_vmess_outbound,
}


def _generate_config(server, local_port) -> dict:
    """Generate sing-box JSON config for a single server."""
    protocol = getattr(server, "protocol", ProxyProtocol.SHADOWSOCKS)

    builder = _SINGBOX_OUTBOUND_BUILDERS.get(protocol)
    if builder is None:
        raise ValueError(f"sing-box engine does not support protocol: {protocol}")
    outbound = builder(server)

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
            {
                "type": "direct",
                "tag": "direct"
            }
        ],
        "route": {
            "rules": [
                {
                    "protocol": "dns",
                    "outbound": "direct"
                },
                {
                    "ip_is_private": True,
                    "outbound": "direct"
                }
            ],
            "final": "proxy"
        }
    }

    return config


class SingBoxEngine(ProxyEngine):
    engine_type = EngineType.SINGBOX

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
        return super().build_args(server, ["run", "-c"], "singbox-")

    def version_args(self):
        return ["version"]

    def process_name(self):
        return "sing-box"


