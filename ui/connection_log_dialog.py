from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QFrame, QLabel
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtCore import Qt

class ConnectionLogDialog(QDialog):
    def __init__(self, parent=None, theme=None):
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
            QTextEdit {{
                background-color: {theme.surface_variant};
                color: {theme.on_surface_variant};
                border: none;
                border-radius: 12px;
                padding: 12px;
                font-family: 'JetBrains Mono', 'Fira Code', monospace;
                font-size: 12px;
            }}
        """)
        self.main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 24)
        
        title = QLabel("Connection Log")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; margin-bottom: 16px; color: {theme.on_surface};")
        layout.addWidget(title)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 16, 0, 0)
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.setStyleSheet(theme.get_button_style("tonal"))
        self.clear_button.clicked.connect(self.clear_log)
        
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(theme.get_button_style("filled"))
        self.close_button.clicked.connect(self.accept)
        
        button_layout.addWidget(self.clear_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)
    
    def add_log(self, message):
        self.log_text.append(message)
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
    
    def clear_log(self):
        self.log_text.clear()
