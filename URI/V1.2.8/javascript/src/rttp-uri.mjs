/**
 * @aicent/rttp - RFC-002 sec. 10 `rttp` URI validation, canonicalisation and
 * ROUTE_SHARD derivation.
 *
 * This module is the reference implementation of the mapping RFC-002 sec. 10.4
 * promises:
 *     "Dereferencing an `rttp` URI emits one pulse ... carrying `action` as the
 *      intent verb."
 * The specification previously had syntax (sec. 10.2 ABNF) but no "URI -> frame
 * field" mapping; this module and `SPEC/RTTP-FRAME-EXT-v1.2.6.md` supply that
 * segment. It is an independent implementation of the same conformance vectors
 * as the Python package `rttp` on PyPI - two implementations that share no code
 * and agree byte for byte is what makes the vectors worth anything.
 *
 * Authority (important):
 *   * URI **syntax** - the sole authority is the RFC-002 sec. 10.2 ABNF. This module
 *     adds no syntax.
 *   * This module does exactly two things: (1) validate and **canonicalise**
 *     per sec. 10.2/sec. 10.3; (2) derive ROUTE_SHARD.
 *
 * Design constraints (each is a requirement in the specification):
 *   * sec. 10.1  `intent` is either 8 lowercase hex digits (a 32-bit routing hash)
 *            or a readable organ token.
 *   * sec. 10.2  `action` is an **open set**: 1*( %x61-7A / DIGIT / "-" ).
 *   * sec. 10.3  The canonical form is **lowercase US-ASCII**; there is no userinfo,
 *            port, query or fragment.
 *   * sec. 10.5  **No DNS**: ROUTE_SHARD is pure computation - no registry, no
 *            resolver, no network.
 *
 * Case is **not** normalised. A case variant is not a spelling difference, it is
 * a different string, and it is rejected (sec. 10.3). Nothing here is ever accepted
 * because a check could not be performed: this module fails closed.
 *
 * ROUTE_SHARD derivation (see spec sec. 5): the first 16 bytes of
 * SHA-256(ASCII(canonical_authority)).
 *
 * Zero dependencies - `node:crypto` and nothing else.
 *
 * @see https://rttp.com/RFC-002/
 */

import { createHash } from 'node:crypto';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** The canonical scheme name. */
export const SCHEME = 'rttp';

/**
 * The prefix a user agent requires on a scheme it does not already know, before
 * it will let a page register a protocol handler. It is a property of the
 * **client**, never of the target: both spellings name the same address, and the
 * canonical output of this module is always `rttp://`.
 *
 * Accepted for **tolerance only** -- the specification defines no such form. A
 * conforming third-party implementation is not required to reproduce this
 * tolerance; refusing the string a browser is about to deliver would, however,
 * break the handler path.
 */
export const BROWSER_HANDLER_SCHEME = 'web+rttp';

/** sec. 4.1: ROUTE_SHARD is a u128. */
export const ROUTE_SHARD_BYTES = 16;

/** sec. 10.2: `lowhex = %x30-39 / %x61-66`; 8 of them is a 32-bit routing hash. */
export const HASH_INTENT_LEN = 8;

/**
 * The capacity of the frame's ACTION field (`0x69`..`0x78`, one byte of
 * ACTION_LEN at `0x68`). **Not** a syntax rule: sec. 10.2 places no length limit on
 * `action`, so `parse()` accepts longer values. A frame builder must reject
 * them, because the field cannot hold more.
 */
export const ACTION_MAX_LEN = 16;

/** The RTTP specification release this module was written against. */
export const SPEC_RELEASE = 'v1.2.6';

// sec. 10.2: name-intent / pillar / root / action = 1*( %x61-7A / DIGIT / "-" )
const TOKEN = /^[a-z0-9-]+$/;
const LOWHEX = /^[0-9a-f]+$/;

// sec. 10.3: this scheme defines no userinfo / port / query / fragment
const FORBIDDEN_CHARS = ['@', '?', '#', '[', ']'];

// ---------------------------------------------------------------------------
// Error
// ---------------------------------------------------------------------------

