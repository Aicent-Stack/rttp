# rttp

**Reference implementation of RTTP (Resonant Time Transfer Protocol): the
128-byte `PulseHeader128` frame, `rttp://` intent addressing, and self-certifying
Ed25519 seals.**

[RFC-002 sec. 4.1](https://rttp.com/RFC-002/) - [sec. 10](https://rttp.com/RFC-002/) - sec. 11 - v1.2.6

---

## Verify it in one command -- no trust required

```console
$ pip install rttp
$ python -m rttp.selftest
rttp 1.2.8 self-test
python 3.14.2 on win32
...
[PASS] all 80 checks passed (3 skipped)     # default install: the Ed25519 checks are skipped

$ pip install rttp[ed25519]
$ python -m rttp.selftest
rttp 1.2.8 self-test
python 3.14.2 on win32
...
[PASS] all 83 checks passed                 # with the optional Ed25519 backend
```

That is the point of this package. A specification is worth exactly what an
independent implementation can reproduce from it -- so instead of asking you to
believe a table of numbers, this ships the vectors and replays them locally.
The 83 checks below are the full set, i.e. with the optional Ed25519 backend
installed; a default install runs 80 checks and skips 3.

* **38 conformance checks** -- `rttp://` parsing, fail-closed rejections, and the
  URI -> `ROUTE_SHARD` -> 128-byte frame chain, bit for bit.
* **2 RFC 8032 checks** -- the Ed25519 backend is shown to be *standard* Ed25519,
  not a lookalike, so a failure tells you which half broke.
* **38 envelope checks** -- 16 rule-layer checks that need no primitive, plus
  round-trip, self-certification, freshness and a 14-case tamper matrix where
  every alteration must be rejected.
* **5 zero-dependency checks** -- a static scan proving the core imports nothing
  outside the standard library.

Offline. No account. No network. `[PASS]` or it is not. Every vector file shipped here is listed in `vectors.manifest.json` with its byte count and SHA-256, produced by a generator rather than typed by hand - recompute the hash yourself if you prefer.

---

## Install

```console
pip install rttp              # core: zero dependencies, standard library only
pip install rttp[ed25519]     # + sovereign-profile seals (Ed25519)
```

Python 3.9+. No compiled extensions in the core.

The core deliberately has **no dependencies**. A protocol reference that cannot be
read without resolving a dependency tree is not much of a reference -- and an
air-gapped reviewer should be able to check the frames.

---

## What is in the box

| Module | What it does | Authority |
|:---|:---|:---|
| `rttp.pulse_header` | `PulseHeader128` codec -- build / parse / verify the 128-byte hardware-aligned header, including the v1.2.6 extension block at `0x66`-`0x7F` | RFC-002 sec. 4.1 + `SPEC/RTTP-FRAME-EXT-v1.2.6.md` |
| `rttp.rttp_uri` | Validate, canonicalise and derive `ROUTE_SHARD` from an `rttp` URI | RFC-002 sec. 10.2 / sec. 10.3 ABNF |
| `rttp.seal` | **Managed profile** -- symmetric HMAC-SHA256 over a pre-shared key table | -- |
| `rttp.seal_asym` | **Sovereign profile** -- Ed25519, self-certifying, no issuance and no registry | `SPEC/RTTP-SEAL-ENVELOPE-v1.2.6.md` (draft) |
| `rttp.aid` | Autonomous Identity derivation | RFC-001 |

Plus `rttp.vectors` -- the published conformance vectors, shipped inside the wheel
so the self-test works from an installed package with no repository checkout.

---

## Quickstart

### Address an intent

```python
from rttp import rttp_uri

parsed = rttp_uri.parse("rttp://brain.epoekie.aicent/verify")
parsed["authority"]          # 'brain.epoekie.aicent'
parsed["action"]             # 'verify'
parsed["route_shard"].hex()  # 16-byte routing hash, pure computation
```

Addressing is **DNS-free** (RFC-002 sec. 10.5): the routing hash is derived from the
authority by SHA-256, so no registry, resolver or network is involved. Malformed
input is rejected rather than normalised -- a case variant is not a spelling
difference, it is a different string.

### Build a frame from a URI

```python
from rttp import pulse_header, rttp_uri

parsed = rttp_uri.parse("rttp://brain.epoekie.aicent/verify")
raw = pulse_header.build_for_uri(
    sequence_id=1, ttl=255, priority=1,
    uri=parsed["canonical_uri"],
    aid_origin=bytes.fromhex("..."),   # originator AID, 32 bytes
)
len(raw)                          # 128
pulse_header.verify(raw)["action"]  # 'verify'
```

`build_for_uri` performs the mapping RFC-002 sec. 10.4 promises: the URI's authority
becomes `ROUTE_SHARD`, its path becomes `ACTION`. Readers that only understand
`0x00`-`0x65` keep working -- the extension block occupies bytes that were already
zero, and `VERSION_ID` stays 130.

### Seal with your own identity

```python
from rttp import seal_asym

keypair = seal_asym.generate_keypair()      # nothing is issued to you
print(keypair["aid_hex"])                   # = SHA-256(public key): your identity

envelope = seal_asym.seal({"intent": "verify", "task_id": "t-1"}, keypair)

ok, reason, aid = seal_asym.verify_envelope(envelope)
# ok=True, signer identity recovered from the packet itself
```

The verifier needs **only the envelope**. There is no key directory, no
credentials to obtain, and no operator who could refuse to issue them.

---

## Two profiles, and when each applies

| | **Managed** -- `seal` | **Sovereign** -- `seal_asym` |
|:---|:---|:---|
| Primitive | HMAC-SHA256 | Ed25519 |
| Key material | pre-shared table | self-generated |
| Identity | a role name | `AID = SHA-256(public key)` |
| Verifier needs | the same key table | only the envelope |
| A stranger can participate | no | **yes** |
| One leaked key | can forge any peer | forges one identity |

Inside a set of symmetric secrets there is no such thing as a stranger -- whoever
holds the shared key can mint anybody's seal. The managed profile is therefore for
a closed organism, where a fixed set of roles genuinely do trust each other.

A protocol that invites third parties needs the sovereign profile. That is not a
preference; it is the difference between a private system and a public one.

---

## Scope -- what this package is not

| | |
|:---|:---|
| OK **Framing** | Real, and specified. |
| OK **Addressing** | Real, and specified. |
| OK **Sealing** | Real, and specified (draft). |
| NO **Transport** | **Not here.** This package encodes, addresses and seals. It does not open sockets, and there is no `send()` -- a client and its transport belong to a separate package, so that the codec stays dependency-free and auditable. |
| NO **Routing service** | Not here. `ROUTE_SHARD` is computed locally; delivering a frame to that hash is an operator's job, not the codec's. |
| NO **Confidentiality** | Signing is not encryption. |

**The seal is an envelope around the frame, not bytes inside it.** A reader that
parses only the 128-byte header sees no seal at all -- which is why the two
concerns are specified separately.

Unknown revisions, algorithms and malformed input **fail closed** everywhere.
Nothing in this package is ever accepted because a check could not be performed.

---

## Conformance vectors

`rttp/vectors/rttp-conformance-v1.2.6.json` is generated, not hand-edited. Each
vector is deterministic: fixed sequence numbers, fixed timestamp, fixed AID -- so
two implementations either agree byte for byte or they do not.

The vector set is the intended deliverable for third-party certification: pass it
and you interoperate; fail it and you know exactly which byte is wrong, without
needing to trust the authors.

---

## Naming

| Ecosystem | Name | Status |
|:---|:---|:---|
| crates.io | `rttp` | held by this project |
| PyPI | `rttp` | **this package** -- `pip install rttp` |
| npm | **`@aicent/rttp`** | the unscoped `rttp` name on npm is held by an unrelated, unmaintained 2017 REST helper, and the `rttp` scope cannot be created at all -- a personal account already holds that name -- so the JavaScript side is published under this project's own organization. The package name itself is still just `rttp` |

---

## Specification status

* **`rttp` URI scheme** -- submitted to IANA under RFC 7595, ticket **#1459939**,
  Provisional (First Come, First Served), **under review**. It is **not yet
  registered** -- as of 2026-09-15 the IANA URI Schemes registry contains no
  `rttp` entry. Please describe it that way.
* **Internet-Draft (IETF)** -- the protocol is under IETF review as the
  Individual Submission Internet-Draft `draft-li-rttp-intent-addressing`
  (revision -01, posted 2026-09-20, informational):
  https://datatracker.ietf.org/doc/draft-li-rttp-intent-addressing/ .
  An Internet-Draft is a working document -- it is not an IETF standard and
  carries no IETF endorsement.
* **Frame layout** -- RFC-002 sec. 4.1, extended by `SPEC/RTTP-FRAME-EXT-v1.2.6.md`.
* **Seal envelope** -- `SPEC/RTTP-SEAL-ENVELOPE-v1.2.6.md`, a **draft**: the format
  is implemented and vector-tested, but it is not yet a numbered RFC-002 section.
* **Managed profile** -- implementation only; it predates the sovereign profile and
  has no standalone specification.

Where this package and a specification disagree, **the specification wins and the
package is wrong.** Please report it.

---

## License

Apache-2.0. See `LICENSE`.
