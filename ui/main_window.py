import logging
import os
import time

from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QButtonGroup, QFrame, QMessageBox, QDialog, QScrollArea,
    QProgressBar, QLineEdit, QGraphicsOpacityEffect, QSystemTrayIcon,
    QMenu, QApplication, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer, Slot, Signal, QPropertyAnimation, QThreadPool
from PySide6.QtGui import QColor, QIcon
from urllib.parse import urlparse

from .toggle_switch import AnimatedToggleSwitch
from .server_item import ServerItem
from .add_server_dialog import AddServerDialog
from .connection_log_dialog import ConnectionLogDialog
from .settings_dialog import SettingsDialog
from .about_dialog import AboutDialog
from utils import twinsock
from utils.connection_manager import ConnectionManager
from utils.server_manager import ServerManager
from utils.subscription_manager import SubscriptionManager, AUTO_UPDATE_INTERVAL_MS
from utils.ping import (
    PingJob, ProxyPingJob, PING_PROBE_HOST, PING_ERROR_SENTINEL,
    DEFAULT_PING_METHOD,
)
from utils.theme import M3Theme
from utils.platform_utils import get_app_dir
from utils.engines.engine_manager import get_engine, ensure_engine, EngineType
from utils.startup_utils import DECLINED_REASON

log = logging.getLogger("main_window")


