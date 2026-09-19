/**
 * Unit tests for @aicent/rttp (main entry).
 *
 * Every expected value is taken from the *published* conformance vectors
 * (`SPEC/conformance-vectors.json`), never from this implementation's own
 * output - otherwise the test would only prove the code agrees with itself.
 *
 * Zero dependencies: `node:test` and `node:assert` only.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  SCHEME,
  BROWSER_HANDLER_SCHEME,
  ROUTE_SHARD_BYTES,
  ACTION_MAX_LEN,
  RttpUriError,
  deriveRouteShard,
  deriveRouteShardHex,
  isValidAction,
  parse,
  parseAndDerive,
} from '../src/rttp-uri.mjs';

test('accepts the published positive vectors and derives the published shards', () => {
  const cases = [
    ['rttp://f3b2a1c4.rttp.aicent/vessel', 'f3b2a1c4.rttp.aicent', 'vessel', 'bf77b78ff6ceafc363226aa586562218'],
    ['rttp://brain.epoekie.aicent/verify', 'brain.epoekie.aicent', 'verify', '459e543b73d86005b72ba77d5756e83c'],
    ['rttp://00000000.rpki.aicent/attest', '00000000.rpki.aicent', 'attest', '753c105fd0f8bf341811acfaaac85b37'],
    ['rttp://a-b-c.d-e.f-g/audit-v2', 'a-b-c.d-e.f-g', 'audit-v2', '905bf68b86aadf883cda2db9640912de'],
  ];
  for (const [uri, authority, action, shard] of cases) {
    const r = parse(uri);
    assert.equal(r.authority, authority, uri);
    assert.equal(r.action, action, uri);
    assert.equal(r.route_shard_hex, shard, uri);
  }
});

test('the browser-handler prefix names the same address; output is always canonical', () => {
  const handlerForm = parse('web+rttp://logic.zcmk.aicent/pulse');
  const plain = parse('rttp://logic.zcmk.aicent/pulse');

  assert.equal(handlerForm.scheme, BROWSER_HANDLER_SCHEME);
  assert.equal(plain.scheme, SCHEME);
  assert.equal(handlerForm.canonical_uri, 'rttp://logic.zcmk.aicent/pulse');
  assert.equal(handlerForm.route_shard_hex, 'cdc32d19641c84aca3292de6276de056');

  // Same authority, same path, same shard - only the reported client differs.
  assert.equal(handlerForm.authority, plain.authority);
  assert.equal(handlerForm.action, plain.action);
  assert.equal(handlerForm.route_shard_hex, plain.route_shard_hex);
});

test('ROUTE_SHARD does not depend on action - routing is where, not what', () => {
  const withAction = parse('rttp://f3b2a1c4.rttp.aicent/vessel');
  const withoutAction = parse('rttp://f3b2a1c4.rttp.aicent');

  assert.equal(withoutAction.action, '');
  assert.equal(withoutAction.action_omitted, true);
  assert.equal(withoutAction.route_shard_hex, withAction.route_shard_hex);
});

test('a hash-intent is read as a 32-bit routing hash; a name-intent is not', () => {
  const hashIntent = parse('rttp://00000000.rpki.aicent/attest');
  assert.equal(hashIntent.intent_is_hash, true);
  assert.equal(hashIntent.intent_hash32, 0);

  const named = parse('rttp://brain.epoekie.aicent/verify');
  assert.equal(named.intent_is_hash, false);
  assert.equal(named.intent_hash32, null);
});

test('rejects every published negative vector (fail closed)', () => {
  const negatives = [
    'rttp://f3b2a1c4.rttp.aicent/VESSEL',
    'rttp://F3B2A1C4.rttp.aicent/vessel',
    'RTTP://f3b2a1c4.rttp.aicent/vessel',
    'WEB+RTTP://f3b2a1c4.rttp.aicent/vessel',
    'rttp://subject@rttp.aicent/vessel',
    'rttp://f3b2a1c4.rttp.aicent/vessel?x=1',
    'rttp://f3b2a1c4.rttp.aicent/vessel#f',
    'rttp://f3b2a1c4.rttp.aicent:443/vessel',
    'rttp://f3b2a1c4.rttp.aicent/a/b',
    'rttp://a.b',
    'rttp://a.b.c.d/e',
    'rttp://f3b2a1c4.rttp.aicent/',
    'https://f3b2a1c4.rttp.aicent/vessel',
    'rttp://f3b2a1c4.rttp.aicent/vessel ',
    'rttp://-lead.rttp.aicent/vessel',
  ];
  for (const uri of negatives) {
    assert.throws(() => parse(uri), RttpUriError, `should reject: ${JSON.stringify(uri)}`);
  }
});

test('a case variant is illegal input, not a normalisable spelling difference', () => {
  assert.throws(() => parse('rttp://f3b2a1c4.rttp.aicent/VESSEL'), /uppercase/);
  assert.throws(() => parse('rttp://F3B2A1C4.rttp.aicent/vessel'), /uppercase/);
  assert.throws(() => parse('rttp://f3b2a1c4.rttp.aicent/VESSEL'), RttpUriError);
});

test('the canonical form is idempotent', () => {
  const once = parse('web+rttp://brain.epoekie.aicent/verify').canonical_uri;
  assert.equal(once, 'rttp://brain.epoekie.aicent/verify');
  assert.equal(parse(once).canonical_uri, once);
  assert.equal(parse(once).route_shard_hex, parse(once).route_shard_hex);
});

test('deriveRouteShard refuses a non-canonical authority and returns 16 bytes', () => {
  assert.throws(() => deriveRouteShard('brain.Epoekie.aicent'), /lowercase/);
  assert.throws(() => deriveRouteShard(''), /empty/);
  assert.equal(deriveRouteShard('brain.epoekie.aicent').length, ROUTE_SHARD_BYTES);
  assert.equal(deriveRouteShardHex('brain.epoekie.aicent').length, ROUTE_SHARD_BYTES * 2);
});

test('isValidAction judges form only - the verb set is open', () => {
  for (const ok of ['vessel', 'verify', 'pulse', 'audit-v2', 'x0']) {
    assert.equal(isValidAction(ok), true, ok);
  }
  for (const bad of ['', '-x', 'x-', 'VESSEL', 'a_b', 'a b', 'a.b', 1, null, undefined]) {
    assert.equal(isValidAction(bad), false, String(bad));
  }
});

test('non-string input is rejected rather than coerced', () => {
  for (const bad of [null, undefined, 1, {}, [], true]) {
    assert.throws(() => parse(bad), RttpUriError, String(bad));
  }
});

test('§10.2 places no length limit on action; the frame field holds 16', () => {
  const longAction = 'a'.repeat(ACTION_MAX_LEN + 1);
  const r = parse(`rttp://f3b2a1c4.rttp.aicent/${longAction}`);
  assert.equal(r.action, longAction);
  assert.ok(r.action.length > ACTION_MAX_LEN);
});

test('parseAndDerive is the same entry point under the specification\'s own wording', () => {
  assert.deepEqual(parseAndDerive('rttp://brain.epoekie.aicent/verify'), parse('rttp://brain.epoekie.aicent/verify'));
});
