from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, 
                           QHBoxLayout, QLineEdit, QSpinBox, QCheckBox,
                           QFormLayout, QGroupBox, QFrame)
from PySide6.QtCore import Qt

class SettingsDialog(QDialog):
    def __init__(self, parent=None, theme=None, current_port="1080", auto_connect=False):
        super().__init__(parent)
        self.theme = theme
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.main_layout = QVBoxLayout(self)
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {theme.surface};
                border-radius: 28px;
                border: none;
            }}
            QLabel {{ color: {theme.on_surface}; border: none; font-size: 14px; }}
            QSpinBox {{
                background-color: {theme.surface_variant};
                color: {theme.on_surface}; border-radius: 8px; padding: 8px; border: none;
            }}
            QCheckBox {{ color: {theme.on_surface}; border: none; font-size: 14px; }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: none;
                background: {theme.surface_variant};
            }}
            QCheckBox::indicator:checked {{
                background: {theme.primary};
            }}
        """)
        self.main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 24)
        
        title = QLabel("Settings")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; margin-bottom: 16px; color: {theme.on_surface};")
        layout.addWidget(title)
        
        form_layout = QFormLayout()
        form_layout.setSpacing(16)
        
        self.port_input = QSpinBox()
        self.port_input.setRange(1024, 65535)
        self.port_input.setValue(int(current_port))
        form_layout.addRow("Local port:", self.port_input)
        
        self.auto_connect_check = QCheckBox("Auto-connect on startup")
        self.auto_connect_check.setChecked(auto_connect)
        form_layout.addRow("", self.auto_connect_check)

        self.minimize_to_tray_check = QCheckBox("Minimize to tray on close")
        self.minimize_to_tray_check.setChecked(parent.settings.get("minimize_to_tray", True))
        form_layout.addRow("", self.minimize_to_tray_check)
        
        layout.addLayout(form_layout)
        
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 24, 0, 0)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.primary}; background: transparent; padding: 10px; font-weight: 500; border: none;
            }}
            QPushButton:hover {{ background: rgba(208, 188, 255, 0.1); border-radius: 20px; }}
        """)
        self.cancel_button.clicked.connect(self.reject)
        
        self.save_button = QPushButton("Save")
        self.save_button.setStyleSheet(theme.get_button_style("filled"))
        self.save_button.clicked.connect(self.accept)
        
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)
        layout.addLayout(button_layout)
    
    def get_settings(self):
        return {
            "local_port": str(self.port_input.value()),
            "auto_connect": self.auto_connect_check.isChecked(),
            "minimize_to_tray": self.minimize_to_tray_check.isChecked()
        }