/**
 * The URI does not conform. **Always fail closed** (sec. 10.5: no fallback, and no
 * `rttps`).
 */
export class RttpUriError extends Error {
  constructor(message) {
    super(message);
    this.name = 'RttpUriError';
  }
}

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

/**
 * sec. 10.2 token check, with the case rule of sec. 10.3 kept separate so that an
 * uppercase letter produces a message that says what is actually wrong.
 *
 * @param {string} value
 * @param {string} what  field name, for the error message
 */
function checkToken(value, what) {
  if (typeof value !== 'string' || value === '') {
    throw new RttpUriError(`${what} is empty`);
  }
  for (const ch of value) {
    if (TOKEN.test(ch)) continue;
    if (ch !== ch.toLowerCase()) {
      // sec. 10.3: the canonical form is lowercase. Uppercase is not a normalisable
      // spelling difference - it is illegal input.
      throw new RttpUriError(
        `${what} contains uppercase '${ch}' - lowercase US-ASCII only (RFC-002 sec. 10.3)`);
    }
    throw new RttpUriError(
      `${what} contains illegal character ${JSON.stringify(ch)} (allowed: a-z, 0-9, '-')`);
  }
  if (value.startsWith('-') || value.endsWith('-')) {
    throw new RttpUriError(`${what} must not begin or end with '-'`);
  }
}

/**
 * @param {string} value
 * @returns {boolean} true for a hash-intent (8 lowhex), false for a name-intent
 */
function checkIntent(value) {
  if (value.length === HASH_INTENT_LEN && LOWHEX.test(value)) return true;
  checkToken(value, 'intent');
  return false;
}

/**
 * sec. 10.2 `action` syntax test: 1*( %x61-7A / DIGIT / "-" ).
 *
 * `action` is an **open set** - this only judges the *form*, never whether the
 * verb is one this specification knows. Frame builders reuse it so the rule is
 * not written twice.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isValidAction(value) {
  if (typeof value !== 'string' || value === '') return false;
  if (value.startsWith('-') || value.endsWith('-')) return false;
  return TOKEN.test(value);
}

// ---------------------------------------------------------------------------
// ROUTE_SHARD derivation
// ---------------------------------------------------------------------------

/**
 * authority -> ROUTE_SHARD (16 bytes).
 *
 *     ROUTE_SHARD = SHA-256( ASCII(canonical_authority) )[0:16]
 *
 * Properties:
 *   * **Deterministic** - one authority always yields one shard.
 *   * **Pure computation** - no DNS, no registry, no network (sec. 10.5).
 *   * **One-way** - the authority cannot be recovered from the shard.
 *   * **Independent of `action`** - it routes *where*, never *what*, which is
 *     exactly why `action` must be a separate frame field (see spec sec. 5.3).
 *
 * @param {string} canonicalAuthority
 * @returns {Uint8Array} 16 bytes
 */
export function deriveRouteShard(canonicalAuthority) {
  if (typeof canonicalAuthority !== 'string' || canonicalAuthority === '') {
    throw new RttpUriError('canonical_authority is empty');
  }
  if (canonicalAuthority !== canonicalAuthority.toLowerCase()) {
    throw new RttpUriError('canonical_authority must be lowercase (RFC-002 sec. 10.3)');
  }
  const digest = createHash('sha256')
    .update(Buffer.from(canonicalAuthority, 'ascii'))
    .digest();
  return new Uint8Array(digest.subarray(0, ROUTE_SHARD_BYTES));
}

/**
 * @param {string} canonicalAuthority
 * @returns {string} 32 lowercase hex characters
 */
export function deriveRouteShardHex(canonicalAuthority) {
  return Buffer.from(deriveRouteShard(canonicalAuthority)).toString('hex');
}

// ---------------------------------------------------------------------------
// Parse / canonicalise
// ---------------------------------------------------------------------------

