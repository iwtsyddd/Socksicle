"""TwinSock v3 — machine-bound vault for secret fields in Socksicle config files.

Threat model (honest):
- Protects against casual glances: strings/hexdump/text viewers of the config
  file will not reveal passwords; in servers.json/subscriptions.json secrets
  are stored only as opaque tws3.<...> tokens (or legacy tws2.<...> tokens).
- Protects against copying config files to another machine: secrets are bound
  with keys derived from the local machine fingerprint (MachineGuid / machine-id
  plus system parameters), so on a foreign machine unlock fails with
  VaultError("foreign"), the app works with empty lists, and on the next write
  the foreign file is renamed to <name>.foreign-<date>.json.
- Protects against reading a single file: the password "pair" is split — data
  (first sock) and drawer.json with a random secret D (second sock);
  data cannot be decrypted without D.
- Cryptographic core (v3):
  - Authenticated Encryption: AES-256-GCM (NIST SP 800-38D, single-pass AEAD
    with 12-byte nonce and 16-byte authentication tag).
  - Key Derivation: HKDF-SHA256 (RFC 5869) with domain-separated info parameters.
  - Stable Hardware Fingerprint: Windows Registry MachineGuid, Linux /etc/machine-id
    (or /var/lib/dbus/machine-id), with uuid.getnode() fallback.
- Backward compatibility:
  - Supports tws3.<base64url(...)> and legacy tws2.<base64url(...)>.
  - Version byte determines cipher: 0x03 (AES-256-GCM) or 0x02 (legacy v2 stream+HMAC).
  - Legacy v2 reading routines are isolated in utils/twinsock_legacy_v2.py.
  - On reading legacy v2 tokens or drawer, the vault unlocks and marks for silent atomic
    upgrade to v3.
- Chain hashes in drawer.json allow noticing file tampering after writing
  (only a log warning, decryption is not blocked).
- Share links: pure tws3:// (and legacy tws2://) share encryption/decryption
  without machine binding.

Token format:
- v3: tws3.<base64url-nopad(0x03 | nonce(12B) | ciphertext+tag(16B))>
- v2: tws2.<base64url-nopad(0x02 | nonce(16B) | tag(32B) | ciphertext)> (decrypt-only)
"""
import base64
import binascii
import hashlib
import json
import logging
import os
import platform
import secrets
import struct
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import twinsock_legacy_v2
from .platform_utils import get_config_dir

log = logging.getLogger(__name__)

# Versioning & Deprecation policy
TOKEN_VERSION_CURRENT = 0x03
TOKEN_VERSION_MIN_SUPPORTED = 0x02  # deprecated, decrypt-only, maintain for backward compat
TOKEN_VERSION = TOKEN_VERSION_CURRENT

TOKEN_PREFIX_CURRENT = "tws3."
TOKEN_PREFIX_LEGACY = "tws2."
TOKEN_PREFIXES = (TOKEN_PREFIX_CURRENT, TOKEN_PREFIX_LEGACY)

SHARE_SCHEME_CURRENT = "tws3://"
SHARE_SCHEME_LEGACY = "tws2://"
SHARE_SCHEMES = (SHARE_SCHEME_CURRENT, SHARE_SCHEME_LEGACY)

SCHEMA = "socksicle-drawer"
DRAWER_VERSION = 3
DRAWER_FILE = "drawer.json"
CHAIN_FILES = ("servers.json", "subscriptions.json")
SECRET_FIELDS = ("key", "password", "uuid", "public_key", "obfs_password")
OBFUSCATION_MARKER = "__obfuscated__"
_EAR_FIELDS = SECRET_FIELDS + ("url",)

