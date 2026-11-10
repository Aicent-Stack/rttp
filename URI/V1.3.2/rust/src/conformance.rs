//! Conformance replay -- the published vector set, executed against THIS build.
//!
//! The vectors ship inside the crate (`vectors/rttp-conformance-v1.2.6.json`)
//! so a stranger can verify an installed package offline, with no repository
//! checkout. The replay covers every published check:
//!   6 positive URIs + 15 negative URIs + 3 frame vectors + 1 compat vector
//!   + 9 fail-closed frames + 1 accepted frame (SPEC_REV extension, sec. 3.2/4)
//!   + 3 envelope checks (canonical signing input, AID self-certification,
//!     Ed25519 signature).
//!
//! The JSON reader (`crate::json`) and the grammar (`crate::rttp_uri`) share
//! no code paths beyond the public parse function -- the replay never trusts
//! a helper written "by the same hand" for a different layer. The envelope's
//! canonical signing input is rebuilt here, from the vector, on purpose: the
//! seal module's own helper is never used to check the seal module.
//!
//! **Nothing may be skipped silently.** A zero-dependency build cannot do the
//! Ed25519 arithmetic, so that one check is reported as `skipped` and counted
//! -- the tests below assert `checked + skipped == PUBLISHED_CHECKS`, so a
//! check can not disappear from the report by accident.

use crate::json::{parse as json_parse, Json};
use crate::pulse_header;
use crate::rttp_uri;
use crate::sha256::{bytes_to_hex, hex_to_bytes, sha256};

/// Domain separation prefix of the seal envelope (SPEC/RTTP-SEAL-ENVELOPE
/// v1.2.6 sec. 3). Deliberately repeated here instead of imported from
/// `crate::seal_asym`: the replay must read the wire format, not the module
/// that writes it.
const SEAL_DOMAIN: &[u8] = b"rttp-seal-v1\n";

/// Checks the published vector set contains in total.
pub const PUBLISHED_CHECKS: usize = 38;

/// Checks a build without the `ed25519` feature can execute -- 38 minus the
/// signature arithmetic.
pub const CHECKS_WITHOUT_PRIMITIVE: usize = 37;

/// Result of one full replay.
#[derive(Debug, Clone)]
pub struct ConformanceResult {
    pub checked: usize,
    pub passed: usize,
    /// Checks this build could not run (optional primitive absent). Always
    /// visible in the count -- never a quiet zero.
    pub skipped: usize,
    pub failures: Vec<String>,
}

impl ConformanceResult {
    /// One-line summary, same shape the Python and JavaScript packages print.
    pub fn summary(&self) -> String {
        if !self.failures.is_empty() {
            format!(
                "[FAIL] {} of {} checks failed ({} skipped)",
                self.failures.len(),
                self.checked,
                self.skipped
            )
        } else if self.skipped > 0 {
            format!(
                "[PASS] all {} checks passed ({} skipped)",
                self.checked, self.skipped
            )
        } else {
            format!("[PASS] all {} checks passed", self.checked)
        }
    }
}

/// Rebuild the canonical signing input and the self-certifying AID from the
/// envelope vector, using only the JSON reader and the in-crate SHA-256.
fn signing_input_from_vector(ev: &Json) -> Result<(Vec<u8>, String), String> {
    let payload = ev.get("payload").cloned().ok_or("missing payload")?;
    if !matches!(payload, Json::Obj(_)) {
        return Err("payload must be an object".into());
    }
    let field = |key: &str| {
        ev.get(key)
            .cloned()
            .ok_or_else(|| format!("missing {}", key))
    };
    let inner = Json::Obj(vec![
        ("aid".into(), field("aid")?),
        ("alg".into(), field("alg")?),
        ("nonce".into(), field("nonce")?),
        ("payload".into(), payload),
        ("pub".into(), field("pub")?),
        ("ts".into(), field("ts")?),
    ]);
    let mut input = SEAL_DOMAIN.to_vec();
    input.extend_from_slice(inner.canonical().as_bytes());
    let pub_hex = ev.get("pub").and_then(Json::as_str).ok_or("missing pub")?;
    let pub_bytes = hex_to_bytes(pub_hex).ok_or("pub is not hex")?;
    if pub_bytes.len() != 32 {
        return Err("pub must be 32 bytes".into());
    }
    Ok((input, bytes_to_hex(&sha256(&pub_bytes))))
}

