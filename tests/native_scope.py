#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Installed toolchains and scratch files must not contribute native externs."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    goose = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='base64-native-scope-') as raw:
        root = Path(raw)
        # Use the actual package sidecar and imports with a tiny native object.
        # Foreign externs have no definitions: collecting either makes JIT fail.
        (root / 'b64_accel.build').write_bytes((ROOT / 'b64_accel.build').read_bytes())
        (root / 'vendor/simdutf').mkdir(parents=True)
        (root / 'vendor/simdutf/simdutf.cpp').write_text('// fixture\n')
        (root / 'b64_accel.cpp').write_text(
            '#include <stdint.h>\nextern "C" int64_t scope_value(void) { return 7; }\n')
        (root / 'b64_accel.goose').write_text(
            'namespace b64_accel;\nextern fn scope_value() -> i64;\n'
            'fn value() -> i64 { return scope_value(); }\n')
        (root / 'main.goose').write_text(
            'import b64_accel from ".";\nimport std;\n'
            'fn main() { print(b64_accel::value()); }\n')
        for name in ('.toolchain', '.build'):
            directory = root / name
            directory.mkdir()
            (directory / 'foreign.goose').write_text(
                'extern fn forbidden_' + name[1:] + '() -> i64;\n')
        result = subprocess.run([str(goose), 'run', 'main.goose'], cwd=root,
                                capture_output=True, text=True, timeout=60)
        if result.returncode or result.stdout.strip() != '7':
            raise RuntimeError(f'foreign native declarations collected:\n'
                               f'{result.stdout}\n{result.stderr}')
    print('native scope: toolchain and scratch externs excluded')


if __name__ == '__main__':
    main()
