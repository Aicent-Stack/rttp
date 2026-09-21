//! `rttp://` URI codec -- validate, canonicalise, derive (RFC-002 sec. 10).
//!
//! Authority boundaries:
//!   Grammar ......... RFC-002 sec. 10.2 ABNF (sole authority; no syntax added here)
//!   Case discipline . sec. 10.3 (lowercase US-ASCII only) + sec. 10.5 (fail closed)
//!   Route derivation  ROUTE_SHARD = SHA-256(ASCII(canonical_authority))[0:16]
//!
//! Design rules inherited from the reference implementations (Python/JS):
//!   * Malformed input is REJECTED, never normalised.
//!   * A check that cannot be performed is a failure, never a pass.
//!   * The `web+rttp://` prefix is a TOLERANCE (the name a browser handler is
//!     registered under) -- accepted, never emitted; `canonical_uri` always
//!     begins `rttp://`.

use crate::sha256::{bytes_to_hex, sha256};
use std::fmt;

pub const SCHEME: &str = "rttp";
pub const WEB_SCHEME: &str = "web+rttp";
pub const ROUTE_SHARD_BYTES: usize = 16;
pub const HASH_INTENT_LEN: usize = 8;

const TOKEN_CHARS: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789-";
const HEX_CHARS: &[u8] = b"0123456789abcdef";
const FORBIDDEN: &[u8] = b"@?#[]";

/// The only error type raised by this module. Fail closed (sec. 10.5): no
/// fallback, no `rttps`, no normalisation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RttpUriError(pub String);

impl fmt::Display for RttpUriError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for RttpUriError {}

/// A parsed, canonicalised `rttp` URI.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedUri {

    /// Which form arrived: `rttp` (canonical) or `web+rttp` (tolerance).
    pub scheme: &'static str,
    pub intent: String,
    pub intent_is_hash: bool,
    /// The 32-bit routing hash, only when `intent_is_hash`.
    pub intent_hash32: Option<u32>,
    pub pillar: String,
    pub root: String,
    /// The intent verb; empty string = omitted (sec. 10.4 default operation).
    pub action: String,
    pub action_omitted: bool,
    /// `<intent>.<pillar>.<root>`, canonical.
    pub authority: String,
    /// Always begins `rttp://` -- even for the `web+rttp` tolerance form.
    pub canonical_uri: String,
    /// ROUTE_SHARD = SHA-256(ASCII(authority))[0:16].
    pub route_shard: [u8; ROUTE_SHARD_BYTES],
}

impl ParsedUri {
    /// The ROUTE_SHARD as lowercase hex (32 characters).
    pub fn route_shard_hex(&self) -> String {
        bytes_to_hex(&self.route_shard)
    }
}

fn is_token_char(b: u8) -> bool {
    TOKEN_CHARS.contains(&b)
}

fn is_hex_char(b: u8) -> bool {
    HEX_CHARS.contains(&b)
}

/// sec. 10.2 token form: 1*( a-z / 0-9 / "-" ), no leading/trailing '-'.
fn check_token(value: &str, what: &str) -> Result<(), RttpUriError> {
    if value.is_empty() {
        return Err(RttpUriError(format!("{} is empty", what)));
    }
    for ch in value.chars() {
        if ch.is_ascii_uppercase() {
            return Err(RttpUriError(format!(
                "{} contains uppercase '{}' - lowercase US-ASCII only (RFC-002 sec. 10.3)",
                what, ch
            )));
        }
        if !is_token_char(ch as u8) {
            return Err(RttpUriError(format!(
                "{} contains illegal character {:?} (allowed: a-z, 0-9, '-')",
                what, ch
            )));
        }
    }
    if value.starts_with('-') || value.ends_with('-') {
        return Err(RttpUriError(format!(
            "{} must not begin or end with '-'",
            what
        )));
    }
    Ok(())
}

/// Returns Ok(true) when the intent is a hash-intent (8 lowercase hex digits),
/// Ok(false) when it is a name-intent.
fn check_intent(value: &str) -> Result<bool, RttpUriError> {
    if value.len() == HASH_INTENT_LEN && value.bytes().all(is_hex_char) {
        return Ok(true);
    }
    check_token(value, "intent")?;
    Ok(false)
}

/// sec. 10.2 action syntax test -- an OPEN set: only the form is judged, never the
/// verb's semantics. Shared with the frame layer.
pub fn is_valid_action(value: &str) -> bool {
    if value.is_empty() {
        return false;
    }
    if value.starts_with('-') || value.ends_with('-') {
        return false;
    }
    value.bytes().all(is_token_char)
}

/// ROUTE_SHARD = SHA-256( ASCII(canonical_authority) )[0:16].
///
/// Deterministic, pure computation, DNS-free (sec. 10.5), independent of `action`
/// (routing decides WHERE, never WHAT -- that is why `action` is a separate
/// frame field).
pub fn derive_route_shard(canonical_authority: &str) -> Result<[u8; ROUTE_SHARD_BYTES], RttpUriError> {
    if canonical_authority.is_empty() {
        return Err(RttpUriError("canonical_authority is empty".into()));
    }
    if canonical_authority != canonical_authority.to_lowercase() {
        return Err(RttpUriError(
            "canonical_authority must be lowercase (RFC-002 sec. 10.3)".into(),
        ));
    }
    let digest = sha256(canonical_authority.as_bytes());
    let mut shard = [0u8; ROUTE_SHARD_BYTES];
    shard.copy_from_slice(&digest[..ROUTE_SHARD_BYTES]);
    Ok(shard)
}

