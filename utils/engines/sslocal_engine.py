"""Shadowsocks-rust sslocal engine implementation."""
import logging

from .base import ProxyEngine, EngineType

log = logging.getLogger("engine.sslocal")


class SslocalEngine(ProxyEngine):
    engine_type = EngineType.SSLOCAL

    def __init__(self):
        super().__init__()
        from utils.ss_backend import SSLOCAL_VERSION
        self._version = SSLOCAL_VERSION

    def find_binary(self):
        from utils.ss_backend import find_sslocal
        return find_sslocal()

    def check_usable(self, path):
        from utils.ss_backend import is_usable
        return is_usable(path)

    def install(self, progress_cb=None):
        from utils.ss_backend import ensure_sslocal
        return ensure_sslocal(progress_cb=progress_cb)

    def build_config(self, server):
        from ..server_model import ProxyProtocol
        if hasattr(server, 'protocol') and server.protocol != ProxyProtocol.SHADOWSOCKS:
            raise ValueError(
                f"sslocal engine does not support {server.protocol.value} protocol. "
                f"Please use xray or sing-box engine instead."
            )
        return {
            "server": server.host,
            "server_port": server.port,
            "method": server.method,
            "password": server.password,
            "local_address": "127.0.0.1",
            "local_port": self.local_port,
        }

    def build_args(self, server):
        return super().build_args(server, ["-c"], "sslocal-")

    def version_args(self):
        return ["--version"]

    def process_name(self):
        return "sslocal"


