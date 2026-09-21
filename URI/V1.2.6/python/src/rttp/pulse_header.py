"""
PulseHeader128 — RFC-002 §4.1 官方 128 字节硬件对齐帧头

（v1.3.0: 每个神经脉冲封装在临床级 PulseHeader128 中，
  128-BYTE 硬件对齐结构，与 CPU 双缓存行共振。）

字段布局（大端，与 RFC-002 §4.1 表逐一对应）:
    0x00  u32   RTTP_MAGIC    0x52545450（物理寄存器门验证）
    0x04  u128  VERSION_ID    锁定 130（v1.3.0-Alpha）
    0x14  u128  SEQUENCE_ID   单调脉冲序号（12ns 审计用）
    0x24  u128  TIMESTAMP     绝对纳秒发射时刻（12ns 精度）
    0x34  u8    TTL_PULSE     跳数上限（255 后脉冲蒸发）
    0x35  u8    PRIORITY      128-bit 分流权重（255 = Sovereign）
    0x36  u128  ROUTE_SHARD   12ns 抖动对齐的 Hive 导航哈希
    0x46  32B   AID_ORIGIN    256-bit 双分片身份 DNA（Genesis^Resonance）

--- v1.2.6 起：保留区分配（详见 SPEC/RTTP-FRAME-EXT-v1.2.6.md）---
    0x66  u8    SPEC_REV      0 = v1.2.6 之前（整块全零）; 1 = v1.2.6
    0x67  u8    FLAGS         bit0 = URI_ANCHORED; 其余位在 v1.2.6 MUST 为 0
    0x68  u8    ACTION_LEN    ACTION 有效字节数（0 = action 省略）
    0x69  16B   ACTION        §10.2 action 动词（小写 ASCII，右补 0x00）
    0x79  7B    RESERVED      v1.2.6 MUST 全零

⚠ **0x00–0x65 一个字节都没有改动**，VERSION_ID 亦保持 130。
   扩展只填「原本就是零」的保留区，因此只读 0x00–0x65 的旧实现天然兼容。
"""

import struct
import time

try:                        # pip 安装后：作为包内模块导入
    from . import rttp_uri
except ImportError:         # 平铺布局（DEMO/ 目录）：作为同目录脚本导入
    import rttp_uri         # action 语法（§10.2）唯一权威所在，避免规则重写

# ---- 固定区 ----
SIZE = 128
MAGIC = 0x52545450          # "RTTP"
VERSION_ID = 130            # v1.3.0-Alpha
AID_ORIGIN_OFFSET = 0x46

# ---- 扩展块（v1.2.6）----
SPEC_REV = 1

OFF_SPEC_REV = 0x66
OFF_FLAGS = 0x67
OFF_ACTION_LEN = 0x68
OFF_ACTION = 0x69
ACTION_MAX_LEN = 16
OFF_RESERVED = 0x79
RESERVED_LEN = 7

FLAG_URI_ANCHORED = 0x01

# 读端只认这些 SPEC_REV；未知修订一律拒斥（fail closed）
KNOWN_SPEC_REVS = (0, 1)


class PulseHeaderError(Exception):
    pass


# ---------------------------------------------------------------------------
# ACTION 编解码
# ---------------------------------------------------------------------------

def encode_action(action: str) -> bytes:
    """action 动词 → 16 字节（小写 ASCII，右补 0x00）。"""
    if action == "":
        return bytes(ACTION_MAX_LEN)
    if not rttp_uri.is_valid_action(action):
        raise PulseHeaderError(
            f"invalid action token {action!r} (RFC-002 §10.2: 1*( a-z / 0-9 / '-' ))")
    raw = action.encode("ascii")
    if len(raw) > ACTION_MAX_LEN:
        raise PulseHeaderError(
            f"action too long: {len(raw)} > {ACTION_MAX_LEN} bytes")
    return raw + bytes(ACTION_MAX_LEN - len(raw))


