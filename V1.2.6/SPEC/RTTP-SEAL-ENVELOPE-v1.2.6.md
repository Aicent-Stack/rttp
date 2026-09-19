# RTTP Seal Envelope — v1.2.6 (Draft)

**Status:** Draft — **not yet part of RFC-002.** Cite it as a draft addition.
**Applies to:** RFC-002 (frames, `rttp` URIs) · RFC-003 (Immune layer)
**Reference implementation:** `PKG/rttp/src/rttp/seal_asym.py`
**Deterministic vector:** §7 (regenerate with `python -m rttp.selftest --vectors`)

---

## 0. Scope and status

RFC-002 §4.1 freezes bytes `0x00`–`0x65` of the 128-byte frame header. The
v1.2.6 extension block (`0x66`–`0x7F`) carries `SPEC_REV`, `FLAGS`, `ACTION` and
7 reserved bytes — **no room for a 64-byte signature**, and widening the header
would break every deployed reader.

A seal therefore does **not** live in the header. It wraps the frame in an
**envelope** — an outer structure that carries the payload plus the identity and
signature needed to attribute it.

This document specifies that envelope for the **sovereign profile** (Ed25519,
self-certifying). The **managed profile** (symmetric HMAC over a pre-shared key
table, `seal.py`) is unchanged and remains valid for closed sets of roles; §1
explains when each applies.

> **Gap this document closes.** The managed profile already carried `ts|nonce`
> with a 120-second window. A sovereign profile that dropped replay protection
> would be *weaker* than the thing it replaces. §3.4 exists for that reason.

---

## 1. Two profiles

| | **Managed** (`seal.py`) | **Sovereign** (this document) |
|:---|:---|:---|
| Primitive | HMAC-SHA256 | Ed25519 |
| Key material | pre-shared table (`seal_keys.json`) | each participant generates its own |
| Who can issue | the operator | **nobody — there is nothing to issue** |
| Identity | a role name in the table | **AID = SHA-256(public key)** |
| Verifier needs | the same table | only the envelope |
| Registry / directory | the table *is* the registry | **none** |
| A stranger can participate | **no** | **yes** |
| Breach of one key | forges **any** participant holding the `switch` key | forges **one** identity |
| Enables | a closed organism | an open protocol, an IANA scheme, a Grant |

**Rule of thumb.** Inside a set of symmetric secrets there is no such thing as a
stranger — every holder of the shared key can mint every other party's seal. A
protocol that asks third parties to participate therefore **cannot** be built on
the managed profile. That is the entire reason this document exists.

---

## 2. Identity

```
AID = SHA-256(public_key)          32 bytes
```

derived by the same function the rest of the stack uses (`aid.derive_from_entropy`),
so an AID means **one** thing everywhere rather than two.

Because the AID is a pure function of the public key, a verifier that receives the
public key can **recompute** the claimed identity instead of being told it. This is
what "self-certifying" means here, and it is why no registry is required.

Consequence to state plainly: **the AID is not a name that can be reassigned.** Lose
the private key and the identity is gone — there is no operator who can restore it.
That is the trade: no issuance means no recovery.

---

## 3. Envelope

### 3.1 Layout

```json
{
  "v":     1,
  "alg":   "ed25519",
  "aid":   "3125ee20b2238281f70ca408192f82152647d365219184fa1fe22c08a42c035e",
  "pub":   "9c097c66ab4f82136ceddaef56854f740bf87da3eec42a249ba40bbb066f1e6a",
  "ts":    1760000000,
  "nonce": "0011223344556677",
  "sig":   "8d8e0d458b1defb6fd078343e7e46fc96cbaa05b6ead9e587d324e4c2358145790042f4a5001f3d902e7da670e2ea5700903363dd2825159a25dc262b25cb305",
  "payload": { "intent": "verify", "task_id": "selftest-0001" }
}
```

