from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QMenu


class TrayManager(QObject):
    connectRequested = Signal(str, int)
    showHideRequested = Signal()
    quitRequested = Signal()

    def __init__(self, theme, icon_path, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.icon_path = icon_path
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self._setup_tray()

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(self.icon_path))
        self.tray_menu = QMenu()

        self.show_action = self.tray_menu.addAction("Show/Hide")
        self.show_action.triggered.connect(self.showHideRequested)

        self.servers_menu = self.tray_menu.addMenu("Servers")
        self.tray_menu.addSeparator()

        self.disconnect_action = self.tray_menu.addAction("Disconnect")
        self.disconnect_action.triggered.connect(
            lambda: self.connectRequested.emit("", -1))
        self.disconnect_action.setEnabled(False)

        self.quit_action = self.tray_menu.addAction("Quit")
        self.quit_action.triggered.connect(self.quitRequested)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.show()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.showHideRequested.emit()

    def rebuild_menu(self, manual_servers, subscriptions):
        self.servers_menu.clear()
        manual_menu = self.servers_menu.addMenu("Manual")
        for i, server in enumerate(manual_servers):
            action = manual_menu.addAction(server.name)
            action.triggered.connect(
                lambda checked=False, i=i: self.connectRequested.emit("Manual", i))
        for sub in subscriptions:
            sub_menu = self.servers_menu.addMenu(sub['name'])
            for i, server in enumerate(sub['servers']):
                action = sub_menu.addAction(server.name)
                action.triggered.connect(
                    lambda checked=False, n=sub['name'], i=i: self.connectRequested.emit(n, i))

    def set_disconnect_enabled(self, enabled):
        self.disconnect_action.setEnabled(enabled)

    def notify(self, title, message):
        self.tray_icon.showMessage(title, message, QIcon(self.icon_path), 3000)

    def show(self):
        self.tray_icon.show()

    def hide(self):
        self.tray_icon.hide()
