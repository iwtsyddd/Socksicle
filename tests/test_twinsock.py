"""Tests for the TwinSock v3 vault (utils/twinsock.py) and its integration."""
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
                   bitness=64, home="/home/user", machine_guid="guid-1234"):
    monkeypatch.setattr(platform_mod, "node", lambda: host)
    monkeypatch.setattr(uuid, "getnode", lambda: mac)
    monkeypatch.setattr(platform_mod, "system", lambda: sysname)
    monkeypatch.setattr(platform_mod, "release", lambda: sysrel)
    monkeypatch.setattr(platform_mod, "machine", lambda: machine)
    monkeypatch.setattr(platform_mod, "processor", lambda: processor)
    monkeypatch.setattr(struct_mod, "calcsize", lambda fmt: 8 if bitness == 64 else 4)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(home)))
    monkeypatch.setattr(tw, "_get_machine_id", lambda: machine_guid)


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
                assert tok.startswith("tws3.")
                assert tok != val
                assert tw.decrypt_field(purpose, tok) == val


def test_v3_token_version_and_layout(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    tw.unlock()
    tok = tw.encrypt_field("manual", "test-secret")
    assert tok.startswith("tws3.")
    raw = tw._b64url_decode(tok[5:])
    assert raw[0] == 0x03  # v3 version byte
    # 1 byte ver + 12 byte nonce + 16 byte AES-GCM tag + len("test-secret")
    assert len(raw) == 1 + 12 + 16 + len("test-secret")


def test_mac_change_does_not_break_v3_vault(vault_env, monkeypatch):
    """Regression test for v2.1 UX bug: changing MAC address / uuid.getnode()

    must not lock out the user as long as MachineGuid / machine_id is stable.
    """
    _patch_machine(monkeypatch, mac=0x11111111, machine_guid="stable-guid")
    tw.unlock()
    tok = tw.encrypt_field("manual", "keep-me-safe")

    # Simulate network adapter change / VPN connection
    _patch_machine(monkeypatch, mac=0x99999999, machine_guid="stable-guid")
    tw._reset()
    assert tw.unlock() is True
    assert tw.vault_status()["tier"] == "A"
    assert tw.vault_status()["repaired"] is False
    assert tw.decrypt_field("manual", tok) == "keep-me-safe"


def test_empty_string_not_tokenized(vault_env, monkeypatch):
    _patch_machine(monkeypatch)
    tw.unlock()
    assert tw.encrypt_field("manual", "") == ""
    assert tw.decrypt_field("manual", "") == ""
    assert tw.tokenize(b"k" * 32, "") == ""
    assert tw.detokenize(b"k" * 32, "") == ""


def test_kernel_release_update_does_not_affect_tier_a(vault_env, monkeypatch):
    """Kernel updates (e.g. 6.18.42 -> 6.18.43) must NOT trigger Tier B repair in v3."""
    _patch_machine(monkeypatch, sysrel="6.18.42", machine_guid="stable-guid")
    tw.unlock()
    assert tw.vault_status()["tier"] == "A"
    tok = tw.encrypt_field("manual", "data-under-kernel-update")

    _patch_machine(monkeypatch, sysrel="6.18.43", machine_guid="stable-guid")
    tw._reset()
    assert tw.unlock() is True
    assert tw.vault_status()["tier"] == "A"
    assert tw.vault_status()["repaired"] is False
    assert tw.decrypt_field("manual", tok) == "data-under-kernel-update"


def test_component_change_reconciled_via_tier_b(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch, machine_guid="guid-A")
    tw.unlock()
    assert tw.vault_status()["tier"] == "A"
    tw.encrypt_field("manual", "hidden")
    draw_before = json.loads((tmp_path / "drawer.json").read_text(encoding="utf-8"))
    assert draw_before["schema"] == "socksicle-drawer"
    assert draw_before["version"] == 3

    # machine_guid changes (e.g. system re-provisioning), but durable components remain
    _patch_machine(monkeypatch, machine_guid="guid-B")
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
    _patch_machine(monkeypatch, host="hostA", machine_guid="guid-A")
    tw.unlock()
    _patch_machine(monkeypatch, host="hostB", machine_guid="guid-B")
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
    for flip_at in (1, 10, len(raw) - 1):
        raw2 = bytearray(raw)
        raw2[flip_at] ^= 0x01
        broken = "tws3." + base64.urlsafe_b64encode(bytes(raw2)).rstrip(b"=").decode("ascii")
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
    _patch_machine(monkeypatch, host="hostA", mac=0x11111111, machine_guid="guid-A")
    tw.unlock()
    draw = json.loads((tmp_path / "drawer.json").read_text(encoding="utf-8"))
    assert draw["schema"] == "socksicle-drawer"
    assert draw["version"] == 3

    _patch_machine(monkeypatch, host="hostB", mac=0x22222222, machine_guid="guid-B")
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
    assert raw[0]["url"].startswith("tws3.")
    assert raw[0]["servers"][0]["password"].startswith("tws3.")
    assert raw[0]["servers"][0]["key"].startswith("tws3.")
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
    _patch_machine(monkeypatch, host="hostA", machine_guid="guid-A")
    from utils import sub_manager as sbm
    monkeypatch.setattr(sbm, "get_config_dir", lambda: tmp_path)
    sbm.save_subscriptions([{
        "name": "Sub", "url": "https://example.com/s",
        "servers": [{"key": "k", "password": "pw", "name": "s1", "host": "h",
                     "port": 1, "method": "m"}],
    }])
    _patch_machine(monkeypatch, host="hostB", machine_guid="guid-B")
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
    _patch_machine(monkeypatch, host="hostA", machine_guid="guid-A")
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    mgr.add_from_link(_ss_link("one.example"))
    assert len(mgr.manual_servers) == 1
    _patch_machine(monkeypatch, host="hostB", machine_guid="guid-B")
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
    assert raw[0]["key"].startswith("tws3.")
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
    assert raw[0]["password"].startswith("tws3.")
    tw._reset()
    mgr2 = sm.ServerManager()
    assert mgr2.manual_servers[0].password == "plain123"


def test_tws3_share_key_auto_generated_for_new_user(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    key = mgr.settings.get("tws3_share_key", "")
    assert key
    assert "tws2_share_key" not in mgr.settings
    assert mgr.has_legacy_tws2_key() is False
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw.get("tws3_share_key") == key
    assert "tws2_share_key" not in raw


def test_tws2_share_key_preserved_as_legacy_until_upgrade(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"tws2_share_key": "friend-key-123", "local_port": 10881}),
        encoding="utf-8")
    mgr = sm.ServerManager()
    assert mgr.settings.get("tws2_share_key") == "friend-key-123"
    assert mgr.has_legacy_tws2_key() is True
    assert mgr.get_share_key() == "friend-key-123"

    # Now upgrade
    new_v3_key = mgr.upgrade_to_tws3_share_key()
    assert new_v3_key != "friend-key-123"
    assert mgr.settings.get("tws3_share_key") == new_v3_key
    assert "tws2_share_key" not in mgr.settings
    assert mgr.has_legacy_tws2_key() is False