# Cryptographic Domain Salts (HKDF)
C = b"socksicle::tws::v3"
SALT_TIER_A = hashlib.sha256(b"socksicle::tws::v3::salt::tierA").digest()
SALT_TIER_B = hashlib.sha256(b"socksicle::tws::v3::salt::tierB").digest()
SALT_PRIMARY = hashlib.sha256(b"socksicle::tws::v3::salt::primary").digest()
SALT_DRAWER_FIELD = hashlib.sha256(b"socksicle::tws::v3::salt::drawer_field").digest()
SALT_PURPOSE = hashlib.sha256(b"socksicle::tws::v3::salt::purpose").digest()
SALT_SHARE = hashlib.sha256(b"socksicle::tws::v3::salt::share").digest()

_lock = threading.Lock()
_D: bytes | None = None
_K_PRIMARY: bytes | None = None
_K_PRIMARY_V2: bytes | None = None
_TIER = ""
_REPAIRED = False
_FOREIGN = False
_MIGRATED = False
_MIGRATION_LOGGED = False


class VaultError(Exception):
    pass


def _norm(v: object) -> str:
    return " ".join(str(v).strip().lower().split())


def _read_registry(sub_key: str, value_name: str) -> str | None:
    try:
        import winreg
        for access_mask in (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ):
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub_key, 0, access_mask)
                val, _ = winreg.QueryValueEx(key, value_name)
                if val:
                    return str(val).strip()
            except OSError:
                continue
    except Exception:
        pass
    return None


def _read_file(path: str) -> str | None:
    try:
        p = Path(path)
        if p.is_file():
            content = p.read_text(encoding="utf-8").strip()
            if content:
                return content
    except Exception:
        pass
    return None


def _get_machine_id() -> str:
    """Retrieve stable machine identifier without depending on fluctuating MAC addresses."""
    if sys.platform == "win32":
        val = _read_registry(r"SOFTWARE\Microsoft\Cryptography", "MachineGuid")
        if val:
            return val
    elif sys.platform.startswith("linux"):
        val = _read_file("/etc/machine-id") or _read_file("/var/lib/dbus/machine-id")
        if val:
            return val
    return str(uuid.getnode())


def _comps():
    return [
        ("machine_id", _get_machine_id()),
        ("hostname", platform.node()),
        ("sysname", platform.system()),
        ("machine", platform.machine()),
        ("bitness", str(struct.calcsize("P") * 8)),
        ("userhome", str(Path.home())),
    ]


def fingerprint() -> tuple[str, str]:
    """Compute Tier A (full) and Tier B (durable subset excluding machine_id) fingerprints."""
    comps = _comps()
    fa = "|".join(f"{i}:{_norm(v)}" for i, (_, v) in enumerate(comps))
    fb = "|".join(f"{i}:{_norm(v)}" for i, (_, v) in enumerate(comps) if i != 0)
    return fa, fb


def _fp_values() -> list[str]:
    return [_norm(v) for _, v in _comps()]


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _derive_key_v3(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-SHA256 key derivation (RFC 5869)."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info,
        backend=None,
    ).derive(ikm)


def _tier_key(tag: str, canon: str) -> bytes:
    salt = SALT_TIER_A if tag == "a" else SALT_TIER_B
    info = b"twinsock-v3-tier" + tag.encode("ascii")
    return _derive_key_v3(canon.encode("utf-8"), salt=salt, info=info)


def _drawer_field_key(km: bytes) -> bytes:
    return _derive_key_v3(km, salt=SALT_DRAWER_FIELD, info=b"twinsock-v3-drawer-field")


def _primary_key(km: bytes, d: bytes) -> bytes:
    return _derive_key_v3(d, salt=km, info=b"twinsock-v3-primary")


def _field_key(purpose: str) -> bytes:
    if _K_PRIMARY is None:
        raise VaultError("locked")
    return _derive_key_v3(_K_PRIMARY, salt=SALT_PURPOSE, info=b"twinsock-v3-purpose::" + purpose.encode("utf-8"))


def _share_derived_key(key: str) -> bytes:
    try:
        d = _b64url_decode(key)
    except (binascii.Error, ValueError):
        d = key.encode("utf-8")
    return _derive_key_v3(d, salt=SALT_SHARE, info=b"twinsock-v3-share")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _strip_token_prefix(token: str) -> str:
    for prefix in TOKEN_PREFIXES:
        if token.startswith(prefix):
            return token[len(prefix):]
    return token


