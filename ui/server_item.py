from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QRadioButton,
    QFrame, QSizePolicy, QDialog, QVBoxLayout
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPainter, QBrush, QFont, QPixmap, QPen
import qrcode


class AnimatedRadioButton(QRadioButton):
    """Material 3 Card Radio Button with tonal hover and selection indicator."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._bg_color = QColor(getattr(theme, "surface_container_low", theme.surface_variant))
        self._bg_anim = QPropertyAnimation(self, b"bgColor")
        self._bg_anim.setDuration(200)
        self._bg_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._actions_width = 160
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "QRadioButton { border: none; background: transparent; } "
            "QRadioButton::indicator { width: 0px; height: 0px; }"
        )

    def enterEvent(self, event):
        if self.isChecked():
            target = QColor(getattr(self.theme, "surface_container_high", self.theme.surface_variant))
        else:
            target = QColor(getattr(self.theme, "surface_container", self.theme.surface_variant))
        self._animate_bg(target)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isChecked():
            target = QColor(getattr(self.theme, "surface_container", self.theme.surface_variant))
        else:
            target = QColor(getattr(self.theme, "surface_container_low", self.theme.surface_variant))
        self._animate_bg(target)
        super().leaveEvent(event)

    def _animate_bg(self, target_color):
        self._bg_anim.stop()
        self._bg_anim.setEndValue(target_color)
        self._bg_anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._bg_color))
        p.drawRoundedRect(self.rect(), 16, 16)

        # M3 Selection Left Pill Indicator (No border outline)
        if self.isChecked():
            p.setBrush(QBrush(QColor(self.theme.primary)))
            p.drawRoundedRect(0, 10, 4, 36, 2, 2)

        # Text
        p.setPen(QColor(self.theme.primary if self.isChecked() else self.theme.on_surface))
        font = QFont("Segoe UI, Arial", 11)
        font.setBold(self.isChecked())
        p.setFont(font)
        text_area_width = max(60, self.width() - self._actions_width - 32)
        elided = p.fontMetrics().elidedText(self.text(), Qt.ElideRight, text_area_width)
        p.drawText(20, 0, text_area_width, self.height(), Qt.AlignVCenter | Qt.AlignLeft, elided)

    def getBgColor(self):
        return self._bg_color

    def setBgColor(self, c):
        self._bg_color = c
        self.update()

    bgColor = Property(QColor, getBgColor, setBgColor)


class ServerItem(QFrame):
    def __init__(self, text, server=None, theme=None, parent=None):
        super().__init__(parent)
        self.server = server
        self.theme = theme
        self.setStyleSheet("border: none; background: transparent;")
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.radio = AnimatedRadioButton(theme, self)
        self.radio.setText(text)
        self.main_layout.addWidget(self.radio)

        self.actions_container = QWidget(self.radio)
        self.actions_layout = QHBoxLayout(self.actions_container)
        self.actions_layout.setContentsMargins(0, 0, 12, 0)
        self.actions_layout.setSpacing(6)

        self.ping_label = QLabel("")
        self.ping_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ping_label.setStyleSheet(
            f"color: {theme.on_surface_variant}; font-size: 11px; font-weight: 500; border: none; background: transparent; outline: none;"
        )
        self.ping_label.hide()

        self.protocol_badge = QLabel("")
        self.protocol_badge.setStyleSheet(
            f"color: {theme.on_surface_variant}; background: transparent; border: none; "
            f"font-size: 10px; font-weight: bold; outline: none;"
        )
        if server:
            proto = getattr(server, "protocol", None)
            if proto and hasattr(proto, "value"):
                parts = [proto.value.upper()]
                sec = getattr(server, "security", "none")
                transport = getattr(server, "transport", "tcp")
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
                elif proto.value == "hysteria2":
                    parts = ["HY2"]
                    if getattr(server, "ports", ""):
                        parts.append("Hop")
                    if getattr(server, "obfs", ""):
                        parts.append("Obfs")
                badge_text = " · ".join(parts)
                self.protocol_badge.setText(badge_text)
            elif getattr(server, "plugin", ""):
                self.protocol_badge.setText("SS")
                self.protocol_badge.setToolTip(f"Plugin: {server.plugin}")

        self.share_button = QPushButton("🔗")
        self.share_button.setFocusPolicy(Qt.NoFocus)
        self.share_button.setFixedSize(30, 30)
        self.share_button.setCursor(Qt.PointingHandCursor)
        self.share_button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.on_surface_variant};
                background: transparent;
                border-radius: 15px;
                border: none;
                outline: none;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.08);
                color: {theme.primary};
            }}
        """)
        self.share_button.clicked.connect(self.show_qr_code)

        self.delete_button = QPushButton("✕")
        self.delete_button.setFocusPolicy(Qt.NoFocus)
        self.delete_button.setFixedSize(30, 30)
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.on_surface_variant};
                background: transparent;
                border-radius: 15px;
                border: none;
                outline: none;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: rgba(255, 100, 100, 0.18);
                color: {theme.error};
            }}
        """)

        self.actions_layout.addStretch()
        self.actions_layout.addWidget(self.ping_label)
        self.actions_layout.addWidget(self.protocol_badge)
        self.actions_layout.addWidget(self.share_button)
        self.actions_layout.addWidget(self.delete_button)
        self._recompute_actions_width()
        self.setFixedHeight(56)

    def show_qr_code(self):
        qr_img = qrcode.make(self.server.key)
        img = qr_img.toqimage()
        d = QDialog(self)
        d.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        d.setAttribute(Qt.WA_TranslucentBackground)

        container = QFrame(d)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {self.theme.surface_container_high};
                border-radius: 28px;
                border: none;
                outline: none;
            }}
        """)
        lay = QVBoxLayout(container)
        lay.setContentsMargins(24, 24, 24, 24)

        title = QLabel(self.server.name if self.server else "Server QR")
        title.setStyleSheet(f"color: {self.theme.on_surface}; font-weight: bold; font-size: 16px; margin-bottom: 8px; border: none;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        lbl = QLabel()
        lbl.setPixmap(QPixmap.fromImage(img).scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl)

        close_btn = QPushButton("Close")
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.setStyleSheet(self.theme.get_button_style("tonal"))
        close_btn.clicked.connect(d.accept)
        lay.addWidget(close_btn)

        d_lay = QVBoxLayout(d)
        d_lay.setContentsMargins(12, 12, 12, 12)
        d_lay.addWidget(container)
        d.exec()

    def set_ping(self, ms):
        if ms is not None and ms >= 0:
            if ms < 100:
                color = getattr(self.theme, "success", "#81C784")
            elif ms < 250:
                color = getattr(self.theme, "tertiary", "#FFD54F")
            else:
                color = getattr(self.theme, "error", "#F2B8B5")
            self.ping_label.setText(f"{ms:.0f}ms")
            self.ping_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; border: none; background: transparent; outline: none;")
            self.ping_label.show()
        else:
            self.ping_label.setText("")
            self.ping_label.hide()
        self._recompute_actions_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recompute_actions_width()

    def showEvent(self, event):
        super().showEvent(event)
        self._recompute_actions_width()

    def _recompute_actions_width(self):
        w = 0
        if self.ping_label.isVisible() and self.ping_label.text():
            w += self.ping_label.fontMetrics().horizontalAdvance(self.ping_label.text()) + 8
        if self.protocol_badge.text():
            w += self.protocol_badge.fontMetrics().horizontalAdvance(self.protocol_badge.text()) + 8
        w += self.share_button.width() + 8
        w += self.delete_button.width() + 16
        self._actions_width = max(110, w)
        self.radio._actions_width = self._actions_width
        self.actions_container.setGeometry(
            max(0, self.radio.width() - self._actions_width),
            0,
            self._actions_width,
            self.radio.height()
        )
        self.radio.update()
