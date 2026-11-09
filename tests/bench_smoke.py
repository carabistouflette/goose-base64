#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check current benchmark results without a frozen performance baseline."""
from pathlib import Path
import subprocess
import sys


def main():
    binary = Path(sys.argv[1]).resolve()
    reference = None
    implementations = ('b64', 'b64_fresh', 'strict', 'strict_fresh',
                       'b64_accel', 'b64_accel_fresh')
    for implementation in implementations:
        result = subprocess.run([str(binary), '1', implementation],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(f'{implementation}: {result.stdout}\n{result.stderr}')
        rows = {}
        lines = result.stdout.splitlines()
        if not lines or not lines[-1].startswith('checksum\t'):
            raise RuntimeError(f'{implementation}: missing final checksum')
        if int(lines[-1].split('\t')[1]) <= 0:
            raise RuntimeError(f'{implementation}: empty workload')
        for line in lines[:-1]:
            fields = line.split('\t')
            if len(fields) != 9 or fields[2] != implementation or fields[4] != '1':
                raise RuntimeError(f'{implementation}: malformed row {line!r}')
            key = tuple(fields[:2])
            if key in rows or fields[7] != '1':
                raise RuntimeError(f'{implementation}: duplicate or incomparable row {line!r}')
            rows[key] = tuple(map(int, fields[5:]))
        if len(rows) != 32:
            raise RuntimeError(f'{implementation}: expected 32 workload rows, got {len(rows)}')
        if reference is None:
            reference = rows
        elif rows != reference:
            raise RuntimeError(f'{implementation}: benchmark content differs from b64')
    print('benchmark smoke: 32 fixtures agree across six implementations/buffer modes; no timing qualification')


if __name__ == '__main__':
    main()