def _peek_version(token: str) -> int:
    if not token:
        return 0
    t = token
    for scheme in SHARE_SCHEMES:
        if t.startswith(scheme):
            t = t[len(scheme):]
            break
    for prefix in TOKEN_PREFIXES:
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    try:
        raw = _b64url_decode(t)
        return raw[0] if raw else 0
    except Exception:
        return 0


def tokenize(k: bytes, plain: str, nonce: bytes | None = None) -> str:
    """Encrypt plaintext using AES-256-GCM (NIST SP 800-38D, 12B nonce + 16B tag)."""
    if not plain:
        return ""
    nonce = nonce or secrets.token_bytes(12)
    pt = plain.encode("utf-8")
    aesgcm = AESGCM(k)
    ct_with_tag = aesgcm.encrypt(nonce, pt, None)
    return TOKEN_PREFIX_CURRENT + _b64url(bytes([TOKEN_VERSION_CURRENT]) + nonce + ct_with_tag)


def detokenize(k: bytes, token: str) -> str:
    """Decrypt token, dispatching by version byte (v3 AES-GCM or v2 legacy stream)."""
    if not token:
        return token
    if not any(token.startswith(p) for p in TOKEN_PREFIXES):
        return token
    payload = _strip_token_prefix(token)
    try:
        raw = _b64url_decode(payload)
    except (binascii.Error, ValueError):
        raise VaultError("integrity")
    if not raw:
        raise VaultError("integrity")
    ver = raw[0]
    if ver == TOKEN_VERSION_CURRENT:
        if len(raw) < 1 + 12 + 16:  # 1 byte ver + 12 byte nonce + 16 byte tag
            raise VaultError("integrity")
        nonce = raw[1:13]
        ct_with_tag = raw[13:]
        try:
            pt = AESGCM(k).decrypt(nonce, ct_with_tag, None)
            return pt.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError):
            raise VaultError("integrity")
    elif ver == TOKEN_VERSION_MIN_SUPPORTED:
        return twinsock_legacy_v2.detokenize_v2(k, token, exc_class=VaultError)
    else:
        raise VaultError(f"unsupported_version:{ver}")


DEFAULT_SHARE_KEY = "abcdfg"


def _encrypt_share_bytes(k: bytes, plain: str) -> str:
    nonce = secrets.token_bytes(12)
    pt = plain.encode("utf-8")
    aesgcm = AESGCM(k)
    ct_with_tag = aesgcm.encrypt(nonce, pt, None)
    return SHARE_SCHEME_CURRENT + _b64url(bytes([TOKEN_VERSION_CURRENT]) + nonce + ct_with_tag)


def encrypt_share(key: str = "", plaintext: str | list = "", lock_export: bool = False, expires_at: int | None = None) -> str:
    """Encrypt a share link or list of links into a clean tws3://<base64url> token.

    Supports bundling multiple servers, permissions (lock_export), and expiration timestamp (expires_at).
    If key is empty or not specified, uses DEFAULT_SHARE_KEY.
    """
    if not plaintext:
        return ""
    if not key:
        key = DEFAULT_SHARE_KEY

    if isinstance(plaintext, list):
        payload_dict = {
            "targets": [str(x) for x in plaintext if str(x).strip()],
            "lock_export": bool(lock_export),
            "expires_at": expires_at,
        }
        pt = json.dumps(payload_dict, ensure_ascii=False)
    elif lock_export or expires_at is not None:
        payload_dict = {
            "target": plaintext,
            "lock_export": bool(lock_export),
            "expires_at": expires_at,
        }
        pt = json.dumps(payload_dict, ensure_ascii=False)
    else:
        pt = str(plaintext)

    return _encrypt_share_bytes(_share_derived_key(key), pt)


