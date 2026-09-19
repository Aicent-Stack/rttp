#!/usr/bin/env node
/**
 * RTTP v1.2.6 一致性校验 —— Node 侧**独立第二实现**
 *
 * 用法（在本目录下）：
 *     node conformance.mjs
 *
 * 为什么要有第二实现：
 *     规范的可信度不来自「作者说它对」，而来自「两个互不共享代码的实现，
 *     对同一份向量给出逐位相同的输出」。本文件不 import 任何 Python 产物，
 *     只用 vectors JSON 作为唯一输入 —— 与 SPEC/tools/conformance.py 交叉验证。
 *
 * 权威边界：语法 = RFC-002 §10.2；帧布局 = §4.1 + spec §2。
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const VECTORS = join(HERE, '..', 'conformance-vectors.json');

const MAGIC = 0x52545450;
const VERSION_ID = 130n;
const SIZE = 128;
const TOKEN = /^[a-z0-9-]+$/;
const HASH_INTENT = /^[0-9a-f]{8}$/;

const failures = [];
let checked = 0;

// ---------------------------------------------------------------------------
// 独立实现：URI 解析 + 规范化
// ---------------------------------------------------------------------------

function parseUri(uri) {
    if (typeof uri !== 'string' || uri === '') throw new Error('empty uri');
    if (uri !== uri.trim()) throw new Error('leading/trailing whitespace');

    let rest;
    if (uri.startsWith('web+rttp://')) rest = uri.slice(11);
    else if (uri.startsWith('rttp://')) rest = uri.slice(7);
    else throw new Error('scheme must be rttp:// or web+rttp://');

    for (const ch of ['@', '?', '#', '[', ']']) {
        if (uri.includes(ch)) throw new Error(`illegal char ${ch}`);
    }

    const slash = rest.indexOf('/');
    let authority, action = '';
    if (slash === -1) {
        authority = rest;
    } else {
        authority = rest.slice(0, slash);
        action = rest.slice(slash + 1);
        if (action.includes('/')) throw new Error('path must be one segment');
        if (action === '') throw new Error('trailing slash with empty action');
    }

    const parts = authority.split('.');
    if (parts.length !== 3) throw new Error('authority must be intent.pillar.root');
    const [intent, pillar, root] = parts;

    const isHash = HASH_INTENT.test(intent);
    if (!isHash && !TOKEN.test(intent)) throw new Error('bad intent');
    if (!TOKEN.test(pillar)) throw new Error('bad pillar');
    if (!TOKEN.test(root)) throw new Error('bad root');
    if (action !== '' && !TOKEN.test(action)) throw new Error('bad action');

    for (const [value, name] of [[intent, 'intent'], [pillar, 'pillar'], [root, 'root']]) {
        if (value.startsWith('-') || value.endsWith('-')) {
            throw new Error(`${name} must not begin/end with '-'`);
        }
    }
    if (action !== '' && (action.startsWith('-') || action.endsWith('-'))) {
        throw new Error("action must not begin/end with '-'");
    }

    const canonicalAuthority = `${intent}.${pillar}.${root}`;
    const shard = createHash('sha256')
        .update(canonicalAuthority, 'ascii').digest().subarray(0, 16);

    return { authority: canonicalAuthority, action, shardHex: shard.toString('hex') };
}

// ---------------------------------------------------------------------------
// 独立实现：128 字节帧构造
// ---------------------------------------------------------------------------

function buildFrame({ sequenceId, ttl, priority, shardHex, aidHex, timestampNs, action, uriAnchored }) {
    const buf = Buffer.alloc(SIZE);
    buf.writeUInt32BE(MAGIC, 0x00);
    buf.writeBigUInt64BE(0n, 0x04);                  // VERSION_ID u128 高半
    buf.writeBigUInt64BE(VERSION_ID, 0x0C);          // VERSION_ID = 130
    const seq = BigInt(sequenceId);
    buf.writeBigUInt64BE(seq >> 64n, 0x14);          // SEQUENCE_ID u128
    buf.writeBigUInt64BE(seq & 0xFFFFFFFFFFFFFFFFn, 0x1C);
    const ts = BigInt(timestampNs);
    buf.writeBigUInt64BE(ts >> 64n, 0x24);           // TIMESTAMP u128
    buf.writeBigUInt64BE(ts & 0xFFFFFFFFFFFFFFFFn, 0x2C);
    buf.writeUInt8(ttl & 0xFF, 0x34);                // TTL_PULSE
    buf.writeUInt8(priority & 0xFF, 0x35);           // PRIORITY
    Buffer.from(shardHex, 'hex').copy(buf, 0x36);    // ROUTE_SHARD u128
    Buffer.from(aidHex, 'hex').copy(buf, 0x46);      // AID_ORIGIN 256-bit
    buf[0x66] = 1;                                   // SPEC_REV
    buf[0x67] = uriAnchored ? 1 : 0;                 // FLAGS
    const actionBytes = Buffer.from(action, 'ascii');
    buf[0x68] = actionBytes.length;                  // ACTION_LEN
    actionBytes.copy(buf, 0x69);                     // ACTION (zero-padded)
    return buf;                                      // 0x79..0x80 RESERVED = 0
}

// ---------------------------------------------------------------------------
// 回放向量
// ---------------------------------------------------------------------------

const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));

for (const c of vectors.positive_uris) {
    checked += 1;
    try {
        const got = parseUri(c.uri);
        if (got.authority !== c.authority) failures.push(`${c.uri} :: authority ${got.authority} != ${c.authority}`);
        if (got.action !== c.action) failures.push(`${c.uri} :: action ${got.action} != ${c.action}`);
        if (got.shardHex !== c.route_shard_hex) failures.push(`${c.uri} :: shard ${got.shardHex} != ${c.route_shard_hex}`);
    } catch (err) {
        failures.push(`${c.uri} :: expected ACCEPT but threw: ${err.message}`);
    }
}

for (const c of vectors.negative_uris) {
    checked += 1;
    try {
        parseUri(c.uri);
        failures.push(`${c.uri} :: expected REJECT but parsed`);
    } catch { /* 预期 */ }
}

