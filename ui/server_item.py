from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtGui import QColor, QPainter, QBrush, QFont, QPen
from PyQt5.QtWidgets import QCheckBox

class AnimatedCheckBox(QCheckBox):
    def __init__(self, text, server_data=None, parent=None):
        super().__init__(text, parent)
        
        # Store server data
        self.server_data = server_data or {}
        
        # Colors
        self._bg_color = QColor(30, 30, 30)
        self._hover_color = QColor(40, 40, 40)
        self._active_color = QColor(68, 68, 68)
        self._indicator_color = QColor(123, 97, 255)  # Purple color
        
        # State tracking
        self._is_hovered = False
        self._slide_offset = 0.0
        
        # Animations
        self._bg_anim = QPropertyAnimation(self, b"bgColor")
        self._bg_anim.setDuration(150)
        self._bg_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._slide_anim = QPropertyAnimation(self, b"slideOffset")
        self._slide_anim.setDuration(300)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # Connect signals
        self.toggled.connect(self.on_toggle_changed)
        
        # Style
        self.setFont(QFont("Arial", 12))
        self.setFixedHeight(34)
        
        # Remove the default QCheckBox indicator
        self.setStyleSheet("""
            QCheckBox::indicator {
                width: 0px;
                height: 0px;
            }
        """)
        
        # Set minimum width to ensure proper display of delete button
        self.setMinimumWidth(200)

    def enterEvent(self, event):
        self._is_hovered = True
        if not self.isChecked():
            self.start_hover_anim()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self._is_hovered = False
        if not self.isChecked():
            self.start_hover_anim()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Draw background
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._bg_color))
        p.drawRoundedRect(self.rect(), 6, 6)
        
        # Draw slide indicator if checked
        if self.isChecked():
            p.setBrush(QBrush(self._indicator_color))
            indicator_height = 4
            indicator_width = self.width() - 12
            
            # Draw with offset for animation
            p.drawRoundedRect(
                6 + int(self._slide_offset),
                self.height() - indicator_height - 2,
                indicator_width,
                indicator_height,
                2, 2
            )
        
        # Draw text
        p.setPen(QColor(255, 255, 255))
        p.setFont(self.font())
        p.drawText(
            12, 
            (self.height() + p.fontMetrics().ascent() - p.fontMetrics().descent()) // 2,
            self.text()
        )

    def start_hover_anim(self):
        start = self._bg_color
        end = self._hover_color if self._is_hovered else QColor(30, 30, 30)
        self._bg_anim.stop()
        self._bg_anim.setStartValue(start)
        self._bg_anim.setEndValue(end)
        self._bg_anim.start()

    def on_toggle_changed(self, checked):
        # Background color animation
        start = self._bg_color
        end = self._active_color if checked else (self._hover_color if self._is_hovered else QColor(30, 30, 30))
        self._bg_anim.stop()
        self._bg_anim.setStartValue(start)
        self._bg_anim.setEndValue(end)
        self._bg_anim.start()
        
        # Slide indicator animation for checked state
        if checked:
            self._slide_anim.stop()
            self._slide_anim.setStartValue(-self.width())
            self._slide_anim.setEndValue(0)
            self._slide_anim.start()

    def getBgColor(self):
        return self._bg_color

    def setBgColor(self, c):
        self._bg_color = c
        self.update()

    def getSlideOffset(self):
        return self._slide_offset
        
    def setSlideOffset(self, offset):
        self._slide_offset = offset
        self.update()

    bgColor = pyqtProperty(QColor, getBgColor, setBgColor)
    slideOffset = pyqtProperty(float, getSlideOffset, setSlideOffset)


class ServerItem(QWidget):
    def __init__(self, text, server_data=None, parent=None):
        super().__init__(parent)
        self.server_data = server_data or {}
        
        # Set up layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create checkbox for server selection
        self.checkbox = AnimatedCheckBox(text, server_data)
        layout.addWidget(self.checkbox)
        
        # Add spacer to push delete button to the right
        layout.addStretch()
        
        # Status indicator
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: #666; margin-right: 5px;")
        self.status_indicator.setFixedWidth(20)
        self.status_indicator.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_indicator)
        
        # Create delete button
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setFixedSize(28, 28)
        self.delete_button.setStyleSheet("""
            QPushButton {
                color: #aaa;
                background: transparent;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                color: white;
                background: rgba(255, 0, 0, 0.2);
            }
            QPushButton:pressed {
                background: rgba(255, 0, 0, 0.4);
            }
        """)
        layout.addWidget(self.delete_button)
        
        # Set fixed height for consistent look
        self.setFixedHeight(34)
    
    def set_status(self, connected=False):
        """Update the status indicator based on connection state"""
        if connected:
            self.status_indicator.setStyleSheet("color: #4CAF50; margin-right: 5px;")  # Green
        else:
            self.status_indicator.setStyleSheet("color: #666; margin-right: 5px;")  # Gray
        
    def set_error(self):
        """Set status indicator to error state"""
        self.status_indicator.setStyleSheet("color: #F44336; margin-right: 5px;")  # Red