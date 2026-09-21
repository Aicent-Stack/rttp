//! `PulseHeader128` -- RFC-002 sec. 4.1 official 128-byte hardware-aligned frame
//! header, plus the v1.2.6 extension block (`0x66`-`0x7F`).
//!
//! Field layout (big-endian, per sec. 4.1):
//! ```text
//!   0x00  u32   RTTP_MAGIC    0x52545450
//!   0x04  u128  VERSION_ID    locked at 130
//!   0x14  u128  SEQUENCE_ID   monotonic pulse sequence
//!   0x24  u128  TIMESTAMP     absolute nanosecond emission time
//!   0x34  u8    TTL_PULSE
//!   0x35  u8    PRIORITY
//!   0x36  u128  ROUTE_SHARD   SHA-256(authority)[0:16] -- see SPEC sec. 5
//!   0x46  32B   AID_ORIGIN    256-bit originator identity
//!   --- v1.2.6 extension (reserved area allocation, SPEC sec. 2) ---
//!   0x66  u8    SPEC_REV      0 = pre-v1.2.6 (whole block zero); 1 = v1.2.6
//!   0x67  u8    FLAGS         bit0 = URI_ANCHORED; others MUST be 0
//!   0x68  u8    ACTION_LEN    valid bytes of ACTION (0 = omitted)
//!   0x69  16B   ACTION        sec. 10.2 verb (lowercase ASCII, zero-padded)
//!   0x79  7B    RESERVED      MUST be zero
//! ```
//! Bytes `0x00`-`0x65` are UNTOUCHED and VERSION_ID stays 130, so readers of
//! the old layout keep working -- the extension only fills bytes that were
//! already zero.
//!
//! This is a real codec -- `build`/`verify` round-trip against the published
//! frame vectors -- in contrast to a raw memory reinterpretation.

use crate::rttp_uri::{self, RttpUriError};
use std::fmt;

pub const SIZE: usize = 128;
pub const MAGIC: u32 = 0x5254_5450; // "RTTP"
pub const VERSION_ID: u128 = 130;

pub const OFF_SPEC_REV: usize = 0x66;
pub const OFF_FLAGS: usize = 0x67;
pub const OFF_ACTION_LEN: usize = 0x68;
pub const OFF_ACTION: usize = 0x69;
pub const OFF_RESERVED: usize = 0x79;
pub const ACTION_MAX_LEN: usize = 16;
pub const RESERVED_LEN: usize = 7;

pub const FLAG_URI_ANCHORED: u8 = 0x01;
pub const SPEC_REV: u8 = 1;

/// Readers accept exactly these revisions; unknown ones fail closed.
pub const KNOWN_SPEC_REVS: [u8; 2] = [0, 1];

/// The only error type raised by the frame layer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PulseHeaderError(pub String);

impl fmt::Display for PulseHeaderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for PulseHeaderError {}

impl From<RttpUriError> for PulseHeaderError {
    fn from(e: RttpUriError) -> Self {
        PulseHeaderError(e.0)
    }
}

/// Decoded frame fields (structural read -- `verify` adds the semantics).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedFrame {
    pub version_id: u128,
    pub sequence_id: u128,
    pub timestamp_ns: u128,
    pub ttl: u8,
    pub priority: u8,
    pub route_shard: [u8; 16],
    pub aid_origin: [u8; 32],
    pub spec_rev: u8,
    pub flags: u8,
    pub uri_anchored: bool,
    pub action: String,
    pub action_len: u8,
    pub action_omitted: bool,
}

/// ACTION verb -> 16 bytes (lowercase ASCII, right-padded with 0x00).
pub fn encode_action(action: &str) -> Result<[u8; ACTION_MAX_LEN], PulseHeaderError> {
    let mut block = [0u8; ACTION_MAX_LEN];
    if action.is_empty() {
        return Ok(block);
    }
    if !rttp_uri::is_valid_action(action) {
        return Err(PulseHeaderError(format!(
            "invalid action token {:?} (RFC-002 sec. 10.2: 1*( a-z / 0-9 / '-' ))",
            action
        )));
    }
    let raw = action.as_bytes();
    if raw.len() > ACTION_MAX_LEN {
        return Err(PulseHeaderError(format!(
            "action too long: {} > {} bytes",
            raw.len(),
            ACTION_MAX_LEN
        )));
    }
    block[..raw.len()].copy_from_slice(raw);
    Ok(block)
}

