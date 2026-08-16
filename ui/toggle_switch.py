from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, QRectF
from PySide6.QtGui import QPainter, QBrush, QColor, QPen


class AnimatedToggleSwitch(QWidget):
    """Material 3 (Material You) Toggle Switch."""

    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(52, 32)
        self._enabled = False
        self._thumb_position = 4.0
        self._animation = QPropertyAnimation(self, b"thumbPosition")
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Dynamic Theme Colors
        if self.theme:
            track_on = QColor(self.theme.primary)
            track_off = QColor(self.theme.surface_container_highest)
            thumb_on = QColor(self.theme.on_primary)
            thumb_off = QColor(self.theme.outline)
            track_border = QColor(self.theme.outline)
        else:
            track_on = QColor("#D0BCFF")
            track_off = QColor("#36343B")
            thumb_on = QColor("#381E72")
            thumb_off = QColor("#938F99")
            track_border = QColor("#938F99")

        # Draw Track
        if self._enabled:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(track_on))
        else:
            p.setPen(QPen(track_border, 1.5))
            p.setBrush(QBrush(track_off))

        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 15, 15)

        # Draw Thumb
        thumb_size = 24 if self._enabled else 16
        thumb_y = (self.height() - thumb_size) / 2

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(thumb_on if self._enabled else thumb_off))
        p.drawEllipse(QRectF(self._thumb_position, thumb_y, thumb_size, thumb_size))

    def toggle(self, enable=None):
        if enable is not None:
            if self._enabled == enable:
                return
            self._enabled = enable
        else:
            self._enabled = not self._enabled

        end_pos = 24.0 if self._enabled else 4.0

        self._animation.stop()
        self._animation.setEndValue(end_pos)
        self._animation.start()

    def getThumbPosition(self):
        return self._thumb_position

    def setThumbPosition(self, pos):
        self._thumb_position = pos
        self.update()

    thumbPosition = Property(float, getThumbPosition, setThumbPosition)

