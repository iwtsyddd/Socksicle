import subprocess
import signal
import os
import time
from PyQt5.QtCore import QObject, QProcess, pyqtSignal, QTimer

class ShadowsocksProcess(QObject):
    """Class to manage the Shadowsocks local process using QProcess"""
    statusChanged = pyqtSignal(str, bool)  # Message, is_error
    connectionStateChanged = pyqtSignal(bool)  # Connected state
    logUpdated = pyqtSignal(str)  # Log message
    
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
        
    def check_ss_local(self):
        """Check if ss-local is available in PATH"""
        try:
            subprocess.run(["which", "ss-local"], 
                         check=True, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
            return True
        except subprocess.CalledProcessError:
            return False
    
    def connect(self, server_data):
        """Connect to a Shadowsocks server using QProcess"""
        if not self.check_ss_local():
            self.statusChanged.emit(
                "Error: ss-local not found. Please install shadowsocks-libev package.", 
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
            
            # Prepare command arguments
            program = "ss-local"
            arguments = [
                "-s", server_data.get("host", ""),
                "-p", server_data.get("port", "443"),
                "-l", self.local_port,
                "-m", server_data.get("method", "aes-256-gcm"),
                "-k", server_data.get("password", ""),
                "-u"  # Enable UDP relay
            ]
            
            # Log command (hide password)
            safe_args = arguments.copy()
            pwd_index = safe_args.index("-k") + 1
            safe_args[pwd_index] = "********"
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
            self.logUpdated.emit(data.strip())
    
    def handle_stderr(self):
        """Handle process stderr"""
        if self.process:
            data = self.process.readAllStandardError().data().decode()
            self.logUpdated.emit(f"Error: {data.strip()}")
    
    def handle_error(self, error):
        """Handle process errors"""
        error_msg = {
            QProcess.FailedToStart: "Failed to start ss-local",
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