class RoundedWindow(QWidget):
    serverPingReady = Signal(int, float)

    def __init__(self):
        super().__init__()
        self.theme = M3Theme()
        self.current_tab = "Manual"
        
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(440, 720)

        icon_file = get_app_dir() / "icon.png"
        self.icon_path = str(icon_file) if icon_file.exists() else "icon.png"

        self.setup_tray_icon()

        self.server_manager = ServerManager()
        self.manual_servers = self.server_manager.manual_servers
        self.settings = self.server_manager.settings
        self.subscription_manager = SubscriptionManager(self.settings)
        self.connection_manager = ConnectionManager(self.settings)
        self.connection_manager.apply_settings(self.settings)

        # Auto-update subscriptions on startup
        if self.settings.get("auto_update_subs", True):
            self.subscription_manager.update_all()

        self.connection_manager.statusChanged.connect(self.on_status_changed)
        self.connection_manager.connectionStateChanged.connect(self.on_connection_state_changed)
        self.connection_manager.logUpdated.connect(self.add_log)
        self.connection_manager.geoInfoReady.connect(self.update_geo_ui)
        self.connection_manager.geoError.connect(self.on_geo_error)
        self.connection_manager.pingResultReady.connect(self.update_ping_ui)
        self.subscription_manager.updated.connect(self._on_sub_updated)
        self.serverPingReady.connect(self.update_server_ping_ui)
        
        # Initialize log dialog
        self.log_dialog = ConnectionLogDialog(self, self.theme)
        self._port_change_notice = False
        self._ping_all_generation = 0
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self._clear_port_change_notice)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.container = QFrame()
        self.container.setStyleSheet(
            f"background-color: {self.theme.surface}; border-radius: 32px; border: none;")
        self.main_layout.addWidget(self.container)
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(20, 16, 20, 20)
        
        self.setup_header()
        self.setup_status_card()
        
        self.tabs_container = QWidget()
        self.tabs_container.setFixedHeight(48)
        self.tabs_layout = QHBoxLayout(self.tabs_container)
        self.tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_layout.setSpacing(8)
        self.layout.addWidget(self.tabs_container)
        
        self.traffic_card = QFrame()
        self.traffic_card.setStyleSheet(
            f"background: {self.theme.surface_variant}; border-radius: 20px; border: none;")
        self.traffic_card.setMinimumHeight(100)
        traffic_card_layout = QVBoxLayout(self.traffic_card)
        traffic_card_layout.setContentsMargins(16, 12, 16, 12)
        traffic_card_layout.setSpacing(2)
        self.traffic_label = QLabel("Traffic: --")
        self.traffic_label.setStyleSheet(
            f"color: {self.theme.on_surface}; font-size: 12px; font-weight: 600;")
        self.traffic_bar = QProgressBar()
        self.traffic_bar.setFixedHeight(8)
        self.traffic_bar.setTextVisible(False)
        self.traffic_bar.setStyleSheet(
            f"QProgressBar {{ background-color: rgba(0,0,0,0.2); border: none;"
            f" border-radius: 4px; }}"
            f" QProgressBar::chunk {{ background-color: {self.theme.primary};"
            f" border-radius: 4px; }}")
        self.expire_label = QLabel("Expires: --")
        self.expire_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 11px;")
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 10px;")
        self.meta_label.setWordWrap(True)
        self.meta_label.setAlignment(Qt.AlignCenter)
        traffic_card_layout.addWidget(self.traffic_label)
        traffic_card_layout.addWidget(self.traffic_bar)
        traffic_card_layout.addWidget(self.expire_label)
        traffic_card_layout.addWidget(self.meta_label)
        self.layout.addWidget(self.traffic_card)
        self.traffic_card.hide()

        self.action_bar = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.add_btn.setStyleSheet(self.theme.get_button_style("tonal"))
        self.add_btn.clicked.connect(self.show_add_dialog)
        self.export_btn = QPushButton("📤")
        self.export_btn.setToolTip("Export Profiles")
        self.export_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.export_btn.setFixedSize(40, 40)
        self.export_btn.clicked.connect(self.export_profiles)
        self.import_btn = QPushButton("📥")
        self.import_btn.setToolTip("Import Profiles")
        self.import_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.import_btn.setFixedSize(40, 40)
        self.import_btn.clicked.connect(self.import_profiles)
        self.update_sub_btn = QPushButton("🔄 Update")
        self.update_sub_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.update_sub_btn.clicked.connect(self.update_current_subscription)
        self.update_sub_btn.hide()
        self.ping_all_btn = QPushButton("⚡ Ping All")
        self.ping_all_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.ping_all_btn.clicked.connect(self.ping_all_servers)
        self.del_sub_btn = QPushButton("🗑 Sub")
        self.del_sub_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.del_sub_btn.clicked.connect(self.delete_current_subscription)
        self.del_sub_btn.hide()
        self.action_bar.addWidget(self.add_btn)
        self.action_bar.addWidget(self.export_btn)
        self.action_bar.addWidget(self.import_btn)
        self.action_bar.addStretch()
        self.action_bar.addWidget(self.update_sub_btn)
        self.action_bar.addWidget(self.ping_all_btn)
        self.action_bar.addWidget(self.del_sub_btn)
        self.layout.addLayout(self.action_bar)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search servers...")
        self.search_bar.setStyleSheet(
            f"background: {self.theme.surface_variant}; color: {self.theme.on_surface};"
            f" padding: 8px 12px; border-radius: 12px; border: none; margin-top: 4px;")
        self.search_bar.textChanged.connect(self.filter_servers)
        self.layout.addWidget(self.search_bar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f" QScrollBar:vertical {{ border: none; background: transparent; width: 6px; }}"
            f" QScrollBar::handle:vertical {{ background: {self.theme.surface_variant};"
            f" border-radius: 3px; min-height: 30px; }}")
        self.scroll_content = QWidget()
        self.server_layout = QVBoxLayout(self.scroll_content)
        self.server_layout.setContentsMargins(0, 0, 0, 0)
        self.server_layout.setSpacing(10)
        self.scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll_area)
        self.opacity_effect = QGraphicsOpacityEffect(self.scroll_area)
        self.scroll_area.setGraphicsEffect(self.opacity_effect)
        self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_anim.setDuration(200)

        self.setup_bottom_nav()
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.button_group.buttonToggled.connect(self.on_checkbox_toggled)

        self._server_items: list[ServerItem] = []
        self.update_tabs()
        self.refresh_server_list()
        self._dragging = False

    def setup_header(self):
        header = QHBoxLayout()
        title = QLabel("Socksicle")
        title.setStyleSheet(
            f"color: {self.theme.on_surface}; font-size: 22px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        for txt, cmd in [("—", self.showMinimized), ("✕", self.close)]:
            btn = QPushButton(txt)
            btn.setFixedSize(36, 36)
            btn.setStyleSheet(
                f"QPushButton {{ color: white; background: transparent;"
                f" border-radius: 18px; border: none; }}"
                f" QPushButton:hover {{ background: {self.theme.surface_variant}; }}")
            btn.clicked.connect(cmd)
            header.addWidget(btn)
        self.layout.addLayout(header)

    def closeEvent(self, event):
        if self.settings.get("minimize_to_tray", True) and self.tray_available:
            event.ignore()
            self.hide()
            self.show_notification("Socksicle", "Application is still running in the tray.")
        else:
            self.quit_app()

    def setup_status_card(self):
        self.status_card = QFrame()
        card_color = QColor(self.theme.secondary_container)
        rgba = f"rgba({card_color.red()}, {card_color.green()}, {card_color.blue()}, 0.4)"
        self.status_card.setStyleSheet(
            f"QFrame {{ background-color: {rgba}; border-radius: 28px; border: none; }}"
            f" QLabel {{ color: {self.theme.on_secondary_container};"
            f" border: none; background: transparent; }}")
        self.status_card.setFixedHeight(120)
        card_layout = QVBoxLayout(self.status_card)
        card_layout.setContentsMargins(24, 16, 24, 16)
        top = QHBoxLayout()
        top.addWidget(QLabel("Connection Status"))
        top.addStretch()
        self.vpn_switch = AnimatedToggleSwitch()
        self.vpn_switch.mousePressEvent = self.on_vpn_switch_clicked
        top.addWidget(self.vpn_switch)
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; background: transparent;")
        self.ping_label = QLabel("Ping: --")
        self.ping_label.setStyleSheet(
            "font-size: 12px; opacity: 0.7; background: transparent;")
        card_layout.addLayout(top)
        card_layout.addWidget(self.status_label)
        card_layout.addWidget(self.ping_label)
        self.layout.addWidget(self.status_card)

    def _set_status(self, text, color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 24px; font-weight: bold; background: transparent;")

    def _proxy_addr_text(self):
        return f"SOCKS5 on 127.0.0.1:{self.connection_manager.local_port}"

    def _notify_port_change(self):
        self._port_change_notice = True
        self.ping_label.setText("Local port will take effect on next connect")
        self.notice_timer.start(8000)

    def _clear_port_change_notice(self):
        if not self._port_change_notice:
            return
        self._port_change_notice = False
        if not self.connection_manager.is_connected:
            self.ping_label.setText("Ping: --")

    def on_status_changed(self, msg, err):
        if not self.connection_manager.is_connected:
            self._ping_all_generation += 1
        self.disconnect_action.setEnabled(self.connection_manager.is_connected)
        if err:
            self._set_status("Error", self.theme.error)
            self.show_notification("Connection Error", msg)
            if not self._port_change_notice:
                self.ping_label.setText("Ping: --")
        elif self.connection_manager.is_connected:
            if not self._port_change_notice:
                self.ping_label.setText(self._proxy_addr_text())
            if self.connection_manager.current_geo:
                self._set_status(
                    f"{self.connection_manager.current_geo['flag']} "
                    f"{self.connection_manager.current_geo['ip']}",
                    self.theme.on_secondary_container)
            elif self.connection_manager.is_connecting:
                self._set_status("⚡ Connecting...", self.theme.on_secondary_container)
            else:
                self._set_status("Connected", self.theme.on_secondary_container)
        else:
            self._set_status("Disconnected", self.theme.on_secondary_container)
            if not self._port_change_notice:
                self.ping_label.setText("Ping: --")

    def on_connection_state_changed(self, conn):
        for item in self._server_items:
            item.radio.update()

    def on_vpn_switch_clicked(self, e):
        if e.button() == Qt.LeftButton:
            self.toggle_connection()

    def _ensure_backend(self):
        """Check that the current engine exists; if not, offer to download it."""
        engine = self.connection_manager.engine
        binary = engine.find_binary()
        if binary is not None:
            check = engine.check_usable(binary)
            if check.usable:
                return True
        engine_name = engine.engine_type.value
        subdir = engine_name.replace("-", "")
        result = QMessageBox.question(
            self, "Socksicle",
            f"Proxy engine ({engine_name}) is not installed.\n\n"
            "Would you like to download it now?\n\n"
            f"Tip: you can also place the binary manually into "
            f"./bin/{subdir}/ next to the app and restart.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes)
        if result != QMessageBox.Yes:
            QMessageBox.information(
                self, "Socksicle",
                "Cannot connect without the backend.\n"
                f"You can install {engine_name} manually later.")
            return False
        mgr = ServerManager()
        mgr.set_sslocal_declined(False)
        outcome = ensure_engine(engine.engine_type)
        if outcome is not None and outcome.ok:
            return True
        if outcome is None or outcome.reason == DECLINED_REASON:
            return False
        QMessageBox.warning(
            self, "Socksicle",
            f"Download failed: {outcome.reason}")
        return False

    @Slot(dict)
    def update_geo_ui(self, info):
        if self.connection_manager.is_connected:
            self._set_status(f"{info['flag']} {info['ip']}", self.theme.on_secondary_container)
            self.show_notification(f"Connected: {info['flag']} {info['ip']}", f"Your IP is now {info['ip']}.")

    @Slot(str)
    def on_geo_error(self, reason):
        if self.connection_manager.is_connected:
            self._set_status("Connected (geo unavailable)", self.theme.on_secondary_container)

    @Slot(object)
    def update_ping_ui(self, ms):
        if self._port_change_notice or not self.connection_manager.is_connected:
            return
        if ms is not None:
            self.ping_label.setText(
                f"Ping: {ms:.0f} ms · {self._proxy_addr_text()}")
        else:
            self.ping_label.setText("Ping: Error")

    def show_notification(self, title, message):
        self.tray_icon.showMessage(title, message, QIcon(self.icon_path), 3000)

    def toggle_connection(self, connect=None):
        if connect is None:
            connect = not self.connection_manager.is_connected
        if connect:
            if not self._ensure_backend():
                return
            btn = self.button_group.checkedButton()
            if btn:
                idx = self.button_group.id(btn)
                servers = self._current_servers()
                if idx < len(servers):
                    server = servers[idx]
                    log.info("Connecting to server index %d in tab %s...",
                             idx, self.current_tab)
                    if self.connection_manager.toggle(server, True):
                        self.vpn_switch.toggle(True)
                        self.status_label.setText("⚡ Connecting...")
                        self.show_notification("Connecting", f"Attempting to connect to {server.name}...")
            else:
                QMessageBox.warning(self, "Error", "Please select a server first!")
        else:
            log.info("Disconnecting...")
            self.connection_manager.toggle(None, False)
            self.vpn_switch.toggle(False)
            self.ping_label.setText("Ping: --")
            self.show_notification("Disconnected", "Your secure connection has been closed.")

    def _current_servers(self):
        if self.current_tab == "Manual":
            return self.manual_servers
        return self.subscription_manager.get_servers(self.current_tab)

    def reconnect_after_resume(self):
        """Called after Windows sleep/hibernate resume: sockets died, rebuild."""
        log.info("System resumed, reconnecting proxy...")
        if not self.connection_manager.is_connected:
            return
        self.connection_manager.disconnect()
        self.vpn_switch.toggle(False)
        QTimer.singleShot(1500, lambda: self.toggle_connection(True))

    def setup_bottom_nav(self):
        nav = QHBoxLayout()
        actions = [
            ("Settings", self.show_settings_dialog),
            ("Logs", self.show_log_dialog),
            ("About", self.show_about_dialog),
        ]
        for txt, cmd in actions:
            btn = QPushButton(txt)
            btn.setStyleSheet(self.theme.get_button_style("text"))
            btn.clicked.connect(cmd)
            nav.addWidget(btn)
            if txt == "Settings":
                nav.addStretch()
        self.layout.addLayout(nav)

    def show_log_dialog(self):
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

    def setup_tray_icon(self):
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(self.icon_path))
        self.tray_menu = QMenu()
        self.show_action = self.tray_menu.addAction("Show/Hide")
        self.show_action.triggered.connect(self.toggle_visibility)
        self.servers_menu = self.tray_menu.addMenu("Servers")
        self.tray_menu.addSeparator()
        self.disconnect_action = self.tray_menu.addAction("Disconnect")
        self.disconnect_action.triggered.connect(
            lambda: self.toggle_connection(False))
        self.disconnect_action.setEnabled(False)
        self.quit_action = self.tray_menu.addAction("Quit")
        self.quit_action.triggered.connect(self.quit_app)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def update_tray_menu(self):
        self.servers_menu.clear()
        manual_menu = self.servers_menu.addMenu("Manual")
        for i, server in enumerate(self.manual_servers):
            action = manual_menu.addAction(server.name)
            action.triggered.connect(
                lambda checked=False, i=i: self.connect_from_tray("Manual", i))
        for sub in self.subscription_manager.subscriptions:
            sub_menu = self.servers_menu.addMenu(sub['name'])
            for i, server in enumerate(sub['servers']):
                action = sub_menu.addAction(server.name)
                action.triggered.connect(
                    lambda checked=False, n=sub['name'], i=i: self.connect_from_tray(n, i))

    def connect_from_tray(self, tab_name, server_index):
        self.switch_tab(tab_name)
        if server_index < len(self._server_items):
            self._server_items[server_index].radio.setChecked(True)
        QTimer.singleShot(100, lambda: self.toggle_connection(True))

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visibility()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def quit_app(self):
        self.connection_manager.disconnect()
        self.tray_icon.hide()
        QApplication.quit()

    def switch_tab(self, name, force=False):
        if self.current_tab == name and not force: return
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.opacity_effect.opacity())
        self.fade_anim.setEndValue(0.0)
        def on_finished():
            try:
                self.fade_anim.finished.disconnect()
            except TypeError:
                log.debug("Signal already disconnected", exc_info=True)
            self.current_tab = name
            self.update_tabs()
            self.refresh_server_list()
            self.del_sub_btn.setVisible(name != "Manual")
            self.update_sub_btn.setVisible(name != "Manual")
            info = self.subscription_manager.traffic_info(name)
            meta = self.subscription_manager.get_metadata(name)
            if info:
                used, total, percent, expire = info
                self.traffic_label.setText(f"Traffic: {used:.1f} / {total:.1f} GB")
                self.traffic_bar.setValue(int(percent))
                if expire: self.expire_label.setText(f"Expires: {expire}")
            if info or meta.get('profile_title') or meta.get('description'):
                self.traffic_card.show()
            else:
                self.traffic_card.hide()

            # Show subscription metadata
            server_count = meta.get('server_count', 0)
            data_parts = []
            if server_count:
                data_parts.append(f"{server_count} servers")
            last_updated = meta.get('last_updated', 0)
            if last_updated:
                data_parts.append("Updated: " + time.strftime('%Y-%m-%d', time.localtime(last_updated)))
            interval = meta.get('profile_update_interval', 0)
            if interval > 0:
                data_parts.append(f"Auto-update: every {interval}h")
            desc = meta.get('description', '')
            if desc and desc.strip():
                self.meta_label.setText(
                    desc if not data_parts else f"{desc}\n{' | '.join(data_parts)}")
                self.meta_label.show()
            else:
                meta_parts = []
                if meta.get('profile_title'):
                    meta_parts.append(meta['profile_title'])
                meta_parts += data_parts
                if meta_parts:
                    self.meta_label.setText(" | ".join(meta_parts))
                    self.meta_label.show()
                else:
                    self.meta_label.hide()

            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(1.0)
            self.fade_anim.start()
        self.fade_anim.finished.connect(on_finished)
        self.fade_anim.start()

    def filter_servers(self, text):
        text = text.lower()
        for item in self._server_items:
            visible = text in item.radio.text().lower() or text in item.server.host.lower()
            item.setVisible(visible)

    def update_current_subscription(self):
        if self.current_tab == "Manual": return
        sub = self.subscription_manager.get(self.current_tab)
        if sub:
            self.update_sub_btn.setText("⏳")
            self.update_sub_btn.setEnabled(False)
            self.subscription_manager.update(sub)

    @Slot(bool, int)
    def _on_sub_updated(self, success, new_count):
        self.update_sub_btn.setText("🔄 Update")
        self.update_sub_btn.setEnabled(True)
        if success:
            self.switch_tab(self.current_tab, force=True)
            if new_count > 0:
                self.show_notification(
                    "Subscription Updated", f"Added {new_count} new nodes.")
            else:
                self.show_notification(
                    "Subscription Updated", "Already up to date.")
        else:
            sub = self.subscription_manager.get(self.current_tab)
            url = sub['url'] if sub else "unknown"
            QMessageBox.warning(self, "Update Failed",
                f"Failed to update subscription.\n\nURL: {url}\n\n"
                "Check your network connection and verify the URL is correct.")

    def update_tabs(self):
        while self.tabs_layout.count():
            item = self.tabs_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        tabs = ["Manual"] + [s['name'] for s in self.subscription_manager.subscriptions]
        for name in tabs:
            is_active = name == self.current_tab
            color = self.theme.primary if is_active else self.theme.on_surface_variant
            border = (
                f"border-bottom: 3px solid {self.theme.primary};" if is_active else "")
            btn = QPushButton(name)
            btn.setStyleSheet(
                f"QPushButton {{ color: {color}; background: transparent; border: none;"
                f" font-weight: 700; font-size: 14px; padding: 8px 4px; {border} }}")
            btn.clicked.connect(lambda checked=False, n=name: self.switch_tab(n))
            self.tabs_layout.addWidget(btn)
        self.tabs_layout.addStretch()

    def refresh_server_list(self):
        for b in self.button_group.buttons(): self.button_group.removeButton(b)
        while self.server_layout.count():
            item = self.server_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        servers = self._current_servers()
        self._server_items = []
        for i, s in enumerate(servers):
            item = ServerItem(s.name, s, self.theme)
            item.delete_button.clicked.connect(
                lambda checked=False, idx=i: self.delete_entry(idx))
            self.button_group.addButton(item.radio, i)
            self.server_layout.addWidget(item)
            self._server_items.append(item)
            curr = self.connection_manager.current_server
            if self.connection_manager.is_connected and curr and curr.key == s.key:
                item.radio.setChecked(True)
        self.server_layout.addStretch()
        self.update_tray_menu()
        self.filter_servers(self.search_bar.text())

    def ping_all_servers(self):
        method = self.settings.get("ping_method", DEFAULT_PING_METHOD)
        servers = self._current_servers()
        pool = QThreadPool.globalInstance()
        pool.setMaxThreadCount(min(16, max(1, len(servers))))
        for i, s in enumerate(servers):
            pool.start(PingJob(i, s.host, s.port, self.serverPingReady.emit,
                               method=method,
                               socks5_port=self.connection_manager.local_port))

    @Slot(int, float)
    def update_server_ping_ui(self, index, ms):
        if index < len(self._server_items):
            self._server_items[index].set_ping(ms if ms >= 0 else None)

    def delete_current_subscription(self):
        if self.current_tab == "Manual": return
        if QMessageBox.question(self, "Delete Sub", f"Remove subscription '{self.current_tab}'?") == QMessageBox.Yes:
            self.subscription_manager.delete(self.current_tab)
            self.current_tab = "Manual"
            self.update_tabs()
            self.refresh_server_list()
            self.update_sub_btn.hide()
            self.del_sub_btn.hide()

    def delete_entry(self, idx):
        if self.current_tab == "Manual":
            self.server_manager.delete_manual(idx)
        else:
            QMessageBox.information(
                self, "Info", "Delete the entire subscription instead.")
            return
        self.refresh_server_list()

    def show_settings_dialog(self):
        current_engine = self.settings.get("engine", "sslocal")
        d = SettingsDialog(self, self.theme, self.connection_manager.local_port,
                           self.settings.get("auto_connect", False),
                           current_engine=current_engine)
        if d.exec() == QDialog.Accepted:
            s = d.get_settings()
            old_engine = self.settings.get("engine", "sslocal")
            new_engine = s.get("engine", "sslocal")
            old_port = self.connection_manager.local_port

            self.settings.update(s)
            self.server_manager.save_settings()

            # Switch engine if changed
            if new_engine != old_engine:
                engine = get_engine(EngineType(new_engine))
                self.connection_manager.switch_engine(engine)

            self.connection_manager.apply_settings(s)

            # A running connection keeps the old port until it restarts
            if (s["local_port"] != old_port and
                    (self.connection_manager.is_connected or
                     self.connection_manager.is_connecting)):
                self._notify_port_change()

            self.subscription_manager.set_settings(self.settings)
            self.subscription_manager.set_auto_update(
                s.get("auto_update_subs", True))

    def export_profiles(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Profiles", "", "JSON Files (*.json)")
        if path:
            try:
                self.server_manager.export_profiles(path, self.subscription_manager.subscriptions)
                self.show_notification("Export Successful", f"Profiles saved to {os.path.basename(path)}")
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
                self.update_tabs()
                self.refresh_server_list()
                self.show_notification("Import Successful", f"Added {added_m} servers and {added_s} subscriptions.")
            else: QMessageBox.information(self, "Import", "No new profiles found in file.")

    def show_add_dialog(self):
        d = AddServerDialog(self, self.theme)
        if d.exec() != QDialog.Accepted:
            return
        raw = d.get_server_key()
        if not raw:
            QMessageBox.warning(
                self, "Empty Link",
                "Please enter a server link, subscription URL, or tws2:// share.")
            return
        link = raw
        if link.startswith("tws2://"):
            share_key = self.settings.get("tws2_share_key", "")
            if not share_key:
                QMessageBox.warning(
                    self, "TwinSock",
                    "No TwinSock share key set in Settings")
                return
            try:
                link = twinsock.decrypt_share(share_key, raw)
            except (twinsock.VaultError, ValueError) as e:
                QMessageBox.warning(
                    self, "TwinSock",
                    f"Failed to decrypt TwinSock share: {e}")
                return
        if link.startswith("http://") or link.startswith("https://"):
            name = urlparse(link).hostname or urlparse(link).netloc or "Subscription"
            if self.subscription_manager.add(name, link):
                self.update_tabs()
                self.switch_tab(name)
            else:
                QMessageBox.warning(
                    self, "Add Failed",
                    "Failed to fetch subscription. Check the URL and your network connection.")
            return
        server = self.server_manager.add_from_link(link)
        if not server:
            QMessageBox.warning(
                self, "Invalid Link",
                "The provided link is malformed.\n\n"
                "Supported formats: ss://, vless://, vmess://, "
                "subscription URL, or tws2://"
            )
            return
        self.refresh_server_list()

    def on_checkbox_toggled(self, button, checked):
        if checked and self.connection_manager.is_connected:
            self.toggle_connection(False)
            QTimer.singleShot(500, lambda: self.toggle_connection(True))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 60:
            self._dragging = True
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._dragging = False