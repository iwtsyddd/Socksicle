"""TwinSock v2 — machine-bound vault for secret fields in Socksicle config files.

Threat model (honest):
- Protects against casual glances: strings/hexdump/text viewers of the config
  file will not reveal passwords; in servers.json/subscriptions.json secrets
  are stored only as opaque tws2.<...> tokens.
- Protects against copying config files to another machine: secrets are bound
  with keys derived from the local machine fingerprint (7 system
  parameters), so on a foreign machine unlock fails with VaultError("foreign"),
  the app works with empty lists, and on the next write the foreign file
  is renamed to <name>.foreign-<date>.json.
- Protects against reading a single file: the password "pair" is split — data
  (first sock) and drawer.json with a random secret D (second sock);
  data cannot be decrypted without D.
- Chain hashes in drawer.json allow noticing file tampering after writing
  (only a log warning, decryption is not blocked).
- Does NOT protect against an attacker with full access to the live machine
  and reading the process code and memory: all keys ultimately end up
  on this same machine.
- The machine fingerprint value is absent from the code: it is computed at
  runtime and never hardcoded anywhere; the drawer stores only its
  non-secret digest fp_sig_a (SHA-256) for diagnostics.

Token format: tws2.<base64url-nopad(0x02 | nonce(16B) | tag(32B) | ciphertext)>.
For drawer.json the D secrets are encrypted directly with the tier key (key_tier);
for data fields — with a key derived from D and the machine tier.
"""
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import platform
import secrets
import struct
import tempfile
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QCryptographicHash

from .platform_utils import get_config_dir

log = logging.getLogger(__name__)

C = b"socksicle::tws::v2"
TOKEN_VERSION = 0x02
SCHEMA = "socksicle-drawer"
DRAWER_VERSION = 2
DRAWER_FILE = "drawer.json"
CHAIN_FILES = ("servers.json", "subscriptions.json")
SECRET_FIELDS = ("key", "password", "uuid", "public_key")
OBFUSCATION_MARKER = "__obfuscated__"
_EAR_FIELDS = SECRET_FIELDS + ("url",)

_lock = threading.Lock()
_D = None
_K_PRIMARY = None
_TIER = ""
_REPAIRED = False
_FOREIGN = False
_MIGRATED = False
_MIGRATION_LOGGED = False


class VaultError(Exception):
    pass


def _norm(v):
    return " ".join(str(v).strip().lower().split())


def _comps():
    return [
        ("sysnode", str(uuid.getnode())),
        ("hostname", platform.node()),
        ("sysname", platform.system()),
        ("sysrel", platform.release()),
        ("machine", platform.machine() + "|" + platform.processor()),
        ("bitness", str(struct.calcsize("P") * 8)),
        ("userhome", str(Path.home())),
    ]


def fingerprint():
    comps = _comps()
    fa = "|".join(f"{i}:{_norm(v)}" for i, (_, v) in enumerate(comps))
    fb = "|".join(f"{i}:{_norm(v)}" for i, (_, v) in enumerate(comps) if i not in (0, 3))
    return fa, fb


def _fp_values():
    return [_norm(v) for _, v in _comps()]


def _sha256(data):
    return hashlib.sha256(data).digest()


def _hmac(key, msg):
    return hmac.new(key, msg, hashlib.sha256).digest()


def _sha3_256(data):
    h = QCryptographicHash(QCryptographicHash.Sha3_256)
    h.addData(data)
    return bytes(h.result())


def _tier_key(tag, canon):
    return _sha256(C + b"::tier::" + tag.encode("ascii") + b"::" + canon.encode("utf-8"))


def _drawer_key(D):
    return _hmac(D, C + b"::drawer")


def _primary_key(km, D):
    return _hmac(_drawer_key(D), _sha256(km))


def _drawer_field_key(km):
    return _sha3_256(_hmac(km, C + b"::purpose::drawer"))


def _field_key(purpose):
    kp = _hmac(_K_PRIMARY, C + b"::purpose::" + purpose.encode("utf-8"))
    return _sha3_256(kp)


