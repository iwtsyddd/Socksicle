import base64
import secrets

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QLineEdit, QSpinBox, QCheckBox, QFormLayout, QFrame,
    QComboBox, QScrollArea, QWidget, QMessageBox
)
from PySide6.QtCore import Qt

from utils.platform_startup import is_autostart_enabled
from utils.platform_utils import is_admin, is_windows
from utils.sub_manager import USER_AGENT_PRESETS
from utils.window_utils import configure_window
from utils.engines.base import DEFAULT_LOCAL_PORT
from utils.ping import DEFAULT_PING_METHOD
from utils.theme import THEME_PRESETS


ENGINE_LABELS = {
    "sslocal": "Shadowsocks (sslocal)",
    "xray": "Xray-core",
    "sing-box": "sing-box",
}

PING_METHOD_LABELS = {
    "http_get": "HTTP GET",
    "http_head": "HTTP HEAD",
    "tcp_connect": "TCP connect",
}

DNS_PRESETS = {
    "default": ("System / Core Default (Auto)", ""),
    "cloudflare": ("Cloudflare DoH (1.1.1.1)", "https://1.1.1.1/dns-query"),
    "quad9": ("Quad9 DoH (Security / Anti-Malware)", "https://dns.quad9.net/dns-query"),
    "adguard": ("AdGuard DoH (AdBlock & Privacy)", "https://dns.adguard-dns.com/dns-query"),
    "google": ("Google DoH (8.8.8.8)", "https://dns.google/dns-query"),
    "custom": ("Custom DNS (DoH / DoT)...", ""),
}


