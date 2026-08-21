import time

from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QProgressBar
from PySide6.QtCore import Qt


class TrafficCard(QFrame):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(
            f"background: {self.theme.surface_variant}; border-radius: 20px; border: none;")
        self.setMinimumHeight(100)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        self.traffic_label = QLabel("Traffic: --")
        self.traffic_label.setStyleSheet(
            f"color: {self.theme.on_surface}; font-size: 12px; font-weight: 600;")

        self.traffic_bar = QProgressBar()
        self.traffic_bar.setFixedHeight(8)
        self.traffic_bar.setTextVisible(False)
        self.traffic_bar.setStyleSheet(
            f"QProgressBar {{ background-color: rgba(0,0,0,0.2); border: none;"
            f" border-radius: 4px; }}"
            f" QProgressBar::chunk {{ background-color: {self.theme.primary};"
            f" border-radius: 4px; }}")

        self.expire_label = QLabel("Expires: --")
        self.expire_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 11px;")

        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 10px;")
        self.meta_label.setWordWrap(True)
        self.meta_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.traffic_label)
        layout.addWidget(self.traffic_bar)
        layout.addWidget(self.expire_label)
        layout.addWidget(self.meta_label)

    def update_from_subscription(self, traffic_info, metadata):
        if traffic_info:
            used, total, percent, expire = traffic_info
            self.traffic_label.setText(f"Traffic: {used:.1f} / {total:.1f} GB")
            self.traffic_bar.setValue(int(percent))
            if expire:
                self.expire_label.setText(f"Expires: {expire}")

        if traffic_info or metadata.get('profile_title') or metadata.get('description'):
            self.show()
        else:
            self.hide()

        server_count = metadata.get('server_count', 0)
        data_parts = []
        if server_count:
            data_parts.append(f"{server_count} servers")
        last_updated = metadata.get('last_updated', 0)
        if last_updated:
            data_parts.append("Updated: " + time.strftime('%Y-%m-%d', time.localtime(last_updated)))
        interval = metadata.get('profile_update_interval', 0)
        if interval > 0:
            data_parts.append(f"Auto-update: every {interval}h")
        desc = metadata.get('description', '')
        if desc and desc.strip():
            self.meta_label.setText(
                desc if not data_parts else f"{desc}\n{' | '.join(data_parts)}")
            self.meta_label.show()
        else:
            meta_parts = []
            if metadata.get('profile_title'):
                meta_parts.append(metadata['profile_title'])
            meta_parts += data_parts
            if meta_parts:
                self.meta_label.setText(" | ".join(meta_parts))
                self.meta_label.show()
            else:
                self.meta_label.hide()

    def apply_theme(self, theme):
        self.theme = theme
        self.setStyleSheet(
            f"background: {getattr(self.theme, 'surface_container_low', self.theme.surface_variant)};"
            f" border-radius: 20px; border: none;")
        self.traffic_label.setStyleSheet(
            f"color: {self.theme.on_surface}; font-size: 12px; font-weight: 600;")
        self.traffic_bar.setStyleSheet(
            f"QProgressBar {{ background-color: rgba(0,0,0,0.2); border: none; border-radius: 4px; }}"
            f" QProgressBar::chunk {{ background-color: {self.theme.primary}; border-radius: 4px; }}")
        self.expire_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 11px;")
        self.meta_label.setStyleSheet(
            f"color: {self.theme.on_surface_variant}; font-size: 10px;")
