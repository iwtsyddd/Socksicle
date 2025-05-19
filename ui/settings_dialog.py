from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, 
                           QHBoxLayout, QLineEdit, QSpinBox, QCheckBox,
                           QFormLayout, QGroupBox)
from PyQt5.QtCore import Qt

class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_port="1080", auto_connect=False):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
                color: white;
            }
            QLabel {
                color: white;
            }
            QLineEdit, QSpinBox {
                background: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton {
                background: #7b61ff;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #8d76ff;
            }
            QPushButton:pressed {
                background: #6a52e0;
            }
            QPushButton#cancelButton {
                background: #444;
            }
            QPushButton#cancelButton:hover {
                background: #555;
            }
            QGroupBox {
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 1.5em;
                padding-top: 0.5em;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QCheckBox {
                color: white;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #555;
                border-radius: 3px;
                background: #333;
            }
            QCheckBox::indicator:checked {
                background: #7b61ff;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        # Connection settings group
        connection_group = QGroupBox("Connection Settings")
        connection_layout = QFormLayout(connection_group)
        
        # Local port setting
        self.port_input = QSpinBox()
        self.port_input.setRange(1024, 65535)
        self.port_input.setValue(int(current_port))
        connection_layout.addRow("Local port:", self.port_input)
        
        # Auto-connect setting
        self.auto_connect_check = QCheckBox("Auto-connect on startup")
        self.auto_connect_check.setChecked(auto_connect)
        connection_layout.addRow("", self.auto_connect_check)
        
        layout.addWidget(connection_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self.reject)
        
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        
        layout.addLayout(button_layout)
    
    def get_settings(self):
        """Get the settings from the dialog"""
        return {
            "local_port": str(self.port_input.value()),
            "auto_connect": self.auto_connect_check.isChecked()
        }