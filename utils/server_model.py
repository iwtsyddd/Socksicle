"""Server model shared across the app."""
import functools
import ipaddress
import logging
import time
from dataclasses import dataclass
from enum import Enum

from .ss_parser import decode_ss_link

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1024)
def is_private_host(host: str) -> bool:
    """Return True if *host* resolves to a private/loopback/reserved IP."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
    except ValueError:
        return False


class ProxyProtocol(str, Enum):
    SHADOWSOCKS = "shadowsocks"
    VLESS = "vless"
    VMESS = "vmess"
    HYSTERIA2 = "hysteria2"


@dataclass
class Server:
    key: str = ""
    name: str = "Server"
    host: str = ""
    port: int = 443
    method: str = "aes-256-gcm"
    password: str = ""
    plugin: str = ""
    plugin_opts: str = ""
    protocol: ProxyProtocol = ProxyProtocol.SHADOWSOCKS
    uuid: str = ""
    security: str = "none"
    transport: str = "tcp"
    flow: str = ""
    encryption: str = "none"
    server_name: str = ""
    fingerprint: str = "chrome"
    public_key: str = ""
    short_id: str = ""
    alter_id: int = 0
    vmess_security: str = "auto"
    path: str = ""
    host_header: str = ""
    is_private: bool = False
    insecure: bool = False
    obfs: str = ""
    obfs_password: str = ""
    ports: str = ""
    up_mbps: int = 0
    down_mbps: int = 0
    lock_export: bool = False
    expires_at: int | None = None

    @property
    def is_expired(self) -> bool:
        """Return True if expires_at is set and current time is past it."""
        if self.expires_at is None or self.expires_at <= 0:
            return False
        return time.time() >= self.expires_at

    @classmethod
    def from_link(cls, raw_link, default_name="Server"):
        """Parse an ss://, vless://, vmess://, hysteria2://, or hy2:// link into a Server, or None."""
        if not raw_link:
            return None
        if raw_link.startswith(('vless://', 'vmess://', 'hysteria2://', 'hy2://')):
            from .link_parser import parse_link
            return parse_link(raw_link, default_name=default_name)
        data = decode_ss_link(raw_link)
        if not data:
            return None
        host = data.get('server', '')
        is_priv = is_private_host(host)
        if is_priv:
            log.warning("SS link points to private/reserved IP: %s", host)
        return cls(
            key=raw_link,
            name=data.get('tag', default_name) or default_name,
            host=host,
            port=int(data.get('port', 443)),
            method=data.get('method', 'aes-256-gcm'),
            password=data.get('password', ''),
            plugin=data.get('plugin', ''),
            plugin_opts=data.get('plugin_opts', ''),
            is_private=is_priv,
        )

    @classmethod
    def from_dict(cls, data):
        """Build a Server from a stored dict (servers.json / subscription)."""
        if not isinstance(data, dict):
            data = {}
        try:
            port = int(data.get('port', 443))
        except (TypeError, ValueError):
            port = 443
        try:
            protocol = ProxyProtocol(data.get('protocol', 'shadowsocks'))
        except ValueError:
            protocol = ProxyProtocol.SHADOWSOCKS
        try:
            alter_id = int(data.get('alter_id', 0))
        except (TypeError, ValueError):
            alter_id = 0
        try:
            up_mbps = int(data.get('up_mbps', 0))
        except (TypeError, ValueError):
            up_mbps = 0
        try:
            down_mbps = int(data.get('down_mbps', 0))
        except (TypeError, ValueError):
            down_mbps = 0
        expires_at_raw = data.get('expires_at')
        expires_at = None
        if expires_at_raw is not None:
            try:
                expires_at = int(expires_at_raw)
            except (ValueError, TypeError):
                expires_at = None
        lock_export = bool(data.get('lock_export', False))
        return cls(
            key=data.get('key', ''),
            name=data.get('name', 'Server'),
            host=data.get('host', ''),
            port=port,
            method=data.get('method', 'aes-256-gcm'),
            password=data.get('password', ''),
            plugin=data.get('plugin', ''),
            plugin_opts=data.get('plugin_opts', ''),
            protocol=protocol,
            uuid=data.get('uuid', ''),
            security=data.get('security', 'none'),
            transport=data.get('transport', 'tcp'),
            flow=data.get('flow', ''),
            encryption=data.get('encryption', 'none'),
            server_name=data.get('server_name', ''),
            fingerprint=data.get('fingerprint', 'chrome'),
            public_key=data.get('public_key', ''),
            short_id=data.get('short_id', ''),
            alter_id=alter_id,
            vmess_security=data.get('vmess_security', 'auto'),
            path=data.get('path', ''),
            host_header=data.get('host_header', ''),
            is_private=data.get('is_private', False),
            insecure=bool(data.get('insecure', False)),
            obfs=data.get('obfs', ''),
            obfs_password=data.get('obfs_password', ''),
            ports=data.get('ports', ''),
            up_mbps=up_mbps,
            down_mbps=down_mbps,
            lock_export=lock_export,
            expires_at=expires_at,
        )

    def to_dict(self):
        """Serialize to storage format."""
        d = {
            "key": self.key,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "method": self.method,
            "password": self.password,
        }
        if self.plugin:
            d["plugin"] = self.plugin
        if self.plugin_opts:
            d["plugin_opts"] = self.plugin_opts
        if self.protocol != ProxyProtocol.SHADOWSOCKS:
            d["protocol"] = self.protocol.value
        if self.uuid:
            d["uuid"] = self.uuid
        if self.security != "none":
            d["security"] = self.security
        if self.transport != "tcp":
            d["transport"] = self.transport
        if self.flow:
            d["flow"] = self.flow
        if self.encryption != "none":
            d["encryption"] = self.encryption
        if self.server_name:
            d["server_name"] = self.server_name
        if self.fingerprint and self.fingerprint != "chrome":
            d["fingerprint"] = self.fingerprint
        if self.public_key:
            d["public_key"] = self.public_key
        if self.short_id:
            d["short_id"] = self.short_id
        if self.alter_id:
            d["alter_id"] = self.alter_id
        if self.vmess_security and self.vmess_security != "auto":
            d["vmess_security"] = self.vmess_security
        if self.path:
            d["path"] = self.path
        if self.host_header:
            d["host_header"] = self.host_header
        if self.is_private:
            d["is_private"] = True
        if self.insecure:
            d["insecure"] = True
        if self.obfs:
            d["obfs"] = self.obfs
        if self.obfs_password:
            d["obfs_password"] = self.obfs_password
        if self.ports:
            d["ports"] = self.ports
        if self.up_mbps:
            d["up_mbps"] = self.up_mbps
        if self.down_mbps:
            d["down_mbps"] = self.down_mbps
        if self.lock_export:
            d["lock_export"] = True
        if self.expires_at is not None:
            d["expires_at"] = self.expires_at
        return d

    @property
    def unique_key(self):
        if self.protocol == ProxyProtocol.SHADOWSOCKS:
            return f"{self.method}:{self.password}@{self.host}:{self.port}"
        if self.protocol == ProxyProtocol.VMESS:
            return f"vmess:{self.uuid}@{self.host}:{self.port}"
        if self.protocol == ProxyProtocol.HYSTERIA2:
            return f"hysteria2:{self.password}@{self.host}:{self.port}"
        return f"vless:{self.uuid}@{self.host}:{self.port}"

    @property
    def display_protocol(self):
        return self.protocol.value.upper()