def _extract_share_payload_bytes(token: str) -> tuple[int, bytes, bytes, bytes] | None:
    """Parse share token into (version, raw_bytes, nonce, ct_with_tag) or None."""
    if not token:
        return None
    t = token.strip()
    for scheme in SHARE_SCHEMES:
        if t.startswith(scheme):
            t = t[len(scheme):]
            break
    for prefix in TOKEN_PREFIXES:
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    try:
        raw = _b64url_decode(t)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    ver = raw[0]
    if ver == TOKEN_VERSION_CURRENT:
        if len(raw) < 1 + 12 + 16:
            return None
        return ver, raw, raw[1:13], raw[13:]
    elif ver == TOKEN_VERSION_MIN_SUPPORTED:
        return ver, raw, b"", b""
    return None


def decrypt_share_payload(key: str, token: str) -> tuple[str | list, dict]:
    """Decrypt a tws3:// or tws2:// share token back to (target_link_or_list, metadata_dict).

    Supports single links, multi-server arrays, clean format ('tws3://<b64url>'),
    legacy ('tws3://tws3.<b64url>'), and bare tokens.
    """
    if not token:
        return token, {"lock_export": False, "expires_at": None}

    parsed = _extract_share_payload_bytes(token)
    if parsed is None:
        # Non-tws link or invalid encoding
        return token, {"lock_export": False, "expires_at": None}

    ver, raw, nonce, ct_with_tag = parsed

    # Determine keys to try
    keys_to_try = []
    if key and key.strip():
        keys_to_try.append(key.strip())
    if DEFAULT_SHARE_KEY not in keys_to_try:
        keys_to_try.append(DEFAULT_SHARE_KEY)

    last_error = None
    decrypted_text = None

    if ver == TOKEN_VERSION_CURRENT:
        for candidate_key in keys_to_try:
            k = _share_derived_key(candidate_key)
            try:
                pt = AESGCM(k).decrypt(nonce, ct_with_tag, None)
                decrypted_text = pt.decode("utf-8")
                break
            except (InvalidTag, UnicodeDecodeError, ValueError) as e:
                last_error = e
                continue
    elif ver == TOKEN_VERSION_MIN_SUPPORTED:
        for candidate_key in keys_to_try:
            try:
                decrypted_text = twinsock_legacy_v2.decrypt_share_v2(candidate_key, token, exc_class=VaultError)
                break
            except Exception as e:
                last_error = e
                continue
    else:
        raise VaultError(f"unsupported TwinSock share token version: {ver}")

    if decrypted_text is None:
        raise VaultError("TwinSock share verification failed (wrong key or tampered token)")

    # Unpack JSON metadata if present
    target_link = decrypted_text
    metadata = {"lock_export": False, "expires_at": None}
    try:
        data = json.loads(decrypted_text)
        if isinstance(data, dict):
            if "targets" in data and isinstance(data["targets"], list):
                target_link = data["targets"]
            elif "servers" in data and isinstance(data["servers"], list):
                target_link = data["servers"]
            elif "target" in data:
                target_link = data["target"]
            metadata["lock_export"] = bool(data.get("lock_export", False))
            metadata["expires_at"] = data.get("expires_at")
            for k, v in data.items():
                if k not in metadata and k not in ("target", "targets", "servers"):
                    metadata[k] = v
        elif isinstance(data, list):
            target_link = data
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return target_link, metadata


def decrypt_share(key: str, token: str) -> str:
    """Decrypt a tws3:// or tws2:// share token back to the original link.

    Accepts clean format ('tws3://<b64url>'), legacy ('tws3://tws3.<b64url>'),
    and bare tokens. Returns target link string for backward compatibility.
    """
    target, _ = decrypt_share_payload(key, token)
    return target


def _drawer_path() -> Path:
    return get_config_dir() / DRAWER_FILE


def _read_drawer() -> dict | None:
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


def _write_drawer(drawer: dict):
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


def unlock() -> bool:
    with _lock:
        return _unlock_locked()