/// Rebuild the complete envelope object from the vector, for the signature
/// check. Only needed with the `ed25519` feature.
#[cfg(feature = "ed25519")]
fn envelope_object_from_vector(ev: &Json) -> Option<Json> {
    let text = |key: &str| ev.get(key).and_then(Json::as_str).map(str::to_string);
    Some(Json::Obj(vec![
        ("v".into(), Json::Num("1".into())),
        ("alg".into(), Json::Str(text("alg")?)),
        ("aid".into(), Json::Str(text("aid")?)),
        ("pub".into(), Json::Str(text("pub")?)),
        ("ts".into(), ev.get("ts")?.clone()),
        ("nonce".into(), Json::Str(text("nonce")?)),
        ("payload".into(), ev.get("payload")?.clone()),
        ("sig".into(), Json::Str(text("sig")?)),
    ]))
}

/// Replay a parsed vector document.
pub fn run(doc: &Json) -> ConformanceResult {
    let mut res = ConformanceResult {
        checked: 0,
        passed: 0,
        skipped: 0,
        failures: Vec::new(),
    };

    let check = |res: &mut ConformanceResult, ok: bool, label: &str, detail: String| {
        res.checked += 1;
        if ok {
            res.passed += 1;
        } else {
            res.failures.push(format!("{}: {}", label, detail));
        }
    };

    // --- positive URIs: accept, canonicalise, derive ------------------------
    if let Some(cases) = doc.get("positive_uris").and_then(Json::as_arr) {
        for case in cases {
            let uri = case.get("uri").and_then(Json::as_str).unwrap_or("");
            let parsed = rttp_uri::parse(uri);
            match parsed {
                Err(e) => check(
                    &mut res,
                    false,
                    uri,
                    format!("expected ACCEPT, rejected: {}", e),
                ),
                Ok(p) => {
                    let mut bad: Vec<String> = Vec::new();
                    for (key, got, want) in [
                        (
                            "canonical_uri",
                            p.canonical_uri.clone(),
                            case.get("canonical_uri")
                                .and_then(Json::as_str)
                                .unwrap_or("")
                                .to_string(),
                        ),
                        (
                            "action",
                            p.action.clone(),
                            case.get("action")
                                .and_then(Json::as_str)
                                .unwrap_or("")
                                .to_string(),
                        ),
                        (
                            "route_shard_hex",
                            crate::sha256::bytes_to_hex(&p.route_shard),
                            case.get("route_shard_hex")
                                .and_then(Json::as_str)
                                .unwrap_or("")
                                .to_string(),
                        ),
                    ] {
                        if got != want {
                            bad.push(format!("{} {:?} != {:?}", key, want, got));
                        }
                    }
                    check(&mut res, bad.is_empty(), uri, bad.join("; "));
                }
            }
        }
    }

    // --- negative URIs: reject, fail closed ---------------------------------
    if let Some(cases) = doc.get("negative_uris").and_then(Json::as_arr) {
        for case in cases {
            let uri = case.get("uri").and_then(Json::as_str).unwrap_or("");
            check(
                &mut res,
                rttp_uri::parse(uri).is_err(),
                uri,
                "expected REJECT but parsed".into(),
            );
        }
    }

    // --- frame vectors: URI -> ROUTE_SHARD -> 128 bytes, bit for bit ----------
    if let Some(cases) = doc.get("frame_vectors").and_then(Json::as_arr) {
        for case in cases {
            let uri = case.get("uri").and_then(Json::as_str).unwrap_or("");
            let label = format!("frame {}", uri);
            let fail = |res: &mut ConformanceResult, detail: String| {
                check(res, false, &label, detail);
            };
            let Some(aid_hex) = case.get("aid_origin_hex").and_then(Json::as_str) else {
                fail(&mut res, "missing aid_origin_hex".into());
                continue;
            };
            let Some(aid) = hex_to_bytes(aid_hex) else {
                fail(&mut res, "bad aid_origin_hex".into());
                continue;
            };
            let mut aid32 = [0u8; 32];
            if aid.len() != 32 {
                fail(&mut res, "aid_origin_hex must be 32 bytes".into());
                continue;
            }
            aid32.copy_from_slice(&aid);

            let seq = case.get("sequence_id").and_then(Json::as_u128).unwrap_or(0);
            let ttl = case.get("ttl").and_then(Json::as_u128).unwrap_or(0) as u8;
            let prio = case.get("priority").and_then(Json::as_u128).unwrap_or(0) as u8;
            let ts = case
                .get("timestamp_ns")
                .and_then(Json::as_u128)
                .unwrap_or(0);
            let want_hex = case.get("header_hex").and_then(Json::as_str).unwrap_or("");

            match pulse_header::build_for_uri(seq, ttl, prio, uri, &aid32, ts) {
                Err(e) => fail(&mut res, format!("build failed: {}", e)),
                Ok(raw) => {
                    if crate::sha256::bytes_to_hex(&raw) != want_hex {
                        fail(
                            &mut res,
                            "frame bytes differ from the published vector".into(),
                        );
                        continue;
                    }
                    match pulse_header::verify(&raw, Some(&aid32)) {
                        Err(e) => fail(&mut res, format!("verify failed on our own frame: {}", e)),
                        Ok(fields) => {
                            let want_action =
                                case.get("action").and_then(Json::as_str).unwrap_or("");
                            check(
                                &mut res,
                                fields.action == want_action,
                                &label,
                                format!("action readback {:?} != {:?}", fields.action, want_action),
                            );
                        }
                    }
                }
            }
        }
    }

    // --- fail-closed frames: malformed extension blocks must be rejected -----
    // Each vector names the rule it exercises (R4-R7 of SPEC sec. 4); the
    // origin is embedded in the frame itself, so nothing is pinned here.
    if let Some(cases) = doc.get("negative_frames").and_then(Json::as_arr) {
        for case in cases {
            let label = case
                .get("label")
                .and_then(Json::as_str)
                .unwrap_or("negative frame");
            let raw = case
                .get("header_hex")
                .and_then(Json::as_str)
                .and_then(hex_to_bytes);
            let Some(bytes) = raw else {
                check(&mut res, false, label, "missing or bad header_hex".into());
                continue;
            };
            check(
                &mut res,
                pulse_header::verify(&bytes, None).is_err(),
                label,
                "expected REJECT but the frame verified".into(),
            );
        }
    }

    // --- accepted frame: SPEC_REV=1 with ACTION_LEN=0 == omission ------------
    if let Some(cases) = doc.get("positive_frames").and_then(Json::as_arr) {
        for case in cases {
            let label = case
                .get("label")
                .and_then(Json::as_str)
                .unwrap_or("accepted frame");
            let raw = case
                .get("header_hex")
                .and_then(Json::as_str)
                .and_then(hex_to_bytes);
            let Some(bytes) = raw else {
                check(&mut res, false, label, "missing or bad header_hex".into());
                continue;
            };
            let want_action = case.get("action").and_then(Json::as_str).unwrap_or("");
            match pulse_header::verify(&bytes, None) {
                Err(e) => check(
                    &mut res,
                    false,
                    label,
                    format!("expected ACCEPT, rejected: {}", e),
                ),
                Ok(fields) => check(
                    &mut res,
                    fields.action == want_action,
                    label,
                    format!("action readback {:?} != {:?}", fields.action, want_action),
                ),
            }
        }
    }

    // --- envelope vector ----------------------------------------------------
    // Two checks run in every build; the signature is the third and the only
    // thing a zero-dependency build may skip.
    if let Some(ev) = doc.get("envelope_vector") {
        let want_input = ev
            .get("signing_input_hex")
            .and_then(Json::as_str)
            .unwrap_or("");
        let want_aid = ev.get("aid").and_then(Json::as_str).unwrap_or("");

        match signing_input_from_vector(ev) {
            Err(e) => {
                check(
                    &mut res,
                    false,
                    "envelope: canonical signing input",
                    e.clone(),
                );
                check(&mut res, false, "envelope: AID self-certification", e);
            }
            Ok((input, aid)) => {
                let got_input = bytes_to_hex(&input);
                check(
                    &mut res,
                    got_input == want_input,
                    "envelope: canonical signing input",
                    format!("{:?} != {:?}", want_input, got_input),
                );
                check(
                    &mut res,
                    aid == want_aid,
                    "envelope: AID self-certification",
                    format!("{:?} != {:?}", want_aid, aid),
                );
            }
        }

        #[cfg(feature = "ed25519")]
        {
            // The vector is pinned to a fixed ts, so the freshness window is
            // deliberately not enforced here.
            match envelope_object_from_vector(ev) {
                None => check(
                    &mut res,
                    false,
                    "envelope: Ed25519 signature",
                    "envelope vector is incomplete".into(),
                ),
                Some(env) => match crate::seal_asym::verify_envelope(&env, None, false) {
                    Ok(aid) => check(
                        &mut res,
                        aid == want_aid,
                        "envelope: Ed25519 signature",
                        format!("verified AID {:?} != {:?}", aid, want_aid),
                    ),
                    Err(e) => check(
                        &mut res,
                        false,
                        "envelope: Ed25519 signature",
                        format!("expected ACCEPT, rejected: {}", e),
                    ),
                },
            }
        }
        #[cfg(not(feature = "ed25519"))]
        {
            res.skipped += 1;
        }
    }

    // --- compat vector: SPEC_REV=0 frames must still verify ------------------
    if let Some(cv) = doc.get("compat_vector_spec_rev_0") {
        let label = "compat SPEC_REV=0";
        let ok = (|| -> Result<bool, String> {
            let hex = cv
                .get("header_hex")
                .and_then(Json::as_str)
                .ok_or("missing header_hex")?;
            let raw = hex_to_bytes(hex).ok_or("bad header_hex")?;
            let aid_hex = cv.get("uri").and_then(Json::as_str).unwrap_or("");
            let _ = aid_hex;
            // The compat vector's aid_origin is inside the frame itself --
            // verify without pinning, then require the rev-0 semantics.
            let fields = pulse_header::verify(&raw, None).map_err(|e| e.to_string())?;
            Ok(fields.spec_rev == 0 && fields.action_omitted)
        })();
        match ok {
            Ok(true) => check(&mut res, true, label, String::new()),
            Ok(false) => check(
                &mut res,
                false,
                label,
                "SPEC_REV=0 semantics mismatch".into(),
            ),
            Err(e) => check(
                &mut res,
                false,
                label,
                format!("expected ACCEPT, rejected: {}", e),
            ),
        }
    }

    res
}

/// Convenience: parse the shipped vector file and replay it.
pub fn run_shipped() -> ConformanceResult {
    match json_parse(include_str!("../vectors/rttp-conformance-v1.2.6.json")) {
        Ok(doc) => run(&doc),
        Err(e) => ConformanceResult {
            checked: 1,
            passed: 0,
            skipped: 0,
            failures: vec![format!("cannot parse shipped vectors: {}", e)],
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shipped_vectors_replay_green() {
        let r = run_shipped();
        println!("{}", r.summary());
        assert!(r.failures.is_empty(), "failures: {:?}", r.failures);
        assert_eq!(
            r.checked + r.skipped,
            PUBLISHED_CHECKS,
            "the whole published vector set must be replayed -- nothing may vanish silently"
        );
        assert_eq!(
            r.checked,
            CHECKS_WITHOUT_PRIMITIVE + usize::from(cfg!(feature = "ed25519")),
            "only the Ed25519 primitive itself may be skipped in the default build"
        );
        assert_eq!(r.checked, r.passed);
    }
}