/// Lowercase hex of the ROUTE_SHARD for an authority.
pub fn route_shard_hex(canonical_authority: &str) -> Result<String, RttpUriError> {
    Ok(crate::sha256::bytes_to_hex(
        &derive_route_shard(canonical_authority)?,
    ))
}

/// Validate, canonicalise and derive. Raises on any violation -- never guesses
/// intent, never normalises (sec. 10.5 fail closed).
pub fn parse(uri: &str) -> Result<ParsedUri, RttpUriError> {
    if uri.is_empty() {
        return Err(RttpUriError("uri is empty".into()));
    }
    if uri.trim() != uri {
        // Leading/trailing whitespace: paste contamination or a prefix-check
        // bypass attempt -- rejected either way.
        return Err(RttpUriError(
            "uri must not contain leading/trailing whitespace".into(),
        ));
    }

    // --- scheme (sec. 10.6 prefix whitelist) ---
    let (scheme, rest) = if let Some(r) = uri.strip_prefix(&(WEB_SCHEME.to_string() + "://")) {
        (WEB_SCHEME, r)
    } else if let Some(r) = uri.strip_prefix(&(SCHEME.to_string() + "://")) {
        (SCHEME, r)
    } else {
        return Err(RttpUriError(format!(
            "not an rttp URI: must begin with '{SCHEME}://' or '{WEB_SCHEME}://'"
        )));
    };

    // --- sec. 10.3 excluded components ---
    for ch in FORBIDDEN {
        if uri.as_bytes().contains(ch) {
            return Err(RttpUriError(format!(
                "illegal character {:?}: this scheme defines no userinfo / query / fragment",
                *ch as char
            )));
        }
    }

    // --- authority / path ---
    let (authority, action) = match rest.find('/') {
        Some(i) => {
            let a = &rest[..i];
            let action = &rest[i + 1..];
            if action.contains('/') {
                return Err(RttpUriError("path must be a single segment '/<action>'".into()));
            }
            if action.is_empty() {
                return Err(RttpUriError(
                    "trailing '/' with empty action: path must be '/<action>'".into(),
                ));
            }
            (a, action)
        }
        None => (rest, ""),
    };

    let segments: Vec<&str> = authority.split('.').collect();
    if segments.len() != 3 {
        return Err(RttpUriError(format!(
            "authority must be exactly '<intent>.<pillar>.<root>' (got {} segment(s))",
            segments.len()
        )));
    }
    let intent = segments[0];
    let pillar = segments[1];
    let root = segments[2];

    let intent_is_hash = check_intent(intent)?;
    check_token(pillar, "pillar")?;
    check_token(root, "root")?;
    if !action.is_empty() {
        check_token(action, "action")?;
    }

    let canonical_authority = format!("{}.{}.{}", intent, pillar, root);
    let mut canonical_uri = format!("{SCHEME}://{canonical_authority}");
    if !action.is_empty() {
        canonical_uri.push('/');
        canonical_uri.push_str(action);
    }

    let route_shard = derive_route_shard(&canonical_authority)?;
    let intent_hash32 = if intent_is_hash {
        Some(u32::from_str_radix(intent, 16).map_err(|e| RttpUriError(e.to_string()))?)
    } else {
        None
    };

    Ok(ParsedUri {
        scheme,
        intent: intent.to_string(),
        intent_is_hash,
        intent_hash32,
        pillar: pillar.to_string(),
        root: root.to_string(),
        action: action.to_string(),
        action_omitted: action.is_empty(),
        authority: canonical_authority,
        canonical_uri,
        route_shard,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_the_pinned_example() {
        let p = parse("rttp://brain.epoekie.aicent/verify").unwrap();
        assert_eq!(p.authority, "brain.epoekie.aicent");
        assert_eq!(p.action, "verify");
        assert!(!p.intent_is_hash);
        assert_eq!(p.route_shard_hex(), "459e543b73d86005b72ba77d5756e83c");
        assert_eq!(p.canonical_uri, "rttp://brain.epoekie.aicent/verify");
    }

    #[test]
    fn tolerance_form_canonicalises_to_rttp() {
        let p = parse("web+rttp://logic.zcmk.aicent/pulse").unwrap();
        assert_eq!(p.scheme, WEB_SCHEME);
        assert_eq!(p.canonical_uri, "rttp://logic.zcmk.aicent/pulse");
    }

    #[test]
    fn rejects_fail_closed() {
        assert!(parse("rttp://f3b2a1c4.rttp.aicent/VESSEL").is_err());
        assert!(parse("RTTP://f3b2a1c4.rttp.aicent/vessel").is_err());
        assert!(parse("rttp://subject@rttp.aicent/vessel").is_err());
        assert!(parse("rttp://a.b").is_err());
        assert!(parse("rttp://f3b2a1c4.rttp.aicent/").is_err());
        assert!(parse("rttp://-lead.rttp.aicent/vessel").is_err());
        assert!(parse("https://f3b2a1c4.rttp.aicent/vessel").is_err());
        assert!(parse("rttp://f3b2a1c4.rttp.aicent/vessel ").is_err());
    }
}
