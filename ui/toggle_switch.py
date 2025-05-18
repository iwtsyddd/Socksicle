from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QRect
from PyQt5.QtGui import QPainter, QBrush, QColor

class AnimatedToggleSwitch(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 24)
        self._enabled = False
        self._thumb_position = 4.0
        self._animation = QPropertyAnimation(self, b"thumbPosition")
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.InOutQuad)
        
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Draw track
        track_brush = QBrush(QColor("#7b61ff") if self._enabled else QColor("#555"))
        p.setPen(Qt.NoPen)
        p.setBrush(track_brush)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        
        # Draw thumb - using QRect to fix any type issues
        thumb_size = self.height() - 4
        thumb_rect = QRect(int(self._thumb_position), 2, thumb_size, thumb_size)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(thumb_rect)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle()
            
    def toggle(self, enable=None):
        if enable is not None:
            if self._enabled == enable:
                return
            self._enabled = enable
        else:
            self._enabled = not self._enabled
            
        end_pos = float(self.width() - self.height() + 2) if self._enabled else 4.0
        
        self._animation.stop()
        self._animation.setStartValue(self._thumb_position)
        self._animation.setEndValue(end_pos)
        self._animation.start()
        
    def thumbPosition(self):
        return self._thumb_position
        
    def setThumbPosition(self, pos):
        self._thumb_position = pos
        self.update()
        
    thumbPosition = pyqtProperty(float, thumbPosition, setThumbPosition)
    
    def isEnabled(self):
        return self._enabled