#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise header-only cache invalidation with the real pinned compiler."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    goose = Path(sys.argv[1]).resolve()
    cc = sys.argv[2] if len(sys.argv) > 2 else 'gcc'
    with tempfile.TemporaryDirectory(prefix='base64-native-cache-') as raw:
        root = Path(raw)
        (root / 'scripts').mkdir()
        vendor = root / 'vendor/simdutf'
        vendor.mkdir(parents=True)
        shutil.copyfile(ROOT / 'scripts/native-manifest.py', root / 'scripts/native-manifest.py')
        (root / 'b64_accel.build').write_text(
            'c_sources = ["b64_accel.cpp", "vendor/simdutf/simdutf.cpp"];\n'
            'c_include = ["vendor/simdutf"];\n')
        (root / 'b64_accel.cpp').write_text(
            '#include <stdint.h>\n#include "simdutf.h"\n'
            'extern "C" int64_t header_value(void) { return HEADER_VALUE; }\n')
        (vendor / 'simdutf.cpp').write_text('// This fixture needs no third-party implementation.\n')
        header = vendor / 'simdutf.h'
        header.write_text('#define HEADER_VALUE 1\n')
        (root / 'b64_accel.goose').write_text(
            'namespace b64_accel;\nextern fn header_value() -> i64;\n'
            'fn value() -> i64 { return header_value(); }\n')
        (root / 'main.goose').write_text(
            'import b64_accel from ".";\nimport std;\n'
            'fn main() { print(b64_accel::value()); }\n')

        def run(*args, expected=0):
            result = subprocess.run(list(map(str, args)), cwd=root, capture_output=True,
                                    text=True, timeout=60)
            if result.returncode != expected:
                raise RuntimeError(f'{args}: exit {result.returncode}\n'
                                   f'{result.stdout}\n{result.stderr}')
            return result.stdout

        def build_value():
            run(goose, 'build', 'main.goose', '--cc', cc, '-O2', '-o', 'program')
            return run(root / 'program').strip()

        def require(condition, message):
            if not condition:
                raise AssertionError(message)

        run(sys.executable, 'scripts/native-manifest.py')
        require(build_value() == '1', 'fixture must execute the initial header value')
        header.write_text('#define HEADER_VALUE 2\n')
        run(sys.executable, 'scripts/native-manifest.py', '--check', expected=1)
        # Negative control: bypassing the stale-manifest gate reproduces the
        # pinned compiler's missing dependency on included native headers.
        require(build_value() == '1', 'negative control no longer reproduces; recheck workaround')
        run(sys.executable, 'scripts/native-manifest.py')
        run(sys.executable, 'scripts/native-manifest.py', '--check')
        require(build_value() == '2', 'refreshed fingerprint must invalidate the native cache')
        target = root / 'b64_accel.build'
        before = (target.read_bytes(), target.stat().st_mtime_ns)
        run(sys.executable, 'scripts/native-manifest.py')
        require((target.read_bytes(), target.stat().st_mtime_ns) == before,
                'refresh must be a no-op')
    print('native cache: header drift rejected, refreshed build correct, unchanged refresh is a no-op')


if __name__ == '__main__':
    main()
