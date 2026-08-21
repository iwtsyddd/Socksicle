from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit,
    QScrollArea, QGraphicsOpacityEffect, QButtonGroup,
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QThreadPool
from .server_item import ServerItem
from utils.ping import AsyncBatchPingJob


class ServerListPanel(QWidget):
    addRequested = Signal()
    exportRequested = Signal()
    importRequested = Signal()
    updateSubRequested = Signal()
    deleteSubRequested = Signal()
    pingAllRequested = Signal()
    serverSelected = Signal(int)
    serverDeleted = Signal(int)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._server_items = []
        self._fade_out_cb = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(0, 4, 0, 8)
        action_bar.setSpacing(6)

        self.add_btn = QPushButton("+ Add")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setFocusPolicy(Qt.NoFocus)
        self.add_btn.setFixedHeight(32)
        self.add_btn.clicked.connect(self.addRequested)
        action_bar.addWidget(self.add_btn)

        self.export_btn = QPushButton("📤")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setFocusPolicy(Qt.NoFocus)
        self.export_btn.setToolTip("Export Profiles")
        self.export_btn.setFixedSize(32, 32)
        self.export_btn.clicked.connect(self.exportRequested)
        action_bar.addWidget(self.export_btn)

        self.import_btn = QPushButton("📥")
        self.import_btn.setCursor(Qt.PointingHandCursor)
        self.import_btn.setFocusPolicy(Qt.NoFocus)
        self.import_btn.setToolTip("Import Profiles")
        self.import_btn.setFixedSize(32, 32)
        self.import_btn.clicked.connect(self.importRequested)
        action_bar.addWidget(self.import_btn)

        action_bar.addStretch()

        self.update_sub_btn = QPushButton("🔄 Update")
        self.update_sub_btn.setCursor(Qt.PointingHandCursor)
        self.update_sub_btn.setFocusPolicy(Qt.NoFocus)
        self.update_sub_btn.setFixedHeight(32)
        self.update_sub_btn.clicked.connect(self.updateSubRequested)
        self.update_sub_btn.hide()
        action_bar.addWidget(self.update_sub_btn)

        self.ping_all_btn = QPushButton("⚡ Ping All")
        self.ping_all_btn.setCursor(Qt.PointingHandCursor)
        self.ping_all_btn.setFocusPolicy(Qt.NoFocus)
        self.ping_all_btn.setFixedHeight(32)
        self.ping_all_btn.clicked.connect(self.pingAllRequested)
        action_bar.addWidget(self.ping_all_btn)

        self.del_sub_btn = QPushButton("🗑 Sub")
        self.del_sub_btn.setCursor(Qt.PointingHandCursor)
        self.del_sub_btn.setFocusPolicy(Qt.NoFocus)
        self.del_sub_btn.setFixedHeight(32)
        self.del_sub_btn.clicked.connect(self.deleteSubRequested)
        self.del_sub_btn.hide()
        action_bar.addWidget(self.del_sub_btn)

        self._apply_action_bar_styles()
        layout.addLayout(action_bar)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search servers...")
        self.search_bar.setStyleSheet(
            f"background: {getattr(self.theme, 'surface_container_highest', self.theme.surface_variant)};"
            f" color: {self.theme.on_surface};"
            f" padding: 8px 12px; border-radius: 12px; border: none; margin-top: 4px; margin-bottom: 8px; outline: none;")
        self.search_bar.textChanged.connect(self._filter_servers)
        layout.addWidget(self.search_bar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.verticalScrollBar().setSingleStep(16)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; outline: none; }}"
            f" QScrollBar:vertical {{ border: none; background: transparent; width: 6px; }}"
            f" QScrollBar::handle:vertical {{ background: {self.theme.surface_variant};"
            f" border-radius: 3px; min-height: 30px; }}")
        self.scroll_content = QWidget()
        self.server_layout = QVBoxLayout(self.scroll_content)
        self.server_layout.setContentsMargins(0, 0, 0, 0)
        self.server_layout.setSpacing(10)
        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area)

        self._opacity_effect = QGraphicsOpacityEffect(self.scroll_area)
        self.scroll_area.setGraphicsEffect(self._opacity_effect)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(200)
        self._fade_anim.finished.connect(self._on_fade_anim_finished)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.buttonToggled.connect(self._on_button_toggled)

    def _on_fade_anim_finished(self):
        cb = self._fade_out_cb
        self._fade_out_cb = None
        if cb:
            cb()

    def _on_button_toggled(self, button, checked):
        if checked:
            idx = self._button_group.id(button)
            if idx >= 0:
                self.serverSelected.emit(idx)

    def refresh(self, servers, connected_server_key=None):
        self.scroll_content.setUpdatesEnabled(False)
        self._button_group.blockSignals(True)
        try:
            for b in self._button_group.buttons():
                self._button_group.removeButton(b)
            while self.server_layout.count():
                item = self.server_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._server_items = []
            for i, s in enumerate(servers):
                item = ServerItem(s.name, s, self.theme)
                item.delete_button.clicked.connect(
                    lambda checked=False, idx=i: self.serverDeleted.emit(idx))
                self._button_group.addButton(item.radio, i)
                self.server_layout.addWidget(item)
                self._server_items.append(item)
                if connected_server_key and s.key == connected_server_key:
                    item.radio.setChecked(True)
            self.server_layout.addStretch()
            self._filter_servers(self.search_bar.text())
        finally:
            self._button_group.blockSignals(False)
            self.scroll_content.setUpdatesEnabled(True)

    def _filter_servers(self, text):
        text = text.lower()
        for item in self._server_items:
            visible = text in item.radio.text().lower() or text in item.server.host.lower()
            item.setVisible(visible)

    def ping_all(self, method, socks5_port):
        servers = [item.server for item in self._server_items]
        if not servers:
            return
        job = AsyncBatchPingJob(
            servers,
            callback=self._on_ping_result,
            method=method,
            socks5_port=socks5_port,
        )
        QThreadPool.globalInstance().start(job)

    def _on_ping_result(self, index, ms):
        if index < len(self._server_items):
            self._server_items[index].set_ping(ms if ms >= 0 else None)

    def get_selected_index(self):
        btn = self._button_group.checkedButton()
        if btn:
            return self._button_group.id(btn)
        return -1

    def set_update_visible(self, visible):
        self.update_sub_btn.setVisible(visible)

    def set_delete_sub_visible(self, visible):
        self.del_sub_btn.setVisible(visible)

    def set_update_button_state(self, text, enabled=True):
        self.update_sub_btn.setText(text)
        self.update_sub_btn.setEnabled(enabled)

    def fade_out(self, on_done=None):
        self._fade_anim.stop()
        self._fade_out_cb = on_done
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def fade_in(self):
        self._fade_anim.stop()
        self._fade_out_cb = None
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _apply_action_bar_styles(self):
        # 1. + Add button (Tonal / Primary Container pill)
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.secondary_container};
                color: {self.theme.on_secondary_container};
                border-radius: 16px;
                padding: 0px 14px;
                height: 32px;
                font-size: 13px;
                font-weight: 700;
                border: none;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {self.theme.primary_container};
                color: {self.theme.on_primary_container};
            }}
            QPushButton:pressed {{
                background-color: {self.theme.primary};
                color: {self.theme.on_primary};
            }}
        """)

        # 2. Icon action buttons (Export 📤 & Import 📥)
        icon_btn_style = f"""
            QPushButton {{
                background-color: {getattr(self.theme, 'surface_container_high', self.theme.surface_variant)};
                color: {self.theme.on_surface};
                border-radius: 16px;
                font-size: 14px;
                padding: 0px;
                border: none;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {getattr(self.theme, 'surface_container_highest', self.theme.surface_bright)};
                color: {self.theme.primary};
            }}
            QPushButton:pressed {{
                background-color: {self.theme.primary_container};
            }}
        """
        self.export_btn.setStyleSheet(icon_btn_style)
        self.import_btn.setStyleSheet(icon_btn_style)

        # 3. Action pill buttons (Ping All ⚡ & Update 🔄)
        pill_btn_style = f"""
            QPushButton {{
                background-color: {getattr(self.theme, 'surface_container_high', self.theme.surface_variant)};
                color: {self.theme.on_surface};
                border-radius: 16px;
                padding: 0px 12px;
                height: 32px;
                font-size: 12px;
                font-weight: 600;
                border: none;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {self.theme.primary_container};
                color: {self.theme.on_primary_container};
            }}
            QPushButton:pressed {{
                background-color: {self.theme.primary};
                color: {self.theme.on_primary};
            }}
            QPushButton:disabled {{
                color: {self.theme.on_surface_variant};
            }}
        """
        self.ping_all_btn.setStyleSheet(pill_btn_style)
        self.update_sub_btn.setStyleSheet(pill_btn_style)

        # 4. Delete subscription button (🗑 Sub)
        self.del_sub_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {self.theme.error};
                border-radius: 16px;
                padding: 0px 10px;
                height: 32px;
                font-size: 12px;
                font-weight: 600;
                border: none;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {getattr(self.theme, 'error_container', '#8C1D18')};
                color: {getattr(self.theme, 'on_error_container', '#F9DEDC')};
            }}
            QPushButton:pressed {{
                background-color: {self.theme.error};
                color: {self.theme.on_error};
            }}
        """)

    def apply_theme(self, theme):
        self.theme = theme
        self._apply_action_bar_styles()
        self.search_bar.setStyleSheet(
            f"background: {getattr(self.theme, 'surface_container_highest', self.theme.surface_variant)};"
            f" color: {self.theme.on_surface};"
            f" padding: 8px 12px; border-radius: 12px; border: none; margin-top: 4px; margin-bottom: 8px; outline: none;")
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; outline: none; }}"
            f" QScrollBar:vertical {{ border: none; background: transparent; width: 6px; }}"
            f" QScrollBar::handle:vertical {{ background: {self.theme.surface_variant};"
            f" border-radius: 3px; min-height: 30px; }}")
