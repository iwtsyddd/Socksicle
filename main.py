#!/usr/bin/env python3
import sys
import os
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from ui.main_window import RoundedWindow
from utils.distro_utils import check_ss_local, get_ss_install_command

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Socksicle")
    app.setDesktopFileName("Socksicle.desktop")

    # Set icon
    dir_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(dir_path, "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Initial dependency check
    if not check_ss_local():
        cmd = get_ss_install_command()
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Dependency Missing")
        msg.setText("shadowsocks-rust (sslocal) is not installed.")
        msg.setInformativeText(f"To install it, run:\n\n{cmd}")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Abort)
        if msg.exec() == QMessageBox.Abort:
            sys.exit(1)

    window = RoundedWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
