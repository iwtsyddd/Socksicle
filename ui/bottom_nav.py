from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, Signal


class BottomNav(QWidget):
    settingsRequested = Signal()
    logsRequested = Signal()
    aboutRequested = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._setup_ui()

    def _setup_ui(self):
        nav = QHBoxLayout(self)
        nav.setContentsMargins(0, 0, 0, 0)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setFocusPolicy(Qt.NoFocus)
        self.settings_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.settings_btn.clicked.connect(self.settingsRequested)
        nav.addWidget(self.settings_btn)

        nav.addStretch()

        self.logs_btn = QPushButton("Logs")
        self.logs_btn.setFocusPolicy(Qt.NoFocus)
        self.logs_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.logs_btn.clicked.connect(self.logsRequested)
        nav.addWidget(self.logs_btn)

        self.about_btn = QPushButton("About")
        self.about_btn.setFocusPolicy(Qt.NoFocus)
        self.about_btn.setStyleSheet(self.theme.get_button_style("text"))
        self.about_btn.clicked.connect(self.aboutRequested)
        nav.addWidget(self.about_btn)

    def apply_theme(self, theme):
        self.theme = theme
        btn_style = self.theme.get_button_style("text")
        self.settings_btn.setStyleSheet(btn_style)
        self.logs_btn.setStyleSheet(btn_style)
        self.about_btn.setStyleSheet(btn_style)
