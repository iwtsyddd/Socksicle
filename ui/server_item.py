from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QRadioButton, QFrame, QSizePolicy, QDialog
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, QEvent
from PySide6.QtGui import QColor, QPainter, QBrush, QFont, QPen, QPixmap, QImage
import qrcode

class AnimatedRadioButton(QRadioButton):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._bg_color = QColor(theme.surface_variant)
        self._bg_anim = QPropertyAnimation(self, b"bgColor")
        self._bg_anim.setDuration(250)
        self._bg_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("QRadioButton { border: none; background: transparent; } QRadioButton::indicator { width: 0px; height: 0px; }")

    def enterEvent(self, event):
        base = QColor(self.theme.surface_variant)
        hover_color = base.lighter(110) if not self.isChecked() else base.darker(120).lighter(110)
        self._animate_bg(hover_color)
        super().enterEvent(event)

    def leaveEvent(self, event):
        base = QColor(self.theme.surface_variant)
        normal_color = base if not self.isChecked() else base.darker(115)
        self._animate_bg(normal_color)
        super().leaveEvent(event)

    def _animate_bg(self, target_color):
        self._bg_anim.stop(); self._bg_anim.setEndValue(target_color); self._bg_anim.start()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen); p.setBrush(QBrush(self._bg_color))
        p.drawRoundedRect(self.rect(), 16, 16)
        if self.isChecked():
            p.setBrush(QBrush(QColor(self.theme.primary))); p.drawRoundedRect(0, 12, 4, 32, 2, 2)
        p.setPen(QColor(self.theme.on_surface) if not self.isChecked() else QColor(self.theme.primary))
        font = QFont("Arial", 11); font.setBold(self.isChecked()); p.setFont(font)
        p.drawText(24, 0, self.width() - 120, self.height(), Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def getBgColor(self): return self._bg_color
    def setBgColor(self, c): self._bg_color = c; self.update()
    bgColor = Property(QColor, getBgColor, setBgColor)

class ServerItem(QFrame):
    def __init__(self, text, server_data=None, theme=None, parent=None):
        super().__init__(parent)
        self.server_data = server_data or {}
        self.theme = theme
        self.setStyleSheet("border: none; background: transparent;")
        self.main_layout = QHBoxLayout(self); self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.radio = AnimatedRadioButton(theme, self); self.radio.setText(text); self.main_layout.addWidget(self.radio)
        
        self.actions_container = QWidget(self.radio)
        self.actions_layout = QHBoxLayout(self.actions_container); self.actions_layout.setContentsMargins(0, 0, 16, 0); self.actions_layout.setSpacing(8)
        
        self.ping_label = QLabel(""); self.ping_label.setStyleSheet(f"color: {theme.on_surface_variant}; font-size: 10px; border: none; background: transparent;")
        
        self.share_button = QPushButton("🔗"); self.share_button.setFixedSize(32, 32); self.share_button.setCursor(Qt.PointingHandCursor)
        self.share_button.setStyleSheet(f"QPushButton {{ color: {theme.on_surface_variant}; background: transparent; border-radius: 16px; border: none; }} QPushButton:hover {{ background: rgba(0, 255, 0, 0.1); color: white; }}")
        self.share_button.clicked.connect(self.show_qr_code)
        
        self.delete_button = QPushButton("✕"); self.delete_button.setFixedSize(32, 32); self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.setStyleSheet(f"QPushButton {{ color: {theme.on_surface_variant}; background: transparent; border-radius: 16px; border: none; }} QPushButton:hover {{ background: rgba(255, 0, 0, 0.2); color: white; }}")
        
        self.actions_layout.addStretch(); self.actions_layout.addWidget(self.ping_label); self.actions_layout.addWidget(self.share_button); self.actions_layout.addWidget(self.delete_button)
        self.setFixedHeight(56)

    def show_qr_code(self):
        qr_img = qrcode.make(self.server_data['key'])
        img = qr_img.toqimage()
        d = QDialog(self); d.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog); d.setAttribute(Qt.WA_TranslucentBackground)
        lay = QHBoxLayout(d); lbl = QLabel(); lbl.setPixmap(QPixmap.fromImage(img).scaled(300, 300)); lay.addWidget(lbl); d.exec()

    def resizeEvent(self, event):
        self.actions_container.setGeometry(self.width() - 160, 0, 160, self.height())
        super().resizeEvent(event)

    def set_ping(self, ms):
        if ms is None: self.ping_label.setText("")
        else: self.ping_label.setText(f"{int(ms)}ms")

    def set_status(self, connected=False):
        pass # Status indicator removed as requested
