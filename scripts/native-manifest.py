#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Keep included native headers in the pinned Goose package cache identity."""
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = '// Native source SHA256: '
INPUTS = ('scripts/native-manifest.py', 'scripts/sanitizer-cc.sh', 'b64_accel.cpp',
          'vendor/simdutf/simdutf.cpp', 'vendor/simdutf/simdutf.h')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'b64_accel.build'
    text = target.read_text()
    body = ''.join(line for line in text.splitlines(keepends=True)
                   if not line.startswith(MARKER)).rstrip() + '\n'
    digest = hashlib.sha256()
    for name, data in [('b64_accel.build', body.encode())] + [
            (name, (ROOT / name).read_bytes()) for name in INPUTS]:
        encoded = name.encode()
        digest.update(len(encoded).to_bytes(8, 'big') + encoded)
        digest.update(len(data).to_bytes(8, 'big') + data)
    expected = body + MARKER + digest.hexdigest() + '\n'
    if args.check:
        if text != expected:
            parser.exit(1, 'Native source fingerprint is stale; run make format.\n')
    elif text != expected:
        target.write_text(expected)


if __name__ == '__main__':
    main()
