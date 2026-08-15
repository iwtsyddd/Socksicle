from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QRadioButton, QFrame, QSizePolicy, QDialog
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPainter, QBrush, QFont, QPixmap
import qrcode

class AnimatedRadioButton(QRadioButton):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._bg_color = QColor(theme.surface_variant)
        self._bg_anim = QPropertyAnimation(self, b"bgColor")
        self._bg_anim.setDuration(250)
        self._bg_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._actions_width = 160
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
        text_area_width = self.width() - self._actions_width - 32
        p.drawText(24, 0, max(100, text_area_width), self.height(), Qt.AlignVCenter | Qt.AlignLeft, self.text())

    def getBgColor(self): return self._bg_color
    def setBgColor(self, c): self._bg_color = c; self.update()
    bgColor = Property(QColor, getBgColor, setBgColor)

class ServerItem(QFrame):
    def __init__(self, text, server=None, theme=None, parent=None):
        super().__init__(parent)
        self.server = server
        self.theme = theme
        self.setStyleSheet("border: none; background: transparent;")
        self.main_layout = QHBoxLayout(self); self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.radio = AnimatedRadioButton(theme, self); self.radio.setText(text); self.main_layout.addWidget(self.radio)
        
        self.actions_container = QWidget(self.radio)
        self.actions_layout = QHBoxLayout(self.actions_container); self.actions_layout.setContentsMargins(0, 0, 16, 0); self.actions_layout.setSpacing(8)
        
        self.ping_label = QLabel(""); self.ping_label.setFixedWidth(44)
        self.ping_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ping_label.setStyleSheet(f"color: {theme.on_surface_variant}; font-size: 10px; border: none; background: transparent;")

        self.protocol_badge = QLabel("")
        self.protocol_badge.setStyleSheet("border: none; background: transparent;")
        if server:
            proto = getattr(server, 'protocol', None)
            if proto and hasattr(proto, 'value'):
                parts = [proto.value.upper()]
                sec = getattr(server, 'security', 'none')
                transport = getattr(server, 'transport', 'tcp')
                if proto.value == "vless":
                    if sec == "reality":
                        parts.append("Reality")
                    elif sec == "tls":
                        parts.append("TLS")
                    if transport and transport != "tcp":
                        parts.append(transport.upper())
                elif proto.value == "vmess":
                    if sec == "tls":
                        parts.append("TLS")
                    if transport and transport != "tcp":
                        parts.append(transport.upper())
                badge_text = " · ".join(parts)
                self.protocol_badge.setStyleSheet(
                    f"color: {theme.on_surface_variant}; background: transparent; border: none; "
                    f"font-size: 9px; font-weight: bold;"
                )
                self.protocol_badge.setText(badge_text)
            elif getattr(server, 'plugin', ''):
                self.protocol_badge.setText("SS")
                self.protocol_badge.setToolTip(f"Plugin: {server.plugin}")
                self.protocol_badge.setStyleSheet(
                    f"color: {theme.on_surface_variant}; background: transparent; border: none; "
                    f"font-size: 9px; font-weight: bold;"
                )
        
        self.share_button = QPushButton("🔗"); self.share_button.setFixedSize(32, 32); self.share_button.setCursor(Qt.PointingHandCursor)
        self.share_button.setStyleSheet(f"QPushButton {{ color: {theme.on_surface_variant}; background: transparent; border-radius: 16px; border: none; }} QPushButton:hover {{ background: rgba(0, 255, 0, 0.1); color: white; }}")
        self.share_button.clicked.connect(self.show_qr_code)
        
        self.delete_button = QPushButton("✕"); self.delete_button.setFixedSize(32, 32); self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.setStyleSheet(f"QPushButton {{ color: {theme.on_surface_variant}; background: transparent; border-radius: 16px; border: none; }} QPushButton:hover {{ background: rgba(255, 0, 0, 0.2); color: white; }}")
        
        self.actions_layout.addStretch(); self.actions_layout.addWidget(self.ping_label); self.actions_layout.addWidget(self.protocol_badge); self.actions_layout.addWidget(self.share_button); self.actions_layout.addWidget(self.delete_button)
        self._recompute_actions_width()
        self.setFixedHeight(56)

    def show_qr_code(self):
        qr_img = qrcode.make(self.server.key)
        img = qr_img.toqimage()
        d = QDialog(self); d.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog); d.setAttribute(Qt.WA_TranslucentBackground)
        lay = QHBoxLayout(d); lbl = QLabel(); lbl.setPixmap(QPixmap.fromImage(img).scaled(300, 300)); lay.addWidget(lbl); d.exec()

    def resizeEvent(self, event):
        self._recompute_actions_width()
        super().resizeEvent(event)

    def _recompute_actions_width(self):
        content_width = self.actions_layout.sizeHint().width() + 16
        clamped = max(160, min(content_width, 280))
        self._actions_width = content_width if content_width > clamped else clamped
        self.radio._actions_width = self._actions_width
        self.actions_container.setGeometry(self.width() - self._actions_width, 0, self._actions_width, self.height())

    def set_ping(self, ms):
        if ms is None: self.ping_label.setText("—")
        else: self.ping_label.setText(f"{round(ms)}ms")
