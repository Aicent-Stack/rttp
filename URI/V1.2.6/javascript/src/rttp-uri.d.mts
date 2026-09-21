/**
 * Type declarations for @aicent/rttp (main entry).
 *
 * Hand-written so the package stays build-free: the published `src/` is exactly
 * what runs, and exactly what a reviewer reads.
 */

/** The canonical field set of a parsed `rttp` URI. */
export interface RttpUri {
  /** The canonical form, or the browser-registration form when that is how the input arrived. */
  scheme: 'rttp' | 'web+rttp';
  /** 8 lowercase hex digits (32-bit routing hash) or a readable organ token. */
  intent: string;
  /** True when `intent` is a hash-intent. */
  intent_is_hash: boolean;
  /** `intent` read as a 32-bit routing hash; `null` when it is a name. */
  intent_hash32: number | null;
  pillar: string;
  root: string;
  /** Empty string when omitted (§10.4 default operation). */
  action: string;
  action_omitted: boolean;
  /** `<intent>.<pillar>.<root>`, canonical. */
  authority: string;
  /** Always starts `rttp://`, whatever prefix the input used. */
  canonical_uri: string;
  /** 16 bytes, SHA-256(authority)[0:16]. */
  route_shard: Uint8Array;
  /** The same 16 bytes as 32 lowercase hex characters. */
  route_shard_hex: string;
}

/** The URI does not conform. Always fail closed (§10.5). */
export declare class RttpUriError extends Error {
  constructor(message: string);
  name: 'RttpUriError';
}

/** The canonical scheme name. */
export declare const SCHEME: 'rttp';

/** The browser protocol-handler form - a property of the client, never of the target. */
export declare const BROWSER_HANDLER_SCHEME: 'web+rttp';

/** §4.1: ROUTE_SHARD is a u128. */
export declare const ROUTE_SHARD_BYTES: 16;

/** Length of a hash-intent, in lowercase hex characters. */
export declare const HASH_INTENT_LEN: 8;

/** Capacity of the frame's ACTION field. Not a syntax rule - see the README. */
export declare const ACTION_MAX_LEN: 16;

/** The RTTP specification release this module was written against. */
export declare const SPEC_RELEASE: string;

/** Parse one `rttp` URI and return its canonical fields. Throws `RttpUriError`. */
export declare function parse(uri: string): RttpUri;

/** Identical to `parse`. */
export declare function parseAndDerive(uri: string): RttpUri;

/** §10.2 `action` syntax test. Judges form only - the verb set is open. */
export declare function isValidAction(value: unknown): boolean;

/** `authority` -> ROUTE_SHARD (16 bytes). Throws `RttpUriError`. */
export declare function deriveRouteShard(canonicalAuthority: string): Uint8Array;

/** `authority` -> ROUTE_SHARD as 32 lowercase hex characters. */
export declare function deriveRouteShardHex(canonicalAuthority: string): string;
