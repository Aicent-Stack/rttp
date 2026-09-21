"""
rttp_uri — RFC-002 §10 `rttp` URI 解析 / 规范化 / ROUTE_SHARD 派生

本模块是 RFC-002 §10.4 所承诺映射的**参考实现**：
    "Dereferencing an `rttp` URI emits one pulse ... carrying `action` as the intent verb."
规范此前只有语法（§10.2 ABNF），没有「URI → 帧字段」的映射；本模块与
`SPEC/RTTP-FRAME-EXT-v1.2.6.md` 一起补上这一段。

权威边界（重要）：
    * URI **语法**唯一权威 = RFC-002 §10.2 ABNF。本模块不新增语法。
    * 本模块只做两件事：① 按 §10.2/§10.3 校验并**规范化**；② 派生 ROUTE_SHARD。

设计约束（逐条对应规范原文）：
    * §10.1  intent 既可为 8 位小写 hex（32-bit routing hash），也可为可读 organ token
    * §10.2  action 是**开集**：1*( %x61-7A / DIGIT / "-" )，例如 vessel / verify / pulse
    * §10.3  规范形式为**小写 US-ASCII**；无 userinfo / port / query / fragment
    * §10.5  **不解析 DNS**：ROUTE_SHARD 纯计算可得，不依赖任何注册表或网络

ROUTE_SHARD 派生规则：见 spec §5。一句话：取 authority 的 SHA-256 前 16 字节。
"""

from __future__ import annotations

import hashlib

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCHEME = "rttp"
WEB_SCHEME = "web+rttp"                      # 浏览器处理器形态：容忍，非规范定义（2026-09-17 起规范不再定义它）

ROUTE_SHARD_BYTES = 16                       # §4.1 ROUTE_SHARD = u128

# §10.2:  name-intent / pillar / root / action = 1*( %x61-7A / DIGIT / "-" )
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_DIGITS = "0123456789"
_TOKEN_CHARS = frozenset(_LOWER + _DIGITS + "-")
_HEX_CHARS = frozenset("0123456789abcdef")   # §10.2 lowhex = %x30-39 / %x61-66

HASH_INTENT_LEN = 8                          # 8 位小写 hex = 32-bit routing hash

# §10.3: 本 scheme 不定义 userinfo / port / query / fragment
_FORBIDDEN_CHARS = ("@", "?", "#", "[", "]")


class RttpUriError(ValueError):
    """URI 不合规。**一律 fail closed**（§10.5：无 fallback，无 rttps）。"""


# ---------------------------------------------------------------------------
# 校验助手
# ---------------------------------------------------------------------------

def _check_token(value: str, what: str) -> None:
    if not value:
        raise RttpUriError(f"{what} is empty")
    for ch in value:
        if ch in _TOKEN_CHARS:
            continue
        if ch.isupper():
            # §10.3 规范形式为小写。大写**不是**可归一化的书写差异，而是非法输入。
            raise RttpUriError(
                f"{what} contains uppercase '{ch}' - lowercase US-ASCII only (RFC-002 §10.3)")
        raise RttpUriError(
            f"{what} contains illegal character {ch!r} "
            f"(allowed: a-z, 0-9, '-')")
    if value[0] == "-" or value[-1] == "-":
        raise RttpUriError(f"{what} must not begin or end with '-'")


def _check_intent(value: str) -> bool:
    """返回 True 表示 hash-intent（8 lowhex），False 表示 name-intent。"""
    if len(value) == HASH_INTENT_LEN and all(c in _HEX_CHARS for c in value):
        return True
    _check_token(value, "intent")
    return False


def is_valid_action(value: str) -> bool:
    """§10.2 action 语法判定：1*( %x61-7A / DIGIT / "-" )。

    `action` 是**开集** —— 本函数只判**形态**，不判动词是否已知语义。
    供帧层（`pulse_header`）复用，避免把同一条规则写两遍。
    """
    if not isinstance(value, str) or not value:
        return False
    if value[0] == "-" or value[-1] == "-":
        return False
    return all(c in _TOKEN_CHARS for c in value)


# ---------------------------------------------------------------------------
# 解析 / 规范化
# ---------------------------------------------------------------------------

def parse(uri: str) -> dict:
    """解析一条 `rttp` URI，返回规范化字段。

    校验顺序刻意保持「先拒斥、后解释」：任何可疑形态立即抛错，绝不猜测意图。
    （§10.5: user agents that do not implement this scheme fail closed.）
    """
    if not isinstance(uri, str):
        raise RttpUriError("uri must be a string")
    if not uri:
        raise RttpUriError("uri is empty")
    if uri != uri.strip():
        # 前后空白：可能是粘贴污染，也可能是绕过前缀检查的尝试 —— 拒斥。
        raise RttpUriError("uri must not contain leading/trailing whitespace")

    # --- scheme（§10.6 前缀白名单）---
    if uri.startswith(WEB_SCHEME + "://"):
        scheme = WEB_SCHEME
        rest = uri[len(WEB_SCHEME) + 3:]
    elif uri.startswith(SCHEME + "://"):
        scheme = SCHEME
        rest = uri[len(SCHEME) + 3:]
    else:
        raise RttpUriError(
            f"not an rttp URI: must begin with '{SCHEME}://' or '{WEB_SCHEME}://'")

    # --- §10.3 排除字符 ---
    for ch in _FORBIDDEN_CHARS:
        if ch in uri:
            raise RttpUriError(
                f"illegal character {ch!r}: this scheme defines no "
                f"userinfo / query / fragment")

    # --- authority 与 path ---
    authority, sep, action = rest.partition("/")
    if sep and "/" in action:
        raise RttpUriError("path must be a single segment '/<action>'")
    if sep and not action:
        # §10.2: path = "/" action, action = 1*(...) —— 至少一个字符。
        # "带空 action 的尾斜杠" 与 "无 path" 是两种不同形态，不可混同。
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
        "action": action,                      # "" = 省略（§10.4 默认操作）
        "action_omitted": action == "",
        "authority": canonical_authority,
        "canonical_uri": canonical_uri,
        "route_shard": derive_route_shard(canonical_authority),
    }


# ---------------------------------------------------------------------------
# ROUTE_SHARD 派生（本文件的核心；规范此前未定义）
# ---------------------------------------------------------------------------

def derive_route_shard(canonical_authority: str) -> bytes:
    """authority → ROUTE_SHARD（16 字节）。

    ROUTE_SHARD = SHA-256( ASCII(canonical_authority) )[0:16]

    性质：
      * **确定性**：同一 authority 永远同一 shard。
      * **纯计算**：无 DNS、无注册表、无网络（§10.5）。
      * **单向**：不可是从 shard 还原 authority（SHA-256 前像抗性）。
      * **与 action 无关**：路由到「哪里」，不路由到「做什么」——
        这正是 `action` 必须作为独立帧字段存在的原因（见 spec §5.3）。
    """
    if not canonical_authority:
        raise RttpUriError("canonical_authority is empty")
    if canonical_authority != canonical_authority.lower():
        raise RttpUriError("canonical_authority must be lowercase (RFC-002 §10.3)")
    return hashlib.sha256(canonical_authority.encode("ascii")).digest()[:ROUTE_SHARD_BYTES]


def route_shard_hex(canonical_authority: str) -> str:
    return derive_route_shard(canonical_authority).hex()


def parse_and_derive(uri: str) -> dict:
    """便捷入口：解析 + 派生，一步到位。"""
    return parse(uri)


if __name__ == "__main__":  # 手工冒烟
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
