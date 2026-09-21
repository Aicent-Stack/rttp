"""
PulseHeader128 -- the 128-byte hardware-aligned frame header of RFC-002 sec. 4.1.

Field layout (big endian, one to one with the table in RFC-002 sec. 4.1):
    0x00  u32   RTTP_MAGIC    0x52545450
    0x04  u128  VERSION_ID    pinned at 130
    0x14  u128  SEQUENCE_ID   monotonic pulse number
    0x24  u128  TIMESTAMP     absolute emission time in nanoseconds
    0x34  u8    TTL_PULSE     hop limit (the pulse evaporates past 255)
    0x35  u8    PRIORITY      routing weight (255 = Sovereign)
    0x36  u128  ROUTE_SHARD   navigation hash
    0x46  32B   AID_ORIGIN    256-bit identity DNA (Genesis^Resonance)

--- since v1.2.6: reserved-area allocation (SPEC/RTTP-FRAME-EXT-v1.2.6.md) ---
    0x66  u8    SPEC_REV      0 = before v1.2.6 (whole block zero); 1 = v1.2.6
    0x67  u8    FLAGS         bit0 = URI_ANCHORED; other bits MUST be 0 in v1.2.6
    0x68  u8    ACTION_LEN    number of significant ACTION bytes (0 = omitted)
    0x69  16B   ACTION        sec. 10.2 intent verb (lowercase ASCII, 0x00 padded)
    0x79  7B    RESERVED      MUST be zero in v1.2.6

Bytes 0x00-0x65 are unchanged and VERSION_ID stays at 130, so a reader that only
looks at 0x00-0x65 stays compatible.
"""

import struct
import time

try:
    from . import rttp_uri
except ImportError:
    import rttp_uri

SIZE = 128
MAGIC = 0x52545450          # "RTTP"
VERSION_ID = 130            # v1.3.0-Alpha
AID_ORIGIN_OFFSET = 0x46

SPEC_REV = 1

OFF_SPEC_REV = 0x66
OFF_FLAGS = 0x67
OFF_ACTION_LEN = 0x68
OFF_ACTION = 0x69
ACTION_MAX_LEN = 16
OFF_RESERVED = 0x79
RESERVED_LEN = 7

FLAG_URI_ANCHORED = 0x01

KNOWN_SPEC_REVS = (0, 1)


class PulseHeaderError(Exception):
    pass


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def encode_action(action: str) -> bytes:
    """Encode an action verb into 16 bytes (lowercase ASCII, 0x00 padded)."""
    if action == "":
        return bytes(ACTION_MAX_LEN)
    if not rttp_uri.is_valid_action(action):
        raise PulseHeaderError(
            f"invalid action token {action!r} (RFC-002 sec. 10.2: 1*( a-z / 0-9 / '-' ))")
    raw = action.encode("ascii")
    if len(raw) > ACTION_MAX_LEN:
        raise PulseHeaderError(
            f"action too long: {len(raw)} > {ACTION_MAX_LEN} bytes")
    return raw + bytes(ACTION_MAX_LEN - len(raw))


def decode_action(block16: bytes) -> str:
    """Decode the 16-byte ACTION block into a verb (bytes only, no grammar check)."""
    if len(block16) != ACTION_MAX_LEN:
        raise PulseHeaderError("action block must be 16 bytes")
    end = block16.find(b"\x00")
    raw = block16 if end < 0 else block16[:end]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise PulseHeaderError(f"ACTION is not ASCII: {exc}") from exc


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def build(sequence_id: int, ttl: int, priority: int,
          route_shard: bytes, aid_origin: bytes,
          timestamp_ns: int = None,
          action: str = "", uri_anchored: bool = False) -> bytes:
    """Build the 128-byte header from the official layout.
    
        `action` / `uri_anchored` are optional since v1.2.6:
          * omitted -> byte-identical to the previous implementation (SPEC_REV is
            still written as 1, see spec sec. 4 R6)
          * action="" -> the default operation of sec. 10.4 (standing read)
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

    buf[OFF_SPEC_REV] = SPEC_REV
    buf[OFF_FLAGS] = FLAG_URI_ANCHORED if uri_anchored else 0x00
    buf[OFF_ACTION_LEN] = len(action.encode("ascii")) if action else 0
    buf[OFF_ACTION:OFF_ACTION + ACTION_MAX_LEN] = action_block

    return bytes(buf)


def build_for_uri(sequence_id: int, ttl: int, priority: int,
                  uri: str, aid_origin: bytes,
                  timestamp_ns: int = None) -> bytes:
    """Build the header straight from an `rttp` URI -- the mapping sec. 10.4 promises.
    
        ROUTE_SHARD comes from the authority, not from the pulse number; ACTION comes
        from the path.
        """
    parsed = rttp_uri.parse(uri)
    return build(sequence_id, ttl, priority,
                 route_shard=parsed["route_shard"],
                 aid_origin=aid_origin,
                 timestamp_ns=timestamp_ns,
                 action=parsed["action"],
                 uri_anchored=True)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def parse(raw: bytes) -> dict:
    """Parse and validate a 128-byte header. Structure only, not legality."""
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
    """Parse and validate version, origin AID and extension block.
    
        Extension block rules (spec sec. 4 R1-R7):
          * SPEC_REV not in KNOWN_SPEC_REVS -> reject
          * SPEC_REV=0 but the extension block is not all zero -> reject (contradiction)
          * SPEC_REV=1 but RESERVED is non-zero or FLAGS has unknown bits -> reject
          * ACTION_LEN > 16 / embedded NUL / not sec. 10.2 grammar -> reject
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
        if any(action_block[len(action.encode("ascii")):]):
            raise PulseHeaderError("ACTION padding must be zero")
        if action and not rttp_uri.is_valid_action(action):
            raise PulseHeaderError(f"ACTION violates RFC-002 sec. 10.2: {action!r}")

    if expected_aid_origin is not None and \
            fields["aid_origin"] != expected_aid_origin:
        raise PulseHeaderError("AID_ORIGIN mismatch (spoofed origin?)")
    return fields


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def to_hex(header_bytes: bytes) -> str:
    return header_bytes.hex()


def from_hex(hex_str: str) -> bytes:
    raw = bytes.fromhex(hex_str)
    if len(raw) != SIZE:
        raise PulseHeaderError("hex must decode to exactly 128 bytes")
    return raw
