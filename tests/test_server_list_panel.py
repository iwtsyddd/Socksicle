"""Tests for ServerListPanel and AnimatedRadioButton optimizations."""
import pytest
from unittest.mock import MagicMock
from PySide6.QtGui import QFont

from ui.server_list_panel import ServerListPanel
from ui.server_item import ServerItem, AnimatedRadioButton
from utils.theme import M3Theme
from utils.server_model import Server, ProxyProtocol


@pytest.fixture(autouse=True)
def _qapp_available(qapp):
    return qapp


def test_animated_radio_button_cached_fonts():
    theme = M3Theme()
    radio = AnimatedRadioButton(theme)
    assert hasattr(radio, "_font_normal")
    assert hasattr(radio, "_font_bold")
    assert isinstance(radio._font_normal, QFont)
    assert isinstance(radio._font_bold, QFont)
    assert radio._font_bold.bold() is True
    assert radio._font_normal.bold() is False


def test_server_list_panel_fade_out_cb():
    theme = M3Theme()
    panel = ServerListPanel(theme)
    
    cb_called = []
    def on_done():
        cb_called.append(True)

    panel.fade_out(on_done)
    assert panel._fade_out_cb is on_done

    # Trigger fade animation finish
    panel._on_fade_anim_finished()
    assert len(cb_called) == 1
    assert panel._fade_out_cb is None

    # Triggering again when cb is None should not fail
    panel._on_fade_anim_finished()
    assert len(cb_called) == 1


def test_server_list_panel_refresh_updates_enabled():
    theme = M3Theme()
    panel = ServerListPanel(theme)

    srv = Server(name="Test Srv", host="1.1.1.1", port=443, protocol=ProxyProtocol.VLESS)
    
    # Verify refresh completes and updatesEnabled is True at the end
    panel.refresh([srv])
    assert panel.scroll_content.updatesEnabled() is True
    assert len(panel._server_items) == 1