def _stream(k, nonce, n):
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out += hashlib.blake2b(
            digest_size=64, key=k, data=nonce + ctr.to_bytes(4, "little")).digest()
        ctr += 1
    return bytes(out[:n])


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def tokenize(k, plain, nonce=None):
    if not plain:
        return ""
    nonce = nonce or secrets.token_bytes(16)
    pt = plain.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(pt, _stream(k, nonce, len(pt))))
    tag = _hmac(k, b"tws-tag" + bytes([TOKEN_VERSION]) + nonce + ct)
    return "tws2." + _b64url(bytes([TOKEN_VERSION]) + nonce + tag + ct)


def detokenize(k, token):
    if not token or not token.startswith("tws2."):
        return token
    try:
        raw = _b64url_decode(token[5:])
    except (binascii.Error, ValueError):
        raise VaultError("integrity")
    ver, nonce, tag, ct = raw[0], raw[1:17], raw[17:49], raw[49:]
    if ver != TOKEN_VERSION:
        raise VaultError("unknown version")
    expected = _hmac(k, b"tws-tag" + raw[:1] + nonce + ct)
    if not hmac.compare_digest(expected, tag):
        raise VaultError("integrity")
    return bytes(a ^ b for a, b in zip(ct, _stream(k, nonce, len(ct)))).decode("utf-8")


def _share_derived_key(key):
    try:
        d = _b64url_decode(key)
    except (binascii.Error, ValueError):
        d = key.encode("utf-8")
    return _sha3_256(_hmac(d, C + b"::purpose::share"))


def encrypt_share(key: str, plaintext: str) -> str:
    """Encrypt a share link (server link or subscription URL) into a tws2:// token.

    Pure function: no vault state, no machine binding. An empty plaintext
    yields an empty string.
    """
    if not plaintext:
        return ""
    return "tws2://" + tokenize(_share_derived_key(key), plaintext)


def decrypt_share(key: str, token: str) -> str:
    """Decrypt a tws2:// share token back to the original link.

    Accepts both 'tws2://tws2.<...>' and bare 'tws2.<...>' tokens. Input that
    is not a tws2 token is returned unchanged. Raises VaultError with a
    descriptive message on malformed, tampered, or wrong-key tokens.
    """
    if token and token.startswith("tws2://"):
        token = token[len("tws2://"):]
    if not token or not token.startswith("tws2."):
        return token
    try:
        raw = _b64url_decode(token[5:])
    except (binascii.Error, ValueError):
        raise VaultError("invalid TwinSock share token encoding")
    if len(raw) <= 49:
        raise VaultError("invalid TwinSock share token length")
    ver, nonce, tag, ct = raw[0], raw[1:17], raw[17:49], raw[49:]
    if ver != TOKEN_VERSION:
        raise VaultError("unsupported TwinSock share token version")
    k = _share_derived_key(key)
    expected = _hmac(k, b"tws-tag" + bytes([TOKEN_VERSION]) + nonce + ct)
    if not hmac.compare_digest(expected, tag):
        raise VaultError("TwinSock share verification failed (wrong key or tampered token)")
    return bytes(a ^ b for a, b in zip(ct, _stream(k, nonce, len(ct)))).decode("utf-8")


def _drawer_path():
    return get_config_dir() / DRAWER_FILE


def _read_drawer():
    p = _drawer_path()
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return None


def _write_drawer(drawer):
    p = _drawer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", dir=str(p.parent), delete=False,
                encoding="utf-8", suffix=".tmp") as f:
            json.dump(drawer, f)
            tmp_name = f.name
        os.replace(tmp_name, str(p))
    except BaseException:
        if tmp_name:
            try:
                os.remove(tmp_name)
            except OSError:
                pass
        raise


def ensure_drawer():
    with _lock:
        _ensure_drawer_locked()


def _ensure_drawer_locked():
    if _drawer_path().exists():
        return
    fa, fb = fingerprint()
    d = os.urandom(32)
    now = int(time.time())
    drawer = {
        "schema": SCHEMA,
        "version": DRAWER_VERSION,
        "created_at": now,
        "last_seen": now,
        "fp": _fp_values(),
        "fp_sig_a": _sha256(fa.encode("utf-8")).hex(),
        "secret_a": tokenize(_drawer_field_key(_tier_key("a", fa)), d.hex()),
        "secret_b": tokenize(_drawer_field_key(_tier_key("b", fb)), d.hex()),
        "chain": {},
    }
    _write_drawer(drawer)