def test_save_settings_keeps_existing_share_key(vault_env, monkeypatch, tmp_path):
    _patch_machine(monkeypatch)
    from utils import server_manager as sm
    monkeypatch.setattr(sm, "get_config_dir", lambda: tmp_path)
    mgr = sm.ServerManager()
    key = mgr.settings["tws3_share_key"]
    del mgr.settings["tws3_share_key"]
    mgr.save_settings()
    assert mgr.settings.get("tws3_share_key") == key
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw.get("tws3_share_key") == key


def test_share_roundtrip_server_link(vault_env):
    key = "test-share-key"
    link = _ss_link("share.example")
    tok = tw.encrypt_share(key, link)
    assert tok.startswith("tws3://")
    assert not tok.startswith("tws3://tws3.")
    assert "ss://" not in tok
    raw = tw._b64url_decode(tok[len("tws3://"):])
    assert raw[0] == 0x03  # v3
    assert tw.decrypt_share(key, tok) == link
    assert tw.decrypt_share(key, tok[len("tws3://"):]) == link


def test_share_legacy_token_and_bare_token_support(vault_env):
    key = "test-share-key"
    link = _ss_link("legacy.example")
    clean_tok = tw.encrypt_share(key, link)
    b64_part = clean_tok[len("tws3://"):]

    # Legacy prefix tws3://tws3.<b64url>
    legacy_tok = "tws3://tws3." + b64_part
    assert tw.decrypt_share(key, legacy_tok) == link

    # Bare token tws3.<b64url>
    bare_tok = "tws3." + b64_part
    assert tw.decrypt_share(key, bare_tok) == link