def _unlock_locked() -> bool:
    global _D, _K_PRIMARY, _K_PRIMARY_V2, _TIER, _REPAIRED, _FOREIGN
    if _K_PRIMARY is not None:
        return True
    fa, fb = fingerprint()
    fa_legacy, fb_legacy = twinsock_legacy_v2.fingerprint_v2()
    draw = _read_drawer()
    if draw is None:
        _ensure_drawer_locked()
        draw = _read_drawer()
    if draw is None or not draw.get("secret_a") or not draw.get("secret_b"):
        _FOREIGN = True
        log.warning("vault: drawer.json missing vault secrets on this machine")
        raise VaultError("foreign")

    # Try Tier A then Tier B
    for tier, canon, canon_leg, field in (
        ("a", fa, fa_legacy, "secret_a"),
        ("b", fb, fb_legacy, "secret_b"),
    ):
        tok = draw.get(field, "")
        if not any(tok.startswith(p) for p in TOKEN_PREFIXES):
            continue

        ver = _peek_version(tok)
        D = None
        was_legacy = False

        if ver == TOKEN_VERSION_CURRENT:
            try:
                km = _tier_key(tier, canon)
                D = bytes.fromhex(detokenize(_drawer_field_key(km), tok))
            except (VaultError, ValueError):
                continue
        elif ver == TOKEN_VERSION_MIN_SUPPORTED:
            try:
                km_leg = twinsock_legacy_v2.tier_key_v2(tier, canon_leg)
                field_k_leg = twinsock_legacy_v2.drawer_field_key_v2(km_leg)
                D = bytes.fromhex(twinsock_legacy_v2.detokenize_v2(field_k_leg, tok, exc_class=VaultError))
                was_legacy = True
            except (VaultError, ValueError):
                continue
        else:
            continue

        if D is not None:
            km_v3_a = _tier_key("a", fa)
            _D = D
            _K_PRIMARY = _primary_key(km_v3_a, D)
            _TIER = "B" if tier == "b" else "A"
            _REPAIRED = (tier == "b")
            _FOREIGN = False

            # Pre-compute legacy primary key if unlocked via legacy tier
            km_leg_a = twinsock_legacy_v2.tier_key_v2("a", fa_legacy)
            _K_PRIMARY_V2 = twinsock_legacy_v2.primary_key_v2(km_leg_a, D)

            # Re-pair / upgrade drawer to v3 if on tier B or if legacy v2 drawer
            if tier == "b" or was_legacy or draw.get("version", 0) < DRAWER_VERSION:
                _repair_locked(draw, fa, fb, D)
                if was_legacy:
                    _mark_migrated()
            else:
                draw["last_seen"] = int(time.time())
                _write_drawer(draw)
            return True

    _FOREIGN = True
    log.warning("vault: drawer.json cannot be unlocked with the local fingerprint")
    raise VaultError("foreign")


def _repair_locked(draw: dict, fa: str, fb: str, d: bytes):
    draw["schema"] = SCHEMA
    draw["version"] = DRAWER_VERSION
    draw["secret_a"] = tokenize(_drawer_field_key(_tier_key("a", fa)), d.hex())
    draw["secret_b"] = tokenize(_drawer_field_key(_tier_key("b", fb)), d.hex())
    draw["fp_sig_a"] = _sha256(fa.encode("utf-8")).hex()
    draw["fp"] = _fp_values()
    draw["last_seen"] = int(time.time())
    _write_drawer(draw)
    log.info("vault: twin sock re-paired and upgraded to v3")


def drop_foreign():
    global _FOREIGN, _D, _K_PRIMARY, _K_PRIMARY_V2, _TIER, _REPAIRED
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
        _K_PRIMARY_V2 = None
        _TIER = ""
        _REPAIRED = False


def _mark_migrated():
    global _MIGRATED, _MIGRATION_LOGGED
    _MIGRATED = True
    if not _MIGRATION_LOGGED:
        _MIGRATION_LOGGED = True
        log.info("config migrated to TwinSock v3")


def migration_occurred() -> bool:
    global _MIGRATED
    with _lock:
        value = _MIGRATED
        _MIGRATED = False
        return value