/// 16-byte ACTION block -> verb string (byte-level decode, no syntax check).
pub fn decode_action(block16: &[u8]) -> Result<String, PulseHeaderError> {
    if block16.len() != ACTION_MAX_LEN {
        return Err(PulseHeaderError("action block must be 16 bytes".into()));
    }
    let end = block16.iter().position(|&b| b == 0).unwrap_or(ACTION_MAX_LEN);
    let raw = &block16[..end];
    match std::str::from_utf8(raw) {
        Ok(s) if s.is_ascii() => Ok(s.to_string()),
        _ => Err(PulseHeaderError("ACTION is not ASCII".into())),
    }
}

/// Build a 128-byte header per the official layout.
///
/// `action` / `uri_anchored` are the OPTIONAL v1.2.6 additions: omitting the
/// action produces a frame byte-identical to what an old implementation would
/// emit apart from SPEC_REV=1 (spec sec. 4 R6); empty action = sec. 10.4 default.
pub fn build(
    sequence_id: u128,
    ttl: u8,
    priority: u8,
    route_shard: &[u8; 16],
    aid_origin: &[u8; 32],
    timestamp_ns: u128,
    action: &str,
    uri_anchored: bool,
) -> Result<[u8; SIZE], PulseHeaderError> {
    let action_block = encode_action(action)?;

    let mut buf = [0u8; SIZE];
    buf[0x00..0x04].copy_from_slice(&MAGIC.to_be_bytes());
    buf[0x04..0x14].copy_from_slice(&VERSION_ID.to_be_bytes());
    buf[0x14..0x24].copy_from_slice(&sequence_id.to_be_bytes());
    buf[0x24..0x34].copy_from_slice(&timestamp_ns.to_be_bytes());
    buf[0x34] = ttl;
    buf[0x35] = priority;
    buf[0x36..0x46].copy_from_slice(route_shard);
    buf[0x46..0x66].copy_from_slice(aid_origin);

    // --- v1.2.6 extension block ---
    buf[OFF_SPEC_REV] = SPEC_REV;
    buf[OFF_FLAGS] = if uri_anchored { FLAG_URI_ANCHORED } else { 0x00 };
    buf[OFF_ACTION_LEN] = action.len() as u8;
    buf[OFF_ACTION..OFF_ACTION + ACTION_MAX_LEN].copy_from_slice(&action_block);
    // 0x79..0x80 stay zero (RESERVED)

    Ok(buf)
}

/// Build directly from an `rttp` URI -- the mapping sec. 10.4 promises:
/// ROUTE_SHARD derives from the authority, ACTION comes from the path.
pub fn build_for_uri(
    sequence_id: u128,
    ttl: u8,
    priority: u8,
    uri: &str,
    aid_origin: &[u8; 32],
    timestamp_ns: u128,
) -> Result<[u8; SIZE], PulseHeaderError> {
    let parsed = rttp_uri::parse(uri)?;
    build(
        sequence_id,
        ttl,
        priority,
        &parsed.route_shard,
        aid_origin,
        timestamp_ns,
        &parsed.action,
        true,
    )
}

/// Structural decode (no semantics).
pub fn parse(raw: &[u8]) -> Result<ParsedFrame, PulseHeaderError> {
    if raw.len() != SIZE {
        return Err(PulseHeaderError(format!("header must be exactly {} bytes", SIZE)));
    }
    let magic = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]);
    if magic != MAGIC {
        return Err(PulseHeaderError(format!("bad RTTP_MAGIC: 0x{:08X}", magic)));
    }
    let be_u128 = |r: &[u8]| -> u128 {
        let mut w = [0u8; 16];
        w.copy_from_slice(r);
        u128::from_be_bytes(w)
    };
    let spec_rev = raw[OFF_SPEC_REV];
    let action = if spec_rev == 0 {
        String::new()
    } else {
        decode_action(&raw[OFF_ACTION..OFF_ACTION + ACTION_MAX_LEN])?
    };
    let mut route_shard = [0u8; 16];
    route_shard.copy_from_slice(&raw[0x36..0x46]);
    let mut aid_origin = [0u8; 32];
    aid_origin.copy_from_slice(&raw[0x46..0x66]);
    let flags = raw[OFF_FLAGS];
    let action_len = raw[OFF_ACTION_LEN];

    Ok(ParsedFrame {
        version_id: be_u128(&raw[0x04..0x14]),
        sequence_id: be_u128(&raw[0x14..0x24]),
        timestamp_ns: be_u128(&raw[0x24..0x34]),
        ttl: raw[0x34],
        priority: raw[0x35],
        route_shard,
        aid_origin,
        spec_rev,
        flags,
        uri_anchored: flags & FLAG_URI_ANCHORED != 0,
        action_len,
        action_omitted: action_len == 0,
        action,
    })
}