class SettingsDialog(QDialog):
    def __init__(self, parent=None, theme=None, current_port=None,
                 auto_connect=False, current_engine="sslocal"):
        super().__init__(parent)
        self.theme = theme
        self._dragging = False
        self._drag_pos = None
        current_port = current_port or str(DEFAULT_LOCAL_PORT)

        # Standalone frameless window with independent taskbar presence (the translucent
        # background is applied by configure_window only when the session can composite).
        self.setWindowFlags(Qt.Window)
        configure_window(self)
        self.resize(480, 680)
        self.setMinimumSize(420, 520)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)

        self.container = QFrame()
        self.container.setObjectName("SettingsContainer")

        combo_bg = getattr(theme, "surface_container_highest", theme.surface_variant)
        combo_border = getattr(theme, "outline_variant", "#44424B")
        popup_bg = getattr(theme, "surface_container_high", theme.surface)

        self.container.setStyleSheet(f"""
            QFrame#SettingsContainer {{
                background-color: {theme.surface};
                border-radius: 28px;
                border: none;
            }}
            QLabel {{ color: {theme.on_surface}; border: none; font-size: 14px; outline: none; }}
            QSpinBox {{
                background-color: {getattr(theme, 'surface_container_highest', theme.surface_variant)};
                color: {theme.on_surface};
                border: 1px solid {getattr(theme, 'outline_variant', '#44424B')};
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 13px;
                outline: none;
            }}
            QSpinBox:focus {{
                border: 1px solid {theme.primary};
            }}
            QComboBox {{
                background-color: {combo_bg};
                color: {theme.on_surface};
                border: 1px solid {combo_border};
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 13px;
                outline: none;
            }}
            QComboBox:hover {{
                border-color: {theme.outline};
            }}
            QComboBox:focus {{
                border: 1px solid {theme.primary};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                background-color: {combo_bg};
                border: none;
                border-left: 1px solid {combo_border};
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
            }}
            QComboBox::drop-down:hover {{
                background-color: {combo_bg};
                border-left: 1px solid {theme.outline};
            }}
            QComboBox::drop-down:pressed {{
                background-color: {combo_bg};
                border-left: 1px solid {theme.primary};
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {theme.on_surface_variant};
                width: 0px;
                height: 0px;
                margin-right: 8px;
            }}
            QComboBox QFrame {{
                background-color: {popup_bg};
                border: 1px solid {combo_border};
                border-radius: 10px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {popup_bg};
                color: {theme.on_surface};
                border: 1px solid {combo_border};
                border-radius: 10px;
                padding: 4px;
                selection-background-color: {getattr(theme, 'primary_container', theme.primary)};
                selection-color: {getattr(theme, 'on_primary_container', theme.on_primary)};
                outline: none;
            }}
            QLineEdit {{
                background-color: {getattr(theme, 'surface_container_highest', theme.surface_variant)};
                color: {theme.on_surface};
                border: 1px solid {getattr(theme, 'outline_variant', '#44424B')};
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 13px;
                outline: none;
            }}
            QLineEdit:focus {{
                border: 1px solid {theme.primary};
            }}
            QCheckBox {{ color: {theme.on_surface}; border: none; font-size: 14px; outline: none; }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {getattr(theme, 'outline_variant', '#44424B')};
                background: {getattr(theme, 'surface_container_highest', theme.surface_variant)};
            }}
            QCheckBox::indicator:checked {{
                background: {theme.primary};
                border-color: {theme.primary};
            }}
        """)
        self.main_layout.addWidget(self.container)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(20, 16, 20, 20)
        container_layout.setSpacing(12)

        # --- Top Header Bar ---
        header_layout = QHBoxLayout()
        self.title_label = QLabel("⚙️  Settings")
        self.title_label.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {theme.on_surface}; border: none;"
        )
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                color: {theme.on_surface_variant};
                background: transparent;
                border-radius: 16px;
                border: none;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {theme.surface_variant};
                color: {theme.on_surface};
            }}
        """)
        close_btn.clicked.connect(self.reject)
        header_layout.addWidget(close_btn)
        container_layout.addLayout(header_layout)

        # --- Scrollable Content Area ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px 0px 0px 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {theme.surface_variant};
                min-height: 24px;
                border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        form_layout = QFormLayout(content_widget)
        form_layout.setContentsMargins(4, 8, 8, 8)
        form_layout.setSpacing(14)

        # --- Theme preset ---
        self.theme_combo = QComboBox()
        for key, label in THEME_PRESETS.items():
            self.theme_combo.addItem(label, key)
        saved_theme = parent.settings.get("theme_preset", "dynamic") if parent else "dynamic"
        theme_keys = list(THEME_PRESETS.keys())
        theme_idx = theme_keys.index(saved_theme) if saved_theme in theme_keys else 0
        self.theme_combo.setCurrentIndex(theme_idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_preset_changed)
        form_layout.addRow("Color theme:", self.theme_combo)

        # --- Engine selection ---
        self.engine_combo = QComboBox()
        for key, label in ENGINE_LABELS.items():
            self.engine_combo.addItem(label, key)
        engine_keys = list(ENGINE_LABELS.keys())
        engine_idx = engine_keys.index(current_engine) if current_engine in engine_keys else 0
        self.engine_combo.setCurrentIndex(engine_idx)
        form_layout.addRow("Proxy engine:", self.engine_combo)

        self.port_input = QSpinBox()
        self.port_input.setRange(1024, 65535)
        self.port_input.setValue(int(current_port))
        form_layout.addRow("Local port:", self.port_input)

        self.auto_connect_check = QCheckBox("Auto-connect on startup")
        self.auto_connect_check.setChecked(auto_connect)
        form_layout.addRow("", self.auto_connect_check)

        autostart_val = parent.settings.get("autostart") if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict) and "autostart" in parent.settings else is_autostart_enabled()
        self.autostart_check = QCheckBox("Start with system (Autostart)")
        self.autostart_check.setChecked(bool(autostart_val))
        form_layout.addRow("", self.autostart_check)

        self.minimize_to_tray_check = QCheckBox("Minimize to tray on close")
        self.minimize_to_tray_check.setChecked(parent.settings.get("minimize_to_tray", True) if parent else True)
        form_layout.addRow("", self.minimize_to_tray_check)

        self.auto_update_check = QCheckBox("Auto-update subscriptions")
        self.auto_update_check.setChecked(parent.settings.get("auto_update_subs", True) if parent else True)
        form_layout.addRow("", self.auto_update_check)

        # --- Subscription User-Agent ---
        ua_label = QLabel("Subscription User-Agent:")
        ua_label.setStyleSheet(f"color: {theme.on_surface}; font-weight: bold; font-size: 13px; margin-top: 6px;")
        form_layout.addRow(ua_label)

        self.ua_combo = QComboBox()
        ua_keys = list(USER_AGENT_PRESETS.keys())
        for key in ua_keys:
            self.ua_combo.addItem(key)
        saved_ua = parent.settings.get("user_agent_key", "socksicle") if parent else "socksicle"
        idx = ua_keys.index(saved_ua) if saved_ua in ua_keys else 0
        self.ua_combo.setCurrentIndex(idx)
        form_layout.addRow("UA preset:", self.ua_combo)

        # --- Custom Secure DNS ---
        dns_label = QLabel("Secure DNS (DoH / DoT):")
        dns_label.setStyleSheet(f"color: {theme.on_surface}; font-weight: bold; font-size: 13px; margin-top: 6px;")
        form_layout.addRow(dns_label)

        self.dns_combo = QComboBox()
        for key, (label, val) in DNS_PRESETS.items():
            self.dns_combo.addItem(label, key)
        saved_dns_preset = parent.settings.get("dns_preset", "default") if parent else "default"
        dns_keys = list(DNS_PRESETS.keys())
        dns_idx = dns_keys.index(saved_dns_preset) if saved_dns_preset in dns_keys else 0
        self.dns_combo.setCurrentIndex(dns_idx)
        self.dns_combo.currentIndexChanged.connect(self._on_dns_preset_changed)
        form_layout.addRow("DNS provider:", self.dns_combo)

        self.custom_dns_input = QLineEdit()
        self.custom_dns_input.setPlaceholderText("https://... or tls://... or 1.1.1.1")
        self.custom_dns_input.setText(parent.settings.get("custom_dns_manual", "") if parent else "")
        self.custom_dns_input.setVisible(saved_dns_preset == "custom")
        form_layout.addRow("Custom DNS:", self.custom_dns_input)

        # --- Ping method ---
        self.ping_method_combo = QComboBox()
        for key, label in PING_METHOD_LABELS.items():
            self.ping_method_combo.addItem(label, key)
        ping_keys = list(PING_METHOD_LABELS.keys())
        saved_method = parent.settings.get("ping_method", DEFAULT_PING_METHOD) if parent else DEFAULT_PING_METHOD
        ping_idx = ping_keys.index(saved_method) if saved_method in ping_keys else 0
        self.ping_method_combo.setCurrentIndex(ping_idx)
        form_layout.addRow("Ping method:", self.ping_method_combo)

        # --- Fake HWID ---
        self.hwid_check = QCheckBox("Send fake X-hwid header")
        self.hwid_check.setChecked(parent.settings.get("fake_hwid", False) if parent else False)
        self.hwid_check.toggled.connect(self._on_hwid_toggled)
        form_layout.addRow("", self.hwid_check)

        self.hwid_input = QLineEdit()
        self.hwid_input.setPlaceholderText("Leave empty for auto-generated HWID")
        self.hwid_input.setText(parent.settings.get("hwid_value", ""))
        self.hwid_input.setVisible(self.hwid_check.isChecked())
        form_layout.addRow("HWID:", self.hwid_input)

        self.is_legacy_tws2 = (
            bool(parent.settings.get("tws2_share_key")) and
            not bool(parent.settings.get("tws3_share_key"))
        ) if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict) else False

        self.tws_key_input = QLineEdit()
        self.tws_key_input.setReadOnly(True)
        self.tws_key_input.setPlaceholderText("Auto-generated on first launch")
        current_tws_key = (
            parent.settings.get("tws3_share_key") or
            parent.settings.get("tws2_share_key", "")
        ) if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict) else ""
        self.tws_key_input.setText(current_tws_key)
        form_layout.addRow("TwinSock key:", self.tws_key_input)

        if self.is_legacy_tws2:
            self.upgrade_tws3_btn = QPushButton("Generate TWS3 Key (Recommended)")
            self.upgrade_tws3_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme.primary};
                    color: #1c1930;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 14px;
                    font-size: 12px;
                    font-weight: bold;
                    margin-top: 4px;
                }}
                QPushButton:hover {{
                    background-color: rgba(187, 134, 252, 0.85);
                }}
            """)
            self.upgrade_tws3_btn.clicked.connect(self._on_upgrade_tws3_clicked)
            form_layout.addRow("", self.upgrade_tws3_btn)
            self.key_hint = QLabel("You are using a legacy v2 key. Generate a v3 key to upgrade to AES-256-GCM AEAD.")
        else:
            self.upgrade_tws3_btn = None
            self.key_hint = QLabel("Personal key that signs and unlocks tws3:// links. Keep it stored securely.")

        self.key_hint.setWordWrap(True)
        self.key_hint.setStyleSheet(f"color: {theme.on_surface_variant}; font-size: 12px;")
        form_layout.addRow("", self.key_hint)

        # --- Beta Features ---
        beta_label = QLabel("Beta Features")
        beta_label.setStyleSheet(f"color: {theme.primary}; font-weight: bold; font-size: 14px; margin-top: 10px;")
        form_layout.addRow(beta_label)

        self.tun_mode_check = QCheckBox("Enable TUN Mode (Global VPN)")
        self.tun_mode_check.setChecked(parent.settings.get("tun_mode", False) if parent else False)
        self.tun_mode_check.toggled.connect(self._on_tun_toggled)
        form_layout.addRow("", self.tun_mode_check)

        self.tun_hint = QLabel(
            "⚠️ TUN Mode routes all system traffic (games, apps, CLI) through the tunnel.\n"
            "• Requires elevated privileges (Windows UAC / Linux Polkit capabilities).\n"
            "• Automatically switches proxy engine to sing-box (sslocal and Xray are disabled in TUN mode)."
        )
        self.tun_hint.setWordWrap(True)
        self.tun_hint.setStyleSheet(f"color: {theme.on_surface_variant}; font-size: 11px; margin-top: 2px;")
        form_layout.addRow("", self.tun_hint)

        self.killswitch_check = QCheckBox("Enable Kill Switch (Beta)")
        self.killswitch_check.setChecked(parent.settings.get("kill_switch", False) if parent else False)
        self.killswitch_check.toggled.connect(self._on_killswitch_toggled)
        form_layout.addRow("", self.killswitch_check)

        self.killswitch_hint = QLabel(
            "🛡️ Blocks all direct internet traffic via OS firewall upon unexpected tunnel drops to prevent real IP leaks.\n"
            "• Local network (LAN) and proxy server endpoints remain accessible.\n"
            "• Requires Administrator privileges on Windows (Windows Defender Firewall rules)."
        )
        self.killswitch_hint.setWordWrap(True)
        self.killswitch_hint.setStyleSheet(f"color: {theme.on_surface_variant}; font-size: 11px; margin-top: 2px;")
        form_layout.addRow("", self.killswitch_hint)

        if self.tun_mode_check.isChecked():
            self._on_tun_toggled(True)

        scroll_area.setWidget(content_widget)
        container_layout.addWidget(scroll_area, 1)

        # --- Bottom Action Bar ---
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 8, 0, 0)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.primary}; background: transparent; padding: 10px 18px; font-weight: 500; border: none;
            }}
            QPushButton:hover {{ background: rgba(208, 188, 255, 0.1); border-radius: 20px; }}
        """)
        self.cancel_button.clicked.connect(self.reject)

        self.save_button = QPushButton("Save")
        self.save_button.setStyleSheet(theme.get_button_style("filled"))
        self.save_button.clicked.connect(self.accept)

        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)
        container_layout.addLayout(button_layout)

    def _on_dns_preset_changed(self, idx):
        preset = self.dns_combo.itemData(idx)
        self.custom_dns_input.setVisible(preset == "custom")

    def _on_killswitch_toggled(self, checked):
        if checked and is_windows() and not is_admin():
            reply = QMessageBox.question(
                self,
                "Administrator Rights Required",
                "Kill Switch requires Administrator privileges to configure Windows Defender Firewall rules.\n\n"
                "Would you like to restart Socksicle with elevated Administrator privileges now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                from utils.platform_utils import elevate_restart
                elevate_restart()
            else:
                self.killswitch_check.setChecked(False)

    def _on_theme_preset_changed(self, idx):
        preset = self.theme_combo.itemData(idx)
        parent = self.parent()
        if preset and parent and hasattr(parent, "theme"):
            parent.theme.apply_theme(preset)
            parent.apply_theme_styles()
            self.theme = parent.theme
            self.save_button.setStyleSheet(self.theme.get_button_style("filled"))

    def _on_hwid_toggled(self, checked):
        self.hwid_input.setVisible(checked)

    def _on_tun_toggled(self, checked):
        if checked:
            idx = self.engine_combo.findData("sing-box")
            if idx >= 0:
                self.engine_combo.setCurrentIndex(idx)
            self.engine_combo.setEnabled(False)
            self.engine_combo.setToolTip("TUN Mode requires sing-box engine")
        else:
            self.engine_combo.setEnabled(True)
            self.engine_combo.setToolTip("")

    def _on_upgrade_tws3_clicked(self):
        new_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        self.tws_key_input.setText(new_key)
        self.is_legacy_tws2 = False
        if self.upgrade_tws3_btn:
            self.upgrade_tws3_btn.hide()
        self.key_hint.setText("Personal key that signs and unlocks tws3:// links. Keep it stored securely.")
        QMessageBox.information(
            self, "TwinSock Key Upgraded",
            "Generated a new TwinSock v3 key.\n\n"
            "Save settings to apply. Remember to share this new key with your peers for tws3:// links."
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 60:
            self._dragging = True
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._dragging and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def get_settings(self):
        engine_val = "sing-box" if self.tun_mode_check.isChecked() else self.engine_combo.currentData()
        dns_preset = self.dns_combo.currentData()
        if dns_preset == "custom":
            custom_dns_val = self.custom_dns_input.text().strip()
        else:
            custom_dns_val = DNS_PRESETS.get(dns_preset, ("", ""))[1]

        res = {
            "engine": engine_val,
            "ping_method": self.ping_method_combo.currentData(),
            "local_port": self.port_input.value(),
            "auto_connect": self.auto_connect_check.isChecked(),
            "autostart": self.autostart_check.isChecked(),
            "minimize_to_tray": self.minimize_to_tray_check.isChecked(),
            "auto_update_subs": self.auto_update_check.isChecked(),
            "user_agent_key": self.ua_combo.currentText(),
            "fake_hwid": self.hwid_check.isChecked(),
            "hwid_value": self.hwid_input.text().strip(),
            "tun_mode": self.tun_mode_check.isChecked(),
            "kill_switch": self.killswitch_check.isChecked(),
            "dns_preset": dns_preset,
            "custom_dns_manual": self.custom_dns_input.text().strip(),
            "custom_dns": custom_dns_val,
            "theme_preset": self.theme_combo.currentData(),
        }
        if self.is_legacy_tws2:
            res["tws2_share_key"] = self.tws_key_input.text().strip()
        else:
            res["tws3_share_key"] = self.tws_key_input.text().strip()
        return res
