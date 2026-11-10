#!/usr/bin/env python3
"""rttp 1.3.2 (PyPI) pre-upload verification — vector re-anchoring release."""
import hashlib, io, os, sys

BASE = r'E:/WEB/_release/rttp/URI/V1.3.2/python'
OLD = r'E:/WEB/_release/rttp/URI/V1.2.8/python'

facts = []
pyproj = io.open(os.path.join(BASE, 'pyproject.toml'), encoding='utf-8').read()
init = io.open(os.path.join(BASE, 'src', 'rttp', '__init__.py'), encoding='utf-8').read()
readme = io.open(os.path.join(BASE, 'README.md'), encoding='utf-8').read()
chg = io.open(os.path.join(BASE, 'CHANGELOG.md'), encoding='utf-8').read()

facts.append(('pyproject version == 1.3.2', 'version = "1.3.2"' in pyproj))
facts.append(('__version__ == 1.3.2', '__version__ = "1.3.2"' in init))
facts.append(('zero dependencies', 'dependencies = []' in pyproj))

frozen = ['LICENSE', 'MANIFEST.in', 'src/rttp/seal.py', 'src/rttp/selftest.py']
for rel in frozen:
    a = io.open(os.path.join(BASE, rel), 'rb').read()
    b = io.open(os.path.join(OLD, rel), 'rb').read()
    facts.append(('frozen byte-identical: ' + rel, a == b))

manifest = io.open(os.path.join(BASE, 'vectors.manifest.json'), encoding='utf-8').read()
facts.append(('manifest pins re-anchored vector digest 8640e390… (13,874 bytes)',
              '"bytes": 13874' in manifest and
              '8640e3906900417037cec341e2e56a2582b4b68620716def8941eb319b72132e' in manifest))

vec = io.open(os.path.join(BASE, 'src/rttp/vectors/rttp-conformance-v1.2.6.json'),
              'rb').read()
facts.append(('vector file digest == 8640e390…2132e (13,874 bytes, re-anchored -02)',
              hashlib.sha256(vec).hexdigest() ==
              '8640e3906900417037cec341e2e56a2582b4b68620716def8941eb319b72132e'))

for rel in ['src/rttp/rttp_uri.py', 'src/rttp/pulse_header.py',
            'src/rttp/aid.py', 'src/rttp/seal_asym.py']:
    new = io.open(os.path.join(BASE, rel), encoding='utf-8').read()
    old = io.open(os.path.join(OLD, rel), encoding='utf-8').read()
    facts.append(('comment-only diff: ' + rel,
                  old.replace('RFC-002', 'AICENT-002') == new))

FROZEN_EXEMPT = 'src/rttp/vectors/rttp-conformance-v1.2.6.json'
left = 0
for dp, _, fs in os.walk(BASE):
    for fn in fs:
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, BASE).replace('\\', '/')
        if rel == FROZEN_EXEMPT or rel == 'CHANGELOG.md' or fn.endswith(('.lock',)):
            continue
        try:
            t = io.open(p, encoding='utf-8').read()
        except Exception:
            continue
        left += t.count('RFC-002') + t.count('1459939') + t.count('not yet registered')
facts.append(('zero RFC-002 / #1459939 / not-yet-registered'
              ' (frozen vector + changelog history exempt)', left == 0))

for needle in ['CRI 27', 'draft-li-rttp-iqa-addressing', 'AICENT-002',
               '[PASS] all 80 checks passed (3 skipped)',
               '[PASS] all 83 checks passed', 'rttp 1.3.2 self-test']:
    facts.append(('README has: ' + needle, needle in readme))
for needle in ['not yet registered', '1459939', 'rttp 1.2.8 self-test',
               '37 checks', '(v1.2.6)']:
    facts.append(('README stale absent: ' + needle, needle not in readme))
for needle in ['## [1.3.2] -- 2026-11-09', 'Vector re-anchoring release']:
    facts.append(('CHANGELOG has: ' + needle, needle in chg))
for needle in ['version = "1.2.8"', '__version__ = "1.2.8"']:
    facts.append(('stale absent: ' + needle, needle not in pyproj + init))

print('PHASE A -- static + hash + zero-diff proof')
bad = 0
for label, ok in facts:
    print('  %-4s %s' % ('OK' if ok else 'FAIL', label))
    bad += 0 if ok else 1
print('phase A:', 'ALL PASS' if bad == 0 else '%d FAIL' % bad)
sys.exit(1 if bad else 0)
