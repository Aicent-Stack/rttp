"""
seal_asym — Radiant Seal, **sovereign profile** (Ed25519, self-certifying)

Why this module exists
----------------------
`seal.py` is the **managed profile**: symmetric HMAC-SHA256 over a shared key
table. It is correct for a closed set of roles that already trust each other and
where the switch holds every key. It cannot be the basis of a public protocol,
because every holder of the `switch` key can forge every other party: inside a
set of symmetric secrets there is no such thing as a stranger.

This module is the **sovereign profile**. It makes three properties hold that
the managed profile cannot:

    1. **No issuance.** A participant generates its own key pair. Nobody hands
       out credentials, so nobody can withhold them.
    2. **Self-certifying identity.** AID = SHA-256(public key). The identity *is*
       the public key, so a verifier needs no registry and no directory lookup.
    3. **Asymmetric unforgeability.** Holding a key lets you sign as *yourself*
       and nobody else.

This is the same shape the RPKI-style Immune layer needs, which is why both
threads meet here.

Identity definition
-------------------
    AID = SHA-256(public_key)               (32 bytes)

derived via `aid.derive_from_entropy`, i.e. the *same* definition used by the
rest of the stack — so an AID means one thing everywhere, not two.

Wire form (the *envelope*)
--------------------------
The seal does **not** travel in the 128-byte header: `0x00`–`0x65` is frozen by
RFC-002 §4.1 and the v1.2.6 extension block has no room for a 64-byte signature.
An envelope wraps a frame (or any payload) instead:

    {
      "v":     1,
      "alg":   "ed25519",
      "aid":   "<32-byte hex>",   # = sha256(pub)  -- self-certification
      "pub":   "<32-byte hex>",   # carried in-band; no lookup needed
      "ts":    1760000000,        # unix seconds, inside the signed input
      "nonce": "<8-byte hex>",    # inside the signed input
      "sig":   "<64-byte hex>",   # ed25519 over the canonical input below
      "payload": { ... }
    }

`ts` and `nonce` are **inside** the signature, not beside it: an attacker who
could rewrite them would not need to break Ed25519 at all. They exist because
the managed profile (`seal.py`) already carried `ts|nonce` with a 120-second
window — the sovereign profile must not be *weaker* than the one it replaces.

Canonical signing input::

    b"rttp-seal-v1\\n" + json_canonical({
        "alg": ..., "aid": ..., "pub": ..., "ts": ..., "nonce": ..., "payload": ...
    })

`json_canonical` = UTF-8, sorted keys, no insignificant whitespace. Hex is
**lowercase only**, consistent with the canonical-form discipline of RFC-002
§10.3 — a case variant is not normalised, it is rejected.

Verification order (fail closed, never "best effort")
-----------------------------------------------------
    1. envelope version and `alg` are recognised
    2. hex fields are lowercase and the right length
    3. **sha256(pub) == aid** — self-certification
    4. **freshness**: `|now - ts| <= MAX_CLOCK_SKEW`
    5. Ed25519 signature over the canonical input

A failure at any step returns `(False, reason, None)`. Nothing is ever accepted
because a check could not be performed.

Draft status
------------
⚠ This envelope format is introduced in v1.2.6 and is **not yet part of
RFC-002**. It is specified in `SPEC/RTTP-SEAL-ENVELOPE-v1.2.6.md`; until that
document is folded into the RFC, treat it as a draft addition and say so when
you cite it.

Installing
----------
    pip install rttp[ed25519]

Without the extra, importing this module succeeds but every call raises
`SealError` with that instruction — it never degrades to an unauthenticated
path.
"""

from __future__ import annotations

import json
import os
import time

from . import aid as aid_mod

# ---------------------------------------------------------------------------
# 可选后端：缺失时明确失败，绝不静默降级为"无签名"
# ---------------------------------------------------------------------------

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    HAVE_ED25519 = True
    _IMPORT_ERROR = None
except ImportError as _exc:  # pragma: no cover - depends on the environment
    HAVE_ED25519 = False
    _IMPORT_ERROR = _exc

ALG = "ed25519"
ENVELOPE_VERSION = 1

#: Maximum accepted |now - ts|, in seconds.
MAX_CLOCK_SKEW = 120

#: Nonce length in bytes (hex-encoded on the wire).
NONCE_BYTES = 8

AID_BYTES = 32
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
SEED_BYTES = 32

