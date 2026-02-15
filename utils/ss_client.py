import subprocess
import signal
import os
import time
import shutil
from PySide6.QtCore import QObject, QProcess, Signal, QTimer
from .distro_utils import check_ss_local, get_ss_install_command

class ShadowsocksProcess(QObject):
    statusChanged = Signal(str, bool)
    connectionStateChanged = Signal(bool)
    logUpdated = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.process = None
        self.local_port = "1080"
        self.is_connected = False
        self.current_server = None
        self.startup_timeout = 1500 # 1.5 сек на запуск
        self.startup_timer = QTimer()
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(self.handle_startup_timeout)
    
    def connect(self, server_data):
        if not check_ss_local():
            cmd = get_ss_install_command()
            self.statusChanged.emit(f"Error: sslocal not found. Run: {cmd}", True)
            return False
            
        if self.is_connected: self.disconnect()
        
        try:
            self.current_server = server_data
            if not self.process:
                self.process = QProcess()
                self.process.readyReadStandardOutput.connect(self.handle_stdout)
                self.process.readyReadStandardError.connect(self.handle_stderr)
                self.process.errorOccurred.connect(self.handle_error)
                self.process.finished.connect(self.handle_finished)
            
            program = "sslocal"
            server_addr = f"{server_data.get('host', '')}:{server_data.get('port', '443')}"
            local_addr = f"127.0.0.1:{self.local_port}"
            
            arguments = ["-s", server_addr, "-b", local_addr, "-m", server_data.get("method", "aes-256-gcm"), "-k", server_data.get("password", ""), "-U"]
            
            print(f"[Shadowsocks] Starting: {program} {' '.join(arguments[:4])} ...", flush=True)
            self.process.start(program, arguments)
            self.startup_timer.start(self.startup_timeout)
            return True
        except Exception as e:
            print(f"[Shadowsocks] Error: {e}", flush=True)
            self.statusChanged.emit(f"Connection failed: {str(e)}", True)
            return False
    
    def handle_startup_timeout(self):
        if self.process and self.process.state() == QProcess.Running:
            print("[Shadowsocks] Process is running.", flush=True)
            self.is_connected = True
            self.connectionStateChanged.emit(True)
            self.statusChanged.emit("Started", False)
        else:
            print("[Shadowsocks] Process failed to start or died immediately.", flush=True)
            self.statusChanged.emit("Failed to start sslocal", True)
            self.disconnect()

    def handle_stdout(self):
        if self.process:
            data = self.process.readAllStandardOutput().data().decode().strip()
            if data:
                print(f"[sslocal-out] {data}", flush=True)
                self.logUpdated.emit(data)
    
    def handle_stderr(self):
        if self.process:
            data = self.process.readAllStandardError().data().decode().strip()
            if data:
                print(f"[sslocal-err] {data}", flush=True)
                self.logUpdated.emit(f"Error: {data}")
    
    def handle_error(self, error):
        print(f"[Shadowsocks] QProcess error: {error}", flush=True)
        self.statusChanged.emit("Process error", True)
    
    def handle_finished(self, exit_code, exit_status):
        print(f"[Shadowsocks] Process finished with code {exit_code}", flush=True)
        if self.is_connected:
            self.statusChanged.emit("Connection lost", True)
        self.is_connected = False
        self.connectionStateChanged.emit(False)
        self.process = None
    
    def disconnect(self):
        if self.process:
            print("[Shadowsocks] Disconnecting...", flush=True)
            self.startup_timer.stop()
            self.process.terminate()
            if not self.process.waitForFinished(1000): self.process.kill()
            self.process = None
            self.is_connected = False
            self.connectionStateChanged.emit(False)
            self.statusChanged.emit("Disconnected", False)
    
    def get_current_server(self): return self.current_server
