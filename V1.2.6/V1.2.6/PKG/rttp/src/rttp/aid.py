"""
AID — Autonomous Identity（对齐 demo.rs: AID::derive_from_entropy）

demo.rs 原文: let node_aid = AID::derive_from_entropy(node_seed);
             NODE_AID_GENESIS: {:032X}  →  genesis_shard 为 u128（16 字节）

本模块以 SHA-256 派生 256-bit 身份 DNA（双分片: Genesis^Resonance），
与 RFC-002 §4.1 的 AID_ORIGIN (0x46, 256-bit) 字段直接对应。
"""

import hashlib

# 交换机（Imperial Nerve）的熵种子 —— 与 demo.rs 中的种子一致
SWITCH_SEED = b"imperial_nerve_genesis_2026_radiant_totality"


def derive_from_entropy(seed: bytes) -> dict:
    """从熵种子派生 256-bit AID（双分片）。"""
    aid = hashlib.sha256(seed).digest()
    return {
        "aid": aid,                                # 32B 完整身份 DNA
        "genesis_shard": aid[:16],                 # u128 Genesis 分片
        "resonance_shard": aid[16:],               # u128 Resonance 分片
        "genesis_shard_hex": aid[:16].hex().upper(),
        "aid_hex": aid.hex(),
    }


def agent_seed(role: str) -> bytes:
    """各 Agent 角色的确定性熵种子。"""
    return f"rttp_agent_{role}_genesis_2026".encode()


def switch_aid() -> dict:
    return derive_from_entropy(SWITCH_SEED)
