import json
import os
import time
import urllib.parse
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QButtonGroup, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5.QtGui import QFont, QColor, QPainter, QBrush, QPen, QIcon
from PyQt5.QtWidgets import QDialog

from .toggle_switch import AnimatedToggleSwitch
from .server_item import ServerItem
from .add_server_dialog import AddServerDialog
from .connection_log_dialog import ConnectionLogDialog
from .settings_dialog import SettingsDialog
from utils.ss_client import ShadowsocksProcess
from utils.ss_parser import decode_ss_link
from utils.ping import http_ping_via_socks5_once

class RoundedWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(" ")
        self.resize(600, 300)
        
        # Configuration file paths
        self.config_file = "servers.json"
        self.settings_file = "settings.json"
        self.servers = []
        self.load_servers()
        self.settings = self.load_settings()
        
        # Create Shadowsocks client process manager
        self.ss_client = ShadowsocksProcess()
        self.ss_client.local_port = self.settings.get("local_port", "1080")
        self.ss_client.statusChanged.connect(self.on_status_changed)
        self.ss_client.connectionStateChanged.connect(self.on_connection_state_changed)
        self.ss_client.logUpdated.connect(self.add_log)
        
        # Create connection log dialog
        self.log_dialog = ConnectionLogDialog(self)
        
        # Try to use nice fonts if available
        try:
            QFontDatabase.addApplicationFont(":/fonts/Inter-Regular.ttf")
        except:
            pass
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Main frame with rounded corners
        self.main_frame = QFrame()
        self.main_frame.mousePressEvent = self.mousePressEvent
        self.main_frame.mouseMoveEvent = self.mouseMoveEvent
        self.main_frame.mouseReleaseEvent = self.mouseReleaseEvent
        self.main_frame.setObjectName("mainFrame")
        self.main_frame.setStyleSheet("""
            #mainFrame {
                background: #1e1e1e;
                border-radius: 12px;
            }
        """)
        
        main_layout.addWidget(self.main_frame)
        
        # Layout for content
        content_layout = QVBoxLayout(self.main_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # Title bar
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(36)
        self.title_bar.setStyleSheet("background-color: transparent;")
        content_layout.addWidget(self.title_bar)
        
        # Title bar layout
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 0, 10, 0)
        title_layout.setSpacing(8)
        
        # Title bar elements
        self.icon = QLabel("⭐️")
        self.icon.setFont(QFont("Arial", 16))
        self.icon.setStyleSheet("color: white;")
        
        self.title = QLabel("Socksicle")
        self.title.setFont(QFont("Arial", 14, QFont.Medium))
        self.title.setStyleSheet("color: white;")
        
        self.vpn_label = QLabel("🛡️ VPN:")
        self.vpn_label.setContentsMargins(0, 3, 0, 0)
        self.vpn_label.setFont(QFont("Arial", 12))
        self.vpn_label.setStyleSheet("color: white;")
        
        self.vpn_switch = AnimatedToggleSwitch()
        self.vpn_switch.mousePressEvent = self.on_vpn_switch_clicked
        
        # Create buttons
        self.add_btn = QPushButton("+ Add")
        self.add_btn.setContentsMargins(3, 3, 0, 0)
        self.add_btn.setFont(QFont("Arial", 10))
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setStyleSheet("""
            QPushButton {
                color: white;
                background: #7b61ff;
                border-radius: 4px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: #8d76ff;
            }
            QPushButton:pressed {
                background: #6a52e0;
            }
        """)
        self.add_btn.clicked.connect(self.show_add_server_dialog)
        
        # Create log button
        self.log_btn = QPushButton("📋 Log")
        self.log_btn.setFont(QFont("Arial", 10))
        self.log_btn.setCursor(Qt.PointingHandCursor)
        self.log_btn.setStyleSheet("""
            QPushButton {
                color: white;
                background: #444;
                border-radius: 4px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: #555;
            }
            QPushButton:pressed {
                background: #666;
            }
        """)
        self.log_btn.clicked.connect(self.show_log_dialog)
        
        # Create settings button
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.setFont(QFont("Arial", 10))
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                color: white;
                background: #444;
                border-radius: 4px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: #555;
            }
            QPushButton:pressed {
                background: #666;
            }
        """)
        self.settings_btn.clicked.connect(self.show_settings_dialog)
        
        # Window control buttons
        self.minimize_btn = QPushButton("—")
        self.minimize_btn.setFixedSize(24, 24)
        self.minimize_btn.setStyleSheet("""
            QPushButton {
                color: white;
                background: transparent;
                border-radius: 12px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
            }
        """)
        self.minimize_btn.clicked.connect(self.showMinimized)
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setStyleSheet("""
            QPushButton {
                color: white;
                background: transparent;
                border-radius: 12px;
            }
            QPushButton:hover {
                background: rgba(255, 0, 0, 0.7);
            }
        """)
        self.close_btn.clicked.connect(self.close)
        
        title_layout.addWidget(self.icon)
        title_layout.addWidget(self.title)
        title_layout.addStretch()
        title_layout.addWidget(self.settings_btn)
        title_layout.addWidget(self.log_btn)
        title_layout.addWidget(self.add_btn) 
        title_layout.addWidget(self.vpn_label)
        title_layout.addWidget(self.vpn_switch)
        title_layout.addWidget(self.minimize_btn)
        title_layout.addWidget(self.close_btn)
        
        # Content area
        self.content_area = QFrame()
        self.content_area.setStyleSheet("background: transparent;")
        content_layout.addWidget(self.content_area)
        
        # Layout for server items
        self.checkbox_layout = QVBoxLayout(self.content_area)
        self.checkbox_layout.setContentsMargins(12, 8, 12, 12)
        self.checkbox_layout.setSpacing(8)
        
        # Create button group
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        
        # Add servers from loaded data
        self.refresh_server_list()
        
        # Fill remaining space
        self.checkbox_layout.addStretch()
        
        # Status bar
        self.status_bar = QFrame()
        self.status_bar.setFixedHeight(30)
        self.status_bar.setStyleSheet("background: rgba(0,0,0,0.2); border-radius: 0 0 12px 12px;")
        content_layout.addWidget(self.status_bar)
        
        # Status bar layout
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(12, 0, 12, 0)

        # Status label
        self.status_label = QLabel("Not connected")
        self.status_label.setFont(QFont("Arial", 10))
        self.status_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); background: transparent;")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        # Ping label 
        self.ping_label = QLabel("Ping: --")
        self.ping_label.setFont(QFont("Arial", 10))
        self.ping_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); background: transparent;")
        self.ping_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_layout.addWidget(self.ping_label)

        
        # For window dragging
        self._dragging = False
        self._drag_pos = None
        
        # Connect signals
        self.button_group.buttonToggled.connect(self.on_checkbox_toggled)
        
        # Set up ping timer
        self.ping_timer = QTimer(self)
        self.ping_timer.timeout.connect(self.update_ping)
        
        # Restore last connection if auto-connect is enabled
        if self.settings.get("auto_connect", False):
            self.restore_last_connection()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    
    def load_settings(self):
        """Load settings from the settings file"""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading settings: {e}")
        
        # Default settings
        return {
            "local_port": "1080",
            "auto_connect": False,
            "last_connected": None
        }
    
    def save_settings(self, settings=None):
        """Save settings to the settings file"""
        if settings is None:
            settings = self.settings
        
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
    
    def restore_last_connection(self):
        """Try to restore the last saved connection"""
        try:
            last_server_index = self.settings.get('last_connected')
            
            if last_server_index is not None and 0 <= last_server_index < len(self.servers):
                # Check buttons
                if len(self.button_group.buttons()) > last_server_index:
                    self.button_group.buttons()[last_server_index].setChecked(True)
                    
                # Auto-connect
                QTimer.singleShot(500, lambda: self.toggle_connection(True))
        except Exception as e:
            self.add_log(f"Failed to restore last connection: {e}")
    
    def load_servers(self):
        """Load servers from the JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.servers = json.load(f)
            else:
                # Default servers if file doesn't exist
                self.servers = []
                self.save_servers()
        except Exception as e:
            print(f"Error loading servers: {e}")
            self.servers = []
    
    def save_servers(self):
        """Save servers to the JSON file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.servers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving servers: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save servers: {e}")
    
    def refresh_server_list(self):
        """Refresh the server list in the UI"""
        # Clear existing checkboxes
        for i in reversed(range(self.checkbox_layout.count())):
            item = self.checkbox_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        
        # Clear button group
        for button in self.button_group.buttons():
            self.button_group.removeButton(button)
        
        # Add servers to the list
        if not self.servers:
            # Add placeholder if no servers
            label = QLabel("No servers added yet. Click '+ Add' to add servers.")
            label.setStyleSheet("color: #888; font-style: italic;")
            self.checkbox_layout.addWidget(label)
        else:
            # Get current connection state and server
            current_server = self.ss_client.get_current_server()
            is_connected = self.ss_client.is_connected
            
            for i, server in enumerate(self.servers):
                # Create server item widget
                server_item = ServerItem(f"🔹 {server.get('name', f'Server {i+1}')}", server, self)
                
                # Connect delete button
                server_item.delete_button.clicked.connect(lambda checked, idx=i: self.delete_server(idx))
                
                # Add checkbox to button group
                self.button_group.addButton(server_item.checkbox, i)
                
                # Add server item to layout
                self.checkbox_layout.addWidget(server_item)
                
                # Update status if this server is currently connected
                if is_connected and current_server and current_server.get('key') == server.get('key'):
                    server_item.set_status(True)
                    server_item.checkbox.setChecked(True)
            
            # Set first checkbox as checked if none is selected
            if not any(button.isChecked() for button in self.button_group.buttons()):
                if self.button_group.buttons():
                    self.button_group.buttons()[0].setChecked(True)
        
        # Add stretch at the end
        self.checkbox_layout.addStretch()
    
    def on_vpn_switch_clicked(self, event):
        """Handle VPN switch click"""
        if event.button() == Qt.LeftButton:
            self.toggle_connection()
    
    def toggle_connection(self, connect=None):
        """Toggle the connection state"""
        if connect is None:
            # Toggle current state
            connect = not self.ss_client.is_connected
        
        if connect:
            # Get the selected server
            selected_button = None
            for button in self.button_group.buttons():
                if button.isChecked():
                    selected_button = button
                    break
            
            if selected_button:
                selected_id = self.button_group.id(selected_button)
                if 0 <= selected_id < len(self.servers):
                    server_data = self.servers[selected_id]
                    
                    # Try to connect
                    success = self.ss_client.connect(server_data)
                    if success:
                        # Update UI without triggering events
                        self.vpn_switch.toggle(True)
                        # Save last connected server
                        self.settings["last_connected"] = selected_id
                        self.save_settings()
                        # Start ping updates
                        
                        self.ping_timer.start(50000)  # Update ping every  seconds
            else:
                QMessageBox.warning(self, "No Server Selected", "Please select a server to connect.")
        else:
            # Disconnect
            self.ss_client.disconnect()
            self.vpn_switch.toggle(False)
            self.ping_timer.stop()
            self.ping_label.setText("Ping: --")
    
    def on_connection_state_changed(self, connected):
        """Handle connection state changes"""
        for i in range(self.checkbox_layout.count()):
            item = self.checkbox_layout.itemAt(i)
            if item and isinstance(item.widget(), ServerItem):
                server_item = item.widget()
                if server_item.checkbox.isChecked():
                    server_item.set_status(connected)
                else:
                    server_item.set_status(False)
    
    def on_status_changed(self, message, is_error):
        """Handle status changes"""
        # Update status label
        self.status_label.setText(message)
        
        # Mark as error in UI if needed
        if is_error:
            self.status_label.setStyleSheet("color: #F44336; background: transparent;")
            for i in range(self.checkbox_layout.count()):
                item = self.checkbox_layout.itemAt(i)
                if item and isinstance(item.widget(), ServerItem):
                    server_item = item.widget()
                    if server_item.checkbox.isChecked():
                        server_item.set_error()
        else:
            self.status_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); background: transparent;")
        
        # Show message box for important errors
        if is_error and not message.startswith("Connection lost"):
            QMessageBox.warning(self, "Connection Error", message)
    
    def delete_server(self, index):
        """Delete server at the specified index"""
        try:
            if 0 <= index < len(self.servers):
                server_name = self.servers[index].get('name', f'Server {index+1}')
                
                # Ask for confirmation
                reply = QMessageBox.question(
                    self, "Delete Server",
                    f"Are you sure you want to delete server '{server_name}'?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    # Disconnect if connected to this server
                    current_server = self.ss_client.get_current_server()
                    if current_server and current_server.get('key') == self.servers[index].get('key'):
                        self.toggle_connection(False)
                    
                    # Remove the server from the list
                    del self.servers[index]
                    self.save_servers()
                    self.refresh_server_list()
                    QMessageBox.information(self, "Success", f"Server '{server_name}' deleted.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete server: {e}")
    
    def parse_server_key(self, key):
        try:
            if not key.startswith('ss://'):
                return None, "Invalid key format. Must start with 'ss://'"

            # Use the imported parser from utils.ss_parser
            parsed = decode_ss_link(key)
            if not parsed:
                return None, "Failed to parse server key"
                
            # Create server data in our format
            server_data = {
                "key": key,
                "name": parsed.get('tag', 'Unknown Server'),
                "host": parsed.get('server', ''),
                "port": str(parsed.get('port', 443)),
                "method": parsed.get('method', 'aes-256-gcm'),
                "password": parsed.get('password', '')
            }
                
            return server_data, None

        except Exception as e:
            return None, f"Error parsing server key: {e}"
    
    def show_add_server_dialog(self):
        """Show dialog to add a new server"""
        dialog = AddServerDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            server_key = dialog.get_server_key()
            if server_key:
                server_data, error = self.parse_server_key(server_key)
                if server_data:
                    # Add to servers list
                    self.servers.append(server_data)
                    self.save_servers()
                    self.refresh_server_list()
                    
                    # Show success message with server details
                    message = f"Added server: {server_data['name']}\n\n" \
                             f"Host: {server_data['host']}\n" \
                             f"Port: {server_data['port']}\n" \
                             f"Encryption: {server_data['method']}"
                    QMessageBox.information(self, "Server Added", message)
                else:
                    QMessageBox.warning(self, "Error", error or "Failed to parse server key")
    
    def show_settings_dialog(self):
        """Show settings dialog"""
        dialog = SettingsDialog(
            self, 
            current_port=self.ss_client.local_port,
            auto_connect=self.settings.get("auto_connect", False)
        )
        if dialog.exec_() == QDialog.Accepted:
            # Get settings from dialog
            new_settings = dialog.get_settings()
            
            # Update settings
            self.settings["local_port"] = new_settings["local_port"]
            self.settings["auto_connect"] = new_settings["auto_connect"]
            self.save_settings()
            
            # Update client port
            previous_port = self.ss_client.local_port
            self.ss_client.local_port = new_settings["local_port"]
            
            # Update port display
            self.port_label.setText(f"Port: {self.ss_client.local_port}")
            
            # If port changed and connected, notify user reconnection is needed
            if previous_port != new_settings["local_port"] and self.ss_client.is_connected:
                reply = QMessageBox.question(
                    self, "Port Changed",
                    "Local port has changed. Do you want to reconnect to apply this change?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.toggle_connection(False)  # Disconnect
                    QTimer.singleShot(500, lambda: self.toggle_connection(True))  # Reconnect
    
    def on_checkbox_toggled(self, button, checked):
        if checked:
            checked_id = self.button_group.id(button)
            if 0 <= checked_id < len(self.servers):
                selected_server = self.servers[checked_id]
                self.add_log(f"Selected server: {selected_server.get('name', 'Unknown')} (ID: {checked_id})")
                
                # If currently connected, reconnect to the new server
                if self.ss_client.is_connected:
                    # Ask if user wants to switch
                    reply = QMessageBox.question(
                        self, "Switch Server",
                        f"Do you want to switch to server '{selected_server.get('name', 'Unknown')}'?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                    )
                    
                    if reply == QMessageBox.Yes:
                        self.toggle_connection(False)  # Disconnect first
                        QTimer.singleShot(500, lambda: self.toggle_connection(True))  # Then connect
    
    def add_log(self, message):
        """Add a message to the log"""
        # Timestamp the message
        timestamp = time.strftime("%H:%M:%S")
        full_message = f"[{timestamp}] {message}"
        
        # Add to log dialog
        self.log_dialog.add_log(full_message)
    
    def show_log_dialog(self):
        """Show the connection log dialog"""
        self.log_dialog.show()
        self.log_dialog.raise_()
    
    def update_ping(self):
        if not self.ss_client.is_connected:
            self.ping_label.setText("Ping: --")
            return
        
        try:
            current_server = self.ss_client.get_current_server()
            if current_server:
                host = 'google.com'
                socks5_port = int(self.ss_client.local_port)

                try:
                    ping_ms = http_ping_via_socks5_once(host, socks5_port, timeout=3)
                    if ping_ms is not None:
                        self.ping_label.setText(f"Ping: {ping_ms:.0f} ms")
                    else:
                        self.ping_label.setText("Ping: Error")
                except Exception:
                    self.ping_label.setText("Ping: Error")

        except Exception:
            self.ping_label.setText("Ping: --")

    
    def paintEvent(self, event):
        # Add subtle shadow effect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Draw shadow
        shadow_color = QColor(0, 0, 0, 40)
        shadow_radius = 20
        
        for i in range(shadow_radius, 0, -1):
            opacity = 40 - i
            if opacity > 0:
                shadow_color.setAlpha(opacity)
                p.setPen(QPen(shadow_color, 1))
                p.drawRoundedRect(
                    shadow_radius - i, 
                    shadow_radius - i, 
                    self.width() - 2 * (shadow_radius - i), 
                    self.height() - 2 * (shadow_radius - i), 
                    12, 12
                )
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Check if clicked in title bar region
            if event.y() <= self.title_bar.height() + 10:  # Add some extra space for ease of use
                self._dragging = True
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._dragging:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Disconnect if connected
        if self.ss_client.is_connected:
            self.ss_client.disconnect()
        
        # Close log dialog
        self.log_dialog.close()
        
        # Accept the event
        event.accept()