def decode_action(block16: bytes) -> str:
    """16 字节 ACTION 区 → 动词字符串（字节级解码，不含语法校验）。"""
    if len(block16) != ACTION_MAX_LEN:
        raise PulseHeaderError("action block must be 16 bytes")
    end = block16.find(b"\x00")
    raw = block16 if end < 0 else block16[:end]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise PulseHeaderError(f"ACTION is not ASCII: {exc}") from exc


# ---------------------------------------------------------------------------
# 构造
# ---------------------------------------------------------------------------

def build(sequence_id: int, ttl: int, priority: int,
          route_shard: bytes, aid_origin: bytes,
          timestamp_ns: int = None,
          action: str = "", uri_anchored: bool = False) -> bytes:
    """按官方解剖表构造 128 字节帧头。

    action / uri_anchored 为 v1.2.6 新增的**可选**参数：
      * 不传时产出与旧实现逐字节相同的帧（SPEC_REV 仍写 1，见 spec §4 R6）
      * action="" 表示 §10.4 的默认操作（standing read / 无动作谓词）
    """
    if len(route_shard) != 16:
        raise PulseHeaderError("route_shard must be 16 bytes (u128)")
    if len(aid_origin) != 32:
        raise PulseHeaderError("aid_origin must be 32 bytes (256-bit)")
    if not 0 <= sequence_id < (1 << 128):
        raise PulseHeaderError("sequence_id out of u128 range")
    if timestamp_ns is None:
        timestamp_ns = time.time_ns()

    action_block = encode_action(action)

    buf = bytearray(SIZE)
    struct.pack_into(">I", buf, 0x00, MAGIC)
    buf[0x04:0x14] = VERSION_ID.to_bytes(16, "big")
    buf[0x14:0x24] = sequence_id.to_bytes(16, "big")
    buf[0x24:0x34] = timestamp_ns.to_bytes(16, "big")
    buf[0x34] = ttl & 0xFF
    buf[0x35] = priority & 0xFF
    buf[0x36:0x46] = route_shard
    buf[0x46:0x66] = aid_origin

    # --- v1.2.6 扩展块 ---
    buf[OFF_SPEC_REV] = SPEC_REV
    buf[OFF_FLAGS] = FLAG_URI_ANCHORED if uri_anchored else 0x00
    buf[OFF_ACTION_LEN] = len(action.encode("ascii")) if action else 0
    buf[OFF_ACTION:OFF_ACTION + ACTION_MAX_LEN] = action_block
    # 0x79..0x80 保持零（RESERVED）

    return bytes(buf)


def build_for_uri(sequence_id: int, ttl: int, priority: int,
                  uri: str, aid_origin: bytes,
                  timestamp_ns: int = None) -> bytes:
    """从一条 `rttp` URI 直接构造帧头 —— 即 §10.4 所承诺的那次映射。

    ROUTE_SHARD 由 authority 派生（而非脉冲序号），ACTION 取自 path。
    """
    parsed = rttp_uri.parse(uri)
    return build(sequence_id, ttl, priority,
                 route_shard=parsed["route_shard"],
                 aid_origin=aid_origin,
                 timestamp_ns=timestamp_ns,
                 action=parsed["action"],
                 uri_anchored=True)


# ---------------------------------------------------------------------------
# 解析 / 校验
# ---------------------------------------------------------------------------

