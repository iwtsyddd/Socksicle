import pytest
from utils.killswitch import KillSwitchManager, _resolve_ip


def test_resolve_ip():
    assert _resolve_ip("1.1.1.1") == "1.1.1.1"
    assert _resolve_ip("127.0.0.1") == "127.0.0.1"
    assert _resolve_ip("") is None


def test_killswitch_singleton():
    ks1 = KillSwitchManager.get_instance()
    ks2 = KillSwitchManager.get_instance()
    assert ks1 is ks2


def test_killswitch_non_admin(monkeypatch):
    monkeypatch.setattr("utils.killswitch.is_admin", lambda: False)
    ks = KillSwitchManager()
    assert ks.enable("1.2.3.4", 443) is False
    assert ks.is_active is False


def test_killswitch_enable_disable_windows(monkeypatch):
    monkeypatch.setattr("utils.killswitch.is_admin", lambda: True)
    monkeypatch.setattr("utils.killswitch.is_windows", lambda: True)
    monkeypatch.setattr("utils.killswitch.is_linux", lambda: False)

    executed_cmds = []

    class DummyProc:
        returncode = 0
        stderr = ""

    def fake_run_netsh(self, args):
        executed_cmds.append(args)
        return DummyProc()

    monkeypatch.setattr(KillSwitchManager, "_run_netsh", fake_run_netsh)

    ks = KillSwitchManager()
    ok = ks.enable("1.2.3.4", 443, engine_path="C:\\test\\xray.exe")
    assert ok is True
    assert ks.is_active is True

    # Verify allow rules and block rule were generated
    assert any("Socksicle_KS_AllowLoopback" in " ".join(cmd) for cmd in executed_cmds)
    assert any("Socksicle_KS_AllowLAN" in " ".join(cmd) for cmd in executed_cmds)
    assert any("Socksicle_KS_AllowServer" in " ".join(cmd) for cmd in executed_cmds)
    assert any("Socksicle_KS_BlockOut" in " ".join(cmd) for cmd in executed_cmds)

    # Disable
    ks.disable()
    assert ks.is_active is False


def test_killswitch_emergency_cleanup(monkeypatch):
    monkeypatch.setattr("utils.killswitch.is_admin", lambda: True)
    monkeypatch.setattr("utils.killswitch.is_windows", lambda: True)
    deleted_rules = []

    def fake_run_netsh(self, args):
        if "delete" in args:
            deleted_rules.append(args)
        class DummyProc:
            returncode = 0
            stderr = ""
        return DummyProc()

    monkeypatch.setattr(KillSwitchManager, "_run_netsh", fake_run_netsh)

    ks = KillSwitchManager()
    ks.clean_stale_rules()
    assert len(deleted_rules) >= 5
