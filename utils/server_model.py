"""Server model shared across the app."""
import ipaddress
import logging
from dataclasses import dataclass
from enum import Enum

from .ss_parser import decode_ss_link

log = logging.getLogger(__name__)


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

    @classmethod
    def from_link(cls, raw_link, default_name="Server"):
        """Parse an ss://, vless://, or vmess:// link into a Server, or None."""
        if not raw_link:
            return None
        if raw_link.startswith(('vless://', 'vmess://')):
            from .link_parser import parse_link
            return parse_link(raw_link, default_name=default_name)
        data = decode_ss_link(raw_link)
        if not data:
            return None
        host = data.get('server', '')
        if is_private_host(host):
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
            is_private=is_private_host(host),
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
        return d

    @property
    def unique_key(self):
        if self.protocol == ProxyProtocol.SHADOWSOCKS:
            return f"{self.method}:{self.password}@{self.host}:{self.port}"
        if self.protocol == ProxyProtocol.VMESS:
            return f"vmess:{self.uuid}@{self.host}:{self.port}"
        return f"vless:{self.uuid}@{self.host}:{self.port}"

    @property
    def display_protocol(self):
        return self.protocol.value.upper()