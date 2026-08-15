"""Startup provisioning orchestration (Qt-aware bridge).

Runs the Qt-free engine provisioning in a background QThread so the Qt UI
stays responsive and reports download progress into a progress dialog.

Supports all registered engines (sslocal, xray, sing-box).
"""
from collections import deque
import time

from PySide6.QtCore import (QCoreApplication, QEventLoop, QObject, QThread,
                            QTimer, Signal, Slot)
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from utils import ss_backend
from utils.distro_utils import get_ss_install_command
from utils.platform_utils import is_windows
from utils.server_manager import ServerManager
from utils.engines.engine_manager import (
    ensure_engine, EngineType, get_engine,
)

PROVISIONING_MESSAGE = "Downloading proxy backend\u2026"
DECLINED_REASON = "User declined backend download"

_BYTE_UNITS = ("KB", "MB", "GB", "TB")
_PROGRESS_WINDOW_S = 1.0          # rolling window for the speed average
_MIN_SPEED_WINDOW_S = 0.25        # minimum real measurement before speed/ETA


def format_bytes(num) -> str:
    """Compact human-readable byte count, e.g. ``512 B``, ``8.4 MB``."""
    if num < 1000:
        return f"{int(num)} B"
    value = float(num)
    for unit in _BYTE_UNITS:
        value /= 1000.0
        if value < 1000.0:
            return f"{_trim_one_decimal(value)} {unit}"
    return f"{_trim_one_decimal(value)} TB"


