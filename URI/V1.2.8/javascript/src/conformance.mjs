/**
 * @aicent/rttp/conformance - the RTTP conformance vectors, and their replay.
 *
 * Why this package exists
 * -----------------------
 * A specification is worth exactly what an independent implementation can
 * reproduce from it. Two implementations that share no code, given the same
 * vectors, must produce bit-identical output; one implementation agreeing with
 * itself proves nothing.
 *
 * This module is therefore an **independent second implementation** of the same
 * vectors as `SPEC/tools/conformance.py` on the Python side. It deliberately
 * imports nothing from `src/rttp-uri.mjs` and must not: a conformance suite that
 * reuses the code it is checking only proves that the code equals itself.
 *
 * Authority boundary: URI syntax = RFC-002 sec. 10.2; frame layout = sec. 4.1 as
 * extended by `SPEC/RTTP-FRAME-EXT-v1.2.6.md`.
 *
 * Zero dependencies: `node:crypto` and `node:fs`, nothing else.
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/**
 * The vector set shipped inside this package. Loading it with `readFileSync`
 * keeps this package importable from plain ESM without JSON import attributes,
 * and lets a caller replay a *newer* vector set without reinstalling.
 */
export const DEFAULT_VECTORS_PATH = fileURLToPath(new URL('./vectors.json', import.meta.url));

// ---------------------------------------------------------------------------
// Frame constants (sec. 4.1)
// ---------------------------------------------------------------------------

const MAGIC = 0x52545450;
const VERSION_ID = 130n;
const SIZE = 128;

/** Offset of ACTION_LEN and of the ACTION field itself. */
const OFF_ACTION_LEN = 0x68;
const OFF_ACTION = 0x69;

/** Offsets fixed by RTTP-FRAME-EXT-v1.2.6 sec. 2 (extension block at 0x66..0x7F). */
const OFF_SPEC_REV = 0x66;
const OFF_FLAGS = 0x67;
const OFF_RESERVED = 0x79;
const KNOWN_SPEC_REVS = new Set([0, 1]);
const FLAG_URI_ANCHORED = 0x01;

/** The ACTION field is 16 bytes; ACTION_LEN is one byte. See RFC-002 sec. 10.2. */
export const ACTION_MAX_LEN = 16;

const TOKEN = /^[a-z0-9-]+$/;
const HASH_INTENT = /^[0-9a-f]{8}$/;

// ---------------------------------------------------------------------------
// Independent implementation: URI parsing + canonicalisation
// ---------------------------------------------------------------------------

/**
 * Parse one `rttp` URI - an implementation written from RFC-002 sec. 10.2 alone,
 * sharing no code with `src/rttp-uri.mjs`.
 *
 * @param {string} uri
 * @returns {{ authority: string, action: string, shardHex: string }}
 */
