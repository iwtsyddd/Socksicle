import json
import os
import time
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QButtonGroup, QFrame, QMessageBox, QDialog, QScrollArea, QProgressBar, QLineEdit, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor

from .toggle_switch import AnimatedToggleSwitch
from .server_item import ServerItem
from .add_server_dialog import AddServerDialog
from .connection_log_dialog import ConnectionLogDialog
from .settings_dialog import SettingsDialog
from utils.ss_client import ShadowsocksProcess
from utils.ss_parser import decode_ss_link
from utils.ping import http_ping_via_socks5_once, direct_tcp_ping
from utils.theme import M3Theme
from utils.geo_utils import fetch_geo_info
from utils.sub_manager import parse_subscription, load_subscriptions, save_subscriptions

class RoundedWindow(QWidget):
    geoInfoReady = Signal(dict)
    pingResultReady = Signal(int, float) # index, ms

    def __init__(self):
        super().__init__()
        self.theme = M3Theme()
        self.current_geo = None
        self.current_tab = "Manual"
        
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(440, 720)
        
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

        # Action bar
        self.action_bar = QHBoxLayout()
        self.add_btn = QPushButton("+ Link"); self.add_btn.setStyleSheet(self.theme.get_button_style("tonal")); self.add_btn.clicked.connect(self.show_add_server_dialog)
        self.add_sub_btn = QPushButton("+ Sub"); self.add_sub_btn.setStyleSheet(self.theme.get_button_style("tonal")); self.add_sub_btn.clicked.connect(self.show_add_sub_dialog)
        self.ping_all_btn = QPushButton("⚡ Ping All"); self.ping_all_btn.setStyleSheet(self.theme.get_button_style("text")); self.ping_all_btn.clicked.connect(self.ping_all_servers)
        self.del_sub_btn = QPushButton("🗑 Sub"); self.del_sub_btn.setStyleSheet(self.theme.get_button_style("text")); self.del_sub_btn.clicked.connect(self.delete_current_subscription)
        self.del_sub_btn.hide()
        
        self.action_bar.addWidget(self.add_btn); self.action_bar.addWidget(self.add_sub_btn); self.action_bar.addStretch(); self.action_bar.addWidget(self.ping_all_btn); self.action_bar.addWidget(self.del_sub_btn)
        self.layout.addLayout(self.action_bar)
        
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

    def setup_status_card(self):
        self.status_card = QFrame(); c = QColor(self.theme.secondary_container); rgba = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.4)"
        self.status_card.setStyleSheet(f"QFrame {{ background-color: {rgba}; border-radius: 28px; border: none; }} QLabel {{ color: {self.theme.on_secondary_container}; border: none; background: transparent; }}"); self.status_card.setFixedHeight(120); card_layout = QVBoxLayout(self.status_card); card_layout.setContentsMargins(24, 16, 24, 16)
        top = QHBoxLayout(); top.addWidget(QLabel("Connection Status")); top.addStretch(); self.vpn_switch = AnimatedToggleSwitch(); self.vpn_switch.mousePressEvent = self.on_vpn_switch_clicked; top.addWidget(self.vpn_switch)
        self.status_label = QLabel("Disconnected"); self.status_label.setStyleSheet("font-size: 24px; font-weight: bold; background: transparent;")
        self.ping_label = QLabel("Ping: --"); self.ping_label.setStyleSheet("font-size: 12px; opacity: 0.7; background: transparent;")
        card_layout.addLayout(top); card_layout.addWidget(self.status_label); card_layout.addWidget(self.ping_label); self.layout.addWidget(self.status_card)

    def setup_bottom_nav(self):
        nav = QHBoxLayout()
        for txt, cmd in [("Settings", self.show_settings_dialog), ("Logs", self.show_log_dialog)]:
            btn = QPushButton(txt); btn.setStyleSheet(self.theme.get_button_style("text")); btn.clicked.connect(cmd); nav.addWidget(btn)
            if txt == "Settings": nav.addStretch()
        self.layout.addLayout(nav)

    def switch_tab(self, name):
        if self.current_tab == name: return
        self.fade_anim.stop(); self.fade_anim.setStartValue(self.opacity_effect.opacity()); self.fade_anim.setEndValue(0.0)
        def on_finished():
            self.fade_anim.finished.disconnect(); self.current_tab = name; self.update_tabs(); self.refresh_server_list()
            self.del_sub_btn.setVisible(name != "Manual")
            sub = next((s for s in self.subscriptions if s['name'] == name), None)
            if sub and sub.get('traffic'):
                t = sub['traffic']; used = t['used'] / (1024**3); total = t['total'] / (1024**3); percent = (t['used']/t['total'])*100 if t['total'] > 0 else 0
                self.traffic_label.setText(f"Traffic: {used:.1f} / {total:.1f} GB"); self.traffic_bar.setValue(int(percent))
                if t.get('expire'): dt = datetime.fromtimestamp(t['expire']).strftime('%Y-%m-%d'); self.expire_label.setText(f"Expires: {dt}")
                self.traffic_card.show()
            else: self.traffic_card.hide()
            self.fade_anim.setStartValue(0.0); self.fade_anim.setEndValue(1.0); self.fade_anim.start()
        self.fade_anim.finished.connect(on_finished); self.fade_anim.start()

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
            item = ServerItem(s.get('name', 'Server'), s, self.theme)
            item.delete_button.clicked.connect(lambda checked=False, idx=i: self.delete_entry(idx))
            self.button_group.addButton(item.radio, i)
            self.server_layout.addWidget(item)
            curr = self.ss_client.get_current_server()
            if self.ss_client.is_connected and curr and curr.get('key') == s.get('key'): item.radio.setChecked(True)
        self.server_layout.addStretch()

    def ping_all_servers(self):
        servers = self.manual_servers if self.current_tab == "Manual" else next((s['servers'] for s in self.subscriptions if s['name'] == self.current_tab), [])
        for i, s in enumerate(servers):
            threading.Thread(target=self._ping_worker, args=(i, s['host'], s['port']), daemon=True).start()

    def _ping_worker(self, index, host, port):
        ms = direct_tcp_ping(host, port)
        self.pingResultReady.emit(index, ms if ms is not None else -1.0)

    @Slot(int, float)
    def update_server_ping_ui(self, index, ms):
        if index < self.server_layout.count() - 1: # -1 for stretch
            item = self.server_layout.itemAt(index).widget()
            if isinstance(item, ServerItem):
                item.set_ping(ms if ms >= 0 else None)

    def delete_current_subscription(self):
        if self.current_tab == "Manual": return
        if QMessageBox.question(self, "Delete Sub", f"Remove subscription '{self.current_tab}'?") == QMessageBox.Yes:
            self.subscriptions = [s for s in self.subscriptions if s['name'] != self.current_tab]
            save_subscriptions(self.subscriptions); self.current_tab = "Manual"; self.update_tabs(); self.refresh_server_list()

    def delete_entry(self, idx):
        if self.current_tab == "Manual":
            if idx < len(self.manual_servers): del self.manual_servers[idx]; self.save_manual_servers()
        else:
            QMessageBox.information(self, "Info", "To delete items from a subscription, delete the subscription itself.")
            return
        self.refresh_server_list()

    def toggle_connection(self, connect=None):
        if connect is None: connect = not self.ss_client.is_connected
        if connect:
            btn = self.button_group.checkedButton()
            if btn:
                idx = self.button_group.id(btn)
                servers = self.manual_servers if self.current_tab == "Manual" else next(s['servers'] for s in self.subscriptions if s['name'] == self.current_tab)
                self.current_geo = None
                if self.ss_client.connect(servers[idx]): self.vpn_switch.toggle(True); self.ping_timer.start(5000); threading.Thread(target=self.background_fetch_geo, args=(servers[idx]['host'],), daemon=True).start()
            else: QMessageBox.warning(self, "Error", "Please select a server first!")
        else: self.ss_client.disconnect(); self.vpn_switch.toggle(False); self.ping_timer.stop(); self.ping_label.setText("Ping: --"); self.current_geo = None

    def on_vpn_switch_clicked(self, e):
        if e.button() == Qt.LeftButton: self.toggle_connection()

    def show_add_server_dialog(self):
        d = AddServerDialog(self, self.theme)
        if d.exec() == QDialog.Accepted:
            key = d.get_server_key(); data = decode_ss_link(key)
            if data: self.manual_servers.append({"key": key, "name": data.get('tag', 'New Server'), "host": data.get('server', ''), "port": str(data.get('port', 443)), "method": data.get('method', 'aes-256-gcm'), "password": data.get('password', '')}); self.save_manual_servers(); self.refresh_server_list()

    def show_add_sub_dialog(self):
        d = QDialog(self); d.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog); d.setAttribute(Qt.WA_TranslucentBackground)
        lay = QVBoxLayout(d); cont = QFrame(); cont.setStyleSheet(f"background: {self.theme.surface}; border-radius: 28px; border: none;"); lay.addWidget(cont); v = QVBoxLayout(cont); v.setContentsMargins(24, 24, 24, 24)
        l1 = QLabel("Subscription Name"); l1.setStyleSheet(f"color: {self.theme.on_surface}; font-weight: bold;"); v.addWidget(l1)
        name_in = QLineEdit(); name_in.setStyleSheet(f"background: {self.theme.surface_variant}; color: white; padding: 10px; border-radius: 12px; border: none;"); v.addWidget(name_in)
        l2 = QLabel("Subscription URL"); l2.setStyleSheet(l1.styleSheet()); v.addWidget(l2); url_in = QLineEdit(); url_in.setStyleSheet(name_in.styleSheet()); v.addWidget(url_in)
        btn_lay = QHBoxLayout(); add = QPushButton("Add"); add.setStyleSheet(self.theme.get_button_style("filled")); add.clicked.connect(d.accept); can = QPushButton("Cancel"); can.setStyleSheet(self.theme.get_button_style("text")); can.clicked.connect(d.reject)
        btn_lay.addWidget(can); btn_lay.addStretch(); btn_lay.addWidget(add); v.addLayout(btn_lay)
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

    def on_status_changed(self, msg, err):
        if self.ss_client.is_connected and self.current_geo: self.status_label.setText(f"{self.current_geo['flag']} {self.current_geo['ip']}")
        else: self.status_label.setText("Error" if err else ("Connected" if self.ss_client.is_connected else "Disconnected"))
        self.status_label.setStyleSheet(f"color: {self.theme.error if err else self.theme.on_secondary_container}; font-size: 24px; font-weight: bold; background: transparent;")

    def on_connection_state_changed(self, conn):
        for i in range(self.server_layout.count()):
            w = self.server_layout.itemAt(i).widget()
            if isinstance(w, ServerItem): w.radio.update()

    def background_fetch_geo(self, host):
        info = fetch_geo_info(host); 
        if info: self.geoInfoReady.emit(info)

    @Slot(dict)
    def update_geo_ui(self, info):
        self.current_geo = info
        if self.ss_client.is_connected: self.status_label.setText(f"{info['flag']} {info['ip']}")

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
        return {"local_port": "1080", "auto_connect": False}
    def save_settings(self):
        with open(self.settings_file, 'w') as f: json.dump(self.settings, f)
    def show_settings_dialog(self):
        d = SettingsDialog(self, self.theme, self.ss_client.local_port, self.settings.get("auto_connect", False))
        if d.exec() == QDialog.Accepted:
            s = d.get_settings(); self.settings.update(s); self.ss_client.local_port = s["local_port"]; self.save_settings()
    def on_checkbox_toggled(self, button, checked):
        if checked and self.ss_client.is_connected:
            self.toggle_connection(False); QTimer.singleShot(500, lambda: self.toggle_connection(True))
    def update_ping(self):
        if self.ss_client.is_connected:
            p = http_ping_via_socks5_once('google.com', int(self.ss_client.local_port)); self.ping_label.setText(f"Ping: {p:.0f} ms" if p else "Ping: Error")
    def add_log(self, msg): self.log_dialog.add_log(f"[{time.strftime('%H:%M:%S')}] {msg}")
    def show_log_dialog(self): self.log_dialog.show()
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 60:
            self._dragging = True; self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._dragging: self.move(e.globalPosition().toPoint() - self._drag_pos)
    def mouseReleaseEvent(self, e): self._dragging = False
