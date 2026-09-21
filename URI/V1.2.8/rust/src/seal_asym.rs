//! Sovereign seal envelope -- SPEC/RTTP-SEAL-ENVELOPE-v1.2.6 sec. 3 (Ed25519,
//! self-certifying). **Feature-gated** (`ed25519`): the default build stays
//! zero-dependency and still replays the envelope's signing input and AID
//! self-certification; only the signature arithmetic needs `ed25519-dalek`.
//!
//! Verification order (fail closed, first failure ends it -- sec. 5):
//!   1. v == 1          2. alg == "ed25519"
//!   3. hex fields lowercase, right length
//!   4. ts integer      5. payload is an object
//!   6. |now - ts| <= 120 s (unless archival)
//!   7. aid == SHA-256(pub) -- self-certification
//!   8. Ed25519 over the canonical signing input ("rttp-seal-v1\n" + JSON)

use crate::json::Json;
use crate::sha256::{bytes_to_hex, hex_to_bytes, sha256};
use ed25519_dalek::{Signer, SigningKey, Verifier, VerifyingKey};
use std::time::{SystemTime, UNIX_EPOCH};

pub const DOMAIN: &[u8] = b"rttp-seal-v1\n";
pub const MAX_SKEW: u64 = 120;
pub const NONCE_BYTES: usize = 8;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SealError(pub String);

impl fmt::Display for SealError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for SealError {}
use std::fmt;

/// A keypair plus its self-certifying identity (`aid = sha256(pub)`).
pub struct Keypair {
    pub signing: SigningKey,
    pub pub_hex: String,
    pub aid_hex: String,
}

pub fn aid_from_public_key(public: &[u8; 32]) -> [u8; 32] {
    sha256(public)
}

/// Generate a keypair from the OS entropy source (`getrandom`, enabled with
/// the same `ed25519` feature).
pub fn generate_keypair() -> Result<Keypair, SealError> {
    let mut seed = [0u8; 32];
    getrandom::getrandom(&mut seed).map_err(|e| SealError(e.to_string()))?;
    Ok(keypair_from_seed(seed))
}

/// Deterministic keypair from a 32-byte seed -- for reproducible test vectors
/// only; production callers should use [`generate_keypair`].
pub fn keypair_from_seed(seed: [u8; 32]) -> Keypair {
    let signing = SigningKey::from_bytes(&seed);
    let verify = signing.verifying_key();
    let pub_bytes = verify.to_bytes();
    Keypair {
        signing,
        pub_hex: bytes_to_hex(&pub_bytes),
        aid_hex: bytes_to_hex(&aid_from_public_key(&pub_bytes)),
    }
}

/// Canonical signing input: every envelope field except `sig` is covered.
pub fn signing_input(env: &Json) -> Result<Vec<u8>, SealError> {
    let obj = match env {
        Json::Obj(_) => env,
        _ => return Err(SealError("envelope must be an object".into())),
    };
    let inner = Json::Obj(vec![
        ("alg".into(), obj.get("alg").cloned().unwrap_or(Json::Null)),
        ("aid".into(), obj.get("aid").cloned().unwrap_or(Json::Null)),
        ("nonce".into(), obj.get("nonce").cloned().unwrap_or(Json::Null)),
        ("payload".into(), obj.get("payload").cloned().unwrap_or(Json::Null)),
        ("pub".into(), obj.get("pub").cloned().unwrap_or(Json::Null)),
        ("ts".into(), obj.get("ts").cloned().unwrap_or(Json::Null)),
    ]);
    let mut out = DOMAIN.to_vec();
    out.extend_from_slice(inner.canonical().as_bytes());
    Ok(out)
}

