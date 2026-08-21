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

from PySide6.QtCore import QObject, QTimer, Signal, Slot, QThreadPool, QMetaObject, Qt, QRunnable, Q_ARG

from .geo_utils import fetch_ip_info_via_proxy
from .ping import (http_ping_via_socks5_once, socks5_proxy_ready, ProxyPingJob,
                   PING_PROBE_HOST)
from .engines.engine_manager import get_current_engine
from .engines.base import DEFAULT_LOCAL_PORT

log = logging.getLogger("connection_manager")

PROBE_INTERVAL_MS = 250
PROBE_TIMEOUT_S = 25.0

GEO_RETRY_ATTEMPTS = 3
GEO_RETRY_PAUSE_S = 1.5
GEO_RETRY_INTERVAL_S = 10.0

DISCONNECTED = "disconnected"
CONNECTING = "connecting"
CONNECTED = "connected"


class _AsyncProbeJob(QRunnable):
    """Probe SOCKS5 proxy readiness in a worker thread without blocking the GUI event loop."""

    def __init__(self, manager, gen: int, port: int):
        super().__init__()
        self.manager = manager
        self.gen = gen
        self.port = port

    def run(self):
        ready = False
        try:
            ready = socks5_proxy_ready(self.port, timeout=0.25)
        except Exception:
            ready = False
        if threading.current_thread() is not threading.main_thread():
            QMetaObject.invokeMethod(
                self.manager, "_on_async_probe_result",
                Qt.QueuedConnection,
                Q_ARG(int, self.gen),
                Q_ARG(bool, ready)
            )
        else:
            self.manager._on_async_probe_result(self.gen, ready)


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
        self._probing_in_flight = False
        self._last_connected_server = None
        self._auto_reconnect_attempts = 0
        self.MAX_AUTO_RECONNECTS = 3

        self._probe_deadline = 0.0
        self.probe_timer = QTimer(self)
        self.probe_timer.setInterval(PROBE_INTERVAL_MS)
        self.probe_timer.timeout.connect(self._probe)

        self.ping_timer = QTimer(self)
        self.ping_timer.setInterval(60000)  # Ping once per minute
        self.ping_timer.timeout.connect(self._update_ping)

    @property
    def engine(self):
        return self._engine

    @property
    def is_connected(self):
        return self.state == CONNECTED

    @property
    def is_reconnecting(self):
        return self._auto_reconnect_attempts > 0 and self.state != CONNECTED

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
        custom_dns = self._settings.get("custom_dns", None)
        if hasattr(self._engine, "custom_dns"):
            self._engine.custom_dns = custom_dns
        self.kill_switch_enabled = bool(self._settings.get("kill_switch", False))
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
        try:
            old.statusChanged.disconnect(self._on_status_changed)
        except (RuntimeError, TypeError):
            pass
        try:
            old.connectionStateChanged.disconnect(self._on_connection_state_changed)
        except (RuntimeError, TypeError):
            pass
        try:
            old.logUpdated.disconnect(self.logUpdated)
        except (RuntimeError, TypeError):
            pass
        self._engine = engine
        engine.statusChanged.connect(self._on_status_changed)
        engine.connectionStateChanged.connect(self._on_connection_state_changed)
        engine.logUpdated.connect(self.logUpdated)
        engine.local_port = old_port

    def toggle(self, server, connect=None):
        """Start or stop the proxy. Returns True when a connect was initiated."""
        if connect is None:
            if self.state == CONNECTING:
                self.disconnect()
                return False
            connect = not self.is_connected

        if connect:
            if server is None:
                return False

            self._last_connected_server = server

            # Hot-reconnect: if already connecting or connected, gracefully disconnect previous instance first
            if self.state in (CONNECTING, CONNECTED) or self._engine.is_running():
                self.disconnect()
                self._last_connected_server = server

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
            curr_gen = self._generation

            if self._engine.start(server):
                # Verify that no disconnect/new connect happened while start() was executing
                if self.state == CONNECTING and self._generation == curr_gen:
                    if threading.current_thread() is not threading.main_thread():
                        QMetaObject.invokeMethod(self, "_start_probe", Qt.QueuedConnection)
                    else:
                        self._start_probe()
                    return True
                else:
                    self._engine.teardown()
                    return False
            self.state = DISCONNECTED
            self.is_connecting = False
        else:
            self._last_connected_server = None
            self._auto_reconnect_attempts = 0
            self.disconnect()
        return False

    @Slot()
    def _start_probe(self):
        self._probing_in_flight = False
        self._probe_deadline = time.monotonic() + PROBE_TIMEOUT_S
        self.probe_timer.start()

    def disconnect(self):
        """Disconnect at any stage: failed start, crash, or mid-connect."""
        self._probing_in_flight = False
        try:
            from .killswitch import KillSwitchManager
            KillSwitchManager.get_instance().disable()
        except Exception as e:
            log.debug("Kill switch disable failed on disconnect: %s", e)
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
            return
        if time.monotonic() > self._probe_deadline:
            self._fail("Failed to establish connection: local proxy did not respond")
            return
        if self._probing_in_flight:
            return
        self._probing_in_flight = True
        QThreadPool.globalInstance().start(
            _AsyncProbeJob(self, self._generation, int(self.local_port))
        )

    @Slot(int, bool)
    def _on_async_probe_result(self, gen: int, ready: bool):
        self._probing_in_flight = False
        if gen != self._generation or self.state != CONNECTING:
            return
        if not self._engine.is_running():
            self._handle_process_stopped()
            return
        if ready:
            self._on_proxy_ready()
        elif time.monotonic() > self._probe_deadline:
            self._fail("Failed to establish connection: local proxy did not respond")

    def _on_proxy_ready(self):
        self._probing_in_flight = False
        self._auto_reconnect_attempts = 0
        self.probe_timer.stop()
        self.state = CONNECTED
        self.is_connecting = False
        self._engine.confirm_connected()
        self.statusChanged.emit("Started", False)
        if getattr(self, "kill_switch_enabled", False) and self.current_server:
            try:
                from .killswitch import KillSwitchManager
                bin_path = getattr(self._engine, "binary_path", None) or self._engine.find_binary()
                KillSwitchManager.get_instance().enable(
                    self.current_server.host,
                    self.current_server.port,
                    bin_path
                )
            except Exception as e:
                log.warning("Failed to enable Kill Switch on proxy connect: %s", e)
        self.ping_timer.start()
        self._geo_last_attempt = time.monotonic()
        self._update_ping()
        threading.Thread(target=self._fetch_geo, daemon=True).start()

    def _fail(self, msg):
        self._probing_in_flight = False
        try:
            from .killswitch import KillSwitchManager
            KillSwitchManager.get_instance().disable()
        except Exception:
            pass
        self.probe_timer.stop()
        self.ping_timer.stop()
        self.state = DISCONNECTED
        self.is_connecting = False
        self._engine.teardown()
        self.statusChanged.emit(msg, True)

    def _handle_process_stopped(self):
        self._probing_in_flight = False
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
            last_server = self._last_connected_server
            self._engine.teardown()
            self.state = DISCONNECTED
            if last_server and self._auto_reconnect_attempts < self.MAX_AUTO_RECONNECTS:
                self._auto_reconnect_attempts += 1
                self.is_connecting = True
                log.info("Engine exited unexpectedly while connected. Auto-reconnecting immediately (attempt %d/%d)...",
                         self._auto_reconnect_attempts, self.MAX_AUTO_RECONNECTS)
                self.statusChanged.emit(f"⚡ Reconnecting ({self._auto_reconnect_attempts}/{self.MAX_AUTO_RECONNECTS})...", False)
                QTimer.singleShot(150, lambda s=last_server: self.toggle(s, True))
            else:
                self.is_connecting = False
                self._last_connected_server = None
                self._auto_reconnect_attempts = 0
                self.statusChanged.emit("Connection lost", True)

    def _on_connection_state_changed(self, conn):
        if not conn and self.state in (CONNECTING, CONNECTED):
            self._handle_process_stopped()

    def _on_status_changed(self, msg, err):
        if err and self.state in (CONNECTING, CONNECTED):
            if self.state == CONNECTED and self._last_connected_server and self._auto_reconnect_attempts < self.MAX_AUTO_RECONNECTS:
                pass
            else:
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
                    try:
                        self.geoInfoReady.emit(info)
                    except (RuntimeError, ReferenceError):
                        return
                return
            for _ in range(int(GEO_RETRY_PAUSE_S * 10)):
                if self.state != CONNECTED or gen != self._generation:
                    return
                time.sleep(0.1)
        if self.state == CONNECTED and gen == self._generation:
            try:
                self.geoError.emit("geo unavailable")
            except (RuntimeError, ReferenceError):
                return

    def _update_ping(self):
        if not self.is_connected:
            return
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