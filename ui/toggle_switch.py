from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, QRect, QPointF
from PySide6.QtGui import QPainter, QBrush, QColor

class AnimatedToggleSwitch(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 32) # M3 Switch dimensions
        self._enabled = False
        self._thumb_position = 4.0
        self._animation = QPropertyAnimation(self, b"thumbPosition")
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Colors (M3 Dark)
        track_on = QColor("#D0BCFF")
        track_off = QColor("#49454F")
        thumb_on = QColor("#381E72")
        thumb_off = QColor("#938F99")
        
        # Draw track
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(track_on if self._enabled else track_off))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 16, 16)
        
        # Draw thumb
        thumb_size = 24 if self._enabled else 16
        thumb_y = (self.height() - thumb_size) / 2
        
        p.setBrush(QBrush(thumb_on if self._enabled else thumb_off))
        p.drawEllipse(QRect(int(self._thumb_position), int(thumb_y), thumb_size, thumb_size))
            
    def toggle(self, enable=None):
        if enable is not None:
            if self._enabled == enable: return
            self._enabled = enable
        else:
            self._enabled = not self._enabled
            
        # Target positions
        end_pos = 24.0 if self._enabled else 4.0
        
        self._animation.stop()
        self._animation.setEndValue(end_pos)
        self._animation.start()
        
    def getThumbPosition(self): return self._thumb_position
    def setThumbPosition(self, pos):
        self._thumb_position = pos
        self.update()
        
    thumbPosition = Property(float, getThumbPosition, setThumbPosition)
