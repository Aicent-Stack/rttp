/**
 * The whole quickstart, in three lines.
 *
 *     node examples/quickstart.mjs
 *
 * Expected output:
 *
 *     459e543b73d86005b72ba77d5756e83c
 *
 * That is not an arbitrary number. It is the ROUTE_SHARD the published
 * conformance vectors pin for this exact address (`positive_uris[1]` and
 * `frame_vectors[1]` in `src/vectors.json`), which is what makes this example
 * checkable rather than merely illustrative - and it is the same value the
 * Python implementation derives, from code that shares nothing with this one.
 */

import { parse } from '@aicent/rttp';

const r = parse('rttp://brain.epoekie.aicent/verify');
console.log(r.route_shard_hex);   // 459e543b73d86005b72ba77d5756e83c
