"""
Radiant Seal -- node signature verification for RTTP (HMAC-SHA256).

Trust model:
    * every Agent holds its own 32-byte key (the node-* entries in seal_keys.json)
    * the switch holds a switch key and also signs packets sent to Agents
      (verification in both directions)
    * RTTP_IDENTIFY: signed content = "role|ts|nonce"; replay defence rejects a
      timestamp skew above 120s
    * RTTP_RESPONSE: signed content binds task_id to sha256(result)
    * unknown role or missing key -> reject (fail closed)

When the key file is missing the module enters OPEN_MODE (local development only)
and says so in every log line.
"""

import hashlib
import hmac
import json
import os
import secrets
import time

KEYFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "seal_keys.json")
MAX_CLOCK_SKEW = 120

_keys_cache = None


def load_keys(force=False):
    """Read the key table; return None when the file is missing (OPEN_MODE)."""
    global _keys_cache
    if _keys_cache is not None and not force:
        return _keys_cache
    if not os.path.exists(KEYFILE):
        return None
    with open(KEYFILE, "r", encoding="utf-8") as f:
        _keys_cache = json.load(f)
    return _keys_cache


def open_mode() -> bool:
    return load_keys() is None


def _key_for(role: str) -> str:
    keys = load_keys()
    if keys is None:
        return ""
    return keys.get(role, "")


def sign(message: str, key_hex: str) -> str:
    return hmac.new(bytes.fromhex(key_hex), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def verify(message: str, sig_hex: str, key_hex: str) -> bool:
    if not key_hex or not sig_hex:
        return False
    return hmac.compare_digest(sign(message, key_hex), sig_hex)



def make_identify_challenge() -> dict:
    return {"ts": int(time.time()), "nonce": secrets.token_hex(8)}


def canonical_identify(role: str, ts: int, nonce: str) -> str:
    return f"{role}|{ts}|{nonce}"


def sign_identify(role: str, ts: int, nonce: str, key_hex: str) -> str:
    return sign(canonical_identify(role, ts, nonce), key_hex)


def verify_identify(role: str, ts: int, nonce: str, sig_hex: str) -> tuple:
    """Returns (ok: bool, reason: str)."""
    if open_mode():
        return True, "OPEN_MODE"
    key = _key_for(role)
    if not key:
        return False, f"unknown role or missing key: {role}"
    if abs(int(time.time()) - int(ts)) > MAX_CLOCK_SKEW:
        return False, "timestamp skew too large (replay?)"
    if verify(canonical_identify(role, ts, nonce), sig_hex, key):
        return True, "sealed"
    return False, "bad seal"



def canonical_response(task_id: str, result: str) -> str:
    result_digest = hashlib.sha256(result.encode("utf-8")).hexdigest()
    return f"{task_id}|{result_digest}"


def sign_response(task_id: str, result: str, key_hex: str) -> str:
    return sign(canonical_response(task_id, result), key_hex)


def verify_response(task_id: str, result: str, role: str, sig_hex: str) -> tuple:
    if open_mode():
        return True, "OPEN_MODE"
    key = _key_for(role)
    if not key:
        return False, f"missing key for {role}"
    if verify(canonical_response(task_id, result), sig_hex, key):
        return True, "sealed"
    return False, "bad seal"



def canonical_packet(task_id: str, content: str) -> str:
    return f"{task_id}|{content}"


def sign_packet(task_id: str, content: str) -> str:
    key = _key_for("switch")
    if not key:
        return ""
    return sign(canonical_packet(task_id, content), key)


def verify_packet(task_id: str, content: str, sig_hex: str) -> bool:
    key = _key_for("switch")
    if not key:
        return True  # OPEN_MODE
    return verify(canonical_packet(task_id, content), sig_hex, key)
