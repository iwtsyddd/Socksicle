from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt5.QtGui import QFont, QTextCursor

class ConnectionLogDialog(QDialog):
    """Dialog to display connection log messages"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connection Log")
        self.setMinimumSize(500, 300)
        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
                color: white;
            }
            QTextEdit {
                background: #2d2d2d;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 4px;
                font-family: monospace;
            }
            QPushButton {
                background: #444;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #555;
            }
            QPushButton#clearButton {
                background: #555;
            }
            QPushButton#clearButton:hover {
                background: #666;
            }
        """)
        
        # Set up layout
        layout = QVBoxLayout(self)
        
        # Create log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Monospace", 9))
        layout.addWidget(self.log_text)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.clear_button = QPushButton("Clear Log")
        self.clear_button.setObjectName("clearButton")
        self.clear_button.clicked.connect(self.clear_log)
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        
        button_layout.addWidget(self.clear_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
    
    def add_log(self, message):
        """Add a message to the log"""
        self.log_text.append(message)
        # Scroll to bottom
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
    
    def clear_log(self):
        """Clear the log"""
        self.log_text.clear()