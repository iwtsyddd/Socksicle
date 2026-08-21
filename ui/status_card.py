from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal, QTimer
from .toggle_switch import AnimatedToggleSwitch


class StatusCard(QFrame):
    vpnSwitchClicked = Signal()
    portNoticeExpired = Signal()

    def __init__(self, theme, is_connected_fn=None, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._is_connected_fn = is_connected_fn or (lambda: False)
        self._port_change_notice = False
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self._clear_port_change_notice)
        self._setup_ui()

    def _setup_ui(self):
        card_bg = getattr(self.theme, "surface_container", self.theme.surface_variant)
        self.setStyleSheet(
            f"QFrame {{ background-color: {card_bg}; border-radius: 28px; border: none; outline: none; }}"
            f" QLabel {{ color: {self.theme.on_surface}; border: none; background: transparent; }}"
        )
        self.setFixedHeight(120)
        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(24, 16, 24, 16)

        top = QHBoxLayout()
        self.status_title_label = QLabel("Connection Status")
        self.status_title_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 13px; font-weight: 500;")
        top.addWidget(self.status_title_label)
        top.addStretch()

        self.vpn_switch = AnimatedToggleSwitch(self, theme=self.theme)
        self.vpn_switch.mousePressEvent = self._on_switch_clicked
        top.addWidget(self.vpn_switch)

        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; background: transparent;")

        self.ping_label = QLabel("Ping: --")
        self.ping_label.setStyleSheet(
            f"font-size: 12px; color: {self.theme.on_surface_variant}; background: transparent;")

        card_layout.addLayout(top)
        card_layout.addWidget(self.status_label)
        card_layout.addWidget(self.ping_label)

    def _on_switch_clicked(self, e):
        from PySide6.QtCore import Qt as Q_Qt
        if e.button() == Q_Qt.LeftButton:
            e.accept()
            self.vpnSwitchClicked.emit()

    def set_status(self, text, color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 24px; font-weight: bold; background: transparent;")

    def set_switch_state(self, checked):
        self.vpn_switch.toggle(checked)

    def reset_to_disconnected(self):
        """Immediately reset all card labels to disconnected state."""
        self.set_status("Disconnected", self.theme.on_secondary_container)
        if not self.port_change_notice:
            self.set_ping_text("Ping: --")
        self.set_switch_state(False)

    def set_ping_text(self, text):
        self.ping_label.setText(text)

    def update_geo(self, info):
        self.set_status(f"{info['flag']} {info['ip']}", self.theme.on_secondary_container)

    def update_ping(self, ms, proxy_addr_text):
        if ms is not None:
            self.ping_label.setText(f"Ping: {ms:.0f} ms · {proxy_addr_text}")
        else:
            self.ping_label.setText("Ping: Error")

    def notify_port_change(self):
        self._port_change_notice = True
        self.ping_label.setText("Local port will take effect on next connect")
        self._notice_timer.start(8000)

    def _clear_port_change_notice(self):
        if not self._port_change_notice:
            return
        self._port_change_notice = False
        if not self._is_connected_fn():
            self.ping_label.setText("Ping: --")

    @property
    def port_change_notice(self):
        return self._port_change_notice

    def apply_theme(self, theme):
        self.theme = theme
        card_bg = getattr(self.theme, "surface_container", self.theme.surface_variant)
        self.setStyleSheet(
            f"QFrame {{ background-color: {card_bg}; border-radius: 28px; border: none; outline: none; }}"
            f" QLabel {{ color: {self.theme.on_surface}; border: none; background: transparent; }}"
        )
        self.status_title_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 13px; font-weight: 500;")
        self.ping_label.setStyleSheet(
            f"font-size: 12px; color: {self.theme.on_surface_variant}; background: transparent;")
        self.vpn_switch.set_theme(self.theme)
