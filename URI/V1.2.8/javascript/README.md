# @aicent/rttp

**RTTP for JavaScript: `rttp://` intent addressing, `ROUTE_SHARD` derivation --
and the published conformance vectors that prove an implementation is right.**

[RFC-002 sec. 10](https://rttp.com/RFC-002/) - spec v1.2.6 - zero dependencies - no build step

---

## Verify it in one command -- no trust required

```console
$ npx @aicent/rttp
[PASS] all 35 checks passed (node, independent implementation)
```

That is the point of this package. A specification is worth exactly what an
independent implementation can reproduce from it, so instead of asking you to
believe a table of numbers, the vectors ship inside the package and replay
locally -- offline, no account, no network. `[PASS]` or it is not. Every vector file shipped here is listed in `vectors.manifest.json` with its byte count and SHA-256, produced by a generator rather than typed by hand - recompute the hash yourself if you prefer.

The JavaScript and Python sides **share no code**. They are separate
implementations of the same published vectors, and they agree byte for byte.

### The other half -- Python, on PyPI

```console
$ pip install rttp
$ python -m rttp.selftest
[PASS] all 80 checks passed (3 skipped)   # default install

$ pip install rttp[ed25519]
$ python -m rttp.selftest
[PASS] all 83 checks passed               # with the optional Ed25519 backend
```

Published as **`rttp`** -- the bare name, because PyPI has no scopes and the name
was free. That package ships a **byte-identical copy** of this same vector set and
replays it offline, exactly as this one does: two registries, two languages, one
specification.

---

## Install

```console
npm install @aicent/rttp
```

Node 18+. No dependencies, no build step, no transitive tree to audit: the
published `src/` is exactly what runs.

---

## Quickstart

```js
import { parse } from '@aicent/rttp';

const r = parse('rttp://brain.epoekie.aicent/verify');

r.authority       // 'brain.epoekie.aicent'
r.intent          // 'brain'
r.pillar          // 'epoekie'
r.root            // 'aicent'
r.action          // 'verify'
r.canonical_uri   // 'rttp://brain.epoekie.aicent/verify'
r.route_shard_hex // '459e543b73d86005b72ba77d5756e83c'  <- pure computation
```

The same three lines ship as a runnable file:

```console
$ node examples/quickstart.mjs
459e543b73d86005b72ba77d5756e83c
```

Its expected output is the shard printed above -- the value the published
conformance vectors pin for that address, so the example can be **checked**
rather than believed. It is also the value the Python implementation derives,
from code that shares nothing with this one.

Addressing is **DNS-free** (RFC-002 sec. 10.5): the routing hash is derived from the
authority by SHA-256, so no registry, resolver or network is involved. A URI
either yields a shard or throws -- there is no fallback, and no `rttps`.

---

## The one rule that surprises people

**Malformed input is rejected, not normalised.** `rttp://.../VESSEL` and
`rttp://F3B2A1C4..../vessel` both throw, because the canonical form is lowercase
US-ASCII (RFC-002 sec. 10.3) and a case variant is not a spelling difference -- it is
a *different string*. Admitting both would give one address two spellings, which
is the ambiguity sec. 10.3 exists to remove.

Nothing here is ever accepted because a check could not be performed: this
package fails closed everywhere.

---

## The browser's registration prefix -- accepted, never advertised

A browser lets a page register a protocol handler only for a scheme it already
knows, or for one carrying the browser's own **reserved registration prefix**. So
the string a web page hands to a handler is not the bare address.

This package **accepts** that form, because refusing a string a browser is about
to deliver would break the handler path -- but it is a **tolerance, and the
specification defines no such form**. The canonical `rttp://` address is what
this package reports, and the only form it ever emits: same authority, same path,
same **route shard** either way.

```js
parse('rttp://logic.zcmk.aicent/pulse').canonical_uri
// 'rttp://logic.zcmk.aicent/pulse'   <- always the canonical form
```

The `scheme` field tells you which form arrived; everything else is identical.

---

## API -- main entry

| Export | What it does |
|:---|:---|
| `parse(uri)` | Validate, canonicalise, derive. Throws `RttpUriError`. |
| `parseAndDerive(uri)` | Identical to `parse`; the specification's own wording. |
| `deriveRouteShard(authority)` | `Uint8Array(16)` = `SHA-256(ASCII(authority))[0:16]`. |
| `deriveRouteShardHex(authority)` | The same, as 32 lowercase hex characters. |
| `isValidAction(value)` | sec. 10.2 `action` form test. The verb set is **open**. |
| `RttpUriError` | The only error type thrown. |
| `SCHEME`, `BROWSER_HANDLER_SCHEME`, `ROUTE_SHARD_BYTES`, `HASH_INTENT_LEN`, `ACTION_MAX_LEN`, `SPEC_RELEASE` | Constants. |

### Returned fields

Field names are `snake_case` **on purpose**: the published conformance vectors use
those names, so this output and the Python package's output compare directly --
field for field, byte for byte.

| Field | Meaning |
|:---|:---|
| `scheme` | Which form arrived: `rttp` for the canonical address |
| `intent` | 8 lowercase hex digits (32-bit routing hash) or a readable organ token |
| `intent_is_hash` / `intent_hash32` | Whether it is a hash-intent, and its value |
| `pillar`, `root` | The other two authority labels |
| `action` | Empty string when omitted (RFC-002 sec. 10.4 default operation) |
| `action_omitted` | The same fact as a boolean |
| `authority` | `<intent>.<pillar>.<root>`, canonical |
| `canonical_uri` | Always begins `rttp://` |
| `route_shard` / `route_shard_hex` | The 16-byte routing hash, two ways |

---

## The conformance vectors -- `@aicent/rttp/conformance`

```js
import { loadVectors, runConformance } from '@aicent/rttp/conformance';

const { checked, failures, passed } = runConformance(loadVectors());
```

Or from the command line:

```console
npx @aicent/rttp                      # replay the shipped vectors
npx @aicent/rttp --vectors ./new.json # replay a different vector set
npx @aicent/rttp --json               # machine-readable output
```

In CI:

```yaml
- run: npx @aicent/rttp
```

| Export | What it does |
|:---|:---|
| `runConformance(vectors)` | Replay a vector set -> `{ checked, failures, passed }` |
| `loadVectors(path?)` | Parse a vector set; defaults to the shipped one |
| `DEFAULT_VECTORS_PATH` | Absolute path of the shipped `vectors.json` |
| `parseUri(uri)` | The independent RFC-002 sec. 10.2 implementation -> `{ authority, action, shardHex }` |
| `buildFrame(fields)` | The independent 128-byte frame builder -> `Buffer` |
| `ACTION_MAX_LEN` | `16` -- the ACTION field's capacity |

`vectors.json` is plain JSON and ships inside the package, also reachable as the
subpath export `@aicent/rttp/vectors.json`. Any language can read it; that is
what it is for.

### What the 35 checks are

| Group | Count | What it proves |
|:---|:---|---:|
| `positive_uris` | 6 | Accept, canonicalise and derive -- including a hash-intent and an omitted action. **Five are conformance claims; one is a `tolerance`** -- the browser-registration prefix -- and the vector set labels it as such |
| `negative_uris` | 15 | **Reject** -- uppercase, userinfo, query, fragment, port, multi-segment path, wrong authority shape, trailing slash, foreign scheme, surrounding whitespace |
| `frame_vectors` | 3 | URI -> `ROUTE_SHARD` -> the 128-byte `PulseHeader128`, bit for bit |
| `compat_vector_spec_rev_0` | 1 | A frame written before the v1.2.6 extension block still verifies |
| `negative_frames` | 9 | **Reject** -- fail-closed frames: ACTION length/padding/embedded NUL/grammar, unknown SPEC_REV, SPEC_REV=0 with a non-zero extension, non-zero RESERVED, unknown FLAGS bit |
| `positive_frames` | 1 | Accept -- SPEC_REV=1 with ACTION_LEN=0 is valid and equivalent to an omitted action |

Each vector is deterministic: fixed sequence numbers, fixed timestamp, fixed AID.
Two implementations either agree byte for byte or they do not.

### Why the checker lives in this package, and why that is still honest

`src/conformance.mjs` is written from RFC-002 sec. 10 alone and **must never import
`src/rttp-uri.mjs`**. A conformance suite that reuses the code under test only
proves the code equals itself. The two files share no code, so the rule is
checkable by reading them.

They ship together for the same reason the Python wheel ships its self-test: so
that a stranger can verify an installed package **offline, with no repository
checkout**. A verification step that requires cloning an unrelated repository is
not a verification step.

`buildFrame` **refuses** an action longer than the field can hold rather than
truncating it: a silently shortened verb would be a routing decision made by the
codec, and the codec does not get to make that decision. (sec. 10.2 sets no length
limit on `action` -- a *parser* must accept a long one; a frame builder cannot.)

The vectors are **generated, not written**. `generated_by` in the JSON names the
generator, and the file says so itself: change the cases in the generator, not the
JSON. Hand-editing a conformance vector is how a specification quietly starts
agreeing with its own bugs.

---

## Scope -- what this package is not

| | |
|:---|:---|
| OK **Validation** | Real, and specified (RFC-002 sec. 10.2 / sec. 10.3). |
| OK **Canonicalisation** | Real, and specified. |
| OK **ROUTE_SHARD derivation** | Real, and specified. |
| OK **Conformance vectors + independent replay** | Published and generated. |
| NO **Framing, as a library API** | `buildFrame` is exported from `./conformance`, where it exists to replay frame vectors -- it is not offered as a general codec. |
| NO **Transport** | Not here. There is no `send()`. |
| NO **Routing service** | Not here. The shard is computed locally; delivering a frame to that hash is an operator's job. |
| NO **Sealing (sec. 11)** | Separate artifacts. |
| NO **Browsers** | Node only -- it uses `node:crypto`. The derivation is trivial to reproduce elsewhere, and the vectors let you prove you did. |

---

## Naming

| Ecosystem | Name | Status |
|:---|:---|:---|
| crates.io | `rttp` | held by this project |
| PyPI | `rttp` | **published** -- the Python reference implementation; `pip install rttp` |
| npm | **`@aicent/rttp`** | the bare `rttp` name on npm is held by an unrelated, unmaintained 2017 REST helper, and the `rttp` scope cannot be created at all -- a personal account already holds that name. This package is therefore published under the organization this project controls; the package name itself is still just `rttp`. |

---

## Specification status

* **`rttp` URI scheme** -- submitted to IANA under RFC 7595, ticket **#1459939**,
  Provisional, **under review**. It is **not yet registered** -- as of 2026-09-20
  the IANA "URI Schemes" registry contains no `rttp` entry. Please describe it
  that way.
* **Internet-Draft (IETF)** -- the protocol is under IETF review as the
  Individual Submission Internet-Draft `draft-li-rttp-intent-addressing`
  (revision -01, posted 2026-09-20, informational):
  https://datatracker.ietf.org/doc/draft-li-rttp-intent-addressing/ .
  An Internet-Draft is a working document -- it is not an IETF standard and
  carries no IETF endorsement.
* **Frame layout** -- RFC-002 sec. 4.1, extended by `SPEC/RTTP-FRAME-EXT-v1.2.6.md`.

Where this package and the specification disagree, **the specification wins and
this package is wrong.** Please report it.

---

## License

Apache-2.0. See `LICENSE`.