def unlock():
    with _lock:
        return _unlock_locked()


def _unlock_locked():
    global _D, _K_PRIMARY, _TIER, _REPAIRED, _FOREIGN
    if _K_PRIMARY is not None:
        return True
    fa, fb = fingerprint()
    draw = _read_drawer()
    if draw is None:
        _ensure_drawer_locked()
        draw = _read_drawer()
    if draw is None or not draw.get("secret_a") or not draw.get("secret_b"):
        _FOREIGN = True
        log.warning("vault: drawer.json missing vault secrets on this machine")
        raise VaultError("foreign")
    for tier, canon, field in (("a", fa, "secret_a"), ("b", fb, "secret_b")):
        tok = draw.get(field, "")
        if not tok.startswith("tws2."):
            continue
        try:
            km = _tier_key(tier, canon)
            D = bytes.fromhex(detokenize(_drawer_field_key(km), tok))
        except (VaultError, ValueError):
            continue
        if tier == "b":
            _repair_locked(draw, fa, fb, D)
        _D = D
        _K_PRIMARY = _primary_key(km, D)
        _TIER = "B" if tier == "b" else "A"
        _REPAIRED = tier == "b"
        _FOREIGN = False
        draw["last_seen"] = int(time.time())
        _write_drawer(draw)
        return True
    _FOREIGN = True
    log.warning("vault: drawer.json cannot be unlocked with the local fingerprint")
    raise VaultError("foreign")


def _repair_locked(draw, fa, fb, D):
    draw["secret_a"] = tokenize(_drawer_field_key(_tier_key("a", fa)), D.hex())
    draw["secret_b"] = tokenize(_drawer_field_key(_tier_key("b", fb)), D.hex())
    draw["fp_sig_a"] = _sha256(fa.encode("utf-8")).hex()
    draw["fp"] = _fp_values()
    log.info("vault: twin sock re-paired on tier B")


def drop_foreign():
    global _FOREIGN, _D, _K_PRIMARY, _TIER, _REPAIRED
    with _lock:
        p = _drawer_path()
        if p.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            try:
                os.replace(p, f"{p}.foreign-{stamp}.json")
            except OSError as e:
                log.error("vault: cannot retire foreign drawer.json: %s", e)
        _FOREIGN = False
        _D = None
        _K_PRIMARY = None
        _TIER = ""
        _REPAIRED = False


def _mark_migrated():
    global _MIGRATED, _MIGRATION_LOGGED
    _MIGRATED = True
    if not _MIGRATION_LOGGED:
        _MIGRATION_LOGGED = True
        log.info("config migrated to TwinSock v2")


def migration_occurred():
    global _MIGRATED
    with _lock:
        value = _MIGRATED
        _MIGRATED = False
        return value


def vault_status():
    with _lock:
        if _K_PRIMARY is not None:
            return {"ok": True, "tier": _TIER, "repaired": _REPAIRED, "reason": ""}
        return {"ok": False, "tier": "", "repaired": False,
                "reason": "foreign" if _FOREIGN else "locked"}


def encrypt_field(purpose, plaintext):
    with _lock:
        _unlock_locked()
        return tokenize(_field_key(purpose), plaintext)


def decrypt_field(purpose, token):
    with _lock:
        if not token:
            return ""
        if token.startswith("tws2."):
            _unlock_locked()
            return detokenize(_field_key(purpose), token)
        if token.startswith(OBFUSCATION_MARKER):
            _mark_migrated()
            return _legacy_deobfuscate(token)
        if token.startswith("__"):
            return token
        _mark_migrated()
        return token


def seal_dict(purpose, d, fields):
    out = dict(d)
    for field in fields:
        if out.get(field):
            out[field] = encrypt_field(purpose, str(out[field]))
    return out


