/**
 * Type declarations for @aicent/rttp/conformance.
 */

/** One URI that a conforming implementation must accept. */
export interface PositiveUriVector {
  uri: string;
  canonical_uri: string;
  authority: string;
  intent: string;
  intent_is_hash: boolean;
  pillar: string;
  root: string;
  action: string;
  action_omitted: boolean;
  route_shard_hex: string;
}

/** One URI that a conforming implementation must reject. */
export interface NegativeUriVector {
  uri: string;
  reason: string;
}

/** One URI -> 128-byte frame vector. */
export interface FrameVector {
  uri: string;
  sequence_id: number;
  ttl: number;
  priority: number;
  timestamp_ns: number;
  aid_origin_hex: string;
  action: string;
  uri_anchored: boolean;
  spec_rev: number;
  route_shard_hex: string;
  header_hex: string;
}

/** A frame written with the pre-extension layout (`SPEC_REV = 0`), which readers must still accept. */
export interface CompatVector {
  uri: string;
  spec_rev: number;
  action: string;
  action_omitted: boolean;
  uri_anchored: boolean;
  expected: string;
  header_hex: string;
}

/** The published vector set. Generated - never hand-edited. */
export interface VectorSet {
  spec: string;
  applies_to: string[];
  generated_by: string;
  note: string;
  route_shard_rule: string;
  frame_size: number;
  action_max_len: number;
  positive_uris: PositiveUriVector[];
  negative_uris: NegativeUriVector[];
  frame_vectors: FrameVector[];
  compat_vector_spec_rev_0: CompatVector;
}

/** Result of one `parseUri` call. */
export interface ParsedUri {
  authority: string;
  action: string;
  shardHex: string;
}

/** Input to `buildFrame`. */
export interface FrameFields {
  sequenceId: number | string | bigint;
  ttl: number;
  priority: number;
  shardHex: string;
  aidHex: string;
  timestampNs: number | string | bigint;
  action: string;
  uriAnchored: boolean;
}

/** Outcome of replaying a vector set. */
export interface ConformanceResult {
  checked: number;
  failures: string[];
  passed: boolean;
}

/** Absolute path of the vector set shipped inside this package. */
export declare const DEFAULT_VECTORS_PATH: string;

/** The ACTION field is 16 bytes. */
export declare const ACTION_MAX_LEN: 16;

/** Independent implementation of RFC-002 sec. 10.2. Throws `Error`. */
export declare function parseUri(uri: string): ParsedUri;

/** Independent implementation of the 128-byte frame. Throws `Error`. */
export declare function buildFrame(fields: FrameFields): Buffer;

/** Load a vector set. Defaults to the one shipped with this package. */
export declare function loadVectors(path?: string): VectorSet;

/** Replay a vector set against the independent implementations. */
export declare function runConformance(vectors: VectorSet): ConformanceResult;
