#!/usr/bin/env python3
"""
rttp self-test -- replay the published conformance vectors against *this* build.

Why a package ships a self-test
-------------------------------
A specification is only worth what an independent implementation can reproduce
from it. This module is the smallest possible statement of that: install the
package, run one command, and either the published vectors reproduce bit for bit
or they do not. No trust in the author is required -- which is the whole point.

    $ python -m rttp.selftest

Sections
--------
1. **Conformance** -- the published vectors: `rttp://` parsing, fail-closed
   rejections, URI -> ROUTE_SHARD -> 128-byte frame, and the SPEC_REV=0
   compatibility vector.
2. **Envelope rules** -- version, algorithm, hex shape, field types, freshness and
   self-certification. None of that needs a cryptographic primitive, so a
   zero-dependency install runs every one of these checks.
3. **Envelope flow** -- round-trip, determinism, origin claims and the tamper
   matrix. Run with the installed Ed25519 backend when there is one; otherwise
   with an injected test signer, and the output says which. The test signer is
   not Ed25519: it is there to show which fields the signed bytes cover.
4. **Ed25519 backend** -- RFC 8032 sec. 7.1 test vectors, so the signature backend
   is shown to be *standard* Ed25519 rather than a lookalike. These two are the
   only checks a zero-dependency install skips.
5. **Zero dependencies** -- a static import scan, plus a runtime guard that counts
   any attempt to open an outbound connection while the self-test runs.

Exit status is 0 only if every check passed. `--vectors` prints the
deterministic envelope vector (for pasting into the spec); `--quiet` prints the
summary line only.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import socket
import sys

from . import aid as aid_mod
from . import pulse_header, rttp_uri

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS_FILE = os.path.join(HERE, "vectors", "rttp-conformance-v1.2.6.json")

# RFC 8032 sec. 7.1 -- TEST 1 (empty message) and TEST 2 (one-byte message 0x72).
# Reproduced here so a failure points at the signature backend, not at our code.
RFC8032_VECTORS = [
    {
        "name": "TEST 1 (empty message)",
        "seed": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "pub": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "msg": "",
        "sig": "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e0652249015"
               "55fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    },
    {
        "name": "TEST 2 (one-byte message 0x72)",
        "seed": "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "pub": "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "msg": "72",
        "sig": "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
               "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    },
]

#: Fixed inputs for the reproducible envelope vector. Derived by hashing
#: constants so the values are auditable rather than magic. `ts` is frozen, so
#: every verification of this vector has to be told the same instant.
ENVELOPE_SEED = aid_mod.derive_from_entropy(b"rttp-selftest-envelope-seed-1")["aid"]
ENVELOPE_PAYLOAD = {"intent": "verify", "task_id": "selftest-0001"}
ENVELOPE_TS = 1760000000
ENVELOPE_NONCE = "0011223344556677"


class _NetworkGuard:
    """Count outbound connection attempts made while this run is in progress.

    A static import scan shows that nothing was *imported*; this shows that
    nothing was *used*. Replacing socket.socket is enough to cover every
    higher-level client, because they all end up constructing one.
    """

    def __init__(self):
        self.calls = 0
        self._real = socket.socket
        guard = self

        class _Blocked(guard._real):
            def connect(self, *args, **kwargs):
                guard.calls += 1
                raise AssertionError("outbound network access attempted")

            def connect_ex(self, *args, **kwargs):
                guard.calls += 1
                raise AssertionError("outbound network access attempted")

        self._blocked = _Blocked

    def install(self):
        socket.socket = self._blocked

    def restore(self):
        socket.socket = self._real


class TestSignerBackend:
    """Hash-based stand-in for a signature backend. NOT Ed25519.

    It exists so the envelope flow can be exercised at all in a zero-dependency
    install, and so the tamper matrix keeps its meaning there: if the signed
    input did not cover `payload`, `ts`, `nonce`, `aid` or `pub`, tampering with
    those fields would stop being detected.

    Forgery with this signer is trivial, which is acceptable because it is only
    ever used by this self-test - never by `seal_asym` on a real envelope. The
    real primitive is proven by the RFC 8032 vectors in section 4.
    """

    name = "test-hash-signer (NOT Ed25519)"

    def available(self) -> bool:
        return True

    def from_seed(self, seed: bytes):
        return bytes(seed)

    def generate(self):
        return bytes(32)

    def private_bytes(self, private_key) -> bytes:
        return bytes(private_key)

    def public_bytes(self, private_key) -> bytes:
        return bytes(private_key)

    def sign(self, private_key, message: bytes) -> bytes:
        digest = hashlib.sha256(b"rttp-selftest-signer"
                                + bytes(private_key) + message).digest()
        return digest + digest

    def verify(self, public_key: bytes, signature: bytes, message: bytes) -> bool:
        return signature == self.sign(public_key, message)


def _select_backend():
    """Ed25519 when it is installed, otherwise the injected test signer."""
    from . import seal_asym

    if seal_asym.HAVE_ED25519:
        return seal_asym.NATIVE_BACKEND, "Ed25519 (cryptography)"
    return TestSignerBackend(), "injected test signer -- NOT Ed25519"


def _rule_layer_envelope():
    """A well-formed envelope for the rule layer, built with no primitive."""
    from . import seal_asym

    signer = TestSignerBackend()
    keypair = seal_asym.generate_keypair(ENVELOPE_SEED, backend=signer)
    envelope = seal_asym.seal(ENVELOPE_PAYLOAD, keypair, ts=ENVELOPE_TS,
                              nonce=ENVELOPE_NONCE)
    return seal_asym, keypair, envelope


class Runner:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.passed = 0
        self.failed = []
        self.skipped = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed += 1
        else:
            self.failed.append((name, detail))
        if not self.quiet:
            mark = "ok  " if ok else "FAIL"
            line = f"  [{mark}] {name}"
            if detail and not ok:
                line += f"\n         {detail}"
            print(line)
        return ok

    def skip(self, name: str, reason: str) -> None:
        self.skipped.append((name, reason))
        if not self.quiet:
            print(f"  [skip] {name} -- {reason}")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def run_conformance(r: Runner) -> None:
    if not os.path.exists(VECTORS_FILE):
        r.check("vectors file present", False, f"missing: {VECTORS_FILE}")
        return
    with open(VECTORS_FILE, "r", encoding="utf-8") as fh:
        expected = json.load(fh)

    if not r.quiet:
        print(f"\n[1] Conformance -- {os.path.basename(VECTORS_FILE)}")

    for case in expected["positive_uris"]:
        try:
            parsed = rttp_uri.parse(case["uri"])
        except rttp_uri.RttpUriError as exc:
            r.check(f"parse {case['uri']}", False, str(exc))
            continue
        got = {
            "canonical_uri": parsed["canonical_uri"],
            "authority": parsed["authority"],
            "intent": parsed["intent"],
            "intent_is_hash": parsed["intent_is_hash"],
            "pillar": parsed["pillar"],
            "root": parsed["root"],
            "action": parsed["action"],
            "action_omitted": parsed["action_omitted"],
            "route_shard_hex": parsed["route_shard"].hex(),
        }
        wrong = {k: (v, case[k]) for k, v in got.items() if case[k] != v}
        r.check(f"parse {case['authority']}"
                + (f"/{case['action']}" if case["action"] else ""),
                not wrong,
                f"mismatched fields: {wrong}")

    for case in expected["negative_uris"]:
        try:
            rttp_uri.parse(case["uri"])
        except rttp_uri.RttpUriError:
            r.check(f"reject {case['reason']}", True)
        else:
            r.check(f"reject {case['reason']}", False,
                    f"{case['uri']!r} parsed but must be rejected")

    switch_aid = bytes.fromhex(expected["frame_vectors"][0]["aid_origin_hex"])
    for case in expected["frame_vectors"]:
        label = f"frame seq={case['sequence_id']} {case['uri']}"
        try:
            raw = pulse_header.build_for_uri(
                case["sequence_id"], case["ttl"], case["priority"], case["uri"],
                aid_origin=switch_aid, timestamp_ns=case["timestamp_ns"])
        except Exception as exc:  # noqa: BLE001 - report, do not abort the run
            r.check(label, False, f"build raised {type(exc).__name__}: {exc}")
            continue
        if raw.hex() != case["header_hex"]:
            r.check(label, False, "128-byte frame differs from the published vector")
            continue
        fields = pulse_header.verify(raw, expected_aid_origin=switch_aid)
        r.check(label, fields["action"] == case["action"],
                f"action {fields['action']!r} != {case['action']!r}")

    for case in expected.get("negative_frames", []):
        label = f"frame {case['rule']} reject: {case['label']}"
        try:
            pulse_header.verify(bytes.fromhex(case["header_hex"]),
                                expected_aid_origin=switch_aid)
        except pulse_header.PulseHeaderError:
            r.check(label, True)
        else:
            r.check(label, False,
                    "accepted a frame the extension rules MUST reject")

    for case in expected.get("positive_frames", []):
        label = f"frame {case['rule']} accept: {case['label']}"
        try:
            fields = pulse_header.verify(bytes.fromhex(case["header_hex"]),
                                         expected_aid_origin=switch_aid)
            r.check(label, fields["action"] == case["action"],
                    f"action {fields['action']!r} != {case['action']!r}")
        except pulse_header.PulseHeaderError as exc:
            r.check(label, False, f"rejected a valid frame: {exc}")

    compat = expected["compat_vector_spec_rev_0"]
    try:
        fields = pulse_header.verify(bytes.fromhex(compat["header_hex"]),
                                     expected_aid_origin=switch_aid)
        r.check("compat vector SPEC_REV=0 accepted",
                fields["spec_rev"] == 0 and fields["action_omitted"],
                "a pre-v1.2.6 frame must be accepted with action treated as omitted")
    except pulse_header.PulseHeaderError as exc:
        r.check("compat vector SPEC_REV=0 accepted", False,
                f"rejected an old frame: {exc}")
    env = expected.get("envelope_vector")
    if env:
        from . import seal_asym

        raw = seal_asym.signing_input(env["alg"], env["aid"], env["pub"], env["ts"],
                                      env["nonce"], env["payload"])
        r.check("envelope vector: canonical signing input reproduces byte for byte",
                raw.hex() == env["signing_input_hex"],
                "the canonical encoding of the sec. 7 vector changed")
        r.check("envelope vector: aid == SHA-256(pub)",
                seal_asym.aid_from_public_key(bytes.fromhex(env["pub"])).hex() == env["aid"],
                "the published AID is not derivable from the published public key")
        if seal_asym.HAVE_ED25519:
            r.check("envelope vector: published signature verifies",
                    seal_asym.NATIVE_BACKEND.verify(bytes.fromhex(env["pub"]),
                                                    bytes.fromhex(env["sig"]), raw),
                    "the sec. 7 signature does not verify over the canonical input")
        else:
            r.skip("envelope vector: published signature verifies",
                   "Ed25519 backend not installed")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def run_ed25519(r: Runner) -> None:
    from . import seal_asym

    if not r.quiet:
        print("\n[4] Ed25519 backend -- RFC 8032 sec. 7.1"
              " (the only checks a zero-dependency install skips)")

    if not seal_asym.HAVE_ED25519:
        for vec in RFC8032_VECTORS:
            r.skip(vec["name"], "cryptography not installed")
        return

    for vec in RFC8032_VECTORS:
        keypair = seal_asym.generate_keypair(bytes.fromhex(vec["seed"]))
        if keypair["public_hex"] != vec["pub"]:
            r.check(f"{vec['name']} public key", False,
                    f"{keypair['public_hex']} != {vec['pub']}")
            continue
        signature = seal_asym.NATIVE_BACKEND.sign(
            keypair["private_key"], bytes.fromhex(vec["msg"])).hex()
        r.check(f"{vec['name']} signature", signature == vec["sig"],
                f"{signature} != {vec['sig']}")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _fixed_keypair_and_envelope(backend=None):
    """The fixed key pair and envelope -- one path for vector export and self-test."""
    from . import seal_asym

    keypair = seal_asym.generate_keypair(ENVELOPE_SEED, backend=backend)
    envelope = seal_asym.seal(ENVELOPE_PAYLOAD, keypair,
                              ts=ENVELOPE_TS, nonce=ENVELOPE_NONCE)
    return seal_asym, keypair, envelope


def build_envelope_vector() -> dict:
    """Build the envelope vector deterministically (for printing / the spec)."""
    seal_asym, keypair, envelope = _fixed_keypair_and_envelope()
    return {
        "seed_hex": keypair["seed_hex"],
        "public_hex": keypair["public_hex"],
        "aid_hex": keypair["aid_hex"],
        "envelope": envelope,
        "canonical_input_hex": seal_asym.signing_input(
            envelope["alg"], envelope["aid"], envelope["pub"],
            envelope["ts"], envelope["nonce"], envelope["payload"]).hex(),
    }



def run_envelope_rules(r: Runner) -> None:
    """Envelope rules that need no cryptographic primitive.

    Version, algorithm, hex shape, field types, freshness and self-certification
    are all decided without Ed25519, so a zero-dependency install runs every
    check in this group. Only the signature itself is left to the flow group.
    """
    seal_asym, keypair, envelope = _rule_layer_envelope()

    if not r.quiet:
        print("\n[2] Envelope rules -- no primitive required")

    def mut(**changes) -> dict:
        out = json.loads(json.dumps(envelope))
        out.update(changes)
        return out

    def drop(field: str) -> dict:
        return {k: v for k, v in envelope.items() if k != field}

    r.check("AID = SHA-256(public key)",
            seal_asym.aid_from_public_key(keypair["public_key"]) == keypair["aid"],
            "identity is not derivable from the public key")
    r.check("well-formed envelope passes the rule layer",
            seal_asym.check_envelope(envelope, now=ENVELOPE_TS)[0],
            "a well-formed envelope was rejected by the rule layer")

    cases = [
        ("envelope version bumped", mut(v=2)),
        ("unknown algorithm", mut(alg="none")),
        ("uppercase hex in pub", mut(pub=envelope["pub"].upper())),
        ("AID is not 32 bytes", mut(aid=envelope["aid"][:-2])),
        ("signature is not 64 bytes", mut(sig=envelope["sig"][:-2])),
        ("nonce is not 8 bytes", mut(nonce=envelope["nonce"] + "00")),
        ("nonce removed", drop("nonce")),
        ("ts is not an integer", mut(ts=str(ENVELOPE_TS))),
        ("ts removed", drop("ts")),
        ("payload is not an object", mut(payload="not-an-object")),
        ("payload removed", drop("payload")),
        ("AID does not match the public key", mut(aid="00" * 32)),
        ("public key swapped, AID kept", mut(pub="11" * 32)),
        ("envelope outside the freshness window", mut(ts=ENVELOPE_TS + 3600)),
    ]
    for label, tampered in cases:
        ok, reason = seal_asym.check_envelope(tampered, now=ENVELOPE_TS)
        r.check(f"rule reject: {label}", not ok,
                f"the rule layer accepted it ({reason!r})")


def run_envelope(r: Runner) -> None:
    from . import seal_asym

    backend, label = _select_backend()

    if not r.quiet:
        print(f"\n[3] Envelope flow -- {label}")

    seal_asym, keypair, envelope = _fixed_keypair_and_envelope(backend)

    r.check("AID = SHA-256(public key)",
            seal_asym.aid_from_public_key(keypair["public_key"]) == keypair["aid"],
            "identity is not derivable from the public key")

    r.check("unseal returns the original payload",
            seal_asym.unseal(envelope, now=ENVELOPE_TS,
                             backend=backend) == ENVELOPE_PAYLOAD,
            "payload changed across seal/unseal")

    r.check("sealing is deterministic",
            seal_asym.seal(ENVELOPE_PAYLOAD, keypair,
                           ts=ENVELOPE_TS, nonce=ENVELOPE_NONCE) == envelope,
            "Ed25519 + canonical JSON must produce byte-identical output")

    ok, reason, _ = seal_asym.verify_envelope(envelope, now=ENVELOPE_TS,
                                              backend=backend)
    r.check("fresh envelope accepted", ok, reason or "")
    ok, _, _ = seal_asym.verify_envelope(envelope, now=ENVELOPE_TS + 3600,
                                         backend=backend)
    r.check("reject: envelope outside the freshness window", not ok,
            "a captured envelope must not still verify an hour later")
    ok, _, _ = seal_asym.verify_envelope(envelope, now=ENVELOPE_TS,
                                         check_freshness=False,
                                         backend=backend)
    r.check("archival mode still verifies (check_freshness=False)", ok,
            "auditing a stored envelope must stay possible")

    ok, _ = seal_asym.verify_claims(envelope, expected_aid_hex=keypair["aid_hex"],
                                    now=ENVELOPE_TS, backend=backend)
    r.check("verify_claims accepts the true origin", ok)
    other = seal_asym.generate_keypair(bytes(32), backend=backend)
    ok, reason = seal_asym.verify_claims(envelope, expected_aid_hex=other["aid_hex"],
                                         now=ENVELOPE_TS, backend=backend)
    r.check("verify_claims rejects a different origin", not ok,
            f"expected rejection, got ok (reason={reason!r})")

    def mutated(**changes) -> dict:
        out = json.loads(json.dumps(envelope))
        out.update(changes)
        return out

    def mutated_payload(**changes) -> dict:
        out = json.loads(json.dumps(envelope))
        out["payload"].update(changes)
        return out

    def without(field: str) -> dict:
        return {k: v for k, v in envelope.items() if k != field}

    tamper_cases = [
        ("payload altered", mutated_payload(task_id="selftest-0002")),
        ("AID swapped for another identity", mutated(aid=other["aid_hex"])),
        ("public key swapped, AID kept", mutated(pub=other["public_hex"])),
        ("signature from another key", mutated(sig=seal_asym.seal(
            ENVELOPE_PAYLOAD, other, ts=ENVELOPE_TS,
            nonce=ENVELOPE_NONCE)["sig"])),
        ("signature truncated", mutated(sig=envelope["sig"][:-2])),
        ("signature bit flipped",
         mutated(sig=("%064x" % (int(envelope["sig"], 16) ^ 1)))),
        ("hex in uppercase", mutated(pub=envelope["pub"].upper())),
        ("unknown algorithm", mutated(alg="none")),
        ("envelope version bumped", mutated(v=2)),
        ("payload removed", without("payload")),
        ("timestamp altered (inside the skew window)", mutated(ts=ENVELOPE_TS + 1)),
        ("timestamp removed", without("ts")),
        ("nonce altered", mutated(nonce="00" * 8)),
        ("nonce removed", without("nonce")),
    ]
    for label, tampered in tamper_cases:
        ok, reason, _ = seal_asym.verify_envelope(tampered, now=ENVELOPE_TS,
                                                  backend=backend)
        r.check(f"reject: {label}", not ok,
                f"accepted a tampered envelope ({reason!r})")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

CORE_MODULES = ("pulse_header", "rttp_uri", "seal", "aid")


def _imported_top_level(path: str) -> set:
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def run_zero_dependency(r: Runner, guard: "_NetworkGuard" = None) -> None:
    if not r.quiet:
        print("\n[5] Zero dependencies -- static scan + runtime guard")

    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is None:
        r.skip("static import scan", "sys.stdlib_module_names requires Python 3.10+")
        if guard is not None:
            r.check("no outbound connection attempted while this run was in progress",
                    guard.calls == 0,
                    f"{guard.calls} connection attempt(s) were made")
        return

    # Sibling modules are not external dependencies. `pulse_header` carries a
    # flat-layout fallback (`import rttp_uri`) so the very same file also works
    # as a bare script inside DEMO/; the package layout uses the relative import.
    siblings = {os.path.splitext(f)[0]
                for f in os.listdir(HERE) if f.endswith(".py")}

    for name in CORE_MODULES:
        path = os.path.join(HERE, f"{name}.py")
        external = sorted(_imported_top_level(path) - set(stdlib) - siblings - {""})
        r.check(f"{name}.py imports only the standard library",
                not external,
                f"third-party imports found: {external}")

    if guard is not None:
        r.check("no outbound connection attempted while this run was in progress",
                guard.calls == 0,
                f"{guard.calls} connection attempt(s) were made")


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rttp.selftest",
        description="Replay the published RTTP conformance vectors against this build.")
    parser.add_argument("--quiet", action="store_true",
                        help="print the summary line only")
    parser.add_argument("--vectors", action="store_true",
                        help="print the deterministic envelope vector and exit")
    args = parser.parse_args(argv)

    from . import __version__

    if args.vectors:
        try:
            print(json.dumps(build_envelope_vector(), indent=2, sort_keys=False))
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] cannot build envelope vector: {exc}", file=sys.stderr)
            return 2
        return 0

    if not args.quiet:
        print(f"rttp {__version__} self-test")
        print(f"python {sys.version.split()[0]} on {sys.platform}")

    guard = _NetworkGuard()
    guard.install()
    try:
        r = Runner(quiet=args.quiet)
        run_conformance(r)
        run_envelope_rules(r)
        run_envelope(r)
        run_ed25519(r)
        run_zero_dependency(r, guard)
    finally:
        guard.restore()

    total = r.passed + len(r.failed)
    print()
    if r.failed:
        print(f"[FAIL] {len(r.failed)} of {total} checks failed")
        for name, detail in r.failed:
            print(f"   - {name}" + (f"\n     {detail}" if detail else ""))
        return 1
    suffix = f" ({len(r.skipped)} skipped)" if r.skipped else ""
    print(f"[PASS] all {r.passed} checks passed{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