def test_share_default_key_and_fallback(vault_env):
    link = _ss_link("public.example")

    # 1. Encrypt with default key (empty key argument)
    tok = tw.encrypt_share("", link)
    assert tok.startswith("tws3://")

    # Decrypt with empty key -> uses DEFAULT_SHARE_KEY
    assert tw.decrypt_share("", tok) == link

    # Decrypt with mismatched personal key -> automatic fallback to DEFAULT_SHARE_KEY
    assert tw.decrypt_share("my-personal-share-key", tok) == link

    # 2. Encrypt with specific personal key
    personal_tok = tw.encrypt_share("personal-key-123", link)
    assert tw.decrypt_share("personal-key-123", personal_tok) == link

    # Decrypting personal link with completely wrong key fails
    with pytest.raises(tw.VaultError):
        tw.decrypt_share("completely-wrong-key-456", personal_tok)


def test_share_metadata_and_payload_roundtrip(vault_env):
    key = "meta-key"
    link = _ss_link("meta.example")
    expires = 1893456000  # Year 2030

    tok = tw.encrypt_share(key, link, lock_export=True, expires_at=expires)
    assert tok.startswith("tws3://")

    # Standard decrypt_share returns pure target link
    assert tw.decrypt_share(key, tok) == link

    # decrypt_share_payload returns target link and metadata dict
    target, meta = tw.decrypt_share_payload(key, tok)
    assert target == link
    assert meta["lock_export"] is True
    assert meta["expires_at"] == expires

    # Test link without metadata returns defaults
    tok_plain = tw.encrypt_share(key, link)
    target_plain, meta_plain = tw.decrypt_share_payload(key, tok_plain)
    assert target_plain == link
    assert meta_plain["lock_export"] is False
    assert meta_plain["expires_at"] is None


def test_server_model_lock_export_and_expiration():
    import time
    from utils.server_model import Server

    # Active server
    s_active = Server(name="Active", expires_at=int(time.time()) + 3600, lock_export=True)
    assert s_active.is_expired is False
    assert s_active.lock_export is True

    # Expired server
    s_expired = Server(name="Expired", expires_at=int(time.time()) - 10, lock_export=False)
    assert s_expired.is_expired is True

    # No expiration
    s_lifetime = Server(name="Lifetime", expires_at=None)
    assert s_lifetime.is_expired is False

    # Serialization roundtrip
    d = s_active.to_dict()
    assert d["lock_export"] is True
    assert d["expires_at"] == s_active.expires_at

    s_restored = Server.from_dict(d)
    assert s_restored.name == "Active"
    assert s_restored.lock_export is True
    assert s_restored.expires_at == s_active.expires_at
    assert s_restored.is_expired is False


def test_export_payload_excludes_locked_servers_and_subs():
    from utils.server_model import Server

    s_normal = Server(name="Normal Srv", host="normal.example")
    s_locked = Server(name="Locked Srv", host="locked.example", lock_export=True)

    sub_normal = {
        "name": "Normal Sub",
        "url": "https://example.com/sub",
        "servers": [s_normal, s_locked],
        "lock_export": False
    }
    sub_locked = {
        "name": "Locked Sub",
        "url": "https://example.com/sub_locked",
        "servers": [s_normal],
        "lock_export": True
    }

    payload = tw.export_payload([s_normal, s_locked], [sub_normal, sub_locked])

    # Manual servers: only s_normal exported
    assert len(payload["manual_servers"]) == 1
    assert payload["manual_servers"][0]["name"] == "Normal Srv"

    # Subscriptions: only sub_normal exported, and its inner servers exclude s_locked
    assert len(payload["subscriptions"]) == 1
    assert payload["subscriptions"][0]["name"] == "Normal Sub"
    assert len(payload["subscriptions"][0]["servers"]) == 1
    assert payload["subscriptions"][0]["servers"][0]["name"] == "Normal Srv"


def test_share_roundtrip_subscription_url(vault_env):
    key = "sub-share-key-2026"
    url = "https://example.com/sub?token=abc123"
    tok = tw.encrypt_share(key, url)
    assert tok.startswith("tws3://")
    assert tw.decrypt_share(key, tok) == url


