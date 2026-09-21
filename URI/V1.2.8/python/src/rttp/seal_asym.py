"""
seal_asym -- Radiant Seal, **sovereign profile** (Ed25519, self-certifying)

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
rest of the stack -- so an AID means one thing everywhere, not two.

Wire form (the *envelope*)
--------------------------
The seal does **not** travel in the 128-byte header: `0x00`-`0x65` is frozen by
RFC-002 sec. 4.1 and the v1.2.6 extension block has no room for a 64-byte signature.
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
window -- the sovereign profile must not be *weaker* than the one it replaces.

Canonical signing input::

    b"rttp-seal-v1\\n" + json_canonical({
        "alg": ..., "aid": ..., "pub": ..., "ts": ..., "nonce": ..., "payload": ...
    })

`json_canonical` = UTF-8, sorted keys, no insignificant whitespace. Hex is
**lowercase only**, consistent with the canonical-form discipline of RFC-002
sec. 10.3 -- a case variant is not normalised, it is rejected.

Verification order (fail closed, never "best effort")
-----------------------------------------------------
    1. envelope version and `alg` are recognised
    2. hex fields are lowercase and the right length
    3. **sha256(pub) == aid** -- self-certification
    4. **freshness**: `|now - ts| <= MAX_CLOCK_SKEW`
    5. Ed25519 signature over the canonical input

A failure at any step returns `(False, reason, None)`. Nothing is ever accepted
because a check could not be performed.

Draft status
------------
NOTE: This envelope format is introduced in v1.2.6 and is **not yet part of
RFC-002**. It is specified in `SPEC/RTTP-SEAL-ENVELOPE-v1.2.6.md`; until that
document is folded into the RFC, treat it as a draft addition and say so when
you cite it.

Installing
----------
    pip install rttp[ed25519]

Without the extra, importing this module succeeds but every call raises
`SealError` with that instruction -- it never degrades to an unauthenticated
path.
"""

from __future__ import annotations

import json
import os
import time

from . import aid as aid_mod

# ---------------------------------------------------------------------------
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
    """The envelope is unavailable, unparsable or malformed."""


def _require_backend() -> None:
    if not HAVE_ED25519:
        raise SealError(
            f"Ed25519 backend unavailable - install it with '{INSTALL_HINT}' "
            f"(import error: {_IMPORT_ERROR})")


# ---------------------------------------------------------------------------
# Signature backend (injectable)
# ---------------------------------------------------------------------------
#
# A default install (zero dependencies) has no `cryptography`, yet the *rule*
# layer of an envelope - version, algorithm, hex shape, ts and payload types,
# freshness, self-certification - needs no primitive at all. The self-test
# therefore runs that layer always, and the flow layer (round-trip,
# determinism, tamper matrix) with an injected test signer, which is what
# proves the binding property: which fields the signed bytes cover.
#
# The test signer is NOT Ed25519. The real primitive is proven separately by
# the RFC 8032 vectors. Injection happens only through a function argument:
# there is no mutable module state and no environment switch.


class SealBackend:
    """Signature backend interface. Default implementation: Ed25519."""

    name = "abstract"

    def available(self) -> bool:
        return False

    def from_seed(self, seed: bytes):
        raise SealError(f"{self.name} backend unavailable")

    def generate(self):
        raise SealError(f"{self.name} backend unavailable")

    def private_bytes(self, private_key) -> bytes:
        raise SealError(f"{self.name} backend unavailable")

    def public_bytes(self, private_key) -> bytes:
        raise SealError(f"{self.name} backend unavailable")

    def sign(self, private_key, message: bytes) -> bytes:
        raise SealError(f"{self.name} backend unavailable")

    def verify(self, public_key: bytes, signature: bytes, message: bytes) -> bool:
        raise SealError(f"{self.name} backend unavailable")


