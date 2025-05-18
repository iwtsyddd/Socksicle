#!/usr/bin/env python3
import sys, os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
from ui.main_window import RoundedWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)


    app.setApplicationName("Socksicle")
    app.setDesktopFileName("Socksicle.desktop")

    
    dir_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(dir_path, "icon.png")
    print("Иконка найдена?", os.path.isfile(icon_path))  # для проверки

    window = RoundedWindow()
    window.show()
    sys.exit(app.exec_())