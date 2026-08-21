"""Shared pytest fixtures for the Socksicle test suite."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication singleton for Qt-based tests."""
    inst = QApplication.instance()
    if inst is None:
        inst = QApplication([])
    yield inst


@pytest.fixture(autouse=True)
def _mock_init_app_fonts(monkeypatch):
    """Prevent font file access violations in parallel xdist workers."""
    import utils.font_utils
    monkeypatch.setattr(utils.font_utils, "init_app_fonts", lambda: None)


@pytest.fixture(scope="session", autouse=True)
def _drain_qt_threadpool():
    """Let queued QRunnable work finish before the QApplication is destroyed."""
    yield
    try:
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(5000)
    except Exception:
        pass
