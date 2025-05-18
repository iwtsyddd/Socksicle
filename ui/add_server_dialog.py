from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
from PyQt5.QtCore import Qt

class AddServerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Server")
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
                color: white;
            }
            QLabel {
                color: white;
            }
            QLineEdit {
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
        """)
        
        layout = QVBoxLayout(self)
        
        # Input field
        self.label = QLabel("Enter server key (ss://...)")
        layout.addWidget(self.label)
        
        self.input_field = QLineEdit()
        layout.addWidget(self.input_field)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self.reject)
        
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.add_button)
        
        layout.addLayout(button_layout)
    
    def get_server_key(self):
        return self.input_field.text().strip()