def vault_status() -> dict:
    with _lock:
        if _K_PRIMARY is not None:
            return {"ok": True, "tier": _TIER, "repaired": _REPAIRED, "reason": ""}
        return {"ok": False, "tier": "", "repaired": False,
                "reason": "foreign" if _FOREIGN else "locked"}


def encrypt_field(purpose: str, plaintext: str) -> str:
    with _lock:
        _unlock_locked()
        return tokenize(_field_key(purpose), plaintext)


def decrypt_field(purpose: str, token: str) -> str:
    with _lock:
        if not token:
            return ""
        if any(token.startswith(p) for p in TOKEN_PREFIXES):
            _unlock_locked()
            ver = _peek_version(token)
            if ver == TOKEN_VERSION_CURRENT:
                return detokenize(_field_key(purpose), token)
            elif ver == TOKEN_VERSION_MIN_SUPPORTED:
                _mark_migrated()
                global _K_PRIMARY_V2
                if _K_PRIMARY_V2 is None and _D is not None:
                    fa_legacy, _ = twinsock_legacy_v2.fingerprint_v2()
                    km_leg = twinsock_legacy_v2.tier_key_v2("a", fa_legacy)
                    _K_PRIMARY_V2 = twinsock_legacy_v2.primary_key_v2(km_leg, _D)
                k_legacy = twinsock_legacy_v2.field_key_v2(_K_PRIMARY_V2, purpose)
                return twinsock_legacy_v2.detokenize_v2(k_legacy, token, exc_class=VaultError)
            else:
                raise VaultError(f"unsupported_version:{ver}")
        if token.startswith(OBFUSCATION_MARKER):
            _mark_migrated()
            return _legacy_deobfuscate(token)
        if token.startswith("__"):
            return token
        _mark_migrated()
        return token


def seal_dict(purpose: str, d: dict, fields: tuple | list) -> dict:
    out = dict(d)
    for field in fields:
        if out.get(field):
            out[field] = encrypt_field(purpose, str(out[field]))
    return out


def unseal_dict(purpose: str, d: dict, fields: tuple | list) -> dict:
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


def file_saved(name: str):
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


def file_intact(name: str) -> bool:
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


def _import_clean(raw: dict) -> dict:
    out = dict(raw)
    for field in _EAR_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value.startswith(OBFUSCATION_MARKER):
            log.warning("import: field %s in legacy __obfuscated__ format, decrypted for migration", field)
            out[field] = _legacy_deobfuscate(value)
    return out


def export_payload(manual_servers, subscriptions):
    def is_locked(item):
        if hasattr(item, "lock_export"):
            return bool(item.lock_export)
        if isinstance(item, dict):
            return bool(item.get("lock_export", False))
        return False

    def server_dict(s):
        return s.to_dict() if hasattr(s, "to_dict") else dict(s)

    exported_manuals = [
        server_dict(s) for s in manual_servers
        if not is_locked(s)
    ]
    exported_subs = []
    for sub in subscriptions:
        if is_locked(sub):
            continue
        sub_dict = dict(sub)
        sub_servers = [
            server_dict(s) for s in sub_dict.get("servers", [])
            if not is_locked(s)
        ]
        exported_subs.append({**sub_dict, "servers": sub_servers})

    return {
        "schema": "socksicle-export",
        "note": "Secret fields (passwords, links) in this file are stored in plain text — "
                "do not share or store it unnecessarily.",
        "manual_servers": exported_manuals,
        "subscriptions": exported_subs,
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
    global _D, _K_PRIMARY, _K_PRIMARY_V2, _TIER, _REPAIRED, _FOREIGN, _MIGRATED, _MIGRATION_LOGGED
    with _lock:
        _D = None
        _K_PRIMARY = None
        _K_PRIMARY_V2 = None
        _TIER = ""
        _REPAIRED = False
        _FOREIGN = False
        _MIGRATED = False
        _MIGRATION_LOGGED = False
