"""
Radiant Seal — RTTP v1.3.0 节点签名验证（HMAC-SHA256）

信任模型:
    * 每个 Agent 持有独立 32 字节密钥（seal_keys.json 中 node-* 条目）
    * 交换机持有 switch 密钥，发给 Agent 的数据包同样签名（双向验证）
    * RTTP_IDENTIFY: 签名内容 = "role|ts|nonce"  （防重放：ts 偏差 > 120s 拒收）
    * RTTP_RESPONSE: 签名内容 = task_id 与 result 的 sha256 绑定
    * 未知角色 / 密钥缺失 → 拒绝（fail-closed）

密钥文件缺失时进入 OPEN_MODE（仅本地开发用），并在每条日志中明示。
"""

import hashlib
import hmac
import json
import os
import secrets
import time

KEYFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "seal_keys.json")
MAX_CLOCK_SKEW = 120  # 秒

_keys_cache = None


def load_keys(force=False):
    """读取密钥表；文件缺失时返回 None（OPEN_MODE）。"""
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


# ---- IDENTIFY 签名 ----

def make_identify_challenge() -> dict:
    return {"ts": int(time.time()), "nonce": secrets.token_hex(8)}


def canonical_identify(role: str, ts: int, nonce: str) -> str:
    return f"{role}|{ts}|{nonce}"


def sign_identify(role: str, ts: int, nonce: str, key_hex: str) -> str:
    return sign(canonical_identify(role, ts, nonce), key_hex)


def verify_identify(role: str, ts: int, nonce: str, sig_hex: str) -> tuple:
    """返回 (ok: bool, reason: str)。"""
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


# ---- RESPONSE 签名（Agent → 交换机）----

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


# ---- 交换机签名（交换机 → Agent，双向信任）----

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
