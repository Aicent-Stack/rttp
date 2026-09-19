#!/usr/bin/env node
/**
 * rttp - replay the RTTP conformance vectors.
 *
 *     npx @aicent/rttp
 *     rttp --vectors ./newer-vectors.json
 *     rttp --json
 *
 * Exit status is 0 only when every check passes: `[PASS]` or it is not.
 */

import { DEFAULT_VECTORS_PATH, loadVectors, runConformance } from '../src/conformance.mjs';

const USAGE = `rttp - replay the RTTP conformance vectors

Usage:
  rttp [--vectors <file>] [--json] [--help]

Options:
  --vectors <file>  replay a different vector set (default: the one shipped
                    with this package)
  --json            emit machine-readable results
  --help            show this message

Exit status: 0 when every check passes, 1 otherwise.
`;

function parseArgs(argv) {
  const opts = { vectors: DEFAULT_VECTORS_PATH, json: false, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') opts.help = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--vectors') {
      i += 1;
      if (argv[i] === undefined) {
        console.error('rttp: --vectors needs a file path');
        process.exit(2);
      }
      opts.vectors = argv[i];
    } else {
      console.error(`rttp: unknown argument ${JSON.stringify(arg)}`);
      console.error(USAGE);
      process.exit(2);
    }
  }
  return opts;
}

const opts = parseArgs(process.argv.slice(2));

if (opts.help) {
  process.stdout.write(USAGE);
  process.exit(0);
}

let vectors;
try {
  vectors = loadVectors(opts.vectors);
} catch (err) {
  console.error(`rttp: cannot read vectors at ${opts.vectors}`);
  console.error(`  ${err.message}`);
  process.exit(2);
}

const { checked, failures, passed } = runConformance(vectors);

if (opts.json) {
  process.stdout.write(`${JSON.stringify({
    passed,
    checked,
    failed: failures.length,
    vectors: opts.vectors,
    spec: vectors.spec,
    applies_to: vectors.applies_to,
    failures,
  }, null, 2)}\n`);
} else if (passed) {
  console.log(`[PASS] all ${checked} checks passed (node, independent implementation)`);
} else {
  console.log(`[FAIL] ${failures.length} of ${checked} checks failed (node)`);
  for (const item of failures) console.log('   -', item);
}

process.exit(passed ? 0 : 1);