class CryptographyBackend(SealBackend):
    """Native backend: standard Ed25519 as provided by `cryptography`."""

    name = "cryptography"

    def available(self) -> bool:
        return HAVE_ED25519

    def from_seed(self, seed: bytes):
        return Ed25519PrivateKey.from_private_bytes(bytes(seed))

    def generate(self):
        return Ed25519PrivateKey.generate()

    def private_bytes(self, private_key) -> bytes:
        return private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_bytes(self, private_key) -> bytes:
        return private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, private_key, message: bytes) -> bytes:
        return private_key.sign(message)

    def verify(self, public_key: bytes, signature: bytes, message: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
            return True
        except InvalidSignature:
            return False


NATIVE_BACKEND = CryptographyBackend()


def _resolve_backend(backend=None) -> SealBackend:
    chosen = NATIVE_BACKEND if backend is None else backend
    if chosen.available():
        return chosen
    raise SealError(
        f"{chosen.name} backend unavailable - install it with '{INSTALL_HINT}' "
        f"(import error: {_IMPORT_ERROR})")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def aid_from_public_key(public_key: bytes) -> bytes:
    """AID = SHA-256(public_key), 32 bytes.
    
        Same definition as `aid.derive_from_entropy`, so an AID means one thing across
        the stack.
        """
    if not isinstance(public_key, (bytes, bytearray)):
        raise SealError("public_key must be bytes")
    if len(public_key) != PUBLIC_KEY_BYTES:
        raise SealError(f"public_key must be {PUBLIC_KEY_BYTES} bytes")
    return aid_mod.derive_from_entropy(bytes(public_key))["aid"]


def generate_keypair(seed: bytes = None, backend: SealBackend = None) -> dict:
    """Generate an Ed25519 key pair and return its AID.
    
        :param seed: 32-byte seed. **For reproducible test vectors only**; omit it in
                     production and let the OS entropy source decide.
        """
    backend = _resolve_backend(backend)
    if seed is None:
        private_key = backend.generate()
    else:
        if not isinstance(seed, (bytes, bytearray)) or len(seed) != SEED_BYTES:
            raise SealError(f"seed must be {SEED_BYTES} bytes")
        private_key = backend.from_seed(bytes(seed))

    raw_seed = backend.private_bytes(private_key)
    public_key = backend.public_bytes(private_key)
    aid_bytes = aid_from_public_key(public_key)

    return {
        "private_key": private_key,
        "seed": raw_seed,
        "public_key": public_key,            # 32B
        "aid": aid_bytes,                    # 32B = sha256(public_key)
        "seed_hex": raw_seed.hex(),
        "public_hex": public_key.hex(),
        "aid_hex": aid_bytes.hex(),
        "backend": backend,
    }


def public_bundle(keypair: dict) -> dict:
    """The safely publishable part (identity and public key); no private material."""
    return {"alg": ALG, "aid": keypair["aid_hex"], "pub": keypair["public_hex"]}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _hex_lower(value, what: str, nbytes: int) -> str:
    if not isinstance(value, str):
        raise SealError(f"{what} must be a hex string")
    if value != value.lower():
        raise SealError(f"{what} must be lowercase hex (RFC-002 sec. 10.3)")
    if len(value) != nbytes * 2:
        raise SealError(f"{what} must be {nbytes} bytes ({nbytes * 2} hex chars)")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise SealError(f"{what} is not valid hex: {exc}") from exc
    return value


def json_canonical(obj) -> bytes:
    """Deterministic JSON encoding (UTF-8, sorted keys, no insignificant space)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def signing_input(alg: str, aid_hex: str, pub_hex: str, ts: int, nonce: str,
                  payload: dict) -> bytes:
    """The signed byte sequence. Every envelope field except `sig` enters this input.
    
        `ts` / `nonce` MUST be inside the signature -- beside it, rewriting them would
        not touch Ed25519 at all and replay defence would be decorative.
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
# ---------------------------------------------------------------------------

def seal(payload: dict, keypair: dict, ts: int = None, nonce: str = None) -> dict:
    """Seal a payload into a self-certifying envelope with your own key.
    
        :param ts:    unix seconds. Omitted = now. **Pass it only for reproducible
                      vectors** -- in production it pins the replay window.
        :param nonce: `NONCE_BYTES` bytes as lowercase hex. Omitted = OS entropy.
        """
    if not isinstance(payload, dict):
        raise SealError("payload must be a dict")
    if not isinstance(keypair, dict) or "private_key" not in keypair:
        raise SealError("keypair must come from generate_keypair()")
    backend = keypair.get("backend") or _resolve_backend()

    if ts is None:
        ts = int(time.time())
    if not isinstance(ts, int) or isinstance(ts, bool):
        raise SealError("ts must be an integer (unix seconds)")

    if nonce is None:
        nonce = os.urandom(NONCE_BYTES).hex()
    _hex_lower(nonce, "nonce", NONCE_BYTES)

    aid_hex = keypair["aid_hex"]
    pub_hex = keypair["public_hex"]
    signature = backend.sign(
        keypair["private_key"],
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


def check_envelope(envelope: dict, now: int = None,
                   max_skew: int = MAX_CLOCK_SKEW,
                   check_freshness: bool = True) -> tuple:
    """Envelope rules: everything except the signature.

    This layer needs no cryptographic primitive, so a default install (zero
    dependencies) runs all of it. Returns (ok, reason). Any failed step is a
    False - "could not check" is never treated as "passed".
    """
    if not isinstance(envelope, dict):
        return False, "envelope must be a dict"
    if envelope.get("v") != ENVELOPE_VERSION:
        return False, f"unsupported envelope version: {envelope.get('v')!r}"
    if envelope.get("alg") != ALG:
        return False, f"unsupported algorithm: {envelope.get('alg')!r}"
    try:
        aid_hex = _hex_lower(envelope.get("aid"), "aid", AID_BYTES)
        pub_hex = _hex_lower(envelope.get("pub"), "pub", PUBLIC_KEY_BYTES)
        _hex_lower(envelope.get("sig"), "sig", SIGNATURE_BYTES)
        _hex_lower(envelope.get("nonce"), "nonce", NONCE_BYTES)
    except SealError as exc:
        return False, str(exc)

    ts = envelope.get("ts")
    if not isinstance(ts, int) or isinstance(ts, bool):
        return False, "ts must be an integer (unix seconds)"

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return False, "payload must be an object"

    if check_freshness:
        reference = int(time.time()) if now is None else now
        drift = abs(reference - ts)
        if drift > max_skew:
            return False, (f"timestamp skew too large ({drift}s > {max_skew}s)"
                           " - replay?")

    if aid_from_public_key(bytes.fromhex(pub_hex)).hex() != aid_hex:
        return False, "AID does not match public key (self-certification failed)"
    return True, "rules ok"


def verify_envelope(envelope: dict, now: int = None,
                    max_skew: int = MAX_CLOCK_SKEW,
                    check_freshness: bool = True,
                    backend: SealBackend = None) -> tuple:
    """Verify an envelope. Returns `(ok: bool, reason: str, aid_hex | None)`.
    
        Any failed step returns False -- "could not check" is never treated as "passed".
    
        :param check_freshness: default True. False is **only** for archived envelopes
            (audit records, test vectors). On live network input it must stay True --
            turn it off and replay attacks become trivial.
        """
    ok, reason = check_envelope(envelope, now=now, max_skew=max_skew,
                                check_freshness=check_freshness)
    if not ok:
        return False, reason, None
    try:
        chosen = _resolve_backend(backend)
        aid_hex = envelope["aid"]
        pub_hex = envelope["pub"]
        sig_hex = envelope["sig"]
        nonce = envelope["nonce"]
        ts = envelope["ts"]
        payload = envelope["payload"]
        public_key = bytes.fromhex(pub_hex)

        if aid_from_public_key(public_key).hex() != aid_hex:
            return False, "AID does not match public key (self-certification failed)", None

        if not chosen.verify(
                public_key, bytes.fromhex(sig_hex),
                signing_input(ALG, aid_hex, pub_hex, ts, nonce, payload)):
            return False, "bad seal (signature does not verify)", None
        return True, "sealed", aid_hex

    except SealError as exc:
        return False, str(exc), None
    except (ValueError, TypeError, KeyError) as exc:
        return False, f"malformed envelope: {exc}", None
    except Exception as exc:  # noqa: BLE001 - fail closed on any backend error
        return False, f"bad seal ({type(exc).__name__}: {exc})", None


def unseal(envelope: dict, now: int = None,
           check_freshness: bool = True,
           backend: SealBackend = None) -> dict:
    """Return the payload if the envelope verifies; otherwise raise SealError."""
    ok, reason, _aid = verify_envelope(envelope, now=now,
                                       check_freshness=check_freshness,
                                       backend=backend)
    if not ok:
        raise SealError(reason)
    return envelope["payload"]


def verify_claims(envelope: dict, expected_aid_hex: str = None,
                  now: int = None, check_freshness: bool = True,
                  backend: SealBackend = None) -> tuple:
    """Verify an envelope and, optionally, require it to come from an expected AID.
    
        Same discipline as `expected_aid_origin` in the frame layer: the origin may be
        required, or it may not.
        """
    ok, reason, aid_hex = verify_envelope(envelope, now=now,
                                          check_freshness=check_freshness,
                                          backend=backend)
    if not ok:
        return False, reason
    if expected_aid_hex is not None and aid_hex != expected_aid_hex.lower():
        return False, "AID mismatch (spoofed origin?)"
    return True, "sealed"
