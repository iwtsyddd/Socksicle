import logging
import os
import threading
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFrame, QMessageBox, QDialog, QFileDialog,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer, Slot
from urllib.parse import urlparse

from .header_bar import HeaderBar
from .bottom_nav import BottomNav
from .traffic_card import TrafficCard
from .status_card import StatusCard
from .tab_bar import TabBar
from .server_list_panel import ServerListPanel
from .tray_manager import TrayManager
from .add_server_dialog import AddServerDialog
from .connection_log_dialog import ConnectionLogDialog
from .settings_dialog import SettingsDialog
from .about_dialog import AboutDialog
from utils import twinsock
from utils.connection_manager import ConnectionManager
from utils.server_manager import ServerManager
from utils.subscription_manager import SubscriptionManager
from utils.ping import DEFAULT_PING_METHOD
from utils.theme import M3Theme
from utils.platform_utils import get_app_dir
from utils.platform_startup import set_autostart
from utils.engines.engine_manager import get_engine, ensure_engine, EngineType
from utils.startup_utils import (
    DECLINED_REASON, provision_backend, show_provisioning_failure
)

log = logging.getLogger("main_window")


class RoundedWindow(QWidget):

    def __init__(self):
        super().__init__()
        self.server_manager = ServerManager()
        self.manual_servers = self.server_manager.manual_servers
        self.settings = self.server_manager.settings
        self.theme = M3Theme(preset_key=self.settings.get("theme_preset", "dynamic"))
        self.current_tab = "Manual"

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(440, 720)

        icon_file = get_app_dir() / "icon.png"
        self.icon_path = str(icon_file) if icon_file.exists() else "icon.png"

        self.tray_manager = TrayManager(self.theme, self.icon_path)
        self.tray_manager.showHideRequested.connect(self._toggle_visibility)
        self.tray_manager.quitRequested.connect(self.quit_app)
        self.tray_manager.connectRequested.connect(self._on_connect_from_tray)

        self.subscription_manager = SubscriptionManager(self.settings)
        self.connection_manager = ConnectionManager(self.settings)
        self.connection_manager.apply_settings(self.settings)

        if self.settings.get("auto_update_subs", True):
            QTimer.singleShot(3000, self.subscription_manager.update_all)

        self.connection_manager.statusChanged.connect(self.on_status_changed)
        self.connection_manager.connectionStateChanged.connect(self.on_connection_state_changed)
        self.connection_manager.logUpdated.connect(self.add_log)
        self.connection_manager.geoInfoReady.connect(self.update_geo_ui)
        self.connection_manager.geoError.connect(self.on_geo_error)
        self.connection_manager.pingResultReady.connect(self.update_ping_ui)
        self.subscription_manager.updated.connect(self._on_sub_updated)

        self.log_dialog = ConnectionLogDialog(self, self.theme)
        self._ping_all_generation = 0

        self.accent_poll_timer = QTimer(self)
        self.accent_poll_timer.setInterval(2500)
        self.accent_poll_timer.timeout.connect(self._check_accent_hotplug)
        self.accent_poll_timer.start()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.container = QFrame()
        self.container.setStyleSheet(
            f"background-color: {self.theme.surface}; border-radius: 32px; border: none; outline: none;")
        self.main_layout.addWidget(self.container)
        self.inner_layout = QVBoxLayout(self.container)
        self.inner_layout.setContentsMargins(20, 16, 20, 20)

        self.header_bar = HeaderBar(self.theme)
        self.header_bar.minimizeRequested.connect(self.showMinimized)
        self.header_bar.closeRequested.connect(self.close)
        self.inner_layout.addWidget(self.header_bar)

        self.status_card = StatusCard(
            self.theme,
            is_connected_fn=lambda: self.connection_manager.is_connected,
        )
        self.status_card.vpnSwitchClicked.connect(self.on_vpn_switch_clicked)
        self.inner_layout.addWidget(self.status_card)

        self.tab_bar = TabBar(self.theme)
        self.tab_bar.tabChanged.connect(self.switch_tab)
        self.inner_layout.addWidget(self.tab_bar)

        self.traffic_card = TrafficCard(self.theme)
        self.inner_layout.addWidget(self.traffic_card)
        self.traffic_card.hide()

        self.server_panel = ServerListPanel(self.theme)
        self.server_panel.addRequested.connect(self.show_add_dialog)
        self.server_panel.exportRequested.connect(self.export_profiles)
        self.server_panel.importRequested.connect(self.import_profiles)
        self.server_panel.updateSubRequested.connect(self.update_current_subscription)
        self.server_panel.deleteSubRequested.connect(self.delete_current_subscription)
        self.server_panel.pingAllRequested.connect(self._ping_all_servers)
        self.server_panel.serverSelected.connect(self._on_server_selected)
        self.server_panel.serverDeleted.connect(self._on_server_deleted)
        self.inner_layout.addWidget(self.server_panel)

        self.bottom_nav = BottomNav(self.theme)
        self.bottom_nav.settingsRequested.connect(self.show_settings_dialog)
        self.bottom_nav.logsRequested.connect(self.show_log_dialog)
        self.bottom_nav.aboutRequested.connect(self.show_about_dialog)
        self.inner_layout.addWidget(self.bottom_nav)

        self._pending_tray_action = None
        self._dragging = False
        self._connect_generation = 0

        tabs = ["Manual"] + [s['name'] for s in self.subscription_manager.subscriptions]
        self.tab_bar.set_tabs(tabs, self.current_tab)
        self._refresh_server_list()

    def _check_accent_hotplug(self):
        if self.theme.check_system_accent_changed():
            self.apply_theme_styles()

    def _proxy_addr_text(self):
        if self.settings.get("tun_mode", False):
            return "TUN (Global VPN)"
        return f"SOCKS5 on 127.0.0.1:{self.connection_manager.local_port}"

    def closeEvent(self, event):
        if self.settings.get("minimize_to_tray", True) and self.tray_manager.tray_available:
            event.ignore()
            self.hide()
            self.tray_manager.notify("Socksicle", "Application is still running in the tray.")
        else:
            self.quit_app()

    def on_vpn_switch_clicked(self):
        self.toggle_connection()

    def _ensure_backend(self):
        engine = self.connection_manager.engine
        binary = engine.find_binary()
        if binary is not None and binary.exists():
            return True
        engine_name = engine.engine_type.value
        subdir = engine_name.replace("-", "")
        result = QMessageBox.question(
            self, "Socksicle",
            f"Proxy engine ({engine_name}) is not installed.\n\n"
            "Would you like to download it now?\n\n"
            f"(It will be saved into %APPDATA%/socksicle/bin/ or ./bin/{subdir}/)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes)
        if result != QMessageBox.Yes:
            return False
        res = provision_backend(parent_widget=self)
        if res is None or not res.ok:
            if res is not None:
                show_provisioning_failure(res, parent=self)
            return False
        return True

    @Slot(dict)
    def update_geo_ui(self, info):
        if self.connection_manager.is_connected:
            self.status_card.update_geo(info)
            self.tray_manager.notify(
                f"Connected: {info['flag']} {info['ip']}",
                f"Your IP is now {info['ip']}.")

    @Slot(str)
    def on_geo_error(self, reason):
        if self.connection_manager.is_connected:
            self.status_card.set_status(
                "Connected (geo unavailable)", self.theme.on_secondary_container)

    @Slot(object)
    def update_ping_ui(self, ms):
        if self.status_card.port_change_notice or not self.connection_manager.is_connected:
            return
        self.status_card.update_ping(ms, self._proxy_addr_text())

    def on_status_changed(self, msg, err):
        if not self.connection_manager.is_connected and not self.connection_manager.is_connecting:
            self._ping_all_generation += 1
        self.tray_manager.set_disconnect_enabled(
            self.connection_manager.is_connected or self.connection_manager.is_connecting
        )
        if err:
            self.status_card.set_status("Error", self.theme.error)
            self.tray_manager.notify("Connection Error", msg)
            if not self.status_card.port_change_notice:
                self.status_card.set_ping_text("Ping: --")
            self.status_card.set_switch_state(False)
        elif self.connection_manager.is_connected:
            self.status_card.set_switch_state(True)
            if not self.status_card.port_change_notice:
                self.status_card.set_ping_text(self._proxy_addr_text())
            if self.connection_manager.current_geo:
                self.status_card.set_status(
                    f"{self.connection_manager.current_geo['flag']} "
                    f"{self.connection_manager.current_geo['ip']}",
                    self.theme.on_secondary_container)
            else:
                self.status_card.set_status("Connected", self.theme.on_secondary_container)
        elif self.connection_manager.is_connecting or self.connection_manager.is_reconnecting or "Reconnecting" in msg:
            self.status_card.set_switch_state(True)
            if not self.status_card.port_change_notice:
                self.status_card.set_ping_text("Ping: --")
            if "Reconnecting" in msg:
                self.status_card.set_status(msg, self.theme.on_secondary_container)
            elif self.settings.get("tun_mode", False):
                self.status_card.set_status("🔧 Creating tunnel...", self.theme.on_secondary_container)
            else:
                self.status_card.set_status("⚡ Connecting...", self.theme.on_secondary_container)
        else:
            self.status_card.reset_to_disconnected()

    def on_connection_state_changed(self, conn):
        if conn:
            self.status_card.set_switch_state(True)
        elif not self.connection_manager.is_connecting and not self.connection_manager.is_reconnecting:
            self.status_card.set_switch_state(False)
            self.status_card.reset_to_disconnected()
        for item in self.server_panel._server_items:
            item.radio.update()

    def _on_server_selected(self, idx):
        if self.connection_manager.is_connected or self.connection_manager.is_connecting:
            servers = self._current_servers()
            if 0 <= idx < len(servers):
                selected = servers[idx]
                curr = self.connection_manager.current_server
                if curr and getattr(curr, "key", None) == getattr(selected, "key", None):
                    return
            self.toggle_connection(True)

    def toggle_connection(self, connect=None):
        if connect is None:
            connect = not (self.connection_manager.is_connected or self.connection_manager.is_connecting)
        if connect:
            if not self._ensure_backend():
                return
            if self.settings.get("tun_mode", False):
                from utils.platform_utils import (
                    is_admin, elevate_restart, is_windows, is_linux,
                    check_tun_capabilities, grant_tun_capabilities
                )
                if is_windows():
                    if not is_admin():
                        reply = QMessageBox.question(
                            self, "Administrator Privileges Required",
                            "TUN Mode (Global VPN) requires Administrator privileges to configure virtual network adapters and routing tables.\n\n"
                            "Would you like to restart Socksicle as Administrator now?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.Yes)
                        if reply == QMessageBox.Yes:
                            elevate_restart()
                        return
                elif is_linux():
                    engine = self.connection_manager.engine
                    binary = engine.find_binary()
                    if binary and not check_tun_capabilities(binary):
                        granted = grant_tun_capabilities(binary, parent_window=self)
                        if not granted or not check_tun_capabilities(binary):
                            QMessageBox.warning(
                                self, "TUN Privileges Required",
                                "TUN Mode (Global VPN) requires network administration "
                                "capabilities (cap_net_admin) on the sing-box binary.\n\n"
                                "Authorization was canceled or failed.\n\n"
                                "You can grant the required capabilities manually by running:\n"
                                f"sudo setcap cap_net_admin,cap_net_bind_service+ep {binary}\n\n"
                                "or disable TUN Mode to use standard SOCKS5 proxy mode."
                            )
                            return
            idx = self.server_panel.get_selected_index()
            if idx >= 0:
                servers = self._current_servers()
                if idx < len(servers):
                    server = servers[idx]
                    if getattr(server, "is_expired", False):
                        QMessageBox.warning(
                            self, "Server Expired",
                            f"The server '{server.name}' has expired and cannot be connected to.")
                        self.status_card.set_switch_state(False)
                        return
                    log.info("Connecting to server index %d in tab %s...",
                             idx, self.current_tab)
                    self._connect_generation += 1
                    task_gen = self._connect_generation
                    self.status_card.set_switch_state(True)
                    if not self.status_card.port_change_notice:
                        self.status_card.set_ping_text("Ping: --")
                    is_tun = self.settings.get("tun_mode", False)
                    if is_tun:
                        self.status_card.set_status("🔧 Creating tunnel...", self.theme.on_secondary_container)
                        self.tray_manager.notify("Connecting", f"Creating tunnel for {server.name}...")
                    else:
                        self.status_card.set_status("⚡ Connecting...", self.theme.on_secondary_container)
                        self.tray_manager.notify("Connecting", f"Attempting to connect to {server.name}...")

                    def _run_connect(gen=task_gen):
                        ok = self.connection_manager.toggle(server, True)
                        if not ok and gen == self._connect_generation:
                            from PySide6.QtCore import QMetaObject, Qt as Q_Qt, Q_ARG
                            QMetaObject.invokeMethod(
                                self.status_card.vpn_switch, "toggle",
                                Q_Qt.QueuedConnection, Q_ARG(bool, False))

                    threading.Thread(target=_run_connect, daemon=True).start()
            else:
                QMessageBox.warning(self, "Error", "Please select a server first!")
        else:
            log.info("Disconnecting...")
            self._connect_generation += 1
            self.status_card.reset_to_disconnected()
            self.tray_manager.notify("Disconnected", "Your secure connection has been closed.")
            threading.Thread(target=lambda: self.connection_manager.toggle(None, False), daemon=True).start()

    def _current_servers(self):
        if self.current_tab == "Manual":
            return self.manual_servers
        return self.subscription_manager.get_servers(self.current_tab)

    def switch_tab(self, name, force=False):
        if self.current_tab == name and not force:
            self._execute_pending_tray_action()
            return

        def on_fade_out():
            self.current_tab = name
            tabs = ["Manual"] + [s['name'] for s in self.subscription_manager.subscriptions]
            self.tab_bar.set_tabs(tabs, name)
            self._refresh_server_list()
            self.server_panel.set_delete_sub_visible(name != "Manual")
            self.server_panel.set_update_visible(name != "Manual")
            info = self.subscription_manager.traffic_info(name)
            meta = self.subscription_manager.get_metadata(name)
            self.traffic_card.update_from_subscription(info, meta)
            self._execute_pending_tray_action()
            self.server_panel.fade_in()

        self.server_panel.fade_out(on_fade_out)

    def _execute_pending_tray_action(self):
        if self._pending_tray_action is None:
            return
        tab_name, server_index = self._pending_tray_action
        self._pending_tray_action = None
        if server_index < len(self.server_panel._server_items):
            self.server_panel._server_items[server_index].radio.setChecked(True)
        QTimer.singleShot(100, lambda: self.toggle_connection(True))

    def reconnect_after_resume(self):
        log.info("System resumed or network restored, reconnecting proxy...")
        if not self.connection_manager.is_connected:
            return
        self.connection_manager.disconnect()
        self.status_card.set_switch_state(False)
        QTimer.singleShot(1500, lambda: self.toggle_connection(True))

    def _refresh_server_list(self):
        servers = self._current_servers()
        connected_key = None
        curr = self.connection_manager.current_server
        if self.connection_manager.is_connected and curr:
            connected_key = curr.key
        self.server_panel.refresh(servers, connected_key)
        self.tray_manager.rebuild_menu(self.manual_servers, self.subscription_manager.subscriptions)

    def _ping_all_servers(self):
        method = self.settings.get("ping_method", DEFAULT_PING_METHOD)
        self.server_panel.ping_all(method, self.connection_manager.local_port)

    def _on_connect_from_tray(self, tab_name, server_index):
        self._pending_tray_action = (tab_name, server_index)
        self.switch_tab(tab_name)

    def show_log_dialog(self):
        if hasattr(self, 'log_dialog') and self.log_dialog:
            self.log_dialog.set_theme(self.theme)
            self.log_dialog.show()
            self.log_dialog.raise_()
            self.log_dialog.activateWindow()

    def add_log(self, msg):
        if self.log_dialog:
            timestamp = time.strftime("%H:%M:%S")
            self.log_dialog.add_log(f"[{timestamp}] {msg}")

    def show_about_dialog(self):
        dialog = AboutDialog(self, self.theme)
        dialog.exec()

    def update_current_subscription(self):
        if self.current_tab == "Manual":
            return
        sub = self.subscription_manager.get(self.current_tab)
        if sub:
            self.server_panel.set_update_button_state("⏳", False)
            self.subscription_manager.update(sub)

    @Slot(bool, int)
    def _on_sub_updated(self, success, new_count):
        self.server_panel.set_update_button_state("🔄 Update", True)
        if success:
            self.switch_tab(self.current_tab, force=True)
            if new_count > 0:
                self.tray_manager.notify(
                    "Subscription Updated", f"Added {new_count} new nodes.")
            else:
                self.tray_manager.notify(
                    "Subscription Updated", "Already up to date.")
        else:
            sub = self.subscription_manager.get(self.current_tab)
            url = sub['url'] if sub else "unknown"
            QMessageBox.warning(self, "Update Failed",
                f"Failed to update subscription.\n\nURL: {url}\n\n"
                "Check your network connection and verify the URL is correct.")

    def delete_current_subscription(self):
        if self.current_tab == "Manual":
            return
        if QMessageBox.question(self, "Delete Sub", f"Remove subscription '{self.current_tab}'?") == QMessageBox.Yes:
            self.subscription_manager.delete(self.current_tab)
            self.current_tab = "Manual"
            tabs = ["Manual"] + [s['name'] for s in self.subscription_manager.subscriptions]
            self.tab_bar.set_tabs(tabs, self.current_tab)
            self._refresh_server_list()
            self.server_panel.set_update_visible(False)
            self.server_panel.set_delete_sub_visible(False)

    def _on_server_deleted(self, idx):
        if self.current_tab == "Manual":
            self.server_manager.delete_manual(idx)
            self._refresh_server_list()
        else:
            QMessageBox.information(
                self, "Info", "Delete the entire subscription instead.")

    def show_settings_dialog(self):
        current_engine = self.settings.get("engine", "sslocal")
        d = SettingsDialog(self, self.theme, self.connection_manager.local_port,
                           self.settings.get("auto_connect", False),
                           current_engine=current_engine)
        geo = self.geometry()
        d.move(geo.center().x() - d.width() // 2,
               max(40, geo.center().y() - d.height() // 2))
        if d.exec() == QDialog.Accepted:
            s = d.get_settings()
            old_engine = self.settings.get("engine", "sslocal")
            new_engine = s.get("engine", "sslocal")
            old_port = int(self.connection_manager.local_port)
            new_port = int(s.get("local_port", old_port))
            old_tun_mode = bool(self.settings.get("tun_mode", False))
            new_tun_mode = bool(s.get("tun_mode", False))
            old_theme_preset = self.settings.get("theme_preset", "dynamic")
            new_theme_preset = s.get("theme_preset", "dynamic")

            has_changes = any(self.settings.get(k) != v for k, v in s.items()) or (new_port != old_port)
            if not has_changes:
                return

            self.settings.update(s)
            if "tws3_share_key" in s:
                self.settings.pop("tws2_share_key", None)
            elif "tws2_share_key" in s:
                self.settings.pop("tws3_share_key", None)
            self.server_manager.save_settings()

            if "autostart" in s:
                set_autostart(s["autostart"])

            if new_theme_preset != old_theme_preset:
                self.theme.apply_theme(new_theme_preset)
                self.apply_theme_styles()

            engine_changed = (new_engine != old_engine)
            tun_changed = (new_tun_mode != old_tun_mode)

            if engine_changed or tun_changed:
                if new_tun_mode:
                    engine = get_engine(EngineType.SINGBOX)
                else:
                    engine = get_engine(EngineType(new_engine))
                self.connection_manager.switch_engine(engine)

            self.connection_manager.apply_settings(s)

            if (new_port != old_port and
                    (self.connection_manager.is_connected or
                     self.connection_manager.is_connecting)):
                self.status_card.notify_port_change()

            self.subscription_manager.set_settings(self.settings)
            self.subscription_manager.set_auto_update(
                s.get("auto_update_subs", True))
        else:
            orig_theme = self.settings.get("theme_preset", "dynamic")
            self.theme.apply_theme(orig_theme)
            self.apply_theme_styles()

    def export_profiles(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Profiles", "", "JSON Files (*.json)")
        if path:
            try:
                self.server_manager.export_profiles(path, self.subscription_manager.subscriptions)
                self.tray_manager.notify("Export Successful", f"Profiles saved to {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export: {e}")

    def import_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profiles", "", "JSON Files (*.json)")
        if path:
            try:
                added_m, added_s = self.server_manager.import_profiles(path, self.subscription_manager.subscriptions)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import: {e}")
                return
            if added_m or added_s:
                tabs = ["Manual"] + [s['name'] for s in self.subscription_manager.subscriptions]
                self.tab_bar.set_tabs(tabs, self.current_tab)
                self._refresh_server_list()
                self.tray_manager.notify("Import Successful", f"Added {added_m} servers and {added_s} subscriptions.")
            else:
                QMessageBox.information(self, "Import", "No new profiles found in file.")

    def show_add_dialog(self):
        has_legacy = self.server_manager.has_legacy_tws2_key()
        d = AddServerDialog(self, self.theme, has_legacy_tws2=has_legacy)
        if d.exec() != QDialog.Accepted:
            return
        raw = d.get_server_key()
        if not raw:
            QMessageBox.warning(
                self, "Empty Link",
                "Please enter a server link, subscription URL, or tws3:// share.")
            return
        link = raw
        metadata = {}
        if link.startswith(("tws3://", "tws3.")) or (
            not link.startswith(("http://", "https://", "ss://", "vless://", "vmess://", "hysteria2://", "hy2://", "tws2://", "tws2."))
            and twinsock._peek_version(link) == twinsock.TOKEN_VERSION_CURRENT
        ):
            share_key = self.server_manager.get_share_key()
            try:
                link, metadata = twinsock.decrypt_share_payload(share_key, raw)
            except (twinsock.VaultError, ValueError) as e:
                QMessageBox.warning(
                    self, "TwinSock",
                    f"Failed to decrypt TwinSock share: {e}")
                return
        elif link.startswith(("tws2://", "tws2.")):
            if not has_legacy:
                QMessageBox.warning(
                    self, "TwinSock",
                    "tws2:// links are legacy and not supported because you are using a TwinSock v3 key without a legacy v2 key.\n\n"
                    "Please request a tws3:// link from the sender or use a standard proxy link."
                )
                return
            share_key = self.settings.get("tws2_share_key", "")
            if not share_key:
                QMessageBox.warning(
                    self, "TwinSock",
                    "No legacy TwinSock share key set in Settings.")
                return
            try:
                link, metadata = twinsock.decrypt_share_payload(share_key, raw)
            except (twinsock.VaultError, ValueError) as e:
                QMessageBox.warning(
                    self, "TwinSock",
                    f"Failed to decrypt TwinSock share: {e}")
                return

        lock_export = metadata.get("lock_export", False)
        expires_at = metadata.get("expires_at")
        is_expired = False
        if expires_at is not None and expires_at > 0 and time.time() >= expires_at:
            is_expired = True

        # Support multiple links/servers in a single import or tws3 payload
        links_to_import = []
        if isinstance(link, list):
            links_to_import = [str(x).strip() for x in link if str(x).strip()]
        elif isinstance(link, str):
            lines = [l.strip() for l in link.splitlines() if l.strip()]
            links_to_import = lines if len(lines) > 1 else [link.strip()]
        else:
            links_to_import = [str(link).strip()]

        imported_servers_count = 0
        imported_subs_count = 0
        last_sub_name = None

        for single_link in links_to_import:
            if single_link.startswith("http://") or single_link.startswith("https://"):
                name = urlparse(single_link).hostname or urlparse(single_link).netloc or "Subscription"
                if self.subscription_manager.add(name, single_link, lock_export=lock_export, expires_at=expires_at):
                    imported_subs_count += 1
                    last_sub_name = name
            else:
                srv = self.server_manager.add_from_link(
                    single_link,
                    lock_export=lock_export,
                    expires_at=expires_at
                )
                if srv:
                    imported_servers_count += 1

        if imported_subs_count > 0:
            tabs = ["Manual"] + [s['name'] for s in self.subscription_manager.subscriptions]
            self.tab_bar.set_tabs(tabs, self.current_tab)
            if last_sub_name:
                self.switch_tab(last_sub_name)

        if imported_servers_count > 0:
            self._refresh_server_list()

        if imported_servers_count == 0 and imported_subs_count == 0:
            QMessageBox.warning(
                self, "Invalid Link",
                "The provided link(s) could not be imported.\n\n"
                "Supported formats: ss://, vless://, vmess://, hysteria2://, "
                "subscription URL, or tws3://"
            )
            return

        if is_expired:
            QMessageBox.information(
                self, "Expired Link",
                "One or more imported links have expired.")

    def apply_theme_styles(self):
        self.container.setStyleSheet(
            f"background-color: {self.theme.surface}; border-radius: 32px; border: none; outline: none;")
        self.header_bar.apply_theme(self.theme)
        self.status_card.apply_theme(self.theme)
        self.traffic_card.apply_theme(self.theme)
        self.tab_bar.apply_theme(self.theme)
        self.server_panel.apply_theme(self.theme)
        self.bottom_nav.apply_theme(self.theme)
        if self.log_dialog:
            self.log_dialog.set_theme(self.theme)
        tabs = ["Manual"] + [s['name'] for s in self.subscription_manager.subscriptions]
        self.tab_bar.set_tabs(tabs, self.current_tab)
        self._refresh_server_list()

    def quit_app(self):
        self.connection_manager.disconnect()
        try:
            from utils.killswitch import KillSwitchManager
            KillSwitchManager.get_instance().cleanup()
        except Exception:
            pass
        self.tray_manager.hide()
        QApplication.quit()

    def closeEvent(self, event):
        if self.settings.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
        else:
            self.quit_app()

    def _toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 60:
            self._dragging = True
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._dragging = False