| Field | Size | Notes |
|:---|:---|:---|
| `v` | int | Envelope format version. `1`. Unknown ⇒ reject. |
| `alg` | string | `"ed25519"`. Unknown ⇒ reject (never "try anyway"). |
| `aid` | 32 B hex | Lowercase. **MUST** equal `SHA-256(pub)`. |
| `pub` | 32 B hex | Lowercase. Carried in-band — this is what removes the lookup. |
| `ts` | int | Unix seconds. Inside the signature. |
| `nonce` | 8 B hex | Lowercase. Inside the signature. |
| `sig` | 64 B hex | Lowercase. Ed25519 over §4. |
| `payload` | object | The frame and/or application content. Opaque to this document. |

**Hex is lowercase only.** Per the canonical-form discipline of RFC-002 §10.3, a
case variant is **not normalised — it is rejected**. Two encodings of the same
bytes would otherwise produce two different signing inputs.

### 3.2 Why the public key travels in-band

A 32-byte public key per envelope is the price of having no directory. The
alternative — resolving AID → public key — reintroduces exactly the registry that
§10.5 of RFC-002 exists to avoid. In-band is the honest trade for `rttp` being
DNS-free.

### 3.3 Why `ts` and `nonce` are inside the signature

Putting them beside the signature rather than inside it means an attacker rewrites
them **without touching Ed25519 at all** — the seal would still verify while the
replay window had been rewritten. They are covered by the same signature as
everything else.

### 3.4 Freshness

```
|now - ts| <= 120 s
```

A verifier **MUST** enforce this window for any envelope arriving over a network.
`check_freshness=False` exists solely to validate **archived** envelopes (audit
records, test vectors) and **MUST NOT** be used on live input.

---

## 4. Canonical signing input

```
signing_input = b"rttp-seal-v1\n" || json_canonical({
    "alg": ..., "aid": ..., "pub": ..., "ts": ..., "nonce": ..., "payload": ...
})
```

`json_canonical` = UTF-8, **sorted keys**, separators `,` and `:` with no
insignificant whitespace, `ensure_ascii=False`.

Every envelope field except `sig` enters the input. A field that a verifier
ignores but a signer covers (or vice versa) is a downgrade channel, so the rule is
total: **no unsigned field.**

The `rttp-seal-v1\n` prefix domain-separates this signature from any other
Ed25519 signature made by the same key.

---

## 5. Verification procedure

In order. The first failure ends verification.

| # | Check | On failure |
|:---|:---|:---|
| 1 | `v == 1` | reject |
| 2 | `alg == "ed25519"` | reject |
| 3 | `aid`, `pub`, `sig`, `nonce` are lowercase hex of the right length | reject |
| 4 | `ts` is an integer | reject |
| 5 | `payload` is an object | reject |
| 6 | `|now - ts| <= 120` (unless archival mode) | reject — *replay?* |
| 7 | **`SHA-256(pub) == aid`** | reject — *self-certification failed* |
| 8 | Ed25519 verifies over §4 | reject — *bad seal* |

**A check that cannot be performed is a failure, never a pass.** A missing
`cryptography` dependency must raise, not silently skip verification.

---

## 6. Rejection rules

An implementation is conformant only if it rejects **all** of the following
(replayed by the reference self-test, 14 cases):

| Tampering | Caught by |
|:---|:---|
| payload altered | 8 |
| `aid` swapped for another identity | 7 |
| `pub` swapped while `aid` kept | 7 |
| signature from a different key | 8 |
| signature truncated | 3 |
| one signature bit flipped | 8 |
| hex in uppercase | 3 |
| `alg` unknown | 2 |
| `v` bumped | 1 |
| `payload` removed | 5 |
| `ts` altered, still inside the window | 8 |
| `ts` removed | 4 |
| `nonce` altered | 8 |
| `nonce` removed | 3 |

The two rows worth noticing are the middle pair under the signature: altering
`ts` by one second stays inside the freshness window, so **only the signature
catches it**. That is the direct test of §3.3.

---

## 7. Conformance vector

Deterministic: same seed, same `ts`, same `nonce` ⇒ byte-identical envelope under
any conforming implementation. Ed25519 is deterministic (RFC 8032), so there is no
signature-nonce randomness to accommodate.