const aidHex = vectors.frame_vectors[0].aid_origin_hex;

for (const c of vectors.frame_vectors) {
    checked += 1;
    const { shardHex, action } = parseUri(c.uri);
    const frame = buildFrame({
        sequenceId: c.sequence_id,
        ttl: c.ttl,
        priority: c.priority,
        shardHex,
        aidHex,
        timestampNs: c.timestamp_ns,
        action,
        uriAnchored: true,
    });
    if (frame.toString('hex') !== c.header_hex) {
        failures.push(`${c.uri} :: frame bytes mismatch`);
    }
}

{
    checked += 1;
    const cv = vectors.compat_vector_spec_rev_0;
    const { shardHex, action } = parseUri(cv.uri);
    const frame = buildFrame({
        sequenceId: vectors.frame_vectors[0].sequence_id,
        ttl: vectors.frame_vectors[0].ttl,
        priority: vectors.frame_vectors[0].priority,
        shardHex,
        aidHex,
        timestampNs: vectors.frame_vectors[0].timestamp_ns,
        action,
        uriAnchored: true,
    });
    frame.fill(0, 0x66, SIZE);  // SPEC_REV=0：扩展块全零
    if (frame.toString('hex') !== cv.header_hex) {
        failures.push('compat vector :: frame bytes mismatch');
    }
}

if (failures.length) {
    console.log(`[FAIL] ${failures.length} of ${checked} checks failed (node)`);
    for (const item of failures) console.log('   -', item);
    process.exit(1);
}
console.log(`[PASS] all ${checked} checks passed (node, independent implementation)`);
