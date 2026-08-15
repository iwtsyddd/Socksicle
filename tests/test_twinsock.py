"""Tests for the TwinSock v2 vault (utils/twinsock.py) and its integration."""
import base64
import json
import struct as struct_mod
import platform as platform_mod
import uuid
from pathlib import Path

import pytest

import utils.twinsock as tw


@pytest.fixture(autouse=True)
def vault_env(tmp_path, monkeypatch):
    monkeypatch.setattr(tw, "get_config_dir", lambda: tmp_path)
    tw._reset()
    yield
    tw._reset()


def _patch_machine(monkeypatch, host="hostA", mac=0x1234567890AB, sysname="Linux",
                   sysrel="6.1.0", machine="x86_64", processor="GenuineIntel",
                   bitness=64, home="/home/user"):
    monkeypatch.setattr(platform_mod, "node", lambda: host)
    monkeypatch.setattr(uuid, "getnode", lambda: mac)
    monkeypatch.setattr(platform_mod, "system", lambda: sysname)
    monkeypatch.setattr(platform_mod, "release", lambda: sysrel)
    monkeypatch.setattr(platform_mod, "machine", lambda: machine)
    monkeypatch.setattr(platform_mod, "processor", lambda: processor)
    monkeypatch.setattr(struct_mod, "calcsize", lambda fmt: 8 if bitness == 64 else 4)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(home)))


def _ss_link(host):
    import base64 as b64
    userinfo = b64.urlsafe_b64encode(b"aes-256-gcm:password").decode().rstrip("=")
    return f"ss://{userinfo}@{host}:8388#ServerOne"