/**
 * Parse one `rttp` URI and return its canonical fields.
 *
 * The validation order deliberately stays "reject before interpreting": any
 * suspicious form throws immediately, and nothing is ever guessed at.
 * (sec. 10.5: user agents that do not implement this scheme fail closed.)
 *
 * Field names are `snake_case` on purpose: the published conformance vectors use
 * those names, so the output of the Python and JavaScript implementations
 * compares directly.
 *
 * @param {string} uri
 * @returns {{
 *   scheme: string,
 *   intent: string,
 *   intent_is_hash: boolean,
 *   intent_hash32: number | null,
 *   pillar: string,
 *   root: string,
 *   action: string,
 *   action_omitted: boolean,
 *   authority: string,
 *   canonical_uri: string,
 *   route_shard: Uint8Array,
 *   route_shard_hex: string
 * }}
 */
export function parse(uri) {
  if (typeof uri !== 'string') {
    throw new RttpUriError('uri must be a string');
  }
  if (uri === '') {
    throw new RttpUriError('uri is empty');
  }
  if (uri !== uri.trim()) {
    // Leading/trailing whitespace may be paste contamination, or an attempt to
    // slip past a prefix check. Either way: reject.
    throw new RttpUriError('uri must not contain leading/trailing whitespace');
  }

  // --- scheme (sec. 10.6 prefix whitelist) ---
  let scheme;
  let rest;
  if (uri.startsWith(`${BROWSER_HANDLER_SCHEME}://`)) {
    scheme = BROWSER_HANDLER_SCHEME;
    rest = uri.slice(BROWSER_HANDLER_SCHEME.length + 3);
  } else if (uri.startsWith(`${SCHEME}://`)) {
    scheme = SCHEME;
    rest = uri.slice(SCHEME.length + 3);
  } else {
    throw new RttpUriError(
      `not an rttp URI: must begin with '${SCHEME}://' or '${BROWSER_HANDLER_SCHEME}://'`);
  }

  // --- sec. 10.3 excluded characters ---
  for (const ch of FORBIDDEN_CHARS) {
    if (uri.includes(ch)) {
      throw new RttpUriError(
        `illegal character ${JSON.stringify(ch)}: this scheme defines no `
        + 'userinfo / query / fragment');
    }
  }

  // --- authority and path ---
  const slash = rest.indexOf('/');
  const authority = slash === -1 ? rest : rest.slice(0, slash);
  const action = slash === -1 ? '' : rest.slice(slash + 1);

  if (slash !== -1 && action.includes('/')) {
    throw new RttpUriError("path must be a single segment '/<action>'");
  }
  if (slash !== -1 && action === '') {
    // sec. 10.2: path = "/" action, action = 1*(...). A trailing slash with an empty
    // action is a different form from "no path", and the two must not be
    // conflated.
    throw new RttpUriError("trailing '/' with empty action: path must be '/<action>'");
  }

  const parts = authority.split('.');
  if (parts.length !== 3) {
    throw new RttpUriError(
      "authority must be exactly '<intent>.<pillar>.<root>' "
      + `(got ${parts.length} segment(s))`);
  }
  const [intent, pillar, root] = parts;

  const intentIsHash = checkIntent(intent);
  checkToken(pillar, 'pillar');
  checkToken(root, 'root');
  if (action) checkToken(action, 'action');

  const canonicalAuthority = `${intent}.${pillar}.${root}`;
  const canonicalUri = `${SCHEME}://${canonicalAuthority}${action ? `/${action}` : ''}`;
  const shard = deriveRouteShard(canonicalAuthority);

  return {
    scheme,
    intent,
    intent_is_hash: intentIsHash,
    intent_hash32: intentIsHash ? parseInt(intent, 16) : null,
    pillar,
    root,
    action,
    action_omitted: action === '',
    authority: canonicalAuthority,
    canonical_uri: canonicalUri,
    route_shard: shard,
    route_shard_hex: Buffer.from(shard).toString('hex'),
  };
}

/**
 * Convenience entry point: parse and derive in one step. Identical to `parse`;
 * it exists so that callers reading the specification's wording have a
 * function to name.
 *
 * @param {string} uri
 * @returns {ReturnType<typeof parse>}
 */
export function parseAndDerive(uri) {
  return parse(uri);
}
