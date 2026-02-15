from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

class AboutDialog(QDialog):
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
        """)
        self.main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 24)
        
        title = QLabel("Socksicle")
        title.setStyleSheet(f"font-size: 24px; font-weight: 700; color: {theme.primary};")
        title.setAlignment(Qt.AlignCenter)
        
        desc = QLabel("A modern, beautiful Shadowsocks GUI client for Linux, built with PySide6 and Material Design 3.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 14px; color: {theme.on_surface};")
        desc.setAlignment(Qt.AlignCenter)
        
        # Clickable GitHub link
        github_link = QLabel(f'<a href="https://github.com/iwtsyddd/Socksicle" style="color: {theme.primary}; text-decoration: none;">View on GitHub</a>')
        github_link.setOpenExternalLinks(True)
        github_link.setAlignment(Qt.AlignCenter)
        
        close_button = QPushButton("Close")
        close_button.setStyleSheet(theme.get_button_style("filled"))
        close_button.clicked.connect(self.accept)
        
        layout.addWidget(title)
        layout.addSpacing(12)
        layout.addWidget(desc)
        layout.addSpacing(16)
        layout.addWidget(github_link)
        layout.addSpacing(24)
        layout.addWidget(close_button)
