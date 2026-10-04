//! # rttp -- Rust reference implementation of RTTP (v1.3.1)
//!
//! `rttp://` intent addressing, `ROUTE_SHARD` derivation, the `PulseHeader128`
//! codec, and the published conformance vectors that prove an implementation
//! is right -- replayed offline, no repository checkout, `[PASS]` or it is not.
//!
//! **Zero dependencies by default.** SHA-256 is implemented in-crate
//! (known-answer tested), the vectors are read through a minimal in-crate JSON
//! reader, and the crate is `#![forbid(unsafe_code)]`. The sovereign seal
//! envelope is available behind the optional `ed25519` feature -- the same
//! split as the Python package's `[ed25519]` extra.
//!
//! ## Verify it
//!
//! ```console
//! $ cargo test          # 13 unit tests + 1 doc test, all green -- the
//!                       # conformance replay walks every published vector
//!                       # (35 checks) byte for byte
//! ```
//!
//! v1.3.1 is the first formal (non-pre-release) publication of this crate;
//! the earlier `1.2.8-alpha` remains published and is not yanked. No API
//! changed in this release. The answer-side AE-128 carrier lives in the
//! sibling crate `iqa-org` 1.3.1 (`iqa_org::envelope`).
//!
//! ## Quickstart
//!
//! ```
//! use rttp::rttp_uri;
//!
//! let parsed = rttp_uri::parse("rttp://brain.epoekie.aicent/verify").unwrap();
//! assert_eq!(parsed.authority, "brain.epoekie.aicent");
//! assert_eq!(parsed.action, "verify");
//! // ROUTE_SHARD = SHA-256(ASCII(authority))[0:16] -- pure computation:
//! assert_eq!(parsed.route_shard_hex(), "459e543b73d86005b72ba77d5756e83c");
//! ```
//!
//! ## Authority
//!
//! Grammar: AICENT-002 sec. 10.2 ABNF. Frame: AICENT-002 sec. 4.1 + SPEC/RTTP-FRAME-EXT-v1.2.6.
//! The `rttp` URI scheme **is registered**: IANA "URI Schemes" registry,
//! Provisional, CRI 27 (2026-09-22), submitted under RFC 7595.
//! The combined Internet-Draft `draft-li-rttp-iqa-addressing` (both schemes,
//! one document) is under IETF review as an Individual Submission.
//! Where this crate and a specification disagree, **the specification wins
//! and this crate is wrong.**

#![forbid(unsafe_code)]

pub mod conformance;
pub mod json;
pub mod pulse_header;
pub mod rttp_uri;
pub mod sha256;

#[cfg(feature = "ed25519")]
pub mod seal_asym;

pub use rttp_uri::{derive_route_shard, is_valid_action, parse, ParsedUri, RttpUriError};
pub use pulse_header::{build_for_uri, verify, ParsedFrame, PulseHeaderError, ACTION_MAX_LEN, VERSION_ID};
