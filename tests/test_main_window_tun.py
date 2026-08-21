"""Tests for MainWindow TUN mode elevation and Linux capabilities handling."""
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import pytest
from PySide6.QtWidgets import QMessageBox

from ui.main_window import RoundedWindow
from utils.server_model import Server, ProxyProtocol
import utils.twinsock as tw


@pytest.fixture
def main_win(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(tw, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.server_manager.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.sub_manager.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.platform_utils.get_config_dir", lambda: tmp_path)
    tw._reset()
    tw.ensure_drawer()
    tw.unlock()

    win = RoundedWindow()
    test_srv = Server(
        name="Test TUN Server",
        host="1.2.3.4",
        port=8388,
        password="secretpassword",
        method="aes-256-gcm",
        protocol=ProxyProtocol.SHADOWSOCKS,
    )
    win.server_manager.manual_servers = [test_srv]
    win.manual_servers = [test_srv]
    win._refresh_server_list()
    if win.server_panel._server_items:
        win.server_panel._server_items[0].radio.setChecked(True)
    return win


def test_tun_linux_no_gui_elevation_when_caps_present(main_win, monkeypatch):
    """On Linux, TUN mode should NOT elevate GUI via elevate_restart if caps are present."""
    main_win.settings["tun_mode"] = True
    monkeypatch.setattr("utils.platform_utils.sys.platform", "linux")
    monkeypatch.setattr("sys.platform", "linux")

    elevate_called = []
    grant_called = []

    monkeypatch.setattr(main_win.connection_manager.engine, "find_binary", lambda: Path("/fake/sing-box"))
    monkeypatch.setattr("ui.main_window.RoundedWindow._ensure_backend", lambda self: True)
    monkeypatch.setattr("utils.platform_utils.elevate_restart", lambda: elevate_called.append(True))
    monkeypatch.setattr("utils.platform_utils.check_tun_capabilities", lambda p: True)
    monkeypatch.setattr("utils.platform_utils.grant_tun_capabilities", lambda p, parent_window=None: grant_called.append(p))
    monkeypatch.setattr(main_win.connection_manager, "toggle", lambda srv, connect: True)

    main_win.toggle_connection(True)

    assert len(elevate_called) == 0
    assert len(grant_called) == 0


def test_tun_linux_grants_caps_without_gui_restart(main_win, monkeypatch):
    """On Linux, missing capabilities trigger grant_tun_capabilities without restarting GUI."""
    main_win.settings["tun_mode"] = True
    monkeypatch.setattr("utils.platform_utils.sys.platform", "linux")
    monkeypatch.setattr("sys.platform", "linux")

    elevate_called = []
    grant_called = []

    checks = [False, True]
    monkeypatch.setattr(main_win.connection_manager.engine, "find_binary", lambda: Path("/fake/sing-box"))
    monkeypatch.setattr("ui.main_window.RoundedWindow._ensure_backend", lambda self: True)
    monkeypatch.setattr("utils.platform_utils.elevate_restart", lambda: elevate_called.append(True))
    monkeypatch.setattr("utils.platform_utils.check_tun_capabilities", lambda p: checks.pop(0) if checks else True)
    monkeypatch.setattr("utils.platform_utils.grant_tun_capabilities", lambda p, parent_window=None: grant_called.append(p) or True)
    monkeypatch.setattr(main_win.connection_manager, "toggle", lambda srv, connect: True)

    main_win.toggle_connection(True)

    assert len(elevate_called) == 0
    assert len(grant_called) == 1


def test_tun_linux_warns_and_aborts_when_grant_fails(main_win, monkeypatch):
    """On Linux, declining polkit prompt shows warning and aborts without restarting GUI."""
    main_win.settings["tun_mode"] = True
    monkeypatch.setattr("utils.platform_utils.sys.platform", "linux")
    monkeypatch.setattr("sys.platform", "linux")

    elevate_called = []
    grant_called = []
    warnings = []

    monkeypatch.setattr(main_win.connection_manager.engine, "find_binary", lambda: Path("/fake/sing-box"))
    monkeypatch.setattr("ui.main_window.RoundedWindow._ensure_backend", lambda self: True)
    monkeypatch.setattr("utils.platform_utils.elevate_restart", lambda: elevate_called.append(True))
    monkeypatch.setattr("utils.platform_utils.check_tun_capabilities", lambda p: False)
    monkeypatch.setattr("utils.platform_utils.grant_tun_capabilities", lambda p, parent_window=None: grant_called.append(p) or False)
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warnings.append((title, text)))

    main_win.toggle_connection(True)

    assert len(elevate_called) == 0
    assert len(grant_called) == 1
    assert len(warnings) == 1
    assert "TUN Privileges Required" in warnings[0][0]


def test_tun_windows_asks_for_uac_elevation_when_not_admin(main_win, monkeypatch):
    """On Windows, TUN mode prompts for UAC restart if not admin."""
    main_win.settings["tun_mode"] = True
    monkeypatch.setattr("utils.platform_utils.sys.platform", "win32")
    monkeypatch.setattr("sys.platform", "win32")

    elevate_called = []
    questions = []

    monkeypatch.setattr("ui.main_window.RoundedWindow._ensure_backend", lambda self: True)
    monkeypatch.setattr("utils.platform_utils.is_admin", lambda: False)
    monkeypatch.setattr("utils.platform_utils.elevate_restart", lambda: elevate_called.append(True))
    monkeypatch.setattr(QMessageBox, "question", lambda parent, title, text, buttons, default: questions.append((title, text)) or QMessageBox.Yes)

    main_win.toggle_connection(True)

    assert len(questions) == 1
    assert "Administrator Privileges Required" in questions[0][0]
    assert len(elevate_called) == 1