/// Seal a payload into a self-certifying envelope.
///
/// `ts` / `nonce` default to now / OS entropy. Passing them explicitly pins
/// the replay window -- for reproducible vectors only.
pub fn seal(
    payload: &Json,
    keypair: &Keypair,
    ts: Option<u64>,
    nonce_hex: Option<&str>,
) -> Result<Json, SealError> {
    if !matches!(payload, Json::Obj(_)) {
        return Err(SealError("payload must be an object".into()));
    }
    let ts = match ts {
        Some(t) => t,
        None => SystemTime::now().duration_since(UNIX_EPOCH).map_err(|e| SealError(e.to_string()))?.as_secs(),
    };
    let nonce = match nonce_hex {
        Some(n) => {
            if n.len() != NONCE_BYTES * 2 || !n.bytes().all(|b| b.is_ascii_hexdigit()) || n.bytes().any(|b| b.is_ascii_uppercase()) {
                return Err(SealError("nonce must be 8 bytes of lowercase hex".into()));
            }
            n.to_string()
        }
        None => {
            let mut raw = [0u8; NONCE_BYTES];
            getrandom::getrandom(&mut raw).map_err(|e| SealError(e.to_string()))?;
            bytes_to_hex(&raw)
        }
    };
    let env = Json::Obj(vec![
        ("v".into(), Json::Num("1".into())),
        ("alg".into(), Json::Str("ed25519".into())),
        ("aid".into(), Json::Str(keypair.aid_hex.clone())),
        ("pub".into(), Json::Str(keypair.pub_hex.clone())),
        ("ts".into(), Json::Num(ts.to_string())),
        ("nonce".into(), Json::Str(nonce)),
        ("payload".into(), payload.clone()),
    ]);
    let input = signing_input(&env)?;
    let sig = keypair.signing.sign(&input).to_bytes();
    if let Json::Obj(pairs) = &env {
        let mut out = pairs.clone();
        out.push(("sig".into(), Json::Str(bytes_to_hex(&sig))));
        return Ok(Json::Obj(out));
    }
    unreachable!()
}

/// Verify an envelope. On success returns the signer AID (hex).
pub fn verify_envelope(env: &Json, now: Option<u64>, check_freshness: bool) -> Result<String, SealError> {
    if env.get("v").and_then(Json::as_u128) != Some(1) {
        return Err(SealError(format!("unsupported envelope version: {:?}", env.get("v"))));
    }
    if env.get("alg").and_then(Json::as_str) != Some("ed25519") {
        return Err(SealError(format!("unsupported algorithm: {:?}", env.get("alg"))));
    }
    let want_len = [("aid", 32), ("pub", 32), ("sig", 64), ("nonce", 8)];
    for (key, bytes) in want_len {
        let v = env.get(key).and_then(Json::as_str).unwrap_or("");
        if v.len() != bytes * 2 || !v.bytes().all(|b| b.is_ascii_hexdigit()) || v.bytes().any(|b| b.is_ascii_uppercase()) {
            return Err(SealError(format!(
                "{} must be {} bytes of lowercase hex -- a case variant is rejected, never normalised",
                key, bytes
            )));
        }
    }
    let ts = env
        .get("ts")
        .and_then(Json::as_u128)
        .ok_or_else(|| SealError("ts must be an integer (unix seconds)".into()))?;
    let ts = u64::try_from(ts).map_err(|_| SealError("ts out of range".into()))?;
    if !matches!(env.get("payload"), Some(Json::Obj(_))) {
        return Err(SealError("payload must be an object".into()));
    }
    if check_freshness {
        let now = now.unwrap_or_else(|| {
            SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
        });
        let drift = now.abs_diff(ts);
        if drift > MAX_SKEW {
            return Err(SealError(format!("timestamp skew too large ({}s > {}s) - replay?", drift, MAX_SKEW)));
        }
    }
    let pub_hex = env.get("pub").and_then(Json::as_str).unwrap_or("");
    let pub_bytes = hex_to_bytes(pub_hex).ok_or_else(|| SealError("bad pub hex".into()))?;
    let mut pub32 = [0u8; 32];
    pub32.copy_from_slice(&pub_bytes);
    let aid = bytes_to_hex(&aid_from_public_key(&pub32));
    if aid != env.get("aid").and_then(Json::as_str).unwrap_or("") {
        return Err(SealError("AID does not match public key (self-certification failed)".into()));
    }
    let key = VerifyingKey::from_bytes(&pub32).map_err(|e| SealError(e.to_string()))?;
    let sig_hex = env.get("sig").and_then(Json::as_str).unwrap_or("");
    let sig_bytes = hex_to_bytes(sig_hex).ok_or_else(|| SealError("bad sig hex".into()))?;
    let mut sig64 = [0u8; 64];
    sig64.copy_from_slice(&sig_bytes);
    let sig = ed25519_dalek::Signature::from_bytes(&sig64);
    let input = signing_input(env)?;
    key.verify(&input, &sig).map_err(|_| SealError("bad seal (signature does not verify)".into()))?;
    Ok(aid)
}
