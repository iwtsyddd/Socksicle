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
