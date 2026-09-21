/**
 * Tests for @aicent/rttp/conformance.
 *
 * The point of this file is not that the shipped vectors pass - it is that the
 * checker **can fail**. A conformance suite that always prints PASS is worse
 * than no suite at all, so most of what follows tampers with the vectors on
 * purpose and requires the checker to notice.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ACTION_MAX_LEN,
  DEFAULT_VECTORS_PATH,
  buildFrame,
  loadVectors,
  parseUri,
  runConformance,
  verifyFrame,
} from '../src/conformance.mjs';

/** A private copy, so one test cannot disturb another. */
function freshVectors() {
  return JSON.parse(JSON.stringify(loadVectors()));
}

const FRAME_FIELDS = {
  sequenceId: 1,
  ttl: 255,
  priority: 1,
  shardHex: 'bf77b78ff6ceafc363226aa586562218',
  aidHex: '5d42ba8b38fe10bfa702bdfe6af536ea16e20e35fbb48d84c3658d80cad2789d',
  timestampNs: 1760000000000000000,
  action: 'vessel',
  uriAnchored: true,
};

test('the shipped vector set passes, and covers 35 checks', () => {
  const { checked, failures, passed } = runConformance(loadVectors());
  assert.deepEqual(failures, []);
  assert.equal(passed, true);
  // 6 positive URIs + 15 negative URIs + 3 frame vectors + 1 compat vector
  // + 9 negative frame relations (RTTP-FRAME-EXT rules R3-R7) + 1 positive frame relation
  assert.equal(checked, 35);
});

test('the shipped vectors are the ones the specification states', () => {
  const v = loadVectors();
  assert.equal(v.spec, 'RTTP-FRAME-EXT-v1.2.6');
  assert.deepEqual(v.applies_to, ['RFC-002 sec. 4.1', 'RFC-002 sec. 10']);
  assert.equal(v.frame_size, 128);
  assert.match(v.route_shard_rule, /SHA-256/);
  assert.equal(v.positive_uris.length, 6);
  assert.equal(v.negative_uris.length, 15);
  assert.equal(v.frame_vectors.length, 3);
  assert.equal(v.negative_frames.length, 9);
  assert.equal(v.positive_frames.length, 1);
  assert.deepEqual(
    [...new Set(v.negative_frames.map((c) => c.rule))].sort(),
    ['R4', 'R5', 'R6', 'R7'],
    'the frame-relation cases must cover the extension rules',
  );
  for (const c of [...v.negative_frames, ...v.positive_frames]) {
    assert.equal(c.header_hex.length, 256);
    assert.equal(c.expected, c.rule === 'R3' ? 'accept' : 'reject');
  }
  // Exactly one forward case is a tolerance rather than a conformance claim: the
  // specification defines no such form, so a third-party implementation is not
  // required to reproduce it. Guard the classification so it cannot drift.
  const tolerances = v.positive_uris.filter((c) => c.tolerance === true);
  assert.equal(tolerances.length, 1);
  assert.equal(typeof tolerances[0].note, 'string');
  assert.match(tolerances[0].note, /tolerance/);
  assert.equal(v.positive_uris.filter((c) => c.tolerance === false).length, 5);
});

test('a tampered ROUTE_SHARD must fail', () => {
  const v = freshVectors();
  v.positive_uris[0].route_shard_hex = `${'0'.repeat(31)}0`;
  const { passed, failures } = runConformance(v);
  assert.equal(passed, false);
  assert.ok(failures.some((f) => f.includes('shard')), failures.join('\n'));
});

test('a single altered frame byte must fail', () => {
  const v = freshVectors();
  const original = v.frame_vectors[1].header_hex;
  v.frame_vectors[1].header_hex = `${original.slice(0, 40)}${original[40] === '0' ? '1' : '0'}${original.slice(41)}`;
  const { passed, failures } = runConformance(v);
  assert.equal(passed, false);
  assert.ok(failures.some((f) => f.includes('frame bytes mismatch')), failures.join('\n'));
});

test('a URI that a conforming implementation rejects must not be on the positive side', () => {
  const v = freshVectors();
  v.positive_uris.push({
    uri: 'https://f3b2a1c4.rttp.aicent/vessel',
    authority: 'f3b2a1c4.rttp.aicent',
    action: 'vessel',
    route_shard_hex: 'bf77b78ff6ceafc363226aa586562218',
  });
  const { passed, failures } = runConformance(v);
  assert.equal(passed, false);
  assert.ok(failures.some((f) => f.includes('expected ACCEPT but threw')), failures.join('\n'));
});

test('a URI that parses must not be on the negative side', () => {
  const v = freshVectors();
  v.negative_uris.push({ uri: 'rttp://brain.epoekie.aicent/verify', reason: 'deliberately wrong' });
  const { passed, failures } = runConformance(v);
  assert.equal(passed, false);
  assert.ok(failures.some((f) => f.includes('expected REJECT but parsed')), failures.join('\n'));
});

test('buildFrame refuses an action the field cannot hold, rather than truncating it', () => {
  assert.equal(Buffer.from('a'.repeat(ACTION_MAX_LEN), 'ascii').length, ACTION_MAX_LEN);
  assert.doesNotThrow(() => buildFrame({ ...FRAME_FIELDS, action: 'a'.repeat(ACTION_MAX_LEN) }));
  assert.throws(() => buildFrame({ ...FRAME_FIELDS, action: 'a'.repeat(ACTION_MAX_LEN + 1) }), /holds 16/);
});

test('buildFrame reproduces the published frame byte for byte', () => {
  const v = loadVectors();
  const c = v.frame_vectors[0];
  const { shardHex, action } = parseUri(c.uri);
  const frame = buildFrame({
    sequenceId: c.sequence_id,
    ttl: c.ttl,
    priority: c.priority,
    shardHex,
    aidHex: c.aid_origin_hex,
    timestampNs: c.timestamp_ns,
    action,
    uriAnchored: c.uri_anchored,
  });
  assert.equal(frame.length, 128);
  assert.equal(frame.toString('hex'), c.header_hex);
});

test('the default vectors path points at a file this package actually ships', () => {
  assert.match(DEFAULT_VECTORS_PATH, /vectors\.json$/);
  assert.doesNotThrow(() => loadVectors(DEFAULT_VECTORS_PATH));
});