CANONICAL_PREFIX = b"rttp-seal-v1\n"

INSTALL_HINT = "pip install rttp[ed25519]"


class SealError(Exception):
    """信封不可用、不可解析或格式非法。"""


def _require_backend() -> None:
    if not HAVE_ED25519:
        raise SealError(
            f"Ed25519 backend unavailable - install it with '{INSTALL_HINT}' "
            f"(import error: {_IMPORT_ERROR})")


# ---------------------------------------------------------------------------
# 身份
# ---------------------------------------------------------------------------

def aid_from_public_key(public_key: bytes) -> bytes:
    """AID = SHA-256(public_key)，32 字节。

    与 `aid.derive_from_entropy` 同一定义 ⇒ AID 在全栈只有一个含义。
    """
    if not isinstance(public_key, (bytes, bytearray)):
        raise SealError("public_key must be bytes")
    if len(public_key) != PUBLIC_KEY_BYTES:
        raise SealError(f"public_key must be {PUBLIC_KEY_BYTES} bytes")
    return aid_mod.derive_from_entropy(bytes(public_key))["aid"]


def generate_keypair(seed: bytes = None) -> dict:
    """生成一对 Ed25519 密钥，并回传其 AID。

    :param seed: 32 字节种子。**仅用于产生可复现的测试向量**；生产调用应省略，
                 由操作系统熵源生成。
    """
    _require_backend()
    if seed is None:
        private_key = Ed25519PrivateKey.generate()
    else:
        if not isinstance(seed, (bytes, bytearray)) or len(seed) != SEED_BYTES:
            raise SealError(f"seed must be {SEED_BYTES} bytes")
        private_key = Ed25519PrivateKey.from_private_bytes(bytes(seed))

    raw_seed = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    aid_bytes = aid_from_public_key(public_key)

    return {
        "private_key": private_key,          # 签名用（勿外传）
        "seed": raw_seed,                    # 32B 私钥种子（勿外传）
        "public_key": public_key,            # 32B
        "aid": aid_bytes,                    # 32B = sha256(public_key)
        "seed_hex": raw_seed.hex(),
        "public_hex": public_key.hex(),
        "aid_hex": aid_bytes.hex(),
    }


def public_bundle(keypair: dict) -> dict:
    """可安全公开的部分（身份 + 公钥），不含任何私钥材料。"""
    return {"alg": ALG, "aid": keypair["aid_hex"], "pub": keypair["public_hex"]}


# ---------------------------------------------------------------------------
# 规范化签名输入
# ---------------------------------------------------------------------------

def _hex_lower(value, what: str, nbytes: int) -> str:
    if not isinstance(value, str):
        raise SealError(f"{what} must be a hex string")
    if value != value.lower():
        raise SealError(f"{what} must be lowercase hex (RFC-002 §10.3)")
    if len(value) != nbytes * 2:
        raise SealError(f"{what} must be {nbytes} bytes ({nbytes * 2} hex chars)")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise SealError(f"{what} is not valid hex: {exc}") from exc
    return value