def test_share_b64url_key(vault_env):
    key = base64.urlsafe_b64encode(b"D" * 32).rstrip(b"=").decode("ascii")
    tok = tw.encrypt_share(key, "vless://uuid@host:443")
    assert tw.decrypt_share(key, tok) == "vless://uuid@host:443"


def test_share_flip_byte_raises(vault_env):
    key = "flip-key"
    tok = tw.encrypt_share(key, _ss_link("flip.example"))
    payload = tok[len("tws3://"):]
    raw = bytearray(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    for flip_at in (1, 10, len(raw) - 1):
        raw2 = bytearray(raw)
        raw2[flip_at] ^= 0x01
        broken = "tws3://" + base64.urlsafe_b64encode(bytes(raw2)).rstrip(b"=").decode("ascii")
        with pytest.raises(tw.VaultError):
            tw.decrypt_share(key, broken)


def test_share_bundle_multiple_servers(vault_env):
    key = "bundle-test-key"
    links = [
        "ss://YWVzLTI1Ni1nY206cGFzc3dvcmRAMTI3LjAuMC4xOjgzODg=#Node%201",
        "vless://uuid-123@example.com:443?security=reality&type=grpc#Node%202",
        "hysteria2://user:pass@hy2.example.com:443#Node%203"
    ]
    tok = tw.encrypt_share(key, links, lock_export=True, expires_at=1893456000)
    assert tok.startswith("tws3://")

    target, metadata = tw.decrypt_share_payload(key, tok)
    assert isinstance(target, list)
    assert len(target) == 3
    assert target == links
    assert metadata["lock_export"] is True
    assert metadata["expires_at"] == 1893456000


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


def test_machine_id_discovery_paths(monkeypatch, tmp_path):
    # Test Linux /etc/machine-id reading
    m_file = tmp_path / "machine-id"
    m_file.write_text("linux-machine-id-value\n", encoding="utf-8")
    monkeypatch.setattr(tw.sys, "platform", "linux")
    monkeypatch.setattr(tw, "_read_file", lambda p: m_file.read_text(encoding="utf-8").strip() if "machine-id" in p else None)
    assert tw._get_machine_id() == "linux-machine-id-value"

    # Test fallback on other OS (e.g. darwin)
    monkeypatch.setattr(tw.sys, "platform", "darwin")
    monkeypatch.setattr(uuid, "getnode", lambda: 0xDEADBEEF)
    assert tw._get_machine_id() == str(0xDEADBEEF)


def test_add_server_dialog_hints_adapt_to_legacy_key(qapp):
    from utils.theme import M3Theme
    from ui.add_server_dialog import AddServerDialog

    # Pure v3 user
    dlg_v3 = AddServerDialog(theme=M3Theme(preset_key="lavender"), has_legacy_tws2=False)
    dlg_v3.input_field.setText("tws3://some_token")
    assert "TwinSock Share" in dlg_v3.hint_label.text()
    dlg_v3.input_field.setText("tws2://legacy_token")
    assert "Deprecated" in dlg_v3.hint_label.text()

    # Legacy v2 user
    dlg_v2 = AddServerDialog(theme=M3Theme(preset_key="lavender"), has_legacy_tws2=True)
    dlg_v2.input_field.setText("tws2://legacy_token")
    assert "TwinSock Share (Legacy)" in dlg_v2.hint_label.text()
    assert "Deprecated" not in dlg_v2.hint_label.text()


def test_settings_dialog_upgrade_tws3_button(qapp, monkeypatch):
    from utils.theme import M3Theme
    from ui.settings_dialog import SettingsDialog
    from PySide6.QtWidgets import QWidget, QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    # Fake parent with legacy tws2 key
    class _FakeLegacyParent(QWidget):
        def __init__(self):
            super().__init__()
            self.settings = {"tws2_share_key": "legacy-key-abc"}

    parent_v2 = _FakeLegacyParent()
    dlg_v2 = SettingsDialog(parent=parent_v2, theme=M3Theme(preset_key="lavender"))
    assert dlg_v2.is_legacy_tws2 is True
    assert dlg_v2.upgrade_tws3_btn is not None
    assert dlg_v2.tws_key_input.text() == "legacy-key-abc"

    # Click upgrade
    dlg_v2._on_upgrade_tws3_clicked()
    assert dlg_v2.is_legacy_tws2 is False
    assert dlg_v2.upgrade_tws3_btn.isHidden()
    new_key = dlg_v2.tws_key_input.text()
    assert new_key != "legacy-key-abc"
    saved = dlg_v2.get_settings()
    assert saved.get("tws3_share_key") == new_key
    assert "tws2_share_key" not in saved


def test_main_window_rejects_tws2_when_pure_tws3(qapp, monkeypatch, tmp_path):
    from ui.main_window import RoundedWindow
    from PySide6.QtWidgets import QDialog, QMessageBox

    _patch_machine(monkeypatch)
    tw.unlock()

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warned.append(text))
    monkeypatch.setattr("utils.server_manager.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.sub_manager.get_config_dir", lambda: tmp_path)

    win = RoundedWindow()
    win.settings["tws3_share_key"] = "pure-v3-share-key"
    win.settings.pop("tws2_share_key", None)

    # Attempt to paste tws2 link
    monkeypatch.setattr("ui.main_window.AddServerDialog.exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr("ui.main_window.AddServerDialog.get_server_key", lambda self: "tws2://tws2.invalid")

    win.show_add_dialog()
    assert any("tws2:// links are legacy and not supported" in w for w in warned)
    assert len(win.server_manager.manual_servers) == 0


def test_main_window_add_tws3_server_link(qapp, monkeypatch, tmp_path):
    from ui.main_window import RoundedWindow
    from PySide6.QtWidgets import QDialog

    _patch_machine(monkeypatch)
    tw.unlock()

    share_key = "test-share-key"
    ss = _ss_link("imported-server.example")
    tws3_link = tw.encrypt_share(share_key, ss)

    monkeypatch.setattr("utils.server_manager.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.sub_manager.get_config_dir", lambda: tmp_path)

    win = RoundedWindow()
    win.settings["tws3_share_key"] = share_key

    monkeypatch.setattr("ui.main_window.AddServerDialog.exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr("ui.main_window.AddServerDialog.get_server_key", lambda self: tws3_link)

    win.show_add_dialog()
    assert any(s.host == "imported-server.example" for s in win.server_manager.manual_servers)


def test_full_v2_to_v3_migration_with_share_key_and_drawer(qapp, monkeypatch, tmp_path):
    import utils.twinsock_legacy_v2 as tw_leg
    from utils.server_manager import ServerManager
    from ui.main_window import RoundedWindow
    from PySide6.QtWidgets import QDialog

    _patch_machine(monkeypatch, host="hostA", mac=0x11111111, machine_guid="guid-A")

    # 1. Existing v2 drawer with secret D
    d_secret = b"D" * 32
    fa_leg, fb_leg = tw_leg.fingerprint_v2()
    km_a_leg = tw_leg.tier_key_v2("a", fa_leg)
    km_b_leg = tw_leg.tier_key_v2("b", fb_leg)
    secret_a_v2 = tw_leg.tokenize_v2(tw_leg.drawer_field_key_v2(km_a_leg), d_secret.hex())
    secret_b_v2 = tw_leg.tokenize_v2(tw_leg.drawer_field_key_v2(km_b_leg), d_secret.hex())
    drawer_v2 = {
        "schema": "socksicle-drawer",
        "version": 2,
        "created_at": 100000,
        "last_seen": 100000,
        "fp": ["comp1"],
        "fp_sig_a": "sig-a",
        "secret_a": secret_a_v2,
        "secret_b": secret_b_v2,
        "chain": {},
    }
    (tmp_path / "drawer.json").write_text(json.dumps(drawer_v2), encoding="utf-8")

    # 2. Existing settings with tws2_share_key
    legacy_share_key = "my-preexisting-share-key"
    (tmp_path / "settings.json").write_text(
        json.dumps({"tws2_share_key": legacy_share_key, "local_port": 1080}),
        encoding="utf-8"
    )

    # 3. Existing servers.json with tws2. encrypted token
    kp_v2 = tw_leg.primary_key_v2(km_a_leg, d_secret)
    k_field_v2 = tw_leg.field_key_v2(kp_v2, "manual")
    v2_pw_token = tw_leg.tokenize_v2(k_field_v2, "my-secret-pw")
    servers_v2 = [{
        "name": "Old Server",
        "host": "old.example.com",
        "port": 8388,
        "method": "aes-256-gcm",
        "password": v2_pw_token,
        "key": "ss://old",
    }]
    (tmp_path / "servers.json").write_text(json.dumps(servers_v2), encoding="utf-8")

    # 4. Generate a tws2:// share link using the user's legacy share key
    d_share = tw_leg._share_derived_key_v2(legacy_share_key)
    tws2_share_link = "tws2://" + tw_leg.tokenize_v2(d_share, _ss_link("shared-via-tws2.example"))

    # 5. Start app / ServerManager on v3
    monkeypatch.setattr("utils.server_manager.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.sub_manager.get_config_dir", lambda: tmp_path)

    mgr = ServerManager()
    assert len(mgr.manual_servers) == 1
    assert mgr.manual_servers[0].password == "my-secret-pw"
    assert mgr.has_legacy_tws2_key() is True
    assert mgr.settings.get("tws2_share_key") == legacy_share_key

    # 6. Verify servers.json on disk migrated to tws3. token
    raw_servers = json.loads((tmp_path / "servers.json").read_text(encoding="utf-8"))
    assert raw_servers[0]["password"].startswith("tws3.")

    # 7. Import the legacy tws2:// share link in UI
    win = RoundedWindow()
    monkeypatch.setattr("ui.main_window.AddServerDialog.exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr("ui.main_window.AddServerDialog.get_server_key", lambda self: tws2_share_link)
    win.show_add_dialog()

    assert any(s.host == "shared-via-tws2.example" for s in win.server_manager.manual_servers)


def test_main_window_tws3_with_metadata(qapp, monkeypatch, tmp_path):
    from ui.main_window import RoundedWindow
    from PySide6.QtWidgets import QDialog, QMessageBox

    _patch_machine(monkeypatch)
    tw.unlock()

    share_key = "test-share-key"
    ss = _ss_link("metadata-server.example")
    expires = 1999999999
    tws3_link = tw.encrypt_share(share_key, ss, lock_export=True, expires_at=expires)

    monkeypatch.setattr("utils.server_manager.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.sub_manager.get_config_dir", lambda: tmp_path)

    win = RoundedWindow()
    win.settings["tws3_share_key"] = share_key

    monkeypatch.setattr("ui.main_window.AddServerDialog.exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr("ui.main_window.AddServerDialog.get_server_key", lambda self: tws3_link)

    win.show_add_dialog()
    srv = next(s for s in win.server_manager.manual_servers if s.host == "metadata-server.example")
    assert srv.lock_export is True
    assert srv.expires_at == expires
    assert srv.is_expired is False

    # Check UI server items have QR button hidden
    assert len(win.server_panel._server_items) == 1
    item = win.server_panel._server_items[0]
    assert item.share_button.isHidden() is True
    assert item.expired_badge.isHidden() is True


def test_main_window_expired_server_blocks_connection(qapp, monkeypatch, tmp_path):
    from ui.main_window import RoundedWindow
    from PySide6.QtWidgets import QDialog, QMessageBox

    _patch_machine(monkeypatch)
    tw.unlock()

    warned = []
    informed = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warned.append((title, text)))
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: informed.append((title, text)))
    monkeypatch.setattr("utils.server_manager.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.sub_manager.get_config_dir", lambda: tmp_path)

    # Expired link (timestamp in past)
    expired_ts = 1000000000
    tws3_expired_link = tw.encrypt_share("", _ss_link("expired.example"), lock_export=False, expires_at=expired_ts)

    win = RoundedWindow()
    monkeypatch.setattr(win, "_ensure_backend", lambda: True)
    monkeypatch.setattr(win.server_panel, "get_selected_index", lambda: 0)
    monkeypatch.setattr("ui.main_window.AddServerDialog.exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr("ui.main_window.AddServerDialog.get_server_key", lambda self: tws3_expired_link)

    win.show_add_dialog()
    assert any("expired" in text.lower() for title, text in informed)
    assert len(win.server_manager.manual_servers) == 1
    srv = win.server_manager.manual_servers[0]
    assert srv.is_expired is True

    # UI item shows [EXPIRED] badge
    assert len(win.server_panel._server_items) == 1
    item = win.server_panel._server_items[0]
    assert item.expired_badge.isHidden() is False

    # Try connecting to expired server
    item.radio.setChecked(True)
    win.toggle_connection(True)

    assert any("Expired" in title for title, text in warned)
    assert win.connection_manager.is_connected is False
    assert win.status_card.vpn_switch._enabled is False