```
seed (private)          e722fed924c7f76b157faab674ea97bb7c3075f55ad7d3c6319418e22b86d611
public                  9c097c66ab4f82136ceddaef56854f740bf87da3eec42a249ba40bbb066f1e6a
AID = SHA-256(public)   3125ee20b2238281f70ca408192f82152647d365219184fa1fe22c08a42c035e
ts                      1760000000
nonce                   0011223344556677
payload                 {"intent":"verify","task_id":"selftest-0001"}

canonical signing input (hex)
  727474702d7365616c2d76310a7b22616964223a2233313235656532306232323338323831663730636134303831393266383231353236343764333635323139313834666131666532326330386134326330333565222c22616c67223a2265643235353139222c226e6f6e6365223a2230303131323233333434353536363737222c227061796c6f6164223a7b22696e74656e74223a22766572696679222c227461736b5f6964223a2273656c66746573742d30303031227d2c22707562223a2239633039376336366162346638323133366365646461656635363835346637343062663837646133656563343261323439626134306262623036366631653661222c227473223a313736303030303030307d

signature
  8d8e0d458b1defb6fd078343e7e46fc96cbaa05b6ead9e587d324e4c2358145790042f4a5001f3d902e7da670e2ea5700903363dd2825159a25dc262b25cb305
```

The reference self-test additionally replays the **RFC 8032 §7.1** vectors
(TEST 1 and TEST 2) so that a failure distinguishes *"our envelope logic is wrong"*
from *"the signature backend is not standard Ed25519"*.

---

## 8. What this does NOT provide

Stated here rather than left for a reviewer to discover.

| Not provided | Consequence / where it belongs |
|:---|:---|
| **Confidentiality** | Signing is not encryption. Payloads are readable. |
| **Revocation** | A compromised key stays valid to any verifier that has never met it. Requires a revocation mechanism — RFC-003 (Immune layer) territory. |
| **Key recovery / rotation** | No operator ⇒ no recovery. Rotation is unspecified. |
| **Transport origin binding** | The envelope proves *who signed*, not *which connection delivered it*. A relay can re-deliver someone else's valid envelope; freshness (§3.4) plus `nonce` is the only current defence. |
| **Nonce replay cache** | Within the 120-second window a replayed envelope still verifies unless the verifier keeps a short-lived nonce store. Implementations exchanging high-value actions **SHOULD** maintain one. |
| **Frame-level sealing** | The seal is an envelope around the frame, not bytes inside it (§0). A reader that only parses `0x00`–`0x7F` sees no seal at all. |

---

## 9. Relationship to RFC-003 (Immune layer)

The sovereign profile is the mechanism RFC-003 was implicitly waiting for:

* `AID = SHA-256(public key)` is a **self-certifying** identifier — the shape an
  attestation layer needs, and the reason a `rpki`-style layer can be built
  without an issuing authority.
* §8's revocation gap is precisely the piece RFC-003 must supply.
* The three-layer picture is unchanged: RFC-002 addresses, this document seals,
  RFC-003 attests and revokes.

---

## 10. Open items

1. ~~**`web+rttp:`**~~ — **CLOSED 2026-09-17, and not by adding a production.**
   The `web+` form was **removed from RFC-002 and RFC-009 entirely** and will
   never be submitted to IANA (`SPEC/IANA/README.md` §2). It is a constraint of
   one browser API, not a scheme of this protocol. RFC-002 §10.7 now records the
   registration status of `rttp` alone.
   ⚠️ **But the reference implementation and the published conformance vectors
   still accept `web+rttp://` and still assert it as valid.** The specification no
   longer defines it, so those vectors are no longer derivable from it — see
   `SPEC/IANA/README.md` §6.
2. **`nonce` cache** (§8) — specify a minimum behaviour before this profile is
   used for anything of value.
3. **Folding into RFC-002** — this document should become a numbered section of
   RFC-002 (or a companion RFC) rather than remaining a draft beside it.
4. **Rust parity** — the published `rttp` crate has no transport layer and no
   envelope. Python and Node are the only conforming implementations so far.