def test_roundtrip_all_secret_fields(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    tw.unlock()
    assert tw.vault_status()["ok"] is True
    values = ["simple", "unicode key ✓", "x" * 300,
              "with spaces  and\ttabs", "1234567890!@#$%^&*()"]
    for purpose in ("manual", "subscriptions"):
        fields = tw.SECRET_FIELDS + (("url",) if purpose == "subscriptions" else ())
        for field in fields:
            for val in values:
                tok = tw.encrypt_field(purpose, val)
                assert tok.startswith("tws2.")
                assert tok != val
                assert tw.decrypt_field(purpose, tok) == val


def test_empty_string_not_tokenized(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    tw.unlock()
    assert tw.encrypt_field("manual", "") == ""
    assert tw.decrypt_field("manual", "") == ""
    assert tw.tokenize(b"k" * 32, "") == ""
    assert tw.detokenize(b"k" * 32, "") == ""


def test_component_change_reconciled_via_tier_b(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch, sysrel="6.1.0")
    tw.unlock()
    assert tw.vault_status()["tier"] == "A"
    tw.encrypt_field("manual", "hidden")
    draw_before = json.loads((tmp_path / "drawer.json").read_text(encoding="utf-8"))
    assert draw_before["schema"] == "socksicle-drawer"
    _patch_machine(monkeypatch, sysrel="6.8.12")
    tw._reset()
    assert tw.unlock() is True
    st = tw.vault_status()
    assert st["tier"] == "B"
    assert st["repaired"] is True
    draw_after = json.loads((tmp_path / "drawer.json").read_text(encoding="utf-8"))
    assert draw_after["secret_a"] != draw_before["secret_a"]
    tw._reset()
    assert tw.unlock() is True
    assert tw.vault_status()["tier"] == "A"
    assert tw.vault_status()["repaired"] is False
    tok = tw.encrypt_field("manual", "new")
    assert tw.decrypt_field("manual", tok) == "new"


def test_hostname_change_is_foreign(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch, host="hostA")
    tw.unlock()
    _patch_machine(monkeypatch, host="hostB")
    tw._reset()
    with pytest.raises(tw.VaultError) as exc:
        tw.unlock()
    assert "foreign" in str(exc.value)


def test_flip_byte_in_token_raises(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    k = b"K" * 32
    tok = tw.tokenize(k, "some secret data")
    payload = tok[5:]
    raw = bytearray(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    for flip_at in (10, 30, len(raw) - 1):
        raw2 = bytearray(raw)
        raw2[flip_at] ^= 0x01
        broken = "tws2." + base64.urlsafe_b64encode(bytes(raw2)).rstrip(b"=").decode("ascii")
        with pytest.raises(tw.VaultError):
            tw.detokenize(k, broken)


def test_same_plaintext_yields_different_tokens(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    tw.unlock()
    t1 = tw.encrypt_field("manual", "same-value")
    t2 = tw.encrypt_field("manual", "same-value")
    assert t1 != t2
    assert tw.decrypt_field("manual", t1) == "same-value"
    assert tw.decrypt_field("manual", t2) == "same-value"


def test_legacy_obfuscation_migrates(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    tw.unlock()
    token = tw._legacy_obfuscate("old-secret")
    assert token.startswith("__obfuscated__")
    assert tw.decrypt_field("manual", token) == "old-secret"
    assert tw.migration_occurred() is True
    assert tw.migration_occurred() is False
    assert tw._legacy_obfuscate("") == ""


def test_foreign_drawer_refused(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch, host="hostA", mac=0x11111111)
    tw.unlock()
    draw = json.loads((tmp_path / "drawer.json").read_text(encoding="utf-8"))
    assert draw["schema"] == "socksicle-drawer"
    _patch_machine(monkeypatch, host="hostB", mac=0x22222222)
    tw._reset()
    with pytest.raises(tw.VaultError) as exc:
        tw.unlock()
    assert "foreign" in str(exc.value)
    assert tw.vault_status() == {"ok": False, "tier": "", "repaired": False,
                                 "reason": "foreign"}
    after = json.loads((tmp_path / "drawer.json").read_text(encoding="utf-8"))
    assert after["secret_a"] == draw["secret_a"]
    assert after["secret_b"] == draw["secret_b"]


def test_subscription_seal_unseal(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import sub_manager as sbm
    monkeypatch.setattr(sbm, "get_config_dir", lambda: tmp_path)
    subs = [{
        "name": "Sub A",
        "url": "https://example.com/sub1",
        "servers": [
            {"key": "ss://raw1", "password": "pw-1", "uuid": "u1", "public_key": "pk1",
             "name": "s1", "host": "h1", "port": 8388, "method": "aes-256-gcm"},
            {"key": "", "password": "", "uuid": "", "public_key": "",
             "name": "s2", "host": "h2", "port": 8389,
             "method": "chacha20-ietf-poly1305"},
        ],
        "traffic": {"used": 1, "total": 100, "expire": 0},
    }]
    sbm.save_subscriptions(subs)
    raw = json.loads((tmp_path / "subscriptions.json").read_text(encoding="utf-8"))
    assert raw[0]["url"].startswith("tws2.")
    assert raw[0]["servers"][0]["password"].startswith("tws2.")
    assert raw[0]["servers"][0]["key"].startswith("tws2.")
    assert raw[0]["servers"][1]["password"] == ""
    assert raw[0]["name"] == "Sub A"
    assert raw[0]["servers"][0]["host"] == "h1"
    loaded = sbm.load_subscriptions()
    assert loaded[0]["url"] == "https://example.com/sub1"
    assert loaded[0]["servers"][0]["password"] == "pw-1"
    assert loaded[0]["servers"][0]["uuid"] == "u1"
    assert loaded[0]["servers"][0]["public_key"] == "pk1"
    assert loaded[0]["servers"][0]["key"] == "ss://raw1"
    assert loaded[0]["name"] == "Sub A"


def test_subscriptions_foreign_loads_empty(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch, host="hostA")
    from utils import sub_manager as sbm
    monkeypatch.setattr(sbm, "get_config_dir", lambda: tmp_path)
    sbm.save_subscriptions([{
        "name": "Sub", "url": "https://example.com/s",
        "servers": [{"key": "k", "password": "pw", "name": "s1", "host": "h",
                     "port": 1, "method": "m"}],
    }])
    _patch_machine(monkeypatch, host="hostB")
    tw._reset()
    assert sbm.load_subscriptions() == []


def test_export_import_roundtrip(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    from utils import sub_manager as sbm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(sbm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    srv = mgr.add_from_link(_ss_link("example.com"))
    assert srv is not None
    assert mgr.manual_servers[0].password == "password"
    subs = [{
        "name": "Sub",
        "url": "https://example.com/s",
        "servers": [{"key": "k1", "password": "pw-sub", "uuid": "", "public_key": "",
                     "name": "s1", "host": "h", "port": 1, "method": "m"}],
        "traffic": None,
    }]
    payload = tw.export_payload(mgr.manual_servers, subs)
    assert payload["schema"] == "socksicle-export"
    assert "note" in payload
    assert payload["manual_servers"][0]["password"] == "password"
    assert payload["subscriptions"][0]["servers"][0]["password"] == "pw-sub"
    manuals, subs2 = tw.import_payload(payload)
    assert len(manuals) == 1
    assert manuals[0].password == "password"
    assert manuals[0].host == "example.com"
    assert subs2[0]["url"] == "https://example.com/s"
    assert subs2[0]["servers"][0].password == "pw-sub"


def test_import_legacy_export_without_schema(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    legacy = tw._legacy_obfuscate("hidden-pw")
    data = {
        "manual_servers": [
            {"name": "a", "host": "h1", "port": 1, "method": "m",
             "password": "plainpw"},
            {"name": "b", "host": "h2", "port": 2, "method": "m",
             "password": legacy},
        ],
        "subscriptions": [],
    }
    manuals, subs = tw.import_payload(data)
    assert subs == []
    assert manuals[0].password == "plainpw"
    assert manuals[1].password == "hidden-pw"


def test_chain_detects_modification(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    tw.unlock()
    path = tmp_path / "servers.json"
    path.write_text("[]", encoding="utf-8")
    assert tw.file_intact("servers.json") is True
    tw.file_saved("servers.json")
    assert tw.file_intact("servers.json") is True
    path.write_text("[1]", encoding="utf-8")
    assert tw.file_intact("servers.json") is False
    assert tw.file_intact("drawer.json") is True


def test_server_manager_foreign_lifecycle(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch, host="hostA")
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    mgr.add_from_link(_ss_link("one.example"))
    assert len(mgr.manual_servers) == 1
    _patch_machine(monkeypatch, host="hostB")
    tw._reset()
    mgr2 = sm.ServerManager()
    assert mgr2.manual_servers == []
    mgr2.add_from_link(_ss_link("two.example"))
    assert len(mgr2.manual_servers) == 1
    retired = [p.name for p in tmp_path.iterdir() if ".foreign-" in p.name]
    assert any("servers.json.foreign-" in n for n in retired)
    assert any("drawer.json.foreign-" in n for n in retired)
    tw._reset()
    mgr3 = sm.ServerManager()
    assert len(mgr3.manual_servers) == 1
    assert mgr3.manual_servers[0].password == "password"
    assert mgr3.manual_servers[0].host == "two.example"


def test_empty_secret_fields_not_tokenized(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    srv = mgr.add_from_link(_ss_link("example.com"))
    srv.password = ""
    mgr.save_manual_servers()
    raw = json.loads((tmp_path / "servers.json").read_text(encoding="utf-8"))
    assert raw[0]["password"] == ""
    assert raw[0]["key"].startswith("tws2.")
    tw._reset()
    mgr2 = sm.ServerManager()
    assert mgr2.manual_servers[0].password == ""
    assert mgr2.manual_servers[0].key.startswith("ss://")


def test_plaintext_secret_migrates_on_save(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    (tmp_path / "servers.json").write_text(json.dumps([
        {"name": "legacy", "host": "h", "port": 8388, "method": "m",
         "password": "plain123"}
    ]), encoding="utf-8")
    mgr = sm.ServerManager()
    assert mgr.manual_servers[0].password == "plain123"
    raw = json.loads((tmp_path / "servers.json").read_text(encoding="utf-8"))
    assert raw[0]["password"].startswith("tws2.")
    tw._reset()
    mgr2 = sm.ServerManager()
    assert mgr2.manual_servers[0].password == "plain123"


def test_tws2_share_key_auto_generated_once(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    key = mgr.settings.get("tws2_share_key", "")
    assert key
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw.get("tws2_share_key") == key
    tw._reset()
    mgr2 = sm.ServerManager()
    assert mgr2.settings.get("tws2_share_key") == key
    tw._reset()
    mgr3 = sm.ServerManager()
    assert mgr3.settings.get("tws2_share_key") == key


def test_tws2_share_key_preexisting_preserved(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"tws2_share_key": "friend-key-123", "local_port": 10881}),
        encoding="utf-8")
    mgr = sm.ServerManager()
    assert mgr.settings.get("tws2_share_key") == "friend-key-123"
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw.get("tws2_share_key") == "friend-key-123"
    assert raw["local_port"] == 10881


def test_save_settings_keeps_existing_share_key(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    key = mgr.settings["tws2_share_key"]
    del mgr.settings["tws2_share_key"]
    mgr.save_settings()
    assert mgr.settings.get("tws2_share_key") == key
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw.get("tws2_share_key") == key


def test_share_roundtrip_server_link(vault_env):
    key = "test-share-key"
    link = _ss_link("share.example")
    tok = tw.encrypt_share(key, link)
    assert tok.startswith("tws2://")
    assert "ss://" not in tok
    assert tw.decrypt_share(key, tok) == link
    assert tw.decrypt_share(key, tok[len("tws2://"):]) == link


def test_share_roundtrip_subscription_url(vault_env):
    key = "sub-share-key-2026"
    url = "https://example.com/sub?token=abc123"
    tok = tw.encrypt_share(key, url)
    assert tok.startswith("tws2://")
    assert tw.decrypt_share(key, tok) == url


def test_share_b64url_key(vault_env):
    key = base64.urlsafe_b64encode(b"D" * 32).rstrip(b"=").decode("ascii")
    tok = tw.encrypt_share(key, "vless://uuid@host:443")
    assert tw.decrypt_share(key, tok) == "vless://uuid@host:443"


def test_share_flip_byte_raises(vault_env):
    key = "flip-key"
    tok = tw.encrypt_share(key, _ss_link("flip.example"))
    payload = tok[len("tws2://tws2."):]
    raw = bytearray(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    for flip_at in (10, 30, len(raw) - 1):
        raw2 = bytearray(raw)
        raw2[flip_at] ^= 0x01
        broken = "tws2://tws2." + base64.urlsafe_b64encode(bytes(raw2)).rstrip(b"=").decode("ascii")
        with pytest.raises(tw.VaultError):
            tw.decrypt_share(key, broken)


def test_share_wrong_key_raises(vault_env):
    link = _ss_link("wrong-key.example")
    tok = tw.encrypt_share("key-a", link)
    with pytest.raises(tw.VaultError):
        tw.decrypt_share("key-b", tok)


def test_share_empty_string(vault_env):
    assert tw.encrypt_share("any-key", "") == ""
    assert tw.decrypt_share("any-key", "") == ""


def test_share_passthrough_non_token(vault_env):
    key = "some-key"
    assert tw.decrypt_share(key, "ss://plain@h:8388#x") == "ss://plain@h:8388#x"
    assert tw.decrypt_share(key, "https://example.com/sub") == "https://example.com/sub"
    assert tw.decrypt_share(key, "random-text") == "random-text"