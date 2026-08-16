"""High-level connection orchestration using the engine abstraction.

Connection flow:

    DISCONNECTED -> CONNECTING -> [engine running?] -> [local SOCKS5 proxy
    responds to a handshake?] -> CONNECTED

On any failure the manager tears the engine down and returns to DISCONNECTED,
reporting the error through `statusChanged`. Connected-ness is verified by
actually probing the local proxy, never by waiting a fixed delay and
assuming success.
"""
import logging
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot, QThreadPool, QMetaObject, Qt

from .geo_utils import fetch_ip_info_via_proxy
from .ping import (http_ping_via_socks5_once, socks5_proxy_ready, ProxyPingJob,
                   PING_PROBE_HOST)
from .engines.engine_manager import get_current_engine
from .engines.base import DEFAULT_LOCAL_PORT

log = logging.getLogger("connection_manager")

PROBE_INTERVAL_MS = 300
PROBE_TIMEOUT_S = 25.0

GEO_RETRY_ATTEMPTS = 3
GEO_RETRY_PAUSE_S = 1.5
GEO_RETRY_INTERVAL_S = 10.0

DISCONNECTED = "disconnected"
CONNECTING = "connecting"
CONNECTED = "connected"


class ConnectionManager(QObject):
    statusChanged = Signal(str, bool)      # message, is_error
    connectionStateChanged = Signal(bool)  # connected
    logUpdated = Signal(str)               # engine output line
    geoInfoReady = Signal(dict)            # {ip, flag} after connect
    geoError = Signal(str)                 # reason when geo lookup failed
    pingResultReady = Signal(object)       # active ping in ms (None on error)

    def __init__(self, settings=None):
        super().__init__()
        self._settings = settings or {}
        self._engine = get_current_engine(self._settings)
        self._engine.statusChanged.connect(self._on_status_changed)
        self._engine.connectionStateChanged.connect(self._on_connection_state_changed)
        self._engine.logUpdated.connect(self.logUpdated)
        self.apply_settings()

        self.state = DISCONNECTED
        self.is_connecting = False
        self.current_geo = None
        self._generation = 0
        self._geo_last_attempt = 0.0

        self._probe_deadline = 0.0
        self.probe_timer = QTimer(self)
        self.probe_timer.setInterval(PROBE_INTERVAL_MS)
        self.probe_timer.timeout.connect(self._probe)

        self.ping_timer = QTimer(self)
        self.ping_timer.setInterval(5000)
        self.ping_timer.timeout.connect(self._update_ping)

    @property
    def engine(self):
        return self._engine

    @property
    def is_connected(self):
        return self.state == CONNECTED

    @property
    def local_port(self):
        return self._engine.local_port

    @local_port.setter
    def local_port(self, port):
        try:
            self._engine.local_port = int(port)
        except (TypeError, ValueError):
            self._engine.local_port = DEFAULT_LOCAL_PORT

    def apply_settings(self, settings=None):
        """Read settings and apply them to the engine."""
        if settings is not None:
            self._settings.update(settings)
        self.local_port = self._settings.get("local_port", DEFAULT_LOCAL_PORT)
        tun_mode = self._settings.get("tun_mode", False)
        if tun_mode:
            from .engines.base import EngineType
            from .engines.engine_manager import get_engine
            if getattr(self._engine, "engine_type", None) != EngineType.SINGBOX:
                self.switch_engine(get_engine(EngineType.SINGBOX))
            if hasattr(self._engine, "tun_mode"):
                self._engine.tun_mode = True
        elif hasattr(self._engine, "tun_mode"):
            self._engine.tun_mode = False

    @property
    def current_server(self):
        return self._engine.get_current_server()

    def switch_engine(self, engine):
        """Switch to a different engine instance."""
        if self.is_connected:
            self.disconnect()
        old_port = self._engine.local_port
        old = self._engine
        old.statusChanged.disconnect(self._on_status_changed)
        old.connectionStateChanged.disconnect(self._on_connection_state_changed)
        old.logUpdated.disconnect(self.logUpdated)
        self._engine = engine
        engine.statusChanged.connect(self._on_status_changed)
        engine.connectionStateChanged.connect(self._on_connection_state_changed)
        engine.logUpdated.connect(self.logUpdated)
        engine.local_port = old_port

    def toggle(self, server, connect=None):
        """Start or stop the proxy. Returns True when a connect was initiated."""
        if self.state == CONNECTING:
            self.disconnect()
            return False
        if connect is None:
            connect = not self.is_connected
        if connect:
            tun_mode = self._settings.get("tun_mode", False)
            proto_val = getattr(getattr(server, "protocol", None), "value", getattr(server, "protocol", ""))
            if tun_mode or proto_val == "hysteria2":
                from .engines.base import EngineType
                from .engines.engine_manager import get_engine
                if getattr(self._engine, "engine_type", None) != EngineType.SINGBOX:
                    log.info("Auto-switching engine to sing-box (TUN: %s, Protocol: %s)", tun_mode, proto_val)
                    self.switch_engine(get_engine(EngineType.SINGBOX))
                if hasattr(self._engine, "tun_mode"):
                    self._engine.tun_mode = bool(tun_mode)
            self.state = CONNECTING
            self.is_connecting = True
            self.current_geo = None
            self._generation += 1
            if self._engine.start(server):
                if threading.current_thread() is not threading.main_thread():
                    QMetaObject.invokeMethod(self, "_start_probe", Qt.QueuedConnection)
                else:
                    self._start_probe()
                return True
            self.state = DISCONNECTED
            self.is_connecting = False
        else:
            self.disconnect()
        return False

    @Slot()
    def _start_probe(self):
        self._probe_deadline = time.monotonic() + PROBE_TIMEOUT_S
        self.probe_timer.start()

    def disconnect(self):
        """Disconnect at any stage: failed start, crash, or mid-connect."""
        if threading.current_thread() is not threading.main_thread():
            QMetaObject.invokeMethod(self.probe_timer, "stop", Qt.QueuedConnection)
            QMetaObject.invokeMethod(self.ping_timer, "stop", Qt.QueuedConnection)
        else:
            self.probe_timer.stop()
            self.ping_timer.stop()
        self.state = DISCONNECTED
        self.is_connecting = False
        self.current_geo = None
        self._generation += 1
        self._engine.disconnect_from_server()

    def _probe(self):
        if not self._engine.is_running():
            self._handle_process_stopped()
        elif time.monotonic() > self._probe_deadline:
            self._fail("Failed to establish connection: local proxy did not respond")
        elif socks5_proxy_ready(int(self.local_port)):
            self._on_proxy_ready()

    def _on_proxy_ready(self):
        self.probe_timer.stop()
        self.state = CONNECTED
        self.is_connecting = False
        self._engine.confirm_connected()
        self.statusChanged.emit("Started", False)
        self.ping_timer.start()
        self._update_ping()
        self._geo_last_attempt = time.monotonic()
        threading.Thread(target=self._fetch_geo, daemon=True).start()

    def _fail(self, msg):
        self.probe_timer.stop()
        self.ping_timer.stop()
        self.state = DISCONNECTED
        self.is_connecting = False
        self._engine.teardown()
        self.statusChanged.emit(msg, True)

    def _handle_process_stopped(self):
        if self.state == CONNECTING:
            self.probe_timer.stop()
            self._engine.teardown()
            self.state = DISCONNECTED
            self.is_connecting = False
            code = self._engine.last_exit_code
            if code is not None:
                msg_fn = getattr(self._engine, 'exit_message', None)
                if msg_fn:
                    self.statusChanged.emit(msg_fn(code), True)
                else:
                    self.statusChanged.emit(
                        f"Engine exited with code {code}", True)
            else:
                self.statusChanged.emit("Connection failed", True)
        elif self.state == CONNECTED:
            self.ping_timer.stop()
            self._engine.teardown()
            self.state = DISCONNECTED
            self.is_connecting = False

    def _on_connection_state_changed(self, conn):
        if not conn and self.state in (CONNECTING, CONNECTED):
            self._handle_process_stopped()

    def _on_status_changed(self, msg, err):
        if err and self.state in (CONNECTING, CONNECTED):
            self.probe_timer.stop()
            self.ping_timer.stop()
            self.state = DISCONNECTED
            self.is_connecting = False
            self._engine.teardown()
        self.statusChanged.emit(msg, err)

    def _fetch_geo(self):
        gen = self._generation
        for _ in range(GEO_RETRY_ATTEMPTS):
            if self.state != CONNECTED or gen != self._generation:
                return
            info = fetch_ip_info_via_proxy(self.local_port)
            if info:
                if self.state == CONNECTED and gen == self._generation:
                    self.current_geo = info
                    self.geoInfoReady.emit(info)
                return
            time.sleep(GEO_RETRY_PAUSE_S)
        if self.state == CONNECTED and gen == self._generation:
            self.geoError.emit("geo unavailable")

    def _update_ping(self):
        if not self.is_connected:
            return
        if self.current_geo is None:
            now = time.monotonic()
            if now - self._geo_last_attempt >= GEO_RETRY_INTERVAL_S:
                self._geo_last_attempt = now
                threading.Thread(target=self._fetch_geo, daemon=True).start()
        gen = self._generation
        QThreadPool.globalInstance().start(ProxyPingJob(
            PING_PROBE_HOST, int(self.local_port),
            lambda ms, gen=gen: self._on_ping_result(gen, ms),
            method="http_head"))

    def _on_ping_result(self, gen, ms):
        """Forward a ping result, dropping results from older connections."""
        if gen != self._generation or not self.is_connected:
            return
        try:
            self.pingResultReady.emit(ms)
        except RuntimeError:
            log.debug("Ping result dropped: manager is shutting down")