"""
rttp — RTTP reference implementation (RFC-002 §4.1 framing · §10 addressing · §11 mapping)

**Zero dependencies.** Everything in the core package runs on the Python standard
library alone. The optional Ed25519 seal backend is the single exception and is
opt-in: `pip install rttp[ed25519]`.

    >>> from rttp import pulse_header, rttp_uri
    >>> parsed = rttp_uri.parse("rttp://brain.epoekie.aicent/verify")
    >>> raw = pulse_header.build_for_uri(1, 255, 1, parsed["canonical_uri"],
    ...                                  aid_origin=bytes(32))
    >>> pulse_header.verify(raw)["action"]
    'verify'

Self-check (this is the point of the package — a stranger can verify an
independent implementation in one command):

    $ python -m rttp.selftest

Modules
-------
`pulse_header`  PulseHeader128 codec — the 128-byte hardware-aligned frame header.
`rttp_uri`      `rttp` URI validation, canonicalisation and ROUTE_SHARD derivation.
`seal`          Radiant Seal, managed profile — symmetric HMAC-SHA256 over a
                pre-shared key table. Suitable for a closed set of mutually
                known roles.
`seal_asym`     Radiant Seal, sovereign profile — Ed25519, self-certifying:
                AID = SHA-256(public key), no issuance and no registry.
`aid`           Autonomous Identity derivation.

Authority boundary
------------------
* URI **syntax** — RFC-002 §10.2 ABNF. This package adds no syntax.
* Frame **layout** — RFC-002 §4.1, extended by SPEC/RTTP-FRAME-EXT-v1.2.6.md.
* Each module docstring names its own authority; where the spec is silent, the
  module says so rather than inventing a rule.
"""

from . import aid, pulse_header, rttp_uri, seal
from .pulse_header import PulseHeaderError
from .rttp_uri import RttpUriError

__version__ = "1.2.6"

#: The protocol revision this package implements. Mirrors `pulse_header.SPEC_REV`.
SPEC_REV = pulse_header.SPEC_REV

#: The RTTP specification release these vectors were generated against.
SPEC_RELEASE = "v1.2.6"

__all__ = [
    "aid",
    "pulse_header",
    "rttp_uri",
    "seal",
    "PulseHeaderError",
    "RttpUriError",
    "__version__",
    "SPEC_REV",
    "SPEC_RELEASE",
]
