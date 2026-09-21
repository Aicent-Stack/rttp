//! Conformance replay — the published vector set, executed against THIS build.
//!
//! The vectors ship inside the crate (`vectors/rttp-conformance-v1.2.6.json`)
//! so a stranger can verify an installed package offline, with no repository
//! checkout. The replay covers all 25 published checks:
//!   6 positive URIs + 15 negative URIs + 3 frame vectors + 1 compat vector.
//!
//! The JSON reader (`crate::json`) and the grammar (`crate::rttp_uri`) share
//! no code paths beyond the public parse function — the replay never trusts
//! a helper written "by the same hand" for a different layer.

use crate::json::{parse as json_parse, Json};
use crate::pulse_header;
use crate::sha256::hex_to_bytes;
use crate::rttp_uri;

/// Result of one full replay.
#[derive(Debug, Clone)]
pub struct ConformanceResult {
    pub checked: usize,
    pub passed: usize,
    pub failures: Vec<String>,
}

/// Replay a parsed vector document.
pub fn run(doc: &Json) -> ConformanceResult {
    let mut res = ConformanceResult { checked: 0, passed: 0, failures: Vec::new() };

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
                Err(e) => check(&mut res, false, uri, format!("expected ACCEPT, rejected: {}", e)),
                Ok(p) => {
                    let mut bad: Vec<String> = Vec::new();
                    for (key, got, want) in [
                        ("canonical_uri", p.canonical_uri.clone(),
                         case.get("canonical_uri").and_then(Json::as_str).unwrap_or("").to_string()),
                        ("action", p.action.clone(),
                         case.get("action").and_then(Json::as_str).unwrap_or("").to_string()),
                        ("route_shard_hex", crate::sha256::bytes_to_hex(&p.route_shard),
                         case.get("route_shard_hex").and_then(Json::as_str).unwrap_or("").to_string()),
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

    // --- frame vectors: URI → ROUTE_SHARD → 128 bytes, bit for bit ----------
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
            let ts = case.get("timestamp_ns").and_then(Json::as_u128).unwrap_or(0);
            let want_hex = case.get("header_hex").and_then(Json::as_str).unwrap_or("");

            match pulse_header::build_for_uri(seq, ttl, prio, uri, &aid32, ts) {
                Err(e) => fail(&mut res, format!("build failed: {}", e)),
                Ok(raw) => {
                    if crate::sha256::bytes_to_hex(&raw) != want_hex {
                        fail(&mut res, "frame bytes differ from the published vector".into());
                        continue;
                    }
                    match pulse_header::verify(&raw, Some(&aid32)) {
                        Err(e) => fail(&mut res, format!("verify failed on our own frame: {}", e)),
                        Ok(fields) => {
                            let want_action = case.get("action").and_then(Json::as_str).unwrap_or("");
                            check(&mut res, fields.action == want_action, &label,
                                  format!("action readback {:?} != {:?}", fields.action, want_action));
                        }
                    }
                }
            }
        }
    }

    // --- compat vector: SPEC_REV=0 frames must still verify ------------------
    if let Some(cv) = doc.get("compat_vector_spec_rev_0") {
        let label = "compat SPEC_REV=0";
        let ok = (|| -> Result<bool, String> {
            let hex = cv.get("header_hex").and_then(Json::as_str).ok_or("missing header_hex")?;
            let raw = hex_to_bytes(hex).ok_or("bad header_hex")?;
            let aid_hex = cv.get("uri").and_then(Json::as_str).unwrap_or("");
            let _ = aid_hex;
            // The compat vector's aid_origin is inside the frame itself —
            // verify without pinning, then require the rev-0 semantics.
            let fields = pulse_header::verify(&raw, None).map_err(|e| e.to_string())?;
            Ok(fields.spec_rev == 0 && fields.action_omitted)
        })();
        match ok {
            Ok(true) => check(&mut res, true, label, String::new()),
            Ok(false) => check(&mut res, false, label, "SPEC_REV=0 semantics mismatch".into()),
            Err(e) => check(&mut res, false, label, format!("expected ACCEPT, rejected: {}", e)),
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
        assert_eq!(r.checked, 25, "expected exactly the 25 published checks");
        assert!(r.failures.is_empty(), "failures: {:?}", r.failures);
        assert_eq!(r.checked, r.passed);
    }
}