def parse(raw: bytes) -> dict:
    """解析并校验 128 字节帧头，返回字段字典（不判合法性，只做结构解码）。"""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != SIZE:
        raise PulseHeaderError(f"header must be exactly {SIZE} bytes")
    raw = bytes(raw)
    magic = struct.unpack_from(">I", raw, 0x00)[0]
    if magic != MAGIC:
        raise PulseHeaderError(f"bad RTTP_MAGIC: 0x{magic:08X}")

    spec_rev = raw[OFF_SPEC_REV]
    flags = raw[OFF_FLAGS]
    action_len = raw[OFF_ACTION_LEN]
    action = "" if spec_rev == 0 else decode_action(
        raw[OFF_ACTION:OFF_ACTION + ACTION_MAX_LEN])

    return {
        "magic_ok": True,
        "version_id": int.from_bytes(raw[0x04:0x14], "big"),
        "sequence_id": int.from_bytes(raw[0x14:0x24], "big"),
        "timestamp_ns": int.from_bytes(raw[0x24:0x34], "big"),
        "ttl": raw[0x34],
        "priority": raw[0x35],
        "route_shard": raw[0x36:0x46],
        "aid_origin": raw[0x46:0x66],
        # --- v1.2.6 ---
        "spec_rev": spec_rev,
        "flags": flags,
        "uri_anchored": bool(flags & FLAG_URI_ANCHORED),
        "action": action,
        "action_len": action_len,
        "action_omitted": action_len == 0,
    }


def verify(raw: bytes, expected_aid_origin: bytes = None) -> dict:
    """解析 + 校验版本、来源 AID 与扩展块，返回字段字典。

    扩展块校验规则（spec §4 R1–R7）：
      * SPEC_REV 不在 KNOWN_SPEC_REVS 内            → 拒斥
      * SPEC_REV=0 但扩展块非全零                    → 拒斥（形态自相矛盾）
      * SPEC_REV=1 但 RESERVED 非零 / FLAGS 未知位   → 拒斥
      * ACTION_LEN > 16 / 有内嵌 NUL / 非 §10.2 语法 → 拒斥
    """
    fields = parse(raw)
    if fields["version_id"] != VERSION_ID:
        raise PulseHeaderError(
            f"VERSION_ID mismatch: {fields['version_id']} != {VERSION_ID}")

    spec_rev = fields["spec_rev"]
    block = bytes(raw[OFF_SPEC_REV:SIZE])

    if spec_rev not in KNOWN_SPEC_REVS:
        raise PulseHeaderError(f"unknown SPEC_REV: {spec_rev} (fail closed)")
    if spec_rev == 0:
        if any(block):
            raise PulseHeaderError(
                "SPEC_REV=0 but extension block is not all-zero")
    else:
        if any(raw[OFF_RESERVED:SIZE]):
            raise PulseHeaderError("RESERVED bytes must be zero in SPEC_REV=1")
        unknown_flags = fields["flags"] & ~FLAG_URI_ANCHORED
        if unknown_flags:
            raise PulseHeaderError(
                f"unknown FLAGS bits set: 0x{unknown_flags:02X}")

        action_block = raw[OFF_ACTION:OFF_ACTION + ACTION_MAX_LEN]
        action = fields["action"]
        if fields["action_len"] > ACTION_MAX_LEN:
            raise PulseHeaderError(
                f"ACTION_LEN {fields['action_len']} > {ACTION_MAX_LEN}")
        if fields["action_len"] != len(action.encode("ascii")):
            raise PulseHeaderError("ACTION_LEN disagrees with ACTION payload")
        # 补零区必须全零（不留夹缝）
        if any(action_block[len(action.encode("ascii")):]):
            raise PulseHeaderError("ACTION padding must be zero")
        if action and not rttp_uri.is_valid_action(action):
            raise PulseHeaderError(f"ACTION violates RFC-002 §10.2: {action!r}")

    if expected_aid_origin is not None and \
            fields["aid_origin"] != expected_aid_origin:
        raise PulseHeaderError("AID_ORIGIN mismatch (spoofed origin?)")
    return fields


# ---------------------------------------------------------------------------
# 十六进制编解码
# ---------------------------------------------------------------------------

def to_hex(header_bytes: bytes) -> str:
    return header_bytes.hex()


def from_hex(hex_str: str) -> bytes:
    raw = bytes.fromhex(hex_str)
    if len(raw) != SIZE:
        raise PulseHeaderError("hex must decode to exactly 128 bytes")
    return raw
