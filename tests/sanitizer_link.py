#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Link instrumented C++ through the C driver and prove vptr checks run."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    wrapper = ROOT / 'scripts/sanitizer-cc.sh'
    with tempfile.TemporaryDirectory(prefix='base64-sanitizer-link-') as raw:
        root = Path(raw)
        (root / 'native.cpp').write_text(
            'struct Base { virtual int value() { return 7; } };\n'
            'extern "C" int native_value(void *p) { return static_cast<Base *>(p)->value(); }\n'
            'extern "C" void *native_object() { static Base b; return &b; }\n')
        (root / 'main.c').write_text(
            'void *native_object(void); int native_value(void *);\n'
            'int main(int argc, char **argv) {\n'
            '  long bad[8] = {0}; (void)argv;\n'
            '  return native_value(argc > 1 ? (void *)bad : native_object()) == 7 ? 0 : 1;\n'
            '}\n')
        (root / 'plain.c').write_text('int main(void) { return 0; }\n')

        def run(*args):
            return subprocess.run(list(map(str, args)), cwd=root, capture_output=True,
                                  text=True, timeout=60)

        for args in [('-O1', 'plain.c', '-o', 'plain'),
                     ('-O1', '-c', 'native.cpp', '-o', 'native.o'),
                     ('-O1', 'main.c', 'native.o', '-lstdc++', '-o', 'probe')]:
            result = run(wrapper, *args)
            if result.returncode:
                raise RuntimeError(f'C/C++ sanitizer build failed:\n{result.stderr}')
        result = run(root / 'probe')
        if result.returncode:
            raise RuntimeError(f'valid virtual call failed:\n{result.stderr}')
        # Explicit vptr diagnostics distinguish real UBSan from a plain SIGSEGV.
        result = run(root / 'probe', 'invalid')
        if result.returncode == 0 or 'invalid vptr' not in result.stderr:
            raise RuntimeError(f'vptr negative control did not trigger:\n{result.stderr}')
    print(f'sanitizer C/C++ link and vptr negative control passed ({os.environ.get("SANITIZER_CC", "gcc")})')


if __name__ == '__main__':
    main()
