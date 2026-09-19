# rttp

**RTTP (Resonant Time Transfer Protocol) for Rust: `rttp://` intent addressing,
`ROUTE_SHARD` derivation, the `PulseHeader128` codec, and the published
conformance vectors that prove an implementation is right.**

[RFC-002 §4.1](https://rttp.com/RFC-002/) · [§10](https://rttp.com/RFC-002/) · v1.2.6 · zero dependencies (default build) · `#![forbid(unsafe_code)]`

---

## Verify it — no trust required

```console
$ cargo test
...
test result: ok. 25 passed
```

That is the point of this crate. A specification is worth exactly what an
independent implementation can reproduce from it — so instead of asking you to
believe a table of numbers, this ships the vectors and replays them locally:
**6 positive URIs + 15 fail-closed rejections + 3 frame vectors + 1 compat
vector**, all offline, no account, no network.

The three implementations — Python (`pip install rttp`), JavaScript
(`npm install @aicent/rttp`), and this one — **share no code** and agree byte
for byte on the same published vector set
(`sha256 b28de8c7…`, shipped in all three packages).

---

## Install

```console
cargo add rttp
```

Zero dependencies in the default build: SHA-256 is implemented in-crate
(known-answer tested against NIST vectors) and the vector file is read through
a minimal in-crate JSON reader. The sovereign seal envelope is available
behind the optional `ed25519` feature — the same split as the Python package's
`[ed25519]` extra.

---

## Quickstart

```rust
use rttp::rttp_uri;

let parsed = rttp_uri::parse("rttp://brain.epoekie.aicent/verify").unwrap();

parsed.authority;              // 'brain.epoekie.aicent'
parsed.action;                 // 'verify'
parsed.route_shard_hex();      // '459e543b73d86005b72ba77d5756e83c' — pure computation
```

The same value the Python and JavaScript implementations derive, from code
that shares nothing with either.

Addressing is **DNS-free** (RFC-002 §10.5): the routing shard derives from the
authority by SHA-256, so no registry, resolver or network is involved.
Malformed input is rejected rather than normalised — a case variant is not a
spelling difference, it is a different string. No fallback, no `rttps`.

### Frame — `PulseHeader128`

```rust
use rttp::build_for_uri;

let raw = build_for_uri(1, 255, 1, "rttp://brain.epoekie.aicent/verify",
                        &aid_origin, timestamp_ns)?;
assert_eq!(raw.len(), 128);
```

Bytes `0x00`–`0x65` are untouched and `VERSION_ID` stays 130 — the v1.2.6
extension block (`0x66`–`0x7F`: SPEC_REV, FLAGS, ACTION) only fills bytes that
were already zero, so readers of the old layout keep working.

### Seal — sovereign envelope (feature `ed25519`)

```toml
rttp = { version = "1.2.6-alpha", features = ["ed25519"] }
```

Ed25519, self-certifying (`AID = SHA-256(public key)`), canonical signing
input prefixed `rttp-seal-v1\n`, `ts`/`nonce` inside the signature, 120-second
freshness. The verifier needs only the envelope — no key directory, no issuer.

---

## Scope — what this crate is not

| | |
|:---|:---|
| ✅ **Addressing / ROUTE_SHARD** | Real, and specified (RFC-002 §10 / RFC-002 §11). |
| ✅ **Framing** | Real, and specified (RFC-002 §4.1 + SPEC/RTTP-FRAME-EXT-v1.2.6). |
| ✅ **Sealing** | Real, and specified (draft) — feature `ed25519`. |
| ✅ **Conformance vectors + independent replay** | Published and generated. |
| ❌ **Transport** | **Not here.** No sockets, no `send()` — the codec stays dependency-free and auditable. |
| ❌ **Routing service** | `ROUTE_SHARD` is computed locally; delivering a frame to that hash is an operator's job. |
| ❌ **Confidentiality** | Signing is not encryption. |

Unknown revisions, algorithms and malformed input **fail closed** everywhere.
Nothing in this crate is ever accepted because a check could not be performed.

---

## Naming

| Ecosystem | Name | Status |
|:---|:---|:---|
| crates.io | `rttp` | **this crate** — `1.2.6-alpha`, implemented against the v1.2.6 specification |
| PyPI | `rttp` | **published** — the Python reference implementation; `pip install rttp` |
| npm | **`@aicent/rttp`** | **published** — the JavaScript independent implementation |

---

## Specification status

* **`rttp` URI scheme** — submitted to IANA under RFC 7595, ticket **#1459939**,
  Provisional, **under review**. It is **not yet registered**. Please describe
  it that way.
* **Frame layout** — RFC-002 §4.1, extended by `SPEC/RTTP-FRAME-EXT-v1.2.6.md`.
* **Seal envelope** — `SPEC/RTTP-SEAL-ENVELOPE-v1.2.6.md`, a **draft**.

Where this crate and a specification disagree, **the specification wins and
the crate is wrong.** Please report it.

---

## License

Apache-2.0. See `LICENSE`.
