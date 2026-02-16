import json
import os
import time
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QButtonGroup, QFrame, QMessageBox, QDialog, QScrollArea, QProgressBar, QLineEdit, QGraphicsOpacityEffect, QSystemTrayIcon, QMenu, QApplication, QFileDialog
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QIcon, QAction

from .toggle_switch import AnimatedToggleSwitch
from .server_item import ServerItem
from .add_server_dialog import AddServerDialog
from .connection_log_dialog import ConnectionLogDialog
from .settings_dialog import SettingsDialog
from .about_dialog import AboutDialog
from utils.ss_client import ShadowsocksProcess
from utils.ss_parser import decode_ss_link
from utils.ping import http_ping_via_socks5_once, direct_tcp_ping
from utils.theme import M3Theme
from utils.geo_utils import fetch_ip_info_via_proxy
from utils.sub_manager import parse_subscription, load_subscriptions, save_subscriptions

class RoundedWindow(QWidget):
    geoInfoReady = Signal(dict)
    pingResultReady = Signal(int, float)
    subscriptionUpdated = Signal(bool, int)

    def __init__(self):
        super().__init__()
        self.theme = M3Theme()
        self.current_geo = None
        self.current_tab = "Manual"
        self.is_connecting = False
        
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(440, 720)
        
        self.setup_tray_icon()
        
        self.config_dir = os.path.expanduser("~/.config/socksicle")
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = os.path.join(self.config_dir, "servers.json")
        self.settings_file = os.path.join(self.config_dir, "settings.json")
        
        self.manual_servers = []
        self.subscriptions = load_subscriptions()
        self.load_manual_servers()
        self.settings = self.load_settings()
        
        self.ss_client = ShadowsocksProcess()
        self.ss_client.local_port = self.settings.get("local_port", "1080")
        self.ss_client.statusChanged.connect(self.on_status_changed)
        self.ss_client.connectionStateChanged.connect(self.on_connection_state_changed)
        self.ss_client.logUpdated.connect(self.add_log)
        
        self.geoInfoReady.connect(self.update_geo_ui)
        self.pingResultReady.connect(self.update_server_ping_ui)
        self.subscriptionUpdated.connect(self._on_sub_updated)
        
        # Initialize log dialog
        self.log_dialog = ConnectionLogDialog(self, self.theme)
        
        self.main_layout = QVBoxLayout(self); self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.container = QFrame(); self.container.setStyleSheet(f"background-color: {self.theme.surface}; border-radius: 32px; border: none;"); self.main_layout.addWidget(self.container)
        self.layout = QVBoxLayout(self.container); self.layout.setContentsMargins(20, 16, 20, 20)
        
        self.setup_header()
        self.setup_status_card()
        
        self.tabs_container = QWidget(); self.tabs_container.setFixedHeight(48)
        self.tabs_layout = QHBoxLayout(self.tabs_container); self.tabs_layout.setContentsMargins(0, 0, 0, 0); self.tabs_layout.setSpacing(8)
        self.layout.addWidget(self.tabs_container)
        
        self.traffic_card = QFrame(); self.traffic_card.setStyleSheet(f"background: {self.theme.surface_variant}; border-radius: 20px; border: none;"); self.traffic_card.setFixedHeight(80)
        t_lay = QVBoxLayout(self.traffic_card); t_lay.setContentsMargins(16, 12, 16, 12)
        self.traffic_label = QLabel("Traffic: --"); self.traffic_label.setStyleSheet(f"color: {self.theme.on_surface}; font-size: 12px; font-weight: 600;")
        self.expire_label = QLabel("Expires: --"); self.expire_label.setStyleSheet(f"color: {self.theme.on_surface_variant}; font-size: 11px;")
        self.traffic_bar = QProgressBar(); self.traffic_bar.setFixedHeight(8); self.traffic_bar.setTextVisible(False); self.traffic_bar.setStyleSheet(f"QProgressBar {{ background-color: rgba(0,0,0,0.2); border: none; border-radius: 4px; }} QProgressBar::chunk {{ background-color: {self.theme.primary}; border-radius: 4px; }}")
        t_lay.addWidget(self.traffic_label); t_lay.addWidget(self.traffic_bar); t_lay.addWidget(self.expire_label)
        self.layout.addWidget(self.traffic_card); self.traffic_card.hide()

        self.action_bar = QHBoxLayout()
        self.add_btn = QPushButton("+ Link"); self.add_btn.setStyleSheet(self.theme.get_button_style("tonal")); self.add_btn.clicked.connect(self.show_add_server_dialog)
        self.add_sub_btn = QPushButton("+ Sub"); self.add_sub_btn.setStyleSheet(self.theme.get_button_style("tonal")); self.add_sub_btn.clicked.connect(self.show_add_sub_dialog)
        
        self.export_btn = QPushButton("📤"); self.export_btn.setToolTip("Export Profiles"); self.export_btn.setStyleSheet(self.theme.get_button_style("text")); self.export_btn.setFixedSize(40, 40); self.export_btn.clicked.connect(self.export_profiles)
        self.import_btn = QPushButton("📥"); self.import_btn.setToolTip("Import Profiles"); self.import_btn.setStyleSheet(self.theme.get_button_style("text")); self.import_btn.setFixedSize(40, 40); self.import_btn.clicked.connect(self.import_profiles)
        
        self.update_sub_btn = QPushButton("🔄 Update"); self.update_sub_btn.setStyleSheet(self.theme.get_button_style("text")); self.update_sub_btn.clicked.connect(self.update_current_subscription); self.update_sub_btn.hide()
        self.ping_all_btn = QPushButton("⚡ Ping All"); self.ping_all_btn.setStyleSheet(self.theme.get_button_style("text")); self.ping_all_btn.clicked.connect(self.ping_all_servers)
        self.del_sub_btn = QPushButton("🗑 Sub"); self.del_sub_btn.setStyleSheet(self.theme.get_button_style("text")); self.del_sub_btn.clicked.connect(self.delete_current_subscription); self.del_sub_btn.hide()
        
        self.action_bar.addWidget(self.add_btn); self.action_bar.addWidget(self.add_sub_btn); self.action_bar.addWidget(self.export_btn); self.action_bar.addWidget(self.import_btn); self.action_bar.addStretch(); self.action_bar.addWidget(self.update_sub_btn); self.action_bar.addWidget(self.ping_all_btn); self.action_bar.addWidget(self.del_sub_btn)
        self.layout.addLayout(self.action_bar)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search servers...")
        self.search_bar.setStyleSheet(f"background: {self.theme.surface_variant}; color: {self.theme.on_surface}; padding: 8px 12px; border-radius: 12px; border: none; margin-top: 4px;")
        self.search_bar.textChanged.connect(self.filter_servers)
        self.layout.addWidget(self.search_bar)

        self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True); self.scroll_area.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }} QScrollBar:vertical {{ border: none; background: transparent; width: 6px; }} QScrollBar::handle:vertical {{ background: {self.theme.surface_variant}; border-radius: 3px; min-height: 30px; }}")
        self.scroll_content = QWidget(); self.server_layout = QVBoxLayout(self.scroll_content); self.server_layout.setContentsMargins(0, 0, 0, 0); self.server_layout.setSpacing(10); self.scroll_area.setWidget(self.scroll_content); self.layout.addWidget(self.scroll_area)
        self.opacity_effect = QGraphicsOpacityEffect(self.scroll_area); self.scroll_area.setGraphicsEffect(self.opacity_effect); self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity"); self.fade_anim.setDuration(200)

        self.setup_bottom_nav()
        self.button_group = QButtonGroup(self); self.button_group.setExclusive(True); self.button_group.buttonToggled.connect(self.on_checkbox_toggled)
        
        self.update_tabs(); self.refresh_server_list()
        self.ping_timer = QTimer(self); self.ping_timer.timeout.connect(self.update_ping)
        self._dragging = False

    def setup_header(self):
        header = QHBoxLayout(); title = QLabel("Socksicle"); title.setStyleSheet(f"color: {self.theme.on_surface}; font-size: 22px; font-weight: 600;"); header.addWidget(title); header.addStretch()
        for txt, cmd in [("—", self.showMinimized), ("✕", self.close)]:
            btn = QPushButton(txt); btn.setFixedSize(36, 36); btn.setStyleSheet(f"QPushButton {{ color: white; background: transparent; border-radius: 18px; border: none; }} QPushButton:hover {{ background: {self.theme.surface_variant}; }}"); btn.clicked.connect(cmd); header.addWidget(btn)
        self.layout.addLayout(header)

    def closeEvent(self, event):
        if self.settings.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
            self.show_notification("Socksicle", "Application is still running in the tray.")
        else:
            self.quit_app()

    def setup_status_card(self):
        self.status_card = QFrame(); c = QColor(self.theme.secondary_container); rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.4)"; self.status_card.setStyleSheet(f"QFrame {{ background-color: {rgba}; border-radius: 28px; border: none; }} QLabel {{ color: {self.theme.on_secondary_container}; border: none; background: transparent; }}"); self.status_card.setFixedHeight(120); card_layout = QVBoxLayout(self.status_card); card_layout.setContentsMargins(24, 16, 24, 16)
        top = QHBoxLayout(); top.addWidget(QLabel("Connection Status")); top.addStretch(); self.vpn_switch = AnimatedToggleSwitch(); self.vpn_switch.mousePressEvent = self.on_vpn_switch_clicked; top.addWidget(self.vpn_switch)
        self.status_label = QLabel("Disconnected"); self.status_label.setStyleSheet("font-size: 24px; font-weight: bold; background: transparent;"); self.ping_label = QLabel("Ping: --"); self.ping_label.setStyleSheet("font-size: 12px; opacity: 0.7; background: transparent;"); card_layout.addLayout(top); card_layout.addWidget(self.status_label); card_layout.addWidget(self.ping_label); self.layout.addWidget(self.status_card)

    def on_status_changed(self, msg, err):
        self.disconnect_action.setEnabled(self.ss_client.is_connected)
        if err:
            self.status_label.setText("Error"); self.status_label.setStyleSheet(f"color: {self.theme.error}; font-size: 24px; font-weight: bold; background: transparent;"); self.is_connecting = False
            self.show_notification("Connection Error", msg)
        elif self.ss_client.is_connected:
            if self.current_geo: self.status_label.setText(f"{self.current_geo['flag']} {self.current_geo['ip']}")
            else:
                if self.is_connecting: self.status_label.setText("⚡ Connecting...")
                else: self.status_label.setText("Connected")
            self.status_label.setStyleSheet(f"color: {self.theme.on_secondary_container}; font-size: 24px; font-weight: bold; background: transparent;")
        else:
            self.status_label.setText("Disconnected"); self.status_label.setStyleSheet(f"color: {self.theme.on_secondary_container}; font-size: 24px; font-weight: bold; background: transparent;"); self.is_connecting = False

    def on_connection_state_changed(self, conn):
        for i in range(self.server_layout.count()):
            w = self.server_layout.itemAt(i).widget()
            if isinstance(w, ServerItem): w.radio.update()

    def on_vpn_switch_clicked(self, e):
        if e.button() == Qt.LeftButton: self.toggle_connection()

    @Slot(dict)
    def update_geo_ui(self, info):
        self.current_geo = info; self.is_connecting = False
        if self.ss_client.is_connected:
            self.status_label.setText(f"{info['flag']} {info['ip']}")
            self.show_notification(f"Connected: {info['flag']} {info['ip']}", f"Your IP is now {info['ip']}.")

    def show_notification(self, title, message):
        self.tray_icon.showMessage(title, message, QIcon("icon.png"), 3000)

    def toggle_connection(self, connect=None):
        if connect is None: connect = not self.ss_client.is_connected
        if connect:
            btn = self.button_group.checkedButton()
            if btn:
                idx = self.button_group.id(btn)
                print(f"[Main] Connecting to server index {idx} in tab {self.current_tab}...", flush=True)
                servers = self.manual_servers if self.current_tab == "Manual" else next((s['servers'] for s in self.subscriptions if s['name'] == self.current_tab), [])
                if idx < len(servers):
                    self.current_geo = None; self.is_connecting = True; self.status_label.setText("⚡ Connecting...")
                    if self.ss_client.connect(servers[idx]):
                        self.vpn_switch.toggle(True); self.ping_timer.start(5000)
                        self.show_notification("Connecting", f"Attempting to connect to {servers[idx]['name']}...")
                        print(f"[Main] Scheduling geo fetch in 1.5s...", flush=True)
                        QTimer.singleShot(1500, self.start_background_geo_fetch)
                        QTimer.singleShot(4000, self.force_connected_status)
            else: QMessageBox.warning(self, "Error", "Please select a server first!")
        else:
            print("[Main] Disconnecting...", flush=True)
            self.ss_client.disconnect(); self.vpn_switch.toggle(False); self.ping_timer.stop(); self.ping_label.setText("Ping: --"); self.current_geo = None; self.is_connecting = False
            self.show_notification("Disconnected", "Your secure connection has been closed.")

    def force_connected_status(self):
        if self.ss_client.is_connected and not self.current_geo:
            print("[Main] Geo-fetch timeout, showing 'Connected' fallback.", flush=True)
            self.is_connecting = False; self.status_label.setText("Connected")

    def start_background_geo_fetch(self):
        if self.ss_client.is_connected:
            print(f"[Main] Triggering background Geo-IP fetch on port {self.ss_client.local_port}...", flush=True)
            threading.Thread(target=self.background_fetch_geo, args=(self.ss_client.local_port,), daemon=True).start()

    def background_fetch_geo(self, port):
        info = fetch_ip_info_via_proxy(port)
        if info: self.geoInfoReady.emit(info)

    def setup_bottom_nav(self):
        nav = QHBoxLayout()
        for txt, cmd in [("Settings", self.show_settings_dialog), ("Logs", self.show_log_dialog), ("About", self.show_about_dialog)]:
            btn = QPushButton(txt); btn.setStyleSheet(self.theme.get_button_style("text")); btn.clicked.connect(cmd); nav.addWidget(btn)
            if txt == "Settings": nav.addStretch()
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
        d = AboutDialog(self, self.theme); d.exec()

    def setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self); self.tray_icon.setIcon(QIcon("icon.png")); self.tray_menu = QMenu()
        self.show_action = self.tray_menu.addAction("Show/Hide"); self.show_action.triggered.connect(self.toggle_visibility)
        self.servers_menu = self.tray_menu.addMenu("Servers"); self.tray_menu.addSeparator()
        self.disconnect_action = self.tray_menu.addAction("Disconnect"); self.disconnect_action.triggered.connect(lambda: self.toggle_connection(False)); self.disconnect_action.setEnabled(False)
        self.quit_action = self.tray_menu.addAction("Quit"); self.quit_action.triggered.connect(self.quit_app)
        self.tray_icon.setContextMenu(self.tray_menu); self.tray_icon.activated.connect(self.on_tray_activated); self.tray_icon.show()

    def update_tray_menu(self):
        self.servers_menu.clear(); manual_menu = self.servers_menu.addMenu("Manual")
        for i, server in enumerate(self.manual_servers):
            action = manual_menu.addAction(server['name']); action.triggered.connect(lambda checked=False, i=i: self.connect_from_tray("Manual", i))
        for sub in self.subscriptions:
            sub_menu = self.servers_menu.addMenu(sub['name'])
            for i, server in enumerate(sub['servers']):
                action = sub_menu.addAction(server['name']); action.triggered.connect(lambda checked=False, n=sub['name'], i=i: self.connect_from_tray(n, i))

    def connect_from_tray(self, tab_name, server_index):
        self.switch_tab(tab_name)
        if server_index < self.server_layout.count() - 1:
            item = self.server_layout.itemAt(server_index).widget()
            if isinstance(item, ServerItem): item.radio.setChecked(True)
        QTimer.singleShot(100, lambda: self.toggle_connection(True))

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger: self.toggle_visibility()
            
    def toggle_visibility(self):
        if self.isVisible(): self.hide()
        else: self.show(); self.activateWindow()

    def quit_app(self):
        self.ss_client.disconnect(); self.tray_icon.hide(); QApplication.quit()

    def switch_tab(self, name):
        if self.current_tab == name: return
        self.fade_anim.stop(); self.fade_anim.setStartValue(self.opacity_effect.opacity()); self.fade_anim.setEndValue(0.0)
        def on_finished():
            try: self.fade_anim.finished.disconnect()
            except: pass
            self.current_tab = name; self.update_tabs(); self.refresh_server_list()
            self.del_sub_btn.setVisible(name != "Manual"); self.update_sub_btn.setVisible(name != "Manual")
            sub = next((s for s in self.subscriptions if s['name'] == name), None)
            if sub and sub.get('traffic'):
                t = sub['traffic']; used = t['used'] / (1024**3); total = t['total'] / (1024**3); percent = (t['used']/t['total'])*100 if t['total'] > 0 else 0
                self.traffic_label.setText(f"Traffic: {used:.1f} / {total:.1f} GB"); self.traffic_bar.setValue(int(percent))
                if t.get('expire'): dt = datetime.fromtimestamp(t['expire']).strftime('%Y-%m-%d'); self.expire_label.setText(f"Expires: {dt}")
                self.traffic_card.show()
            else: self.traffic_card.hide()
            self.fade_anim.setStartValue(0.0); self.fade_anim.setEndValue(1.0); self.fade_anim.start()
        self.fade_anim.finished.connect(on_finished); self.fade_anim.start()

    def filter_servers(self, text):
        text = text.lower()
        for i in range(self.server_layout.count()):
            item = self.server_layout.itemAt(i).widget()
            if isinstance(item, ServerItem):
                visible = text in item.radio.text().lower() or text in item.server_data.get('host', '').lower()
                item.setVisible(visible)

    def update_current_subscription(self):
        if self.current_tab == "Manual": return
        sub = next((s for s in self.subscriptions if s['name'] == self.current_tab), None)
        if sub:
            self.update_sub_btn.setText("⏳"); self.update_sub_btn.setEnabled(False)
            threading.Thread(target=self._update_sub_worker, args=(sub,), daemon=True).start()

    @Slot(bool, int)
    def _on_sub_updated(self, success, new_count):
        self.update_sub_btn.setText("🔄 Update"); self.update_sub_btn.setEnabled(True)
        if success:
            self.switch_tab(self.current_tab)
            if new_count > 0: self.show_notification("Subscription Updated", f"Added {new_count} new nodes.")
            else: self.show_notification("Subscription Updated", "Already up to date.")
        else: QMessageBox.warning(self, "Error", "Failed to update subscription.")

    def _update_sub_worker(self, sub_to_update):
        links, traffic = parse_subscription(sub_to_update['url'])
        if links:
            old_keys = {s['key'] for s in sub_to_update.get('servers', [])}
            new_servers = []
            new_count = 0
            for l in links:
                data = decode_ss_link(l)
                if data:
                    new_servers.append({"key": l, "name": data.get('tag', 'Server'), "host": data.get('server', ''), "port": str(data.get('port', 443)), "method": data.get('method', 'aes-256-gcm'), "password": data.get('password', '')})
                    if l not in old_keys: new_count += 1
            sub_to_update['servers'] = new_servers; sub_to_update['traffic'] = traffic
            save_subscriptions(self.subscriptions); self.subscriptionUpdated.emit(True, new_count)
        else: self.subscriptionUpdated.emit(False, 0)

    def update_tabs(self):
        while self.tabs_layout.count():
            item = self.tabs_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        tabs = ["Manual"] + [s['name'] for s in self.subscriptions]
        for name in tabs:
            btn = QPushButton(name); is_active = name == self.current_tab; color = self.theme.primary if is_active else self.theme.on_surface_variant; border = f"border-bottom: 3px solid {self.theme.primary};" if is_active else ""
            btn.setStyleSheet(f"QPushButton {{ color: {color}; background: transparent; border: none; font-weight: 700; font-size: 14px; padding: 8px 4px; {border} }}")
            btn.clicked.connect(lambda checked=False, n=name: self.switch_tab(n)); self.tabs_layout.addWidget(btn)
        self.tabs_layout.addStretch()

    def refresh_server_list(self):
        for b in self.button_group.buttons(): self.button_group.removeButton(b)
        while self.server_layout.count():
            item = self.server_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        servers = self.manual_servers if self.current_tab == "Manual" else next((s['servers'] for s in self.subscriptions if s['name'] == self.current_tab), [])
        for i, s in enumerate(servers):
            item = ServerItem(s.get('name', 'Server'), s, self.theme); item.delete_button.clicked.connect(lambda checked=False, idx=i: self.delete_entry(idx)); self.button_group.addButton(item.radio, i); self.server_layout.addWidget(item)
            curr = self.ss_client.get_current_server();
            if self.ss_client.is_connected and curr and curr.get('key') == s.get('key'): item.radio.setChecked(True)
        self.server_layout.addStretch(); self.update_tray_menu()
        self.filter_servers(self.search_bar.text())

    def ping_all_servers(self):
        servers = self.manual_servers if self.current_tab == "Manual" else next((s['servers'] for s in self.subscriptions if s['name'] == self.current_tab), [])
        for i, s in enumerate(servers): threading.Thread(target=self._ping_worker, args=(i, s['host'], s['port']), daemon=True).start()

    def _ping_worker(self, index, host, port):
        ms = direct_tcp_ping(host, port); self.pingResultReady.emit(index, ms if ms is not None else -1.0)

    @Slot(int, float)
    def update_server_ping_ui(self, index, ms):
        if index < self.server_layout.count() - 1:
            item = self.server_layout.itemAt(index).widget()
            if isinstance(item, ServerItem): item.set_ping(ms if ms >= 0 else None)

    def delete_current_subscription(self):
        if self.current_tab == "Manual": return
        if QMessageBox.question(self, "Delete Sub", f"Remove subscription '{self.current_tab}'?") == QMessageBox.Yes:
            self.subscriptions = [s for s in self.subscriptions if s['name'] != self.current_tab]
            save_subscriptions(self.subscriptions); self.current_tab = "Manual"; self.update_tabs(); self.refresh_server_list(); self.update_sub_btn.hide(); self.del_sub_btn.hide()

    def delete_entry(self, idx):
        if self.current_tab == "Manual":
            if idx < len(self.manual_servers): del self.manual_servers[idx]; self.save_manual_servers()
        else: QMessageBox.information(self, "Info", "Delete the entire subscription instead."); return
        self.refresh_server_list()
        
    def load_manual_servers(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f: self.manual_servers = json.load(f)
            except: pass
    def save_manual_servers(self):
        with open(self.config_file, 'w') as f: json.dump(self.manual_servers, f)
    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f: return json.load(f)
            except: pass
        return {"local_port": "1080", "auto_connect": False, "minimize_to_tray": True}
    def save_settings(self):
        with open(self.settings_file, 'w') as f: json.dump(self.settings, f)
    def show_settings_dialog(self):
        d = SettingsDialog(self, self.theme, self.ss_client.local_port, self.settings.get("auto_connect", False))
        if d.exec() == QDialog.Accepted:
            s = d.get_settings(); self.settings.update(s); self.ss_client.local_port = s["local_port"]; self.save_settings()

    def export_profiles(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Profiles", "", "JSON Files (*.json)")
        if path:
            data = {"manual_servers": self.manual_servers, "subscriptions": self.subscriptions}
            try:
                with open(path, 'w') as f: json.dump(data, f, indent=4)
                self.show_notification("Export Successful", f"Profiles saved to {os.path.basename(path)}")
            except Exception as e: QMessageBox.critical(self, "Error", f"Failed to export: {e}")

    def import_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profiles", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r') as f: data = json.load(f)
                added_m = 0; added_s = 0
                if "manual_servers" in data:
                    for s in data["manual_servers"]:
                        if s not in self.manual_servers: self.manual_servers.append(s); added_m += 1
                if "subscriptions" in data:
                    for sub in data["subscriptions"]:
                        if not any(x['url'] == sub['url'] for x in self.subscriptions): self.subscriptions.append(sub); added_s += 1
                if added_m or added_s:
                    self.save_manual_servers(); save_subscriptions(self.subscriptions); self.update_tabs(); self.refresh_server_list()
                    self.show_notification("Import Successful", f"Added {added_m} servers and {added_s} subscriptions.")
                else: QMessageBox.information(self, "Import", "No new profiles found in file.")
            except Exception as e: QMessageBox.critical(self, "Error", f"Failed to import: {e}")
    def show_add_server_dialog(self):
        d = AddServerDialog(self, self.theme)
        if d.exec() == QDialog.Accepted:
            key = d.get_server_key()
            if not decode_ss_link(key): QMessageBox.warning(self, "Invalid Link", "The provided ss:// link is malformed."); return
            data = decode_ss_link(key); self.manual_servers.append({"key": key, "name": data.get('tag', 'New Server'), "host": data.get('server', ''), "port": str(data.get('port', 443)), "method": data.get('method', 'aes-256-gcm'), "password": data.get('password', '')}); self.save_manual_servers(); self.refresh_server_list()
    def show_add_sub_dialog(self):
        d = QDialog(self); d.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog); d.setAttribute(Qt.WA_TranslucentBackground)
        lay = QVBoxLayout(d); cont = QFrame(); cont.setStyleSheet(f"background: {self.theme.surface}; border-radius: 28px; border: none;"); lay.addWidget(cont); v = QVBoxLayout(cont); v.setContentsMargins(24, 24, 24, 24)
        l1 = QLabel("Subscription Name"); l1.setStyleSheet(f"color: {self.theme.on_surface}; font-weight: bold;"); v.addWidget(l1)
        name_in = QLineEdit(); name_in.setStyleSheet(f"background: {self.theme.surface_variant}; color: white; padding: 10px; border-radius: 12px; border: none;"); v.addWidget(name_in)
        l2 = QLabel("Subscription URL"); l2.setStyleSheet(l1.styleSheet()); v.addWidget(l2); url_in = QLineEdit(); url_in.setStyleSheet(name_in.styleSheet()); v.addWidget(url_in)
        btn_lay = QHBoxLayout(); add = QPushButton("Add"); add.setStyleSheet(self.theme.get_button_style("filled")); add.clicked.connect(d.accept); can = QPushButton("Cancel"); can.setStyleSheet(self.theme.get_button_style("text")); can.clicked.connect(d.reject); btn_lay.addWidget(can); btn_lay.addStretch(); btn_lay.addWidget(add); v.addLayout(btn_lay)
        if d.exec() == QDialog.Accepted:
            url, name = url_in.text().strip(), name_in.text().strip()
            if url and name:
                links, traffic = parse_subscription(url)
                if links:
                    servers = []
                    for l in links:
                        data = decode_ss_link(l)
                        if data: servers.append({"key": l, "name": data.get('tag', 'Server'), "host": data.get('server', ''), "port": str(data.get('port', 443)), "method": data.get('method', 'aes-256-gcm'), "password": data.get('password', '')})
                    self.subscriptions.append({"name": name, "url": url, "servers": servers, "traffic": traffic}); save_subscriptions(self.subscriptions); self.update_tabs(); self.switch_tab(name)
    def on_checkbox_toggled(self, button, checked):
        if checked and self.ss_client.is_connected: self.toggle_connection(False); QTimer.singleShot(500, lambda: self.toggle_connection(True))
    def update_ping(self):
        if self.ss_client.is_connected:
            p = http_ping_via_socks5_once('google.com', int(self.ss_client.local_port)); self.ping_label.setText(f"Ping: {p:.0f} ms" if p else "Ping: Error")
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 60:
            self._dragging = True; self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._dragging: self.move(e.globalPosition().toPoint() - self._drag_pos)
    def mouseReleaseEvent(self, e): self._dragging = False