def _trim_one_decimal(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_duration(seconds) -> str:
    """Compact human duration: ``45 s``, ``2 m 5 s``, ``1 h 10 m``."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} m {secs} s"
    hours, mins = divmod(minutes, 60)
    return f"{hours} h {mins} m"


def format_status(downloaded, total, speed=0.0, eta_seconds=None) -> str:
    """One download-status line like ``8.4 MB / 12.5 MB · 2.1 MB/s``.

    ``total`` is None when the server gave no ``Content-Length`` (only the
    downloaded amount is shown); ``eta_seconds`` is only displayed once it
    can be estimated reliably (>= 1 s).
    """
    if total is None:
        parts = [format_bytes(downloaded)]
    else:
        parts = [f"{format_bytes(downloaded)} / {format_bytes(total)}"]
    if speed and speed > 0:
        parts.append(f"{format_bytes(speed)}/s")
    if eta_seconds is not None and eta_seconds >= 1:
        parts.append(f"~{format_duration(eta_seconds)} left")
    return " \u00b7 ".join(parts)


class ProgressTracker(QObject):
    """Bridges download progress callbacks into a QProgressDialog.

    Lives in the calling (GUI) thread; the worker's ``progress`` signal is
    delivered to :meth:`update` via a queued connection.  Per-chunk
    callbacks only record state (and the speed/ETA estimates); a QTimer
    (10 Hz) flushes the latest state into the dialog via :meth:`flush`.
    Batching matters: QProgressDialog's ``setValue()`` calls
    ``processEvents()`` when the dialog is modal, and updating it from
    every queued chunk opened a re-entrancy cascade that could starve the
    remaining progress events.  Speed is averaged over a rolling ~1 s
    window and only shown after a real measurement exists; ETA is only
    offered when the total size is known.
    """

    _FLUSH_INTERVAL_MS = 100

    def __init__(self, dialog, clock=time.monotonic):
        super().__init__()
        self._dialog = dialog
        self._clock = clock
        self._samples = deque()
        self._downloaded = 0
        self._total = None
        self._speed = 0.0
        self._eta = None
        self._timer = QTimer(self)
        self._timer.setInterval(self._FLUSH_INTERVAL_MS)
        self._timer.timeout.connect(self.flush)
        self._timer.start()

    @Slot(int, object)
    def update(self, downloaded: int, total) -> None:
        self._downloaded = downloaded
        if total is not None:
            self._total = total
        now = self._clock()
        self._samples.append((now, downloaded))
        cutoff = now - _PROGRESS_WINDOW_S
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()

        speed = 0.0
        eta = None
        if len(self._samples) >= 2:
            start_t, start_b = self._samples[0]
            span = now - start_t
            if span >= _MIN_SPEED_WINDOW_S:
                delta = downloaded - start_b
                if delta > 0:
                    speed = delta / span
                    if self._total is not None:
                        remaining = self._total - downloaded
                        if remaining > 0:
                            eta = remaining / speed
        self._speed = speed
        self._eta = eta

    @Slot()
    def flush(self) -> None:
        if self._total is not None:
            self._dialog.setMaximum(self._total)
            self._dialog.setValue(self._downloaded)
        self._dialog.setLabelText(
            PROVISIONING_MESSAGE + "\n"
            + format_status(self._downloaded, self._total,
                            self._speed, self._eta))

    @Slot()
    def stop(self) -> None:
        self.flush()
        self._timer.stop()


class _ProvisionWorker(QObject):
    """Calls ensure_engine() off the GUI thread, forwarding download
    progress, and reports the result."""

    finished = Signal(object)    # InstallResult
    progress = Signal(int, object)  # (downloaded_bytes, total_or_None)

    def __init__(self, engine_type):
        super().__init__()
        self._engine_type = engine_type

    @Slot()
    def run(self):
        try:
            result = ensure_engine(
                self._engine_type,
                progress_cb=lambda downloaded, total: self.progress.emit(
                    downloaded, total))
        except Exception as e:
            from utils.engines.base import InstallResult
            result = InstallResult(
                False, None, f"Unexpected provisioning error: {e}")
        self.finished.emit(result)


def ask_download_sslocal() -> bool:
    """Ask the user whether to download the sslocal backend.

    Returns True if the user accepted, False if declined.
    """
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle("Socksicle")
    msg.setText("Proxy backend not found.")
    msg.setInformativeText(
        "Would you like to download it automatically?\n\n"
        "Without it, you cannot connect to any server.")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.button(QMessageBox.Yes).setText("Download")
    msg.button(QMessageBox.No).setText("Skip")
    return msg.exec() == QMessageBox.Yes


def provision_backend(engine_type=None) -> object | None:
    """Ensure a usable proxy backend without blocking the UI thread.

    If engine_type is None, the currently selected engine from settings is used.
    """
    from utils.server_manager import ServerManager as _SM
    mgr = _SM()
    settings = mgr.settings

    if engine_type is None:
        engine_type_str = settings.get("engine", "sslocal")
        try:
            engine_type = EngineType(engine_type_str)
        except ValueError:
            engine_type = EngineType.SSLOCAL

    engine = get_engine(engine_type)
    binary = engine.find_binary()
    if binary is not None:
        check = engine.check_usable(binary)
        if check.usable:
            from utils.engines.base import InstallResult
            return InstallResult(True, binary, "Reusing existing backend.")

    if engine_type == EngineType.SSLOCAL and mgr.is_sslocal_declined():
        return None

    if not ask_download_sslocal():
        if engine_type == EngineType.SSLOCAL:
            mgr.set_sslocal_declined(True)
        return None

    dialog = QProgressDialog(PROVISIONING_MESSAGE, "Cancel", 0, 0)
    dialog.setWindowTitle("Socksicle")
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    tracker = ProgressTracker(dialog)

    thread = QThread()
    worker = _ProvisionWorker(engine_type)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(tracker.update)

    loop = QEventLoop()
    outcome = {}
    already_done = False

    def _finish(result):
        nonlocal already_done
        if already_done:
            return
        already_done = True
        outcome["result"] = result
        loop.quit()

    worker.finished.connect(_finish)
    dialog.canceled.connect(lambda: _finish(None))

    dialog.setMinimumDuration(600)
    thread.start()
    loop.exec()
    QCoreApplication.processEvents()
    tracker.stop()
    dialog.close()
    thread.quit()
    thread.wait()
    worker.deleteLater()
    return outcome.get("result")


def manual_install_instructions() -> str:
    """User-facing manual installation instructions for the current OS."""
    if is_windows():
        return (
            "1. Go to: https://github.com/shadowsocks/shadowsocks-rust/releases\n"
            "2. Download the latest Windows release and extract sslocal.exe\n"
            "3. Place sslocal.exe into:\n"
            "   %APPDATA%\\socksicle\\bin\\\n"
            "   (or add it to your PATH)\n"
            "   (You can also drop it into ./bin/sslocal/ next to the app)\n\n"
            "Alternative with Rust installed:\n"
            "   cargo install shadowsocks-rust")
    cmd = get_ss_install_command()
    return (f"{cmd}\n\n"
            "You can also drop the sslocal binary into ./bin/sslocal/ "
            "next to the app.")


def show_provisioning_failure(result: ss_backend.InstallResult) -> None:
    """Explain that automatic provisioning failed and how to proceed."""
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle("Backend Missing")
    msg.setText(
        "The Shadowsocks backend (sslocal) could not be installed "
        "automatically.")
    msg.setInformativeText("To install it manually:\n\n"
                           + manual_install_instructions())
    msg.setDetailedText(result.reason if result else "Provisioning cancelled.")
    msg.setStandardButtons(QMessageBox.Ok)
    msg.exec()