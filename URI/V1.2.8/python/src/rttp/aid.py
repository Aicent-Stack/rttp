"""
AID -- Autonomous Identity, derived exactly as demo.rs does.

SHA-256 derives the 256-bit identity DNA as two shards (Genesis^Resonance),
matching the AID_ORIGIN field (0x46, 256-bit) of RFC-002 sec. 4.1.
"""

import hashlib

SWITCH_SEED = b"imperial_nerve_genesis_2026_radiant_totality"


def derive_from_entropy(seed: bytes) -> dict:
    """Derive the 256-bit AID (two shards) from an entropy seed."""
    aid = hashlib.sha256(seed).digest()
    return {
        "aid": aid,
        "genesis_shard": aid[:16],
        "resonance_shard": aid[16:],
        "genesis_shard_hex": aid[:16].hex().upper(),
        "aid_hex": aid.hex(),
    }


def agent_seed(role: str) -> bytes:
    """Deterministic entropy seed for each Agent role."""
    return f"rttp_agent_{role}_genesis_2026".encode()


def switch_aid() -> dict:
    return derive_from_entropy(SWITCH_SEED)
