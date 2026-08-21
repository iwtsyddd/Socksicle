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


@pytest.fixture(autouse=True)
def _flush_qt_events(qapp):
    """Flush any deferred deletions and queued events after each test."""
    yield
    inst = QApplication.instance()
    if inst is not None:
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        inst.processEvents()