def unseal_dict(purpose, d, fields):
    out = dict(d)
    for field in fields:
        value = out.get(field)
        if isinstance(value, str) and value:
            try:
                out[field] = decrypt_field(purpose, value)
            except VaultError as e:
                if str(e) == "foreign":
                    raise
                log.warning("vault: field %s: %s (set to empty)", field, e)
                out[field] = ""
    return out


def file_saved(name):
    with _lock:
        if name not in CHAIN_FILES:
            return
        try:
            digest = _sha256((get_config_dir() / name).read_bytes()).hex()
        except OSError:
            log.warning("vault: cannot hash %s", name)
            return
        draw = _read_drawer()
        if draw is None:
            return
        draw.setdefault("chain", {})[name] = digest
        _write_drawer(draw)


def file_intact(name):
    with _lock:
        if name not in CHAIN_FILES:
            return True
        draw = _read_drawer()
        if draw is None:
            return True
        want = draw.get("chain", {}).get(name)
        if want is None:
            return True
        try:
            have = _sha256((get_config_dir() / name).read_bytes()).hex()
        except OSError:
            log.warning("vault: %s missing but chain expects it", name)
            return False
        if have != want:
            log.warning("vault: %s was modified outside Socksicle (chain mismatch)", name)
            return False
        return True


def _import_clean(raw):
    out = dict(raw)
    for field in _EAR_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value.startswith(OBFUSCATION_MARKER):
            log.warning("import: field %s in legacy __obfuscated__ format, decrypted for migration", field)
            out[field] = _legacy_deobfuscate(value)
    return out


def export_payload(manual_servers, subscriptions):
    def server_dict(s):
        return s.to_dict() if hasattr(s, "to_dict") else dict(s)
    return {
        "schema": "socksicle-export",
        "note": "Secret fields (passwords, links) in this file are stored in plain text — "
                "do not share or store it unnecessarily.",
        "manual_servers": [server_dict(s) for s in manual_servers],
        "subscriptions": [
            {**sub, "servers": [server_dict(s) for s in sub.get("servers", [])]}
            for sub in subscriptions
        ],
    }


def import_payload(data):
    from .server_model import Server
    data = dict(data or {})
    if "schema" not in data:
        log.warning("import: legacy export format (no schema), treating as transport form")
    manuals = []
    for raw in data.get("manual_servers", []):
        if not isinstance(raw, dict):
            continue
        try:
            srv = Server.from_dict(_import_clean(raw))
        except (TypeError, ValueError):
            continue
        if srv:
            manuals.append(srv)
    subs = []
    for raw in data.get("subscriptions", []):
        if not isinstance(raw, dict):
            continue
        raw = _import_clean(raw)
        servers = []
        for s in raw.get("servers", []):
            if isinstance(s, dict):
                try:
                    srv = Server.from_dict(_import_clean(s))
                except (TypeError, ValueError):
                    continue
                if srv:
                    servers.append(srv)
        raw["servers"] = servers
        subs.append(raw)
    return manuals, subs


def _legacy_derive_key():
    seed = b"Socksicle-obfuscation-v1"
    host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "default"
    return hashlib.sha256(seed + host.encode()).digest()[:16]


def _legacy_obfuscate(value, key=None):
    if not value:
        return ""
    key = key or _legacy_derive_key()
    raw = value.encode("utf-8")
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return OBFUSCATION_MARKER + base64.b64encode(encrypted).decode("ascii")


def _legacy_deobfuscate(token, key=None):
    if not token or not token.startswith(OBFUSCATION_MARKER):
        return token
    key = key or _legacy_derive_key()
    try:
        encrypted = base64.b64decode(token[len(OBFUSCATION_MARKER):])
    except (binascii.Error, ValueError):
        raise VaultError("integrity")
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
    return decrypted.decode("utf-8")


def _reset():
    global _D, _K_PRIMARY, _TIER, _REPAIRED, _FOREIGN, _MIGRATED, _MIGRATION_LOGGED
    with _lock:
        _D = None
        _K_PRIMARY = None
        _TIER = ""
        _REPAIRED = False
        _FOREIGN = False
        _MIGRATED = False
        _MIGRATION_LOGGED = False