export function parseUri(uri) {
  if (typeof uri !== 'string' || uri === '') throw new Error('empty uri');
  if (uri !== uri.trim()) throw new Error('leading/trailing whitespace');

  let rest;
  // The browser-registration form is accepted as a **tolerance only**: the
  // specification defines no such form, but a browser hands it to the handler.
  if (uri.startsWith('web+rttp://')) rest = uri.slice(11);
  else if (uri.startsWith('rttp://')) rest = uri.slice(7);
  else throw new Error('scheme must be rttp:// or the browser-registration form');

  for (const ch of ['@', '?', '#', '[', ']']) {
    if (uri.includes(ch)) throw new Error(`illegal char ${ch}`);
  }

  const slash = rest.indexOf('/');
  let authority;
  let action = '';
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
// Independent implementation: the 128-byte frame
// ---------------------------------------------------------------------------

/**
 * Build one `PulseHeader128` from a URI and the vector's frame fields.
 *
 * Refuses an `action` that cannot fit the field rather than truncating it: a
 * silently shortened verb would be a routing decision made by the codec, and the
 * codec does not get to make that decision.
 *
 * @param {{
 *   sequenceId: number|string|bigint, ttl: number, priority: number,
 *   shardHex: string, aidHex: string, timestampNs: number|string|bigint,
 *   action: string, uriAnchored: boolean
 * }} fields
 * @returns {Buffer} 128 bytes
 */
export function buildFrame({ sequenceId, ttl, priority, shardHex, aidHex, timestampNs, action, uriAnchored }) {
  const actionBytes = Buffer.from(action, 'ascii');
  if (actionBytes.length > ACTION_MAX_LEN) {
    throw new Error(`action is ${actionBytes.length} bytes; the field holds ${ACTION_MAX_LEN}`);
  }
  if (shardHex.length !== 32) throw new Error('ROUTE_SHARD must be 32 hex characters');
  if (aidHex.length !== 64) throw new Error('AID_ORIGIN must be 64 hex characters');

  const buf = Buffer.alloc(SIZE);
  buf.writeUInt32BE(MAGIC, 0x00);
  buf.writeBigUInt64BE(0n, 0x04);                  // VERSION_ID u128 high half
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
  buf[OFF_ACTION_LEN] = actionBytes.length;        // ACTION_LEN
  actionBytes.copy(buf, OFF_ACTION);               // ACTION (zero-padded)
  return buf;                                      // 0x79..0x80 RESERVED = 0
}

/**
 * Verify a `PulseHeader128`, mirroring the Python `pulse_header.verify`.
 *
 * Implements the extension-block rules of RTTP-FRAME-EXT-v1.2.6 sec. 2 / sec. 4
 * (R2-R7) and the ACTION grammar of RFC-002 sec. 10.2. Every failure throws: a
 * check that cannot be performed is a failure, never a pass.
 *
 * @param {Buffer} raw 128 bytes
 * @param {{ expectedAidOrigin?: string }} [options]
 * @returns {{ specRev: number, flags: number, uriAnchored: boolean,
 *             action: string, actionOmitted: boolean }}
 */
export function verifyFrame(raw, options = {}) {
  if (!Buffer.isBuffer(raw) || raw.length !== SIZE) {
    throw new Error(`frame must be ${SIZE} bytes`);
  }
  if (raw.readUInt32BE(0x00) !== MAGIC) throw new Error('bad RTTP_MAGIC');
  if (raw.readBigUInt64BE(0x0C) !== VERSION_ID) throw new Error('unsupported VERSION_ID');

  const specRev = raw[OFF_SPEC_REV];
  if (!KNOWN_SPEC_REVS.has(specRev)) {
    throw new Error(`unknown SPEC_REV: ${specRev} (fail closed)`);
  }

  const flags = raw[OFF_FLAGS];
  const actionLen = raw[OFF_ACTION_LEN];

  if (specRev === 0) {
    // R6: a pre-v1.2.6 frame must have an all-zero extension block.
    for (let i = OFF_SPEC_REV; i < SIZE; i += 1) {
      if (raw[i] !== 0) throw new Error('SPEC_REV=0 but extension block is not all-zero');
    }
  } else {
    // R7: unknown FLAGS bits and any RESERVED byte are rejections.
    if ((flags & ~FLAG_URI_ANCHORED) !== 0) {
      throw new Error(`unknown FLAGS bits set: 0x${(flags & ~FLAG_URI_ANCHORED).toString(16).padStart(2, '0')}`);
    }
    for (let i = OFF_RESERVED; i < SIZE; i += 1) {
      if (raw[i] !== 0) throw new Error('RESERVED bytes must be zero in SPEC_REV=1');
    }
    // R4: ACTION_LEN is one byte, the field holds 16.
    if (actionLen > ACTION_MAX_LEN) {
      throw new Error(`ACTION_LEN ${actionLen} > ${ACTION_MAX_LEN}`);
    }
    for (let i = OFF_ACTION + actionLen; i < OFF_ACTION + ACTION_MAX_LEN; i += 1) {
      if (raw[i] !== 0) throw new Error('ACTION padding must be zero');
    }
  }

  let action = '';
  if (specRev === 1 && actionLen > 0) {
    action = raw.subarray(OFF_ACTION, OFF_ACTION + actionLen).toString('ascii');
    if (!TOKEN.test(action)) {
      throw new Error(`ACTION violates RFC-002 sec. 10.2: ${JSON.stringify(action)}`);
    }
  }

  if (options.expectedAidOrigin !== undefined) {
    const got = raw.subarray(0x46, 0x66).toString('hex');
    if (got !== options.expectedAidOrigin) {
      throw new Error('AID_ORIGIN does not match the expected origin');
    }
  }

  return {
    specRev,
    flags,
    uriAnchored: (flags & FLAG_URI_ANCHORED) !== 0,
    action,
    actionOmitted: action === '',
  };
}

// ---------------------------------------------------------------------------
// Vector loading and replay
// ---------------------------------------------------------------------------

/**
 * @param {string} [path] defaults to the vector set shipped with this package
 * @returns {object} the parsed vector set
 */
export function loadVectors(path = DEFAULT_VECTORS_PATH) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

/**
 * Replay a vector set against the independent implementations above.
 *
 * @param {object} vectors
 * @returns {{ checked: number, failures: string[], passed: boolean }}
 */
export function runConformance(vectors) {
  const failures = [];
  let checked = 0;

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
    } catch { /* expected */ }
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
    try {
      verifyFrame(frame, { expectedAidOrigin: aidHex });
    } catch (err) {
      failures.push(`${c.uri} :: published frame rejected by verifyFrame: ${err.message}`);
    }
  }

  for (const c of (vectors.negative_frames || [])) {
    checked += 1;
    try {
      verifyFrame(Buffer.from(c.header_hex, 'hex'), { expectedAidOrigin: aidHex });
      failures.push(`frame ${c.rule} :: ${c.label} :: expected REJECT but accepted`);
    } catch { /* expected */ }
  }

  for (const c of (vectors.positive_frames || [])) {
    checked += 1;
    try {
      const got = verifyFrame(Buffer.from(c.header_hex, 'hex'), { expectedAidOrigin: aidHex });
      if (got.action !== c.action) {
        failures.push(`frame ${c.rule} :: action ${got.action} != ${c.action}`);
      }
    } catch (err) {
      failures.push(`frame ${c.rule} :: ${c.label} :: expected ACCEPT but rejected: ${err.message}`);
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
    frame.fill(0, 0x66, SIZE);  // SPEC_REV=0: the extension block is all zero
    if (frame.toString('hex') !== cv.header_hex) {
      failures.push('compat vector :: frame bytes mismatch');
    }
    try {
      const got = verifyFrame(Buffer.from(cv.header_hex, 'hex'), { expectedAidOrigin: aidHex });
      if (got.specRev !== 0 || !got.actionOmitted) {
        failures.push('compat vector :: SPEC_REV=0 semantics mismatch');
      }
    } catch (err) {
      failures.push(`compat vector :: verifyFrame rejected an old frame: ${err.message}`);
    }
  }

  return { checked, failures, passed: failures.length === 0 };
}
