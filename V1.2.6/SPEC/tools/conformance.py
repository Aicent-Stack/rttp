#!/usr/bin/env python3
"""
RTTP v1.2.6 一致性工具 —— 生成 / 校验 conformance vectors

用法（在本目录下）：
    python conformance.py --generate      # 重新生成 ../conformance-vectors.json
    python conformance.py --check         # 用向量回放当前实现
    python conformance.py --show          # 打印关键向量（供写入 spec 正文）

为什么需要它：
    规范要能被**互不信任的独立实现**验证。本工具把「URI → ROUTE_SHARD → 128 字节帧」
    这条链路固化成确定性向量：任何语言的实现只要通过同一份向量，即可互操作。
    （Node 侧镜像实现可用同向量交叉验证，见 spec §6。）

权威边界：语法唯一权威 = RFC-002 §10.2 ABNF；帧布局唯一权威 = §4.1 + spec §2。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.normpath(os.path.join(HERE, "..", "..", "DEMO"))
VECTORS = os.path.normpath(os.path.join(HERE, "..", "conformance-vectors.json"))

sys.path.insert(0, DEMO)

import rttp_uri            # noqa: E402
import pulse_header        # noqa: E402
import aid as aid_mod      # noqa: E402

# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

# Forward: URIs. Taken from the RFC-002 §10.1 examples plus boundary shapes.
#
# Each entry is (uri, tolerance): `tolerance` is None for a conformance claim, or
# a note when the case is a **tolerance** - the reference implementation accepts
# it, but the specification defines no such form, so a conforming third-party
# implementation is not required to reproduce it.
POSITIVE_URIS = [
    ("rttp://f3b2a1c4.rttp.aicent/vessel", None),      # §10.1 hash form
    ("rttp://brain.epoekie.aicent/verify", None),      # §10.1 readable form
    ("rttp://f3b2a1c4.rttp.aicent", None),             # action 省略 = 默认操作
    ("rttp://00000000.rpki.aicent/attest", None),      # hash 全零（合法边界）
    # The scheme name a browser registers for this handler. §10.2 defines no such
    # form and §10.6 names no prefix: §10.6 requires a handler to reject anything
    # that is neither `rttp` nor the exact name it was registered under - which is
    # why a string of this shape, delivered by a browser, must be accepted.
    ("web+rttp://logic.zcmk.aicent/pulse",
     "tolerance - the specification defines no such form; accepted because it is "
     "the scheme name under which a handler is registered (RFC-002 §10.6)"),
    ("rttp://a-b-c.d-e.f-g/audit-v2", None),           # 连字符位置
]

# Negative: MUST be rejected (fail closed, §10.5).
NEGATIVE_URIS = [
    ("rttp://f3b2a1c4.rttp.aicent/VESSEL", "uppercase action - lowercase only (RFC-002 §10.3)"),
    ("rttp://F3B2A1C4.rttp.aicent/vessel", "uppercase intent - lowercase only (RFC-002 §10.3)"),
    ("RTTP://f3b2a1c4.rttp.aicent/vessel", "uppercase scheme prefix - canonical form is lowercase (RFC-002 §10.3)"),
    ("WEB+RTTP://f3b2a1c4.rttp.aicent/vessel", "uppercase scheme prefix on the handler form (RFC-002 §10.3)"),
    ("rttp://subject@rttp.aicent/vessel", "userinfo is not defined (RFC-002 §10.3)"),
    ("rttp://f3b2a1c4.rttp.aicent/vessel?x=1", "query is not defined (RFC-002 §10.3)"),
    ("rttp://f3b2a1c4.rttp.aicent/vessel#f", "fragment is not defined (RFC-002 §10.3)"),
    ("rttp://f3b2a1c4.rttp.aicent:443/vessel", "port is not defined (RFC-002 §10.3)"),
    ("rttp://f3b2a1c4.rttp.aicent/a/b", "second path segment - path is a single '/<action>'"),
    ("rttp://a.b", "authority has two segments, must be <intent>.<pillar>.<root>"),
    ("rttp://a.b.c.d/e", "authority has four segments, must be <intent>.<pillar>.<root>"),
    ("rttp://f3b2a1c4.rttp.aicent/", "trailing '/' with empty action - action is 1*(...)"),
    ("https://f3b2a1c4.rttp.aicent/vessel", "not an rttp scheme - there is no fallback (RFC-002 §10.5)"),
    ("rttp://f3b2a1c4.rttp.aicent/vessel ", "trailing whitespace"),
    ("rttp://-lead.rttp.aicent/vessel", "intent begins with '-'"),
]

# 帧向量：固定 seq / ts，使输出逐位可复现
FRAME_CASES = [
    ("rttp://f3b2a1c4.rttp.aicent/vessel", 255, 1, 1),
    ("rttp://brain.epoekie.aicent/verify", 255, 1, 2),
    ("rttp://f3b2a1c4.rttp.aicent", 128, 255, 3),      # action 省略
]

FIXED_TS_NS = 1_760_000_000_000_000_000


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

def _build_payload() -> dict:
    switch_aid = aid_mod.switch_aid()["aid"]

    positive = []
    for uri, tolerance in POSITIVE_URIS:
        p = rttp_uri.parse(uri)
        positive.append({
            "uri": uri,
            "canonical_uri": p["canonical_uri"],
            "authority": p["authority"],
            "intent": p["intent"],
            "intent_is_hash": p["intent_is_hash"],
            "pillar": p["pillar"],
            "root": p["root"],
            "action": p["action"],
            "action_omitted": p["action_omitted"],
            "route_shard_hex": p["route_shard"].hex(),
            # `tolerance: false` = a conformance claim. `tolerance: true` = the
            # reference implementation accepts it, but the specification defines no
            # such form; the note says why. Not a conformance claim.
            "tolerance": tolerance is not None,
            "note": tolerance,
        })

    negative = [{"uri": u, "reason": r} for u, r in NEGATIVE_URIS]

    frames = []
    for uri, ttl, prio, seq in FRAME_CASES:
        raw = pulse_header.build_for_uri(seq, ttl, prio, uri,
                                         aid_origin=switch_aid,
                                         timestamp_ns=FIXED_TS_NS)
        fields = pulse_header.verify(raw, expected_aid_origin=switch_aid)
        frames.append({
            "uri": uri,
            "sequence_id": seq,
            "ttl": ttl,
            "priority": prio,
            "timestamp_ns": FIXED_TS_NS,
            "aid_origin_hex": switch_aid.hex(),
            "action": fields["action"],
            "uri_anchored": fields["uri_anchored"],
            "spec_rev": fields["spec_rev"],
            "route_shard_hex": fields["route_shard"].hex(),
            "header_hex": raw.hex(),
        })

    # 兼容向量：SPEC_REV=0 —— 模拟 v1.2.6 之前的实现所发出的帧
    legacy_uri, legacy_ttl, legacy_prio, legacy_seq = FRAME_CASES[0]
    legacy = bytearray(pulse_header.build_for_uri(
        legacy_seq, legacy_ttl, legacy_prio, legacy_uri,
        aid_origin=switch_aid, timestamp_ns=FIXED_TS_NS))
    legacy[pulse_header.OFF_SPEC_REV:pulse_header.SIZE] = bytes(26)  # 清空扩展块
    legacy = bytes(legacy)
    legacy_fields = pulse_header.verify(legacy, expected_aid_origin=switch_aid)

    return {
        "spec": "RTTP-FRAME-EXT-v1.2.6",
        "applies_to": ["RFC-002 §4.1", "RFC-002 §10"],
        "generated_by": "SPEC/tools/conformance.py",
        "note": "Generated file - do not edit by hand. Change the cases in conformance.py instead.",
        "route_shard_rule": "ROUTE_SHARD = SHA-256(ASCII(canonical_authority))[0:16]",
        "frame_size": 128,
        "action_max_len": pulse_header.ACTION_MAX_LEN,
        "positive_uris": positive,
        "negative_uris": negative,
        "frame_vectors": frames,
        "compat_vector_spec_rev_0": {
            "uri": legacy_uri,
            "spec_rev": legacy_fields["spec_rev"],
            "action": legacy_fields["action"],
            "action_omitted": legacy_fields["action_omitted"],
            "uri_anchored": legacy_fields["uri_anchored"],
            "expected": "verify() MUST accept; action is treated as omitted (RFC-002 §10.4 default operation)",
            "header_hex": legacy.hex(),
        },
    }


def cmd_generate() -> int:
    payload = _build_payload()
    with open(VECTORS, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"[GEN] {VECTORS}")
    print(f"      positive={len(payload['positive_uris'])} "
          f"negative={len(payload['negative_uris'])} "
          f"frames={len(payload['frame_vectors'])}")
    return 0


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def cmd_check() -> int:
    if not os.path.exists(VECTORS):
        print(f"[ERR] vectors missing: {VECTORS} (run --generate first)")
        return 2
    with open(VECTORS, "r", encoding="utf-8") as fh:
        expected = json.load(fh)

    failures = []
    checked = 0

    for case in expected["positive_uris"]:
        checked += 1
        p = rttp_uri.parse(case["uri"])
        got = {
            "canonical_uri": p["canonical_uri"],
            "authority": p["authority"],
            "action": p["action"],
            "route_shard_hex": p["route_shard"].hex(),
        }
        for key, want in got.items():
            if case[key] != want:
                failures.append(f"{case['uri']} :: {key} {want!r} != {case[key]!r}")

    for case in expected["negative_uris"]:
        checked += 1
        try:
            rttp_uri.parse(case["uri"])
            failures.append(f"{case['uri']} :: expected REJECT but parsed")
        except rttp_uri.RttpUriError:
            pass

    switch_aid = bytes.fromhex(expected["frame_vectors"][0]["aid_origin_hex"])
    for case in expected["frame_vectors"]:
        checked += 1
        raw = pulse_header.build_for_uri(
            case["sequence_id"], case["ttl"], case["priority"], case["uri"],
            aid_origin=switch_aid, timestamp_ns=case["timestamp_ns"])
        if raw.hex() != case["header_hex"]:
            failures.append(f"{case['uri']} :: frame bytes mismatch")
            continue
        fields = pulse_header.verify(raw, expected_aid_origin=switch_aid)
        if fields["action"] != case["action"]:
            failures.append(f"{case['uri']} :: action readback mismatch")

    cv = expected["compat_vector_spec_rev_0"]
    checked += 1
    try:
        fields = pulse_header.verify(bytes.fromhex(cv["header_hex"]),
                                     expected_aid_origin=switch_aid)
        if fields["spec_rev"] != 0 or not fields["action_omitted"]:
            failures.append("compat vector :: SPEC_REV=0 semantics mismatch")
    except pulse_header.PulseHeaderError as exc:
        failures.append(f"compat vector :: expected ACCEPT but rejected: {exc}")

    if failures:
        print(f"[FAIL] {len(failures)} of {checked} checks failed")
        for item in failures:
            print("   -", item)
        return 1
    print(f"[PASS] all {checked} checks passed")
    return 0


def cmd_show() -> int:
    payload = _build_payload()
    print("=== URI -> ROUTE_SHARD ===")
    for c in payload["positive_uris"]:
        act = c["action"] or "(omitted)"
        print(f"{c['authority']:<28} action={act:<10} shard={c['route_shard_hex']}")
    print()
    print("=== Frame vectors (first 40 hex) ===")
    for c in payload["frame_vectors"]:
        print(f"seq={c['sequence_id']} action={c['action'] or '(omitted)':<10} "
              f"{c['header_hex'][:40]}...")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="RTTP v1.2.6 conformance")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--generate", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--show", action="store_true")
    args = ap.parse_args()
    if args.generate:
        return cmd_generate()
    if args.check:
        return cmd_check()
    return cmd_show()


if __name__ == "__main__":
    raise SystemExit(main())
