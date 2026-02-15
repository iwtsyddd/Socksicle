import subprocess
import signal
import os
import time
import shutil
from PySide6.QtCore import QObject, QProcess, Signal, QTimer
from .distro_utils import check_ss_local, get_ss_install_command

class ShadowsocksProcess(QObject):
    """Class to manage the Shadowsocks local process using QProcess (shadowsocks-rust)"""
    statusChanged = Signal(str, bool)  # Message, is_error
    connectionStateChanged = Signal(bool)  # Connected state
    logUpdated = Signal(str)  # Log message
    
    def __init__(self):
        super().__init__()
        self.process = None
        self.local_port = "1080"
        self.is_connected = False
        self.current_server = None
        self.retry_count = 0
        self.max_retries = 3
        self.startup_timeout = 5000  # 5 seconds
        self.startup_timer = QTimer()
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(self.handle_startup_timeout)
    
    def connect(self, server_data):
        """Connect to a Shadowsocks server using sslocal"""
        if not check_ss_local():
            cmd = get_ss_install_command()
            self.statusChanged.emit(
                f"Error: sslocal not found.\nTo install it, run:\n{cmd}", 
                True
            )
            return False
            
        if self.is_connected:
            self.disconnect()
        
        try:
            # Store current server
            self.current_server = server_data
            
            # Create QProcess if needed
            if not self.process:
                self.process = QProcess()
                self.process.readyReadStandardOutput.connect(self.handle_stdout)
                self.process.readyReadStandardError.connect(self.handle_stderr)
                self.process.errorOccurred.connect(self.handle_error)
                self.process.finished.connect(self.handle_finished)
            
            # Prepare command arguments for sslocal (shadowsocks-rust)
            program = "sslocal"
            # sslocal uses -s (server_addr:port), -b (local_addr:port), -m (method), -k (password)
            # Use -U for both TCP and UDP relay
            server_addr = f"{server_data.get('host', '')}:{server_data.get('port', '443')}"
            local_addr = f"127.0.0.1:{self.local_port}"
            
            arguments = [
                "-s", server_addr,
                "-b", local_addr,
                "-m", server_data.get("method", "aes-256-gcm"),
                "-k", server_data.get("password", ""),
                "-U"  # Enable TCP and UDP relay
            ]
            
            # Log command (hide password)
            safe_args = arguments.copy()
            try:
                pwd_index = safe_args.index("-k") + 1
                safe_args[pwd_index] = "********"
            except (ValueError, IndexError):
                pass
            self.logUpdated.emit(f"Starting: {program} {' '.join(safe_args)}")
            
            # Start process
            self.process.start(program, arguments)
            
            # Start startup timeout timer
            self.startup_timer.start(self.startup_timeout)
            
            return True
                
        except Exception as e:
            self.statusChanged.emit(f"Connection failed: {str(e)}", True)
            self.logUpdated.emit(f"Error: {str(e)}")
            return False
    
    def handle_startup_timeout(self):
        """Handle startup timeout"""
        if self.process and self.process.state() == QProcess.Running:
            # Process is running, consider it successful
            self.is_connected = True
            self.connectionStateChanged.emit(True)
            self.statusChanged.emit(
                f"Connected to {self.current_server.get('name', 'Shadowsocks server')}", 
                False
            )
        else:
            # Process failed to start properly
            if self.retry_count < self.max_retries:
                self.retry_count += 1
                self.logUpdated.emit(f"Retry attempt {self.retry_count}/{self.max_retries}")
                self.connect(self.current_server)
            else:
                self.statusChanged.emit("Failed to start after retries", True)
                self.disconnect()
    
    def handle_stdout(self):
        """Handle process stdout"""
        if self.process:
            data = self.process.readAllStandardOutput().data().decode()
            if data:
                self.logUpdated.emit(data.strip())
    
    def handle_stderr(self):
        """Handle process stderr"""
        if self.process:
            data = self.process.readAllStandardError().data().decode()
            if data:
                self.logUpdated.emit(f"Error: {data.strip()}")
    
    def handle_error(self, error):
        """Handle process errors"""
        error_msg = {
            QProcess.FailedToStart: "Failed to start sslocal",
            QProcess.Crashed: "Process crashed",
            QProcess.Timedout: "Process timed out",
            QProcess.WriteError: "Write error",
            QProcess.ReadError: "Read error",
            QProcess.UnknownError: "Unknown error"
        }.get(error, "Process error")
        
        self.statusChanged.emit(f"Error: {error_msg}", True)
    
    def handle_finished(self, exit_code, exit_status):
        """Handle process finish"""
        if exit_code != 0:
            self.statusChanged.emit(f"Process exited with code {exit_code}", True)
        
        self.is_connected = False
        self.connectionStateChanged.emit(False)
        self.process = None
    
    def disconnect(self):
        """Disconnect from the current server"""
        if self.process:
            self.startup_timer.stop()
            self.retry_count = 0
            
            # Try to terminate gracefully first
            self.logUpdated.emit("Disconnecting...")
            self.process.terminate()
            
            # Wait for process to terminate
            if not self.process.waitForFinished(2000):  # 2 seconds timeout
                self.logUpdated.emit("Force killing process...")
                self.process.kill()
            
            self.process = None
            self.is_connected = False
            self.connectionStateChanged.emit(False)
            self.statusChanged.emit("Disconnected", False)
    
    def get_current_server(self):
        """Get the currently connected server data"""
        return self.current_server