def json_canonical(obj) -> bytes:
    """确定性 JSON 编码（UTF-8 · 键排序 · 无多余空白）。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def signing_input(alg: str, aid_hex: str, pub_hex: str, ts: int, nonce: str,
                  payload: dict) -> bytes:
    """被签名的字节序列。信封里除 `sig` 外的全部字段都进入此输入。

    `ts` / `nonce` **必须**在签名之内 —— 否则改写它们根本不需要破解
    Ed25519，防重放就成了摆设。
    """
    return CANONICAL_PREFIX + json_canonical({
        "alg": alg,
        "aid": aid_hex,
        "pub": pub_hex,
        "ts": ts,
        "nonce": nonce,
        "payload": payload,
    })


# ---------------------------------------------------------------------------
# 封装 / 验证
# ---------------------------------------------------------------------------

def seal(payload: dict, keypair: dict, ts: int = None, nonce: str = None) -> dict:
    """用自有私钥把 payload 封成自证明信封。

    :param ts:    unix 秒。省略则取当前时刻。**传入仅为产生可复现向量** ——
                  生产调用不要传，否则等于把重放窗口钉死在某个时刻。
    :param nonce: `NONCE_BYTES` 字节小写 hex。省略则取操作系统熵源。
    """
    _require_backend()
    if not isinstance(payload, dict):
        raise SealError("payload must be a dict")
    if not isinstance(keypair, dict) or "private_key" not in keypair:
        raise SealError("keypair must come from generate_keypair()")

    if ts is None:
        ts = int(time.time())
    if not isinstance(ts, int) or isinstance(ts, bool):
        raise SealError("ts must be an integer (unix seconds)")

    if nonce is None:
        nonce = os.urandom(NONCE_BYTES).hex()
    _hex_lower(nonce, "nonce", NONCE_BYTES)

    aid_hex = keypair["aid_hex"]
    pub_hex = keypair["public_hex"]
    signature = keypair["private_key"].sign(
        signing_input(ALG, aid_hex, pub_hex, ts, nonce, payload))

    return {
        "v": ENVELOPE_VERSION,
        "alg": ALG,
        "aid": aid_hex,
        "pub": pub_hex,
        "ts": ts,
        "nonce": nonce,
        "sig": signature.hex(),
        "payload": payload,
    }


def verify_envelope(envelope: dict, now: int = None,
                    max_skew: int = MAX_CLOCK_SKEW,
                    check_freshness: bool = True) -> tuple:
    """验证信封。返回 `(ok: bool, reason: str, aid_hex: str | None)`。

    任何一步失败即返回 False —— **绝不把"无法检查"当成"通过"**。

    :param check_freshness: 默认 True。设为 False **仅**用于校验已归档的信封
        （例如审计历史记录）。面对任何网络输入必须保持 True —— 关掉它，
        重放攻击即刻成立。
    """
    try:
        _require_backend()

        if not isinstance(envelope, dict):
            return False, "envelope must be a dict", None
        if envelope.get("v") != ENVELOPE_VERSION:
            return False, f"unsupported envelope version: {envelope.get('v')!r}", None
        if envelope.get("alg") != ALG:
            return False, f"unsupported algorithm: {envelope.get('alg')!r}", None

        aid_hex = _hex_lower(envelope.get("aid"), "aid", AID_BYTES)
        pub_hex = _hex_lower(envelope.get("pub"), "pub", PUBLIC_KEY_BYTES)
        sig_hex = _hex_lower(envelope.get("sig"), "sig", SIGNATURE_BYTES)
        nonce = _hex_lower(envelope.get("nonce"), "nonce", NONCE_BYTES)

        ts = envelope.get("ts")
        if not isinstance(ts, int) or isinstance(ts, bool):
            return False, "ts must be an integer (unix seconds)", None

        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return False, "payload must be an object", None

        if check_freshness:
            reference = int(time.time()) if now is None else now
            drift = abs(reference - ts)
            if drift > max_skew:
                return False, (f"timestamp skew too large ({drift}s > {max_skew}s)"
                               " - replay?"), None

        public_key = bytes.fromhex(pub_hex)

        # --- 自证明：身份必须由公钥推出，而不是被声称 ---
        if aid_from_public_key(public_key).hex() != aid_hex:
            return False, "AID does not match public key (self-certification failed)", None

        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(sig_hex),
            signing_input(ALG, aid_hex, pub_hex, ts, nonce, payload),
        )
        return True, "sealed", aid_hex

    except InvalidSignature:
        return False, "bad seal (signature does not verify)", None
    except SealError as exc:
        return False, str(exc), None
    except (ValueError, TypeError, KeyError) as exc:
        return False, f"malformed envelope: {exc}", None


def unseal(envelope: dict, now: int = None,
           check_freshness: bool = True) -> dict:
    """验证通过则返回 payload；否则抛 SealError（含原因）。"""
    ok, reason, _aid = verify_envelope(envelope, now=now,
                                       check_freshness=check_freshness)
    if not ok:
        raise SealError(reason)
    return envelope["payload"]


def verify_claims(envelope: dict, expected_aid_hex: str = None,
                  now: int = None, check_freshness: bool = True) -> tuple:
    """验证信封，并（可选）要求它确实来自某个预期的 AID。

    与帧层的 `expected_aid_origin` 是同一个纪律：来源可以被要求，也可以不被。
    """
    ok, reason, aid_hex = verify_envelope(envelope, now=now,
                                          check_freshness=check_freshness)
    if not ok:
        return False, reason
    if expected_aid_hex is not None and aid_hex != expected_aid_hex.lower():
        return False, "AID mismatch (spoofed origin?)"
    return True, "sealed"
