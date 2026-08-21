from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, Property, QRectF, QTimer
from PySide6.QtGui import QPainter, QBrush, QColor


class TabBar(QWidget):
    """Segmented subscription/group tab bar with a smooth sliding indicator pill."""

    tabChanged = Signal(str)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(48)
        self._tabs_layout = QHBoxLayout(self)
        self._tabs_layout.setContentsMargins(0, 8, 0, 8)
        self._tabs_layout.setSpacing(8)
        self._current_tab = None
        self._tab_names = []
        self._buttons = {}
        self._indicator_rect = QRectF(0, 0, 0, 0)
        self._animation = QPropertyAnimation(self, b"indicatorRect")
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    def getIndicatorRect(self) -> QRectF:
        return self._indicator_rect

    def setIndicatorRect(self, rect: QRectF):
        self._indicator_rect = rect
        self.update()

    indicatorRect = Property(QRectF, getIndicatorRect, setIndicatorRect)

    def set_tabs(self, tab_names, active_tab, animated=True):
        if list(tab_names) == self._tab_names and self._buttons:
            self.set_active_tab(active_tab, animated=animated)
            return

        self._tab_names = list(tab_names)
        self._current_tab = active_tab
        self._buttons.clear()

        while self._tabs_layout.count():
            item = self._tabs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for name in tab_names:
            btn = QPushButton(name, self)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda checked=False, n=name: self._on_btn_clicked(n))
            self._tabs_layout.addWidget(btn)
            self._buttons[name] = btn

        self._tabs_layout.addStretch()
        self._update_button_styles()

        # Update indicator geometry once layout has placed widgets
        QTimer.singleShot(0, lambda: self.set_active_tab(active_tab, animated=False))

    def _on_btn_clicked(self, name):
        if self._current_tab != name:
            self.set_active_tab(name, animated=True)
            self.tabChanged.emit(name)

    def set_active_tab(self, active_tab, animated=True):
        self._current_tab = active_tab
        self._update_button_styles()

        btn = self._buttons.get(active_tab)
        if not btn:
            return

        target_rect = QRectF(float(btn.x()), float(btn.y()), float(btn.width()), float(btn.height()))
        if target_rect.width() <= 0:
            QTimer.singleShot(10, lambda: self.set_active_tab(active_tab, animated=False))
            return

        if not animated or self._indicator_rect.isEmpty() or self._indicator_rect.width() <= 0:
            self._animation.stop()
            self._indicator_rect = target_rect
            self.update()
            return

        if abs(self._indicator_rect.x() - target_rect.x()) < 0.5 and abs(self._indicator_rect.width() - target_rect.width()) < 0.5:
            return

        self._animation.stop()
        self._animation.setStartValue(self._indicator_rect)
        self._animation.setEndValue(target_rect)
        self._animation.start()

    def _update_button_styles(self):
        active_fg = getattr(self.theme, "on_primary_container", self.theme.on_primary)
        inactive_fg = self.theme.on_surface_variant
        hover_color = "rgba(255, 255, 255, 0.08)"

        for name, btn in self._buttons.items():
            if name == self._current_tab:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        color: {active_fg};
                        background-color: transparent;
                        border-radius: 16px;
                        font-weight: 700;
                        font-size: 13px;
                        padding: 0px 18px;
                        border: none;
                        outline: none;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        color: {inactive_fg};
                        background-color: transparent;
                        border-radius: 16px;
                        font-weight: 600;
                        font-size: 13px;
                        padding: 0px 14px;
                        border: none;
                        outline: none;
                    }}
                    QPushButton:hover {{
                        background-color: {hover_color};
                        color: {self.theme.on_surface};
                    }}
                """)

    def paintEvent(self, event):
        if not self._indicator_rect.isEmpty() and self._indicator_rect.width() > 0:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            bg = getattr(self.theme, "primary_container", self.theme.primary)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(bg)))
            p.drawRoundedRect(self._indicator_rect, 16.0, 16.0)
        super().paintEvent(event)

    def apply_theme(self, theme):
        self.theme = theme
        self._update_button_styles()
        self.update()
