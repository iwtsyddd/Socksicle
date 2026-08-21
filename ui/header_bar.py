from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal


class HeaderBar(QWidget):
    minimizeRequested = Signal()
    closeRequested = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._setup_ui()

    def _setup_ui(self):
        header = QHBoxLayout(self)
        header.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("Socksicle")
        self.title_label.setFocusPolicy(Qt.NoFocus)
        self.title_label.setStyleSheet(
            f"color: {self.theme.on_surface}; font-size: 22px; font-weight: 600; "
            f"border: none; background: transparent; outline: none;")
        header.addWidget(self.title_label)
        header.addStretch()

        hover_bg = getattr(self.theme, 'surface_container_highest', self.theme.surface_variant)
        btn_style = (
            f"QPushButton {{ color: white; background: transparent;"
            f" border-radius: 18px; border: none; outline: none; }}"
            f" QPushButton:hover {{ background: {hover_bg}; }}")

        self.min_btn = QPushButton("—")
        self.min_btn.setFocusPolicy(Qt.NoFocus)
        self.min_btn.setFixedSize(36, 36)
        self.min_btn.setStyleSheet(btn_style)
        self.min_btn.clicked.connect(self.minimizeRequested)
        header.addWidget(self.min_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setFixedSize(36, 36)
        self.close_btn.setStyleSheet(btn_style)
        self.close_btn.clicked.connect(self.closeRequested)
        header.addWidget(self.close_btn)

    def apply_theme(self, theme):
        self.theme = theme
        self.title_label.setStyleSheet(
            f"color: {self.theme.on_surface}; font-size: 22px; font-weight: 600; "
            f"border: none; background: transparent; outline: none;")
        hover_bg = getattr(self.theme, 'surface_container_highest', self.theme.surface_variant)
        btn_style = (
            f"QPushButton {{ color: white; background: transparent;"
            f" border-radius: 18px; border: none; outline: none; }}"
            f" QPushButton:hover {{ background: {hover_bg}; }}")
        self.min_btn.setStyleSheet(btn_style)
        self.close_btn.setStyleSheet(btn_style)
