"""Manual server list and app settings persistence, plus profile import/export."""
import base64
import json
import logging
import os
import secrets
import time

from .platform_utils import get_config_dir
from .server_model import Server
from .sub_manager import save_subscriptions
from .engines.base import DEFAULT_LOCAL_PORT
from .ping import DEFAULT_PING_METHOD
from . import twinsock

log = logging.getLogger(__name__)


class ServerManager:
    def __init__(self):
        twinsock.ensure_drawer()
        self.config_dir = str(get_config_dir())
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = os.path.join(self.config_dir, "servers.json")
        self.settings_file = os.path.join(self.config_dir, "settings.json")
        self.manual_servers = self.load_manual_servers()
        if twinsock.migration_occurred():
            self.save_manual_servers()
        self.settings = self.load_settings()
        self._ensure_tws3_share_key()

    def load_manual_servers(self):
        if os.path.exists(self.config_file):
            twinsock.file_intact("servers.json")
            try:
                with open(self.config_file, 'r', encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    servers = []
                    for s in data:
                        if isinstance(s, dict):
                            try:
                                servers.append(
                                    twinsock.unseal_dict("manual", s, twinsock.SECRET_FIELDS))
                            except twinsock.VaultError as e:
                                log.warning("vault: manual servers unusable on this machine: %s", e)
                                return []
                    return [Server.from_dict(s) for s in servers]
            except (json.JSONDecodeError, OSError, ValueError) as e:
                log.error("Failed to load manual servers: %s", e)
        return []

    def save_manual_servers(self):
        payload = []
        try:
            for s in self.manual_servers:
                payload.append(twinsock.seal_dict("manual", s.to_dict(), twinsock.SECRET_FIELDS))
        except twinsock.VaultError as e:
            if str(e) != "foreign":
                raise
            log.warning("vault: foreign config, retiring servers.json and starting fresh")
            self._retire_foreign(self.config_file)
            twinsock.drop_foreign()
            payload = [
                twinsock.seal_dict("manual", s.to_dict(), twinsock.SECRET_FIELDS)
                for s in self.manual_servers
            ]
        try:
            with open(self.config_file, 'w', encoding="utf-8") as f:
                json.dump(payload, f)
        except (OSError, IOError) as e:
            log.error("Failed to save manual servers: %s", e)
            return
        twinsock.file_saved("servers.json")

    def _retire_foreign(self, path):
        if not os.path.exists(path):
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            os.replace(path, f"{path}.foreign-{stamp}.json")
        except OSError as e:
            log.error("Failed to retire foreign config %s: %s", path, e)

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding="utf-8", errors="replace") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError, ValueError) as e:
                log.error("Failed to load settings: %s", e)
        return {"local_port": DEFAULT_LOCAL_PORT, "auto_connect": False,
                "minimize_to_tray": True, "sslocal_declined": False,
                "auto_update_subs": True, "user_agent_key": "socksicle",
                "fake_hwid": False, "hwid_value": "",
                "engine": "sslocal", "ping_method": DEFAULT_PING_METHOD,
                "tun_mode": False, "theme_preset": "dynamic"}

    def has_legacy_tws2_key(self) -> bool:
        """True if the user has an unupgraded legacy tws2_share_key and has not generated a native tws3_share_key."""
        return bool(self.settings.get("tws2_share_key")) and not bool(self.settings.get("tws3_share_key"))

    def get_share_key(self) -> str:
        return self.settings.get("tws3_share_key") or self.settings.get("tws2_share_key", "")

    def upgrade_to_tws3_share_key(self) -> str:
        new_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        self.settings["tws3_share_key"] = new_key
        self.settings.pop("tws2_share_key", None)
        self.save_settings()
        log.info("vault: upgraded user share key to native TwinSock v3")
        return new_key

    def _ensure_tws3_share_key(self):
        if self.settings.get("tws3_share_key") or self.settings.get("tws2_share_key"):
            return
        self.settings["tws3_share_key"] = base64.urlsafe_b64encode(
            secrets.token_bytes(32)).rstrip(b"=").decode()
        self.save_settings()
        log.info("generated TwinSock v3 share key")

    def save_settings(self):
        if not self.settings.get("tws3_share_key") and not self.settings.get("tws2_share_key"):
            key = self._stored_tws_share_key()
            if key:
                self.settings["tws3_share_key"] = key
            else:
                self.settings["tws3_share_key"] = base64.urlsafe_b64encode(
                    secrets.token_bytes(32)).rstrip(b"=").decode()
                log.info("generated TwinSock v3 share key")
        with open(self.settings_file, 'w', encoding="utf-8") as f:
            json.dump(self.settings, f)

    def _stored_tws_share_key(self):
        if not os.path.exists(self.settings_file):
            return None
        try:
            with open(self.settings_file, 'r', encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if isinstance(data, dict):
                key = data.get("tws3_share_key") or data.get("tws2_share_key")
                if isinstance(key, str) and key:
                    return key
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log.error("Failed to read stored settings: %s", e)
        return None

    def add_from_link(self, raw_link, default_name="New Server", lock_export: bool = False, expires_at: int | None = None):
        """Parse an ss://, vless://, vmess://, hysteria2://, or hy2:// link and append it to the manual server list."""
        server = Server.from_link(raw_link, default_name=default_name)
        if not server:
            return None
        if lock_export:
            server.lock_export = True
        if expires_at is not None:
            server.expires_at = expires_at
        self.manual_servers.append(server)
        self.save_manual_servers()
        return server

    def delete_manual(self, index):
        if index < 0 or index >= len(self.manual_servers):
            return
        del self.manual_servers[index]
        self.save_manual_servers()

    def export_profiles(self, path, subscriptions):
        data = twinsock.export_payload(self.manual_servers, subscriptions)
        with open(path, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def import_profiles(self, path, subscriptions):
        """Merge profiles from a JSON file. Returns (added_servers, added_subs)."""
        with open(path, 'r', encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0, 0
        manuals, subs = twinsock.import_payload(data)
        added_m = 0
        for srv in manuals:
            if srv not in self.manual_servers:
                self.manual_servers.append(srv)
                added_m += 1
        if added_m:
            self.save_manual_servers()
        added_s = 0
        for raw_sub in subs:
            if not any(x['url'] == raw_sub['url'] for x in subscriptions):
                subscriptions.append(raw_sub)
                added_s += 1
        if added_s:
            save_subscriptions(subscriptions)
        return added_m, added_s

    def is_sslocal_declined(self):
        return bool(self.settings.get("sslocal_declined", False))

    def set_sslocal_declined(self, declined=True):
        self.settings["sslocal_declined"] = bool(declined)
        self.save_settings()