/// Parse + validate version, origin AID and the extension block (rules R1-R7
/// of SPEC sec. 4). `expected_aid_origin` optionally pins the origin.
pub fn verify(
    raw: &[u8],
    expected_aid_origin: Option<&[u8; 32]>,
) -> Result<ParsedFrame, PulseHeaderError> {
    let fields = parse(raw)?;
    if fields.version_id != VERSION_ID {
        return Err(PulseHeaderError(format!(
            "VERSION_ID mismatch: {} != {}",
            fields.version_id, VERSION_ID
        )));
    }

    let spec_rev = fields.spec_rev;
    if !KNOWN_SPEC_REVS.contains(&spec_rev) {
        return Err(PulseHeaderError(format!(
            "unknown SPEC_REV: {} (fail closed)",
            spec_rev
        )));
    }

    if spec_rev == 0 {
        // SPEC_REV=0 demands the whole extension block be zero (formal
        // self-consistency -- R2).
        if raw[OFF_SPEC_REV..SIZE].iter().any(|&b| b != 0) {
            return Err(PulseHeaderError(
                "SPEC_REV=0 but extension block is not all-zero".into(),
            ));
        }
    } else {
        if raw[OFF_RESERVED..SIZE].iter().any(|&b| b != 0) {
            return Err(PulseHeaderError(
                "RESERVED bytes must be zero in SPEC_REV=1".into(),
            ));
        }
        let unknown = fields.flags & !FLAG_URI_ANCHORED;
        if unknown != 0 {
            return Err(PulseHeaderError(format!(
                "unknown FLAGS bits set: 0x{:02X}",
                unknown
            )));
        }

        let action_block = &raw[OFF_ACTION..OFF_ACTION + ACTION_MAX_LEN];
        let alen = fields.action_len as usize;
        if alen > ACTION_MAX_LEN {
            return Err(PulseHeaderError(format!(
                "ACTION_LEN {} > {}",
                alen, ACTION_MAX_LEN
            )));
        }
        if alen != fields.action.len() {
            return Err(PulseHeaderError(
                "ACTION_LEN disagrees with ACTION payload".into(),
            ));
        }
        // No gap between the verb and the padding (R5).
        if action_block[fields.action.len()..].iter().any(|&b| b != 0) {
            return Err(PulseHeaderError("ACTION padding must be zero".into()));
        }
        if !fields.action.is_empty() && !rttp_uri::is_valid_action(&fields.action) {
            return Err(PulseHeaderError(format!(
                "ACTION violates RFC-002 sec. 10.2: {:?}",
                fields.action
            )));
        }
    }

    if let Some(expected) = expected_aid_origin {
        if &fields.aid_origin != expected {
            return Err(PulseHeaderError("AID_ORIGIN mismatch (spoofed origin?)".into()));
        }
    }
    Ok(fields)
}

#[cfg(test)]
mod tests {
    use super::*;

    const AID: [u8; 32] = [0x42; 32];

    #[test]
    fn build_verify_roundtrip() {
        let raw = build(7, 255, 1, &[0xAA; 16], &AID, 1760000000, "verify", true).unwrap();
        let f = verify(&raw, Some(&AID)).unwrap();
        assert_eq!(f.version_id, 130);
        assert_eq!(f.spec_rev, 1);
        assert!(f.uri_anchored);
        assert_eq!(f.action, "verify");
        assert_eq!(f.route_shard, [0xAA; 16]);
    }

    #[test]
    fn spec_rev_zero_requires_all_zero_extension() {
        let mut raw = build(1, 64, 128, &[0u8; 16], &AID, 5, "", false).unwrap();
        raw[OFF_SPEC_REV] = 0;
        assert!(verify(&raw, None).is_ok());
        raw[OFF_ACTION] = 0x01; // contradicts SPEC_REV=0
        assert!(verify(&raw, None).is_err());
    }

    #[test]
    fn wrong_version_and_unknown_rev_fail() {
        let mut raw = build(1, 1, 1, &[0u8; 16], &AID, 1, "", false).unwrap();
        raw[0x04] = 0xFF;
        assert!(verify(&raw, None).is_err());
        let mut raw2 = build(1, 1, 1, &[0u8; 16], &AID, 1, "", false).unwrap();
        raw2[OFF_SPEC_REV] = 9;
        assert!(verify(&raw2, None).is_err());
    }

    #[test]
    fn action_rules() {
        assert!(encode_action("a-b-c9").is_ok());
        assert!(encode_action("-lead").is_err());
        assert!(encode_action("toolongverb_0123456789abcdef").is_err());
        let mut raw = build(1, 1, 1, &[0u8; 16], &AID, 1, "pulse", true).unwrap();
        raw[OFF_ACTION] = b'P'; // uppercase sneaks into ACTION
        assert!(verify(&raw, None).is_err());
    }
}
