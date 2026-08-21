"""TwinSock v2 Legacy Module (DEPRECATED).

This module contains the legacy TwinSock v2 cryptographic routines:
- Custom stream cipher based on BLAKE2b-512 in keyed mode + HMAC-SHA256 authentication tag
- Legacy KDF based on HMAC-SHA256 + SHA3-256
- Machine fingerprinting based on uuid.getnode() (MAC-based)

DEPRECATION & LIFETIME POLICY:
- Maintained as DECRYPT-ONLY (read-only) for backward compatibility with older
  vault files (drawer.json, servers.json, subscriptions.json) and legacy tws2:// share tokens.
- Deprecated as of TwinSock v3 (TOKEN_VERSION_MIN_SUPPORTED = 0x02).
- Removal target: after v2.0 or when telemetry/warning logs confirm zero remaining v2 configs.
- Do NOT use for new encryption. All new tokens must be generated using TwinSock v3 (AES-256-GCM + HKDF).
"""
import base64
import binascii
import hashlib
import hmac
import logging
import platform
import secrets
import struct
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

LEGACY_C = b"socksicle::tws::v2"
LEGACY_TOKEN_VERSION = 0x02


def _norm(v: object) -> str:
    return " ".join(str(v).strip().lower().split())


def _comps_v2():
    return [
        ("sysnode", str(uuid.getnode())),
        ("hostname", platform.node()),
        ("sysname", platform.system()),
        ("sysrel", platform.release()),
        ("machine", platform.machine() + "|" + platform.processor()),
        ("bitness", str(struct.calcsize("P") * 8)),
        ("userhome", str(Path.home())),
    ]


def fingerprint_v2():
    comps = _comps_v2()
    fa = "|".join(f"{i}:{_norm(v)}" for i, (_, v) in enumerate(comps))
    fb = "|".join(f"{i}:{_norm(v)}" for i, (_, v) in enumerate(comps) if i not in (0, 3))
    return fa, fb


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _sha3_256(data: bytes) -> bytes:
    return hashlib.sha3_256(data).digest()


def tier_key_v2(tag: str, canon: str) -> bytes:
    return _sha256(LEGACY_C + b"::tier::" + tag.encode("ascii") + b"::" + canon.encode("utf-8"))


def drawer_key_v2(d: bytes) -> bytes:
    return _hmac(d, LEGACY_C + b"::drawer")


def primary_key_v2(km: bytes, d: bytes) -> bytes:
    return _hmac(drawer_key_v2(d), _sha256(km))


def drawer_field_key_v2(km: bytes) -> bytes:
    return _sha3_256(_hmac(km, LEGACY_C + b"::purpose::drawer"))


def field_key_v2(kp: bytes, purpose: str) -> bytes:
    return _sha3_256(_hmac(kp, LEGACY_C + b"::purpose::" + purpose.encode("utf-8")))


def _stream_v2(k: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out += hashlib.blake2b(
            nonce + ctr.to_bytes(4, "little"),
            digest_size=64,
            key=k,
        ).digest()
        ctr += 1
    return bytes(out[:n])


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def tokenize_v2(k: bytes, plain: str, nonce: bytes | None = None) -> str:
    """Generate a legacy v2 token. Used primarily for testing backward compatibility."""
    if not plain:
        return ""
    nonce = nonce or secrets.token_bytes(16)
    pt = plain.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(pt, _stream_v2(k, nonce, len(pt))))
    tag = _hmac(k, b"tws-tag" + bytes([LEGACY_TOKEN_VERSION]) + nonce + ct)
    return "tws2." + _b64url(bytes([LEGACY_TOKEN_VERSION]) + nonce + tag + ct)


def detokenize_v2(k: bytes, token: str, exc_class: type[Exception] = Exception) -> str:
    """Decrypt a legacy v2 token (0x02) using BLAKE2b stream + HMAC-SHA256 tag."""
    log.warning("vault: legacy v2 token encountered, path is deprecated and will be removed in future release")
    if not token or not token.startswith("tws2."):
        return token
    try:
        raw = _b64url_decode(token[5:])
    except (binascii.Error, ValueError):
        raise exc_class("integrity")
    if len(raw) <= 49:
        raise exc_class("integrity")
    ver, nonce, tag, ct = raw[0], raw[1:17], raw[17:49], raw[49:]
    if ver != LEGACY_TOKEN_VERSION:
        raise exc_class(f"unsupported_version:{ver}")
    expected = _hmac(k, b"tws-tag" + raw[:1] + nonce + ct)
    if not hmac.compare_digest(expected, tag):
        raise exc_class("integrity")
    return bytes(a ^ b for a, b in zip(ct, _stream_v2(k, nonce, len(ct)))).decode("utf-8")


def _share_derived_key_v2(key: str) -> bytes:
    try:
        d = _b64url_decode(key)
    except (binascii.Error, ValueError):
        d = key.encode("utf-8")
    return _sha3_256(_hmac(d, LEGACY_C + b"::purpose::share"))


def decrypt_share_v2(key: str, token: str, exc_class: type[Exception] = Exception) -> str:
    """Decrypt a legacy v2 share token."""
    log.warning("vault: legacy v2 share token encountered, decrypting via legacy path")
    if token and token.startswith("tws2://"):
        token = token[len("tws2://"):]
    if not token or not token.startswith("tws2."):
        return token
    try:
        raw = _b64url_decode(token[5:])
    except (binascii.Error, ValueError):
        raise exc_class("invalid TwinSock share token encoding")
    if len(raw) <= 49:
        raise exc_class("invalid TwinSock share token length")
    ver, nonce, tag, ct = raw[0], raw[1:17], raw[17:49], raw[49:]
    if ver != LEGACY_TOKEN_VERSION:
        raise exc_class("unsupported TwinSock share token version")
    k = _share_derived_key_v2(key)
    expected = _hmac(k, b"tws-tag" + bytes([LEGACY_TOKEN_VERSION]) + nonce + ct)
    if not hmac.compare_digest(expected, tag):
        raise exc_class("TwinSock share verification failed (wrong key or tampered token)")
    return bytes(a ^ b for a, b in zip(ct, _stream_v2(k, nonce, len(ct)))).decode("utf-8")
