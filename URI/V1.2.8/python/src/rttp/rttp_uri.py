"""
rttp_uri -- parse, canonicalise and derive ROUTE_SHARD for `rttp` URIs (RFC-002 sec. 10).

This is the reference implementation of the mapping promised by RFC-002 sec. 10.4:
"Dereferencing an `rttp` URI emits one pulse ... carrying `action` as the intent
verb." The specification had the grammar (sec. 10.2 ABNF) but no URI -> frame-field
mapping; this module and SPEC/RTTP-FRAME-EXT-v1.2.6.md supply that step.

Authority boundary:
    * the only authority for URI syntax is the RFC-002 sec. 10.2 ABNF; this module
      adds none
    * it does two things: validate and canonicalise per sec. 10.2 / sec. 10.3, and
      derive ROUTE_SHARD

Design constraints (one per source clause):
    * sec. 10.1  intent is either 8 lowercase hex digits (32-bit routing hash) or a
                 readable organ token
    * sec. 10.2  action is an open set: 1*( lowercase letter / DIGIT / "-" )
    * sec. 10.3  canonical form is lowercase US-ASCII; no userinfo / port / query /
                 fragment
    * sec. 10.5  no DNS: ROUTE_SHARD is pure computation, no registry, no network

ROUTE_SHARD derivation: spec sec. 5 -- the first 16 bytes of SHA-256(authority).
"""

from __future__ import annotations

import hashlib

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

SCHEME = "rttp"
WEB_SCHEME = "web+rttp"

ROUTE_SHARD_BYTES = 16                       # sec. 4.1 ROUTE_SHARD = u128

# sec. 10.2:  name-intent / pillar / root / action = 1*( %x61-7A / DIGIT / "-" )
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_DIGITS = "0123456789"
_TOKEN_CHARS = frozenset(_LOWER + _DIGITS + "-")
_HEX_CHARS = frozenset("0123456789abcdef")   # sec. 10.2 lowhex = %x30-39 / %x61-66

HASH_INTENT_LEN = 8

_FORBIDDEN_CHARS = ("@", "?", "#", "[", "]")


class RttpUriError(ValueError):
    """The URI is not conformant. Always fail closed (sec. 10.5: no fallback, no rttps)."""


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _check_token(value: str, what: str) -> None:
    if not value:
        raise RttpUriError(f"{what} is empty")
    for ch in value:
        if ch in _TOKEN_CHARS:
            continue
        if ch.isupper():
            raise RttpUriError(
                f"{what} contains uppercase '{ch}' - lowercase US-ASCII only (RFC-002 sec. 10.3)")
        raise RttpUriError(
            f"{what} contains illegal character {ch!r} "
            f"(allowed: a-z, 0-9, '-')")
    if value[0] == "-" or value[-1] == "-":
        raise RttpUriError(f"{what} must not begin or end with '-'")


def _check_intent(value: str) -> bool:
    """True for hash-intent (8 lowercase hex digits), False for name-intent."""
    if len(value) == HASH_INTENT_LEN and all(c in _HEX_CHARS for c in value):
        return True
    _check_token(value, "intent")
    return False


def is_valid_action(value: str) -> bool:
    """Judge the sec. 10.2 action grammar: 1*( lowercase letter / DIGIT / "-" ).
    
        `action` is an open set -- this checks the shape only, never whether the verb
        has a known meaning. Shared with the frame layer so the rule is written once.
        """
    if not isinstance(value, str) or not value:
        return False
    if value[0] == "-" or value[-1] == "-":
        return False
    return all(c in _TOKEN_CHARS for c in value)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def parse(uri: str) -> dict:
    """Parse one `rttp` URI and return the canonical fields.
    
        The order of checks is deliberately reject-first: any suspicious shape raises
        immediately and intent is never guessed.
        (sec. 10.5: user agents that do not implement this scheme fail closed.)
        """
    if not isinstance(uri, str):
        raise RttpUriError("uri must be a string")
    if not uri:
        raise RttpUriError("uri is empty")
    if uri != uri.strip():
        raise RttpUriError("uri must not contain leading/trailing whitespace")

    if uri.startswith(WEB_SCHEME + "://"):
        scheme = WEB_SCHEME
        rest = uri[len(WEB_SCHEME) + 3:]
    elif uri.startswith(SCHEME + "://"):
        scheme = SCHEME
        rest = uri[len(SCHEME) + 3:]
    else:
        raise RttpUriError(
            f"not an rttp URI: must begin with '{SCHEME}://' or '{WEB_SCHEME}://'")

    for ch in _FORBIDDEN_CHARS:
        if ch in uri:
            raise RttpUriError(
                f"illegal character {ch!r}: this scheme defines no "
                f"userinfo / query / fragment")

    authority, sep, action = rest.partition("/")
    if sep and "/" in action:
        raise RttpUriError("path must be a single segment '/<action>'")
    if sep and not action:
        raise RttpUriError("trailing '/' with empty action: path must be '/<action>'")

    parts = authority.split(".")
    if len(parts) != 3:
        raise RttpUriError(
            f"authority must be exactly '<intent>.<pillar>.<root>' "
            f"(got {len(parts)} segment(s))")
    intent, pillar, root = parts

    is_hash = _check_intent(intent)
    _check_token(pillar, "pillar")
    _check_token(root, "root")
    if action:
        _check_token(action, "action")

    canonical_authority = f"{intent}.{pillar}.{root}"
    canonical_uri = f"{SCHEME}://{canonical_authority}"
    if action:
        canonical_uri += f"/{action}"

    return {
        "scheme": scheme,
        "intent": intent,
        "intent_is_hash": is_hash,
        "intent_hash32": int(intent, 16) if is_hash else None,
        "pillar": pillar,
        "root": root,
        "action": action,
        "action_omitted": action == "",
        "authority": canonical_authority,
        "canonical_uri": canonical_uri,
        "route_shard": derive_route_shard(canonical_authority),
    }


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def derive_route_shard(canonical_authority: str) -> bytes:
    """authority -> ROUTE_SHARD (16 bytes).
    
        ROUTE_SHARD = SHA-256( ASCII(canonical_authority) )[0:16]
    
        Properties:
          * deterministic: the same authority always yields the same shard
          * pure computation: no DNS, no registry, no network (sec. 10.5)
          * one-way: a shard cannot be turned back into an authority (SHA-256 preimage)
          * independent of action: it routes to *where*, not to *what*, which is why
            `action` exists as its own frame field (spec sec. 5.3)
        """
    if not canonical_authority:
        raise RttpUriError("canonical_authority is empty")
    if canonical_authority != canonical_authority.lower():
        raise RttpUriError("canonical_authority must be lowercase (RFC-002 sec. 10.3)")
    return hashlib.sha256(canonical_authority.encode("ascii")).digest()[:ROUTE_SHARD_BYTES]


def route_shard_hex(canonical_authority: str) -> str:
    return derive_route_shard(canonical_authority).hex()


def parse_and_derive(uri: str) -> dict:
    """Convenience entry point: parse and derive in one step."""
    return parse(uri)


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        try:
            r = parse(arg)
            print(f"OK    {r['canonical_uri']}")
            print(f"      authority   = {r['authority']}")
            print(f"      route_shard = {r['route_shard'].hex()}")
            print(f"      action      = {r['action'] or '(omitted)'}")
        except RttpUriError as exc:
            print(f"REJECT {arg}\n      {exc}")
