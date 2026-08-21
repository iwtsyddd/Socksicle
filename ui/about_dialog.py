from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame)
from PySide6.QtCore import Qt

from utils.window_utils import configure_window


class AboutDialog(QDialog):
    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowFlags(Qt.Dialog)
        configure_window(self)

        self.main_layout = QVBoxLayout(self)
        self.container = QFrame()
        self.main_layout.addWidget(self.container)

        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(24, 24, 24, 24)

        self.title = QLabel("Socksicle v1.5")
        self.title.setAlignment(Qt.AlignCenter)

        self.desc = QLabel(
            "A modern, high-performance proxy client (Shadowsocks, VLESS, VMess, Hysteria 2) "
            "with Material You (M3) dynamic theming and TUN mode."
        )
        self.desc.setWordWrap(True)
        self.desc.setAlignment(Qt.AlignCenter)

        self.github_link = QLabel()
        self.github_link.setOpenExternalLinks(True)
        self.github_link.setAlignment(Qt.AlignCenter)

        self.close_button = QPushButton("Close")
        self.close_button.setFocusPolicy(Qt.NoFocus)
        self.close_button.clicked.connect(self.accept)

        self.layout.addWidget(self.title)
        self.layout.addSpacing(12)
        self.layout.addWidget(self.desc)
        self.layout.addSpacing(16)
        self.layout.addWidget(self.github_link)
        self.layout.addSpacing(24)
        self.layout.addWidget(self.close_button)

        if theme:
            self.set_theme(theme)

    def set_theme(self, theme):
        self.theme = theme
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {theme.surface};
                border-radius: 28px;
                border: none;
                outline: none;
            }}
        """)
        self.title.setStyleSheet(f"font-size: 24px; font-weight: 700; color: {theme.primary}; border: none; outline: none;")
        self.desc.setStyleSheet(f"font-size: 13px; color: {theme.on_surface}; border: none; outline: none;")
        self.github_link.setText(
            f'<a href="https://github.com/iwtsyddd/Socksicle" style="color: {theme.primary}; text-decoration: none;">View on GitHub</a>'
        )
        self.close_button.setStyleSheet(theme.get_button_style("filled"))

