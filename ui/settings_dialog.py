from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                           QHBoxLayout, QLineEdit, QSpinBox, QCheckBox,
                           QFormLayout, QGroupBox, QFrame, QComboBox)
from PySide6.QtCore import Qt

from utils.sub_manager import USER_AGENT_PRESETS
from utils.engines.base import DEFAULT_LOCAL_PORT
from utils.ping import DEFAULT_PING_METHOD


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


class SettingsDialog(QDialog):
    def __init__(self, parent=None, theme=None, current_port=None,
                 auto_connect=False, current_engine="sslocal"):
        super().__init__(parent)
        self.theme = theme
        current_port = current_port or str(DEFAULT_LOCAL_PORT)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.main_layout = QVBoxLayout(self)
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {theme.surface};
                border-radius: 28px;
                border: none;
            }}
            QLabel {{ color: {theme.on_surface}; border: none; font-size: 14px; }}
            QSpinBox {{
                background-color: {theme.surface_variant};
                color: {theme.on_surface}; border-radius: 8px; padding: 8px; border: none;
            }}
            QComboBox {{
                background-color: {theme.surface_variant};
                color: {theme.on_surface}; border-radius: 8px; padding: 8px; border: none;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme.surface};
                color: {theme.on_surface};
                border: 1px solid {theme.surface_variant};
                border-radius: 8px;
                selection-background-color: {theme.primary};
            }}
            QLineEdit {{
                background-color: {theme.surface_variant};
                color: {theme.on_surface}; border-radius: 8px; padding: 8px; border: none;
            }}
            QCheckBox {{ color: {theme.on_surface}; border: none; font-size: 14px; }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: none;
                background: {theme.surface_variant};
            }}
            QCheckBox::indicator:checked {{
                background: {theme.primary};
            }}
        """)
        self.main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Settings")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; margin-bottom: 16px; color: {theme.on_surface};")
        layout.addWidget(title)

        form_layout = QFormLayout()
        form_layout.setSpacing(16)

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

        self.minimize_to_tray_check = QCheckBox("Minimize to tray on close")
        self.minimize_to_tray_check.setChecked(parent.settings.get("minimize_to_tray", True))
        form_layout.addRow("", self.minimize_to_tray_check)

        self.auto_update_check = QCheckBox("Auto-update subscriptions")
        self.auto_update_check.setChecked(parent.settings.get("auto_update_subs", True))
        form_layout.addRow("", self.auto_update_check)

        # --- Subscription User-Agent ---
        ua_label = QLabel("Subscription User-Agent:")
        ua_label.setStyleSheet(f"color: {theme.on_surface}; font-weight: bold; font-size: 13px; margin-top: 8px;")
        form_layout.addRow(ua_label)

        self.ua_combo = QComboBox()
        ua_keys = list(USER_AGENT_PRESETS.keys())
        for key in ua_keys:
            self.ua_combo.addItem(key)
        saved_ua = parent.settings.get("user_agent_key", "socksicle")
        idx = ua_keys.index(saved_ua) if saved_ua in ua_keys else 0
        self.ua_combo.setCurrentIndex(idx)
        form_layout.addRow("UA preset:", self.ua_combo)

        # --- Ping method ---
        self.ping_method_combo = QComboBox()
        for key, label in PING_METHOD_LABELS.items():
            self.ping_method_combo.addItem(label, key)
        ping_keys = list(PING_METHOD_LABELS.keys())
        saved_method = parent.settings.get("ping_method", DEFAULT_PING_METHOD)
        ping_idx = ping_keys.index(saved_method) if saved_method in ping_keys else 0
        self.ping_method_combo.setCurrentIndex(ping_idx)
        form_layout.addRow("Ping method:", self.ping_method_combo)

        # --- Fake HWID ---
        self.hwid_check = QCheckBox("Send fake X-hwid header")
        self.hwid_check.setChecked(parent.settings.get("fake_hwid", False))
        self.hwid_check.toggled.connect(self._on_hwid_toggled)
        form_layout.addRow("", self.hwid_check)

        self.hwid_input = QLineEdit()
        self.hwid_input.setPlaceholderText("Leave empty for auto-generated HWID")
        self.hwid_input.setText(parent.settings.get("hwid_value", ""))
        self.hwid_input.setVisible(self.hwid_check.isChecked())
        form_layout.addRow("HWID:", self.hwid_input)

        self.tws2_key_input = QLineEdit()
        self.tws2_key_input.setReadOnly(True)
        self.tws2_key_input.setPlaceholderText("Auto-generated on first launch")
        self.tws2_key_input.setText(parent.settings.get("tws2_share_key", ""))
        form_layout.addRow("TwinSock key:", self.tws2_key_input)

        key_hint = QLabel("Personal key that signs and unlocks tws2:// links. Keep it stored securely.")
        key_hint.setWordWrap(True)
        key_hint.setStyleSheet(f"color: {theme.on_surface_variant}; font-size: 12px;")
        form_layout.addRow("", key_hint)

        layout.addLayout(form_layout)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 24, 0, 0)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.primary}; background: transparent; padding: 10px; font-weight: 500; border: none;
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
        layout.addLayout(button_layout)

    def _on_hwid_toggled(self, checked):
        self.hwid_input.setVisible(checked)

    def get_settings(self):
        return {
            "engine": self.engine_combo.currentData(),
            "ping_method": self.ping_method_combo.currentData(),
            "local_port": self.port_input.value(),
            "auto_connect": self.auto_connect_check.isChecked(),
            "minimize_to_tray": self.minimize_to_tray_check.isChecked(),
            "auto_update_subs": self.auto_update_check.isChecked(),
            "user_agent_key": self.ua_combo.currentText(),
            "fake_hwid": self.hwid_check.isChecked(),
            "hwid_value": self.hwid_input.text().strip(),
            "tws2_share_key": self.tws2_key_input.text().strip(),
        }
