"""Kill Switch implementation for Socksicle.

Provides OS firewall-level traffic blocking (Windows netsh / Linux nftables/iptables)
to prevent real IP leaks if the VPN proxy tunnel drops unexpectedly.
"""
import atexit
import ipaddress
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional, List

from .platform_utils import is_windows, is_linux, is_admin

log = logging.getLogger("killswitch")

# Firewall rule names for Windows netsh
_WIN_RULE_PREFIX = "Socksicle_KS_"
_WIN_RULES = [
    f"{_WIN_RULE_PREFIX}BlockOut",
    f"{_WIN_RULE_PREFIX}AllowLoopback",
    f"{_WIN_RULE_PREFIX}AllowLAN",
    f"{_WIN_RULE_PREFIX}AllowServer",
    f"{_WIN_RULE_PREFIX}AllowApp",
]

_LAN_RANGES_V4 = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"]
_LAN_RANGES_V6 = ["fe80::/10", "fc00::/7"]


def _resolve_ip(host: str) -> Optional[str]:
    """Resolve a domain host to an IPv4/IPv6 address string."""
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if infos:
            return infos[0][4][0]
    except Exception as e:
        log.debug("DNS resolution for kill switch target '%s' failed: %s", host, e)
    return None


class KillSwitchManager:
    """Manages OS firewall rules for Kill Switch protection."""

    _instance = None
    _active = False
    _current_server_ip: Optional[str] = None
    _current_server_port: Optional[int] = None
    _current_app_path: Optional[str] = None

    @classmethod
    def get_instance(cls) -> "KillSwitchManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._registered_atexit = False
        if not self._registered_atexit:
            atexit.register(self.cleanup)
            self._registered_atexit = True

    @property
    def is_active(self) -> bool:
        return self._active

    def clean_stale_rules(self) -> None:
        """Emergency cleanup of leftover firewall rules on startup or crash recovery."""
        if is_windows():
            if not is_admin():
                log.debug("Skipping stale rule cleanup: no admin rights")
                return
            log.info("Checking and cleaning any stale Socksicle Kill Switch firewall rules...")
            for rule in _WIN_RULES:
                self._run_netsh(["advfirewall", "firewall", "delete", "rule", f"name={rule}"])
        elif is_linux():
            if not is_admin():
                return
            try:
                subprocess.run(["nft", "delete", "table", "inet", "socksicle_ks"],
                               capture_output=True, check=False)
            except Exception:
                pass

    def enable(self, server_host: str, server_port: Optional[int] = None,
               engine_path: Optional[str] = None) -> bool:
        """Enable Kill Switch protection for the given server and engine."""
        if not is_admin():
            log.warning("Cannot enable Kill Switch: Administrator / root privileges required")
            return False

        server_ip = _resolve_ip(server_host)
        self._current_server_ip = server_ip
        self._current_server_port = int(server_port) if server_port else None
        self._current_app_path = str(engine_path) if engine_path else None

        # Clean existing rules first to avoid duplicate collisions
        self.clean_stale_rules()

        success = False
        if is_windows():
            success = self._enable_windows(server_ip, self._current_server_port, self._current_app_path)
        elif is_linux():
            success = self._enable_linux(server_ip, self._current_server_port)
        else:
            log.warning("Kill switch is not supported on this platform: %s", sys.platform)
            return False

        self._active = success
        if success:
            log.info("Kill Switch ENABLED (Target server: %s:%s)", server_ip or server_host, server_port)
        return success

    def disable(self) -> bool:
        """Disable Kill Switch protection and tear down firewall rules."""
        self.clean_stale_rules()
        self._active = False
        self._current_server_ip = None
        self._current_server_port = None
        self._current_app_path = None
        log.info("Kill Switch DISABLED")
        return True

    def cleanup(self) -> None:
        """Teardown handler on application shutdown."""
        if self._active or is_admin():
            self.clean_stale_rules()
            self._active = False

    def _run_netsh(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run netsh command hidden without opening console window."""
        creationflags = 0
        if is_windows():
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return subprocess.run(
            ["netsh"] + args,
            capture_output=True,
            text=True,
            creationflags=creationflags,
            check=False
        )

    def _enable_windows(self, server_ip: Optional[str], server_port: Optional[int],
                        engine_path: Optional[str]) -> bool:
        """Set up netsh advfirewall rules on Windows."""
        try:
            # 1. Allow Loopback (127.0.0.1 and ::1)
            res = self._run_netsh([
                "advfirewall", "firewall", "add", "rule",
                f"name={_WIN_RULE_PREFIX}AllowLoopback",
                "dir=out", "action=allow",
                "remoteip=127.0.0.1,::1"
            ])
            if res.returncode != 0:
                log.warning("Failed to add loopback rule: %s", res.stderr)

            # 2. Allow Local LAN subnets
            lan_ips = ",".join(_LAN_RANGES_V4 + _LAN_RANGES_V6)
            self._run_netsh([
                "advfirewall", "firewall", "add", "rule",
                f"name={_WIN_RULE_PREFIX}AllowLAN",
                "dir=out", "action=allow",
                f"remoteip={lan_ips}"
            ])

            # 3. Allow Remote VPN Server endpoint
            if server_ip:
                server_args = [
                    "advfirewall", "firewall", "add", "rule",
                    f"name={_WIN_RULE_PREFIX}AllowServer",
                    "dir=out", "action=allow",
                    f"remoteip={server_ip}"
                ]
                if server_port:
                    server_args.extend(["protocol=any"])
                self._run_netsh(server_args)

            # 4. Allow Engine Executable
            if engine_path and os.path.exists(engine_path):
                self._run_netsh([
                    "advfirewall", "firewall", "add", "rule",
                    f"name={_WIN_RULE_PREFIX}AllowApp",
                    "dir=out", "action=allow",
                    f"program={engine_path}"
                ])

            # 5. Block all other outbound traffic
            block_res = self._run_netsh([
                "advfirewall", "firewall", "add", "rule",
                f"name={_WIN_RULE_PREFIX}BlockOut",
                "dir=out", "action=block"
            ])
            return block_res.returncode == 0
        except Exception as e:
            log.error("Failed to enable Windows Kill Switch: %s", e)
            self.clean_stale_rules()
            return False

    def _enable_linux(self, server_ip: Optional[str], server_port: Optional[int]) -> bool:
        """Set up nftables rules on Linux."""
        try:
            cmd = (
                "nft add table inet socksicle_ks; "
                "nft 'add chain inet socksicle_ks output { type filter hook output priority 0; policy drop; }'; "
                "nft add rule inet socksicle_ks output oif \"lo\" accept; "
                "nft add rule inet socksicle_ks output oif \"socksicle-tun\" accept; "
                "nft add rule inet socksicle_ks output ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 } accept; "
            )
            if server_ip:
                cmd += f"nft add rule inet socksicle_ks output ip daddr {server_ip} accept; "
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
            return res.returncode == 0
        except Exception as e:
            log.error("Failed to enable Linux Kill Switch: %s", e)
            return False
