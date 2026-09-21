# Changelog -- `rttp` (Python)

All notable changes to the `rttp` package. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is
[Semantic Versioning](https://semver.org/).

---

## [1.2.8] -- 2026-09-21

**Version-only re-publish.** The code, the vector file and every self-test result
are identical to `1.2.7`; only the version string moves, so the final PyPI release
carries the stack number. `1.2.7` stays installable -- pin `1.2.8` for new work.

* No wire-format, URI-grammar, public-API or vector change.
* `python -m rttp.selftest` still reports 83 checks in full, and 80 passed with
  3 skipped on a zero-dependency install.

## [1.2.7] -- 2026-09-21

**Conformance surface grown; wire format untouched.** The shipped
`rttp/vectors/rttp-conformance-v1.2.6.json` is now 13,460 bytes
(`sha256 4b743e63...`) and the self-test replays every added case: **83 checks**
in full, and **80 passed with 3 skipped** on a zero-dependency install -- a check
that cannot be performed is reported as skipped, never as passed.

### Added

* **Nine fail-closed frame cases, one positive frame.** Each of the nine frames
  must be rejected; the positive frame must be accepted with an empty action.
* **The published Ed25519 envelope vector**, replayed three ways: the canonical
  signing input byte for byte, `AID == SHA-256(public key)`, and the signature
  itself (the third one skips without the optional primitive).

### Changed

* **Skipped checks are now counted and printed**, so a default install can no
  longer look like a full pass.
* Per-section counts are reported: 38 conformance, 16 envelope rules, 22 envelope
  flow, 2 RFC 8032, 5 zero-dependency.

### Note

* PyPI and npm carry `1.2.7`; crates.io carries the same code as the pre-release
  `1.2.8-alpha`. The registry version strings differ by publishing policy, not by
  code -- the vectors and their `sha256` are identical everywhere.

## [1.2.6] -- 2026-09-19

**Version alignment -- no code change.** Every module, byte layout and
conformance vector is identical to 0.1.2, and the self-test still reports the
the same 53 checks (full set, i.e. with the optional Ed25519 backend). Only the version string and the maturity classifier change.

### Changed

* **The version number now mirrors the stack version.** PyPI and npm carry
  `1.2.6`, so a single number identifies this code on every distribution
  channel; crates.io carries the same code as the pre-release `1.2.6-alpha`.
  The old `0.1.x` line was a package-maturity number that corresponded to
  nothing in the specification, and it made the same package look like two
  different releases on two registries.
* **`Development Status` classifier: `3 - Alpha` -> `4 - Beta`.** A
  non-pre-release version must not ship with an "Alpha" classifier; leaving
  the two in conflict invites the question "which one is true?".
* Install command note: on crates.io every published version of this crate is
  a pre-release, so Cargo will not select it from a plain `rttp` requirement.
  Write `cargo add rttp@1.2.6-alpha` (or pin `rttp = "1.2.6-alpha"`).

## [0.1.2] -- 2026-09-18

**Metadata correction -- no code change.** Every module, byte layout and
conformance vector is identical to 0.1.1, and the self-test still reports the
the same 53 checks (full set, i.e. with the optional Ed25519 backend).

### Fixed

* **The distribution identity now matches the IANA registration.** The package
  was authored as `RTTP Working Group` -- a name that appears in no filing. The
  `rttp` URI-scheme registration on file with IANA (ticket `[IANA #1459939]`)
  names **`RTTP.COM Organization`** as the `Author/Change controller`, and every
  other public surface uses that same name. Both package manifests now say it
  too:

  | Field | Before | After |
  |:---|:---|:---|
  | `pyproject.toml` -> `authors` (PyPI) | `RTTP Working Group` | **`RTTP.COM Organization`** |
  | `package.json` -> `author` (npm) | `RTTP Working Group` | **`RTTP.COM Organization`** |

  Package metadata cannot be edited after publication, so 0.1.0 and 0.1.1 keep
  the old string inside their own metadata; this is the version that carries the
  correction. Project pages display the latest version, so the visible author
  name becomes correct once this release is out.

## [0.1.1] -- 2026-09-18

**Documentation only -- no code change.** Every module, byte layout and
conformance vector is identical to 0.1.0, and the self-test still reports the
the same 53 checks (full set, i.e. with the optional Ed25519 backend).

### Fixed

* **A distribution claim that was wrong, not merely outdated.** The 0.1.0 entry
  below said the JavaScript side "will publish under the `@rttp` scope". That
  scope **cannot be created at all**: npm already has a personal account named
  `rttp`, and an organization name may not collide with a user name. The
  JavaScript side is published as **`@aicent/rttp`** -- this project's own
  organization, with the package name itself still just `rttp`.
* **README distribution table** now names the npm package exactly
  (`@aicent/rttp`), and gives `pip install rttp` for this package, matching the
  table in the JavaScript package's README.

### Distribution status at this release

| Registry | Name | State |
|:---|:---|:---|
| PyPI | `rttp` | this package -- `pip install rttp` |
| npm | `@aicent/rttp` | **published 0.1.1** -- 2026-09-18 |
| crates.io | `rttp` | held by this project |

## [0.1.0] -- 2026-09-17

First release. Scope is deliberately narrow: **framing, addressing and sealing**,
with zero dependencies and no transport.

### Added

* **`rttp.pulse_header`** -- `PulseHeader128` codec for the 128-byte
  hardware-aligned frame header (RFC-002 sec. 4.1), including the v1.2.6 extension
  block:
  * `SPEC_REV` `0x66` - `FLAGS` `0x67` - `ACTION_LEN` `0x68` - `ACTION` `0x69`(16B)
    - `RESERVED` `0x79`(7B)
  * bytes `0x00`-`0x65` are **not touched**, `VERSION_ID` stays 130 -- readers
    that only understand the original layout remain conformant
  * `build()` - `build_for_uri()` - `parse()` - `verify()` - `to_hex()` /
    `from_hex()`
  * strict verification (R1-R7): unknown `SPEC_REV` rejected, `SPEC_REV=0` with a
    non-zero block rejected, non-zero `RESERVED` rejected, unknown `FLAGS` bits
    rejected, `ACTION` padding must be zero, `ACTION_LEN` must agree with the
    payload
* **`rttp.rttp_uri`** -- validation, canonicalisation and `ROUTE_SHARD`
  derivation for `rttp://` URIs (RFC-002 sec. 10.2 / sec. 10.3):
  * `ROUTE_SHARD = SHA-256(ASCII(canonical_authority))[0:16]` -- deterministic,
    pure computation, **no DNS** (sec. 10.5)
  * hash-intent (`8lowhex`) and name-intent forms; open-set `action` vocabulary
  * fail-closed rejection of uppercase, `userinfo`, `port`, `query`,
    `fragment`, multi-segment paths, wrong segment counts, leading/trailing `-`,
    whitespace, and non-`rttp` schemes
  * accepts both `rttp://` and `web+rttp://` -- the second as a **tolerance** for
    the browser protocol-handler form, which RFC-002 no longer defines
    (2026-09-17). Not a conformance claim; see "Known gaps" below.
* **`rttp.seal`** -- managed profile: HMAC-SHA256 over a pre-shared key table,
  bidirectional switch<->agent signing, `ts|nonce` with a 120-second skew window.
* **`rttp.seal_asym`** -- **sovereign profile**: Ed25519 seals with
  `AID = SHA-256(public_key)`.
  * self-certifying: the envelope carries the public key, so a verifier
    recomputes the identity instead of trusting a claim -- **no issuance, no
    registry, no directory**
  * `ts` and `nonce` are **inside** the signed input, so they cannot be rewritten
    without breaking the signature
  * freshness enforced by default (`|now - ts| <= 120 s`); archival verification
    available explicitly via `check_freshness=False`
  * lowercase-hex only -- a case variant is rejected, not normalised
  * `generate_keypair()` - `seal()` - `unseal()` - `verify_envelope()` -
    `verify_claims()` - `public_bundle()` - `signing_input()`
  * requires the `ed25519` extra; without it every call raises `SealError` with
    the install instruction rather than degrading to an unsigned path
* **`rttp.aid`** -- Autonomous Identity derivation (RFC-001), shared by both
  profiles so an AID means one thing across the stack.
* **`rttp.selftest`** -- `python -m rttp.selftest`, **53 checks with the optional Ed25519 backend (29 by default)**:
  * 25 conformance vectors (6 positive URIs - 15 rejections - 3 deterministic
    frames - 1 `SPEC_REV=0` compatibility vector)
  * RFC 8032 sec. 7.1 TEST 1 / TEST 2, proving the signature backend is standard
    Ed25519 -- so a failure identifies *which* half broke
  * 22 envelope checks, including a 14-case tamper matrix in which every single
    alteration must be rejected, and an explicit replay-window test
  * 4 static-scan checks proving the core modules import nothing outside the
    standard library
  * `--vectors` prints the deterministic envelope vector for the specification;
    `--quiet` prints the summary line only
* **`rttp/vectors/rttp-conformance-v1.2.6.json`** -- the published vectors, shipped
  as package data so the self-test runs from an installed wheel, offline.
* Console entry point `rttp-selftest`.
* **`MANIFEST.in`** -- the source distribution carries `README.md`,
  `CHANGELOG.md`, `LICENSE`, `pyproject.toml` and the published vectors, and
  excludes virtual environments and build noise. Both the wheel and the sdist
  pass `twine check`.

### Notes

* **Zero dependencies** in the core, and that is a machine-checked claim rather
  than a promise -- see the static-scan section of the self-test.
* The reference implementation evaluates the
  **`iqa`** namespace nowhere: this package is the `rttp` protocol only.
* ~~Distribution: PyPI `rttp`. The npm name `rttp` is held by an unrelated,
  unmaintained project, so the JavaScript side will publish under the `@rttp`
  scope.~~ -- **corrected 2026-09-18.** PyPI `rttp` is now **published** (0.1.0,
  2026-09-17). The npm name `rttp` is indeed held by an unrelated, unmaintained
  project -- but the **`@rttp` scope cannot be created at all**, because a
  personal account already holds that name. The JavaScript side is therefore
  published as **`@aicent/rttp`**: this project's own organization, with the
  package name still just `rttp`.

### Known gaps

Tracked in `SPEC/RTTP-SEAL-ENVELOPE-v1.2.6.md` sec. 8 and sec. 10. Deliberately listed
here so nobody has to discover them:

* No transport and no client. The core encodes, addresses and seals; sending is a
  separate package's job.
* No revocation, and no key rotation story. Both belong to RFC-003.
* No replay **cache**: freshness (sec. 3.4) bounds the window, but within it a replayed
  envelope still verifies unless the verifier keeps a short-lived nonce store.
* No transport-origin binding: the seal proves who signed, not which connection
  delivered it.
* Rust parity: the published `rttp` crate has no transport layer and no envelope.
  Python and Node are the conforming implementations so far.
* ~~the browser-registration prefix is accepted because RFC-002 sec. 10.6 requires
  it...~~ -- **superseded 2026-09-17.** That form was removed from both
  specifications and will never be submitted to IANA. `rttp_uri` still accepts it
  as a **tolerance** -- a browser hands the handler that string, and refusing it
  would break the protocol-handler path -- but the specification defines no such
  form, so the acceptance is **outside the specification** and a conforming
  third-party implementation is not required to reproduce it.
* ~~**Open, and ours to fix:** the published vectors asserted things the
  specification no longer said.~~ -- **resolved 2026-09-18.** The generator now
  classifies every forward case explicitly:
  * `positive_uris` -- each entry carries `tolerance` (boolean) and `note`. The
    case whose `uri` carries the browser-registration prefix is `tolerance: true`,
    with its reason recorded: it is accepted only because that is the scheme name
    under which a handler is registered (RFC-002 sec. 10.6) -- never because the
    specification defines it. It is **not** a conformance claim, and the 25-check
    total is unchanged.
  * `negative_uris` -- the two case-clause citations were corrected from
    `(RFC-002 sec. 10.2)` to **`sec. 10.3`**, the clause that actually carries the
    lowercase rule. sec. 10.2 now appears nowhere in the vector set.
  Regenerated (`SPEC/tools/conformance.py --generate`), replayed (`--check`,
  25/25), and mirrored byte-identically into both packages. After the change:
  Python self-test 53/53, Node runner 25/25.
