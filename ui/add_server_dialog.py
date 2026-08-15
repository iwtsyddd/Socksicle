from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QFrame
from PySide6.QtCore import Qt

from utils.server_model import ProxyProtocol


_PROTOCOL_HINTS = {
    "ss://": "Shadowsocks",
    "vless://": "VLESS",
    "vmess://": "VMess",
    "tws2://": "TwinSock Share",
    "https://": "Subscription URL",
    "http://": "Subscription URL",
}


class AddServerDialog(QDialog):

    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self.theme = theme
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
            QLabel {{ color: {theme.on_surface}; font-size: 14px; margin-bottom: 8px; border: none; }}
            QLineEdit {{
                background-color: {theme.surface_variant};
                color: {theme.on_surface};
                border: none;
                border-radius: 12px;
                padding: 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                background-color: rgba(255, 255, 255, 0.05);
            }}
        """)
        self.main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Add Server")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; margin-bottom: 16px; color: {theme.on_surface};")
        layout.addWidget(title)

        layout.addWidget(QLabel("Paste ss://, vless://, vmess://, subscription URL or tws2://"))
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("ss://... / vless://... / vmess://... / https://... / tws2://...")
        self.input_field.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.input_field)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet(f"color: {theme.on_surface_variant}; font-size: 11px; margin-top: 2px; border: none; background: transparent;")
        layout.addWidget(self.hint_label)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 16, 0, 0)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.primary}; background: transparent; padding: 10px; font-weight: 500; border: none;
            }}
            QPushButton:hover {{ background: rgba(208, 188, 255, 0.1); border-radius: 20px; }}
        """)
        self.cancel_button.clicked.connect(self.reject)

        self.add_button = QPushButton("Add")
        self.add_button.setStyleSheet(theme.get_button_style("filled"))
        self.add_button.clicked.connect(self.accept)

        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.add_button)
        layout.addLayout(button_layout)

    def _on_text_changed(self, text):
        text = text.strip().lower()
        detected = None
        for prefix, label in _PROTOCOL_HINTS.items():
            if text.startswith(prefix):
                detected = label
                break
        if detected:
            self.hint_label.setText(f"Detected: {detected}")
            self.hint_label.setStyleSheet(
                f"color: {self.theme.primary}; font-size: 11px; font-weight: bold; "
                f"margin-top: 2px; border: none; background: transparent;"
            )
        else:
            self.hint_label.setText("")
            self.hint_label.setStyleSheet(
                f"color: {self.theme.on_surface_variant}; font-size: 11px; "
                f"margin-top: 2px; border: none; background: transparent;"
            )

    def get_server_key(self): return self.input_field.text().strip()
