"""Subscription state: load/save, add/update/delete, traffic summary, auto-update."""
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal, QTimer

from .server_model import Server
from .sub_manager import load_subscriptions, parse_subscription, save_subscriptions

# How often the auto-update timer checks subscriptions for pending refreshes.
AUTO_UPDATE_INTERVAL_MS = 5 * 60 * 1000


class SubscriptionManager(QObject):
    updated = Signal(bool, int)  # success, new node count

    def __init__(self, settings=None):
        super().__init__()
        self._lock = threading.Lock()
        self._settings = settings or {}
        self.subscriptions = load_subscriptions()
        for sub in self.subscriptions:
            sub['servers'] = [Server.from_dict(s) for s in sub.get('servers', [])]

        # Auto-update timer
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._check_auto_update)
        self._auto_timer.start(AUTO_UPDATE_INTERVAL_MS)

    def _get_sub_settings(self):
        """Extract subscription-related settings for parse_subscription."""
        return {
            "user_agent_key": self._settings.get("user_agent_key", "socksicle"),
            "fake_hwid": self._settings.get("fake_hwid", False),
            "hwid_value": self._settings.get("hwid_value", ""),
        }

    def _serialize_unlocked(self):
        return [
            {
                **sub,
                "servers": [s.to_dict() for s in sub.get("servers", [])],
            }
            for sub in self.subscriptions
        ]

    def _serialized(self):
        with self._lock:
            return self._serialize_unlocked()

    def get(self, name):
        with self._lock:
            return next((s for s in self.subscriptions if s['name'] == name), None)

    def get_servers(self, name):
        sub = self.get(name)
        return list(sub['servers']) if sub else []

    def add(self, name, url, lock_export: bool = False, expires_at: int | None = None):
        """Fetch and store a new subscription. Returns True on success."""
        links, meta = parse_subscription(url, self._get_sub_settings())
        if not links:
            return False
        servers = []
        seen_keys = set()
        for link in links:
            s = Server.from_link(link)
            if s:
                if lock_export:
                    s.lock_export = True
                if expires_at is not None:
                    s.expires_at = expires_at
                dedup_key = s.key.strip() if s.key else s.unique_key
                if dedup_key not in seen_keys:
                    servers.append(s)
                    seen_keys.add(dedup_key)
        with self._lock:
            sub_dict = {
                "name": name,
                "url": url,
                "servers": servers,
                "traffic": meta.get('traffic'),
                "profile_title": meta.get('profile_title', ''),
                "support_url": meta.get('support_url', ''),
                "profile_web_page_url": meta.get('profile_web_page_url', ''),
                "announce": meta.get('announce', ''),
                "description": meta.get('description', ''),
                "profile_update_interval": meta.get('profile_update_interval', 0),
                "last_updated": time.time(),
            }
            if lock_export:
                sub_dict["lock_export"] = True
            if expires_at is not None:
                sub_dict["expires_at"] = expires_at
            self.subscriptions.append(sub_dict)
            save_subscriptions(self._serialize_unlocked())
        return True

    def update(self, sub):
        """Refresh a subscription off the GUI thread; emits `updated` when done."""
        threading.Thread(target=self._update_worker, args=(sub,), daemon=True).start()

    def _update_worker(self, sub, emit_signal=True):
        """Refresh a subscription; emits `updated` only when emit_signal is True."""
        links, meta = parse_subscription(sub['url'], self._get_sub_settings())
        if not links:
            if emit_signal:
                self.updated.emit(False, 0)
            return

        old_keys = {s.key.strip() if s.key else s.unique_key for s in sub.get('servers', [])}
        new_servers = []
        seen_keys = set()
        new_count = 0

        sub_lock_export = bool(sub.get('lock_export', False))
        sub_expires_at = sub.get('expires_at')

        for link in links:
            s = Server.from_link(link)
            if s:
                if sub_lock_export:
                    s.lock_export = True
                if sub_expires_at is not None:
                    s.expires_at = sub_expires_at
                dedup_key = s.key.strip() if s.key else s.unique_key
                if dedup_key not in seen_keys:
                    new_servers.append(s)
                    seen_keys.add(dedup_key)
                    if dedup_key not in old_keys:
                        new_count += 1

        with self._lock:
            sub['servers'] = new_servers

            # Update metadata
            if meta.get('traffic'):
                sub['traffic'] = meta['traffic']
            for key in ('profile_title', 'support_url', 'profile_web_page_url',
                         'announce', 'description', 'profile_update_interval'):
                if key in meta:
                    sub[key] = meta[key]
            sub['last_updated'] = time.time()

            save_subscriptions(self._serialize_unlocked())
        if emit_signal:
            self.updated.emit(True, new_count)

    def delete(self, name):
        with self._lock:
            self.subscriptions = [s for s in self.subscriptions if s['name'] != name]
            save_subscriptions(self._serialize_unlocked())

    def traffic_info(self, name):
        """Return (used_gb, total_gb, percent, expire_str) or None when absent."""
        sub = self.get(name)
        if not sub or not sub.get('traffic'):
            return None
        t = sub['traffic']
        used = t['used'] / (1024 ** 3)
        total = t['total'] / (1024 ** 3)
        percent = (t['used'] / t['total']) * 100 if t['total'] > 0 else 0
        expire = (
            datetime.fromtimestamp(t['expire']).strftime('%Y-%m-%d')
            if t.get('expire') else None
        )
        return used, total, percent, expire

    def get_metadata(self, name):
        """Return subscription metadata dict."""
        sub = self.get(name)
        if not sub:
            return {}
        return {
            'profile_title': sub.get('profile_title', ''),
            'server_count': len(sub.get('servers', [])),
            'support_url': sub.get('support_url', ''),
            'announce': sub.get('announce', ''),
            'description': sub.get('description', ''),
            'profile_update_interval': sub.get('profile_update_interval', 0),
            'last_updated': sub.get('last_updated', 0),
        }

    # --- Auto-update ---

    def set_settings(self, settings):
        """Replace the settings dict used for subscription parsing."""
        self._settings = settings

    def set_auto_update(self, enabled, interval_ms=AUTO_UPDATE_INTERVAL_MS):
        """Enable/disable the periodic auto-update timer."""
        if enabled:
            self._auto_timer.start(interval_ms)
        else:
            self._auto_timer.stop()

    def _check_auto_update(self):
        """Periodically check if any subscription needs updating."""
        now = time.time()
        due = []
        with self._lock:
            for sub in self.subscriptions:
                interval_hours = sub.get('profile_update_interval', 0)
                if interval_hours <= 0:
                    continue
                last = sub.get('last_updated', 0)
                elapsed_hours = (now - last) / 3600
                if elapsed_hours >= interval_hours:
                    due.append(sub)
        for sub in due:
            threading.Thread(
                target=self._update_worker, args=(sub,), daemon=True,
                kwargs={"emit_signal": False}
            ).start()

    def update_all(self):
        """Update all subscriptions (for app startup)."""
        with self._lock:
            subs = list(self.subscriptions)
        for sub in subs:
            threading.Thread(
                target=self._update_worker, args=(sub,), daemon=True,
                kwargs={"emit_signal": False}
            ).start()
