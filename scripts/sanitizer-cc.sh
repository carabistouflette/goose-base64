#!/usr/bin/env bash
set -euo pipefail
compiler=${SANITIZER_CC:-gcc}
sanitizers=address,undefined
extra=()
case "$("$compiler" --version)" in
    *clang*)
        # Goose links generated C with this driver even when the native package
        # contains C++. Clang needs the C++ UBSan runtime for vptr checks.
        # Request vptr explicitly: newer Clang omits it from "undefined".
        sanitizers+=,vptr
        extra+=(-fsanitize-link-c++-runtime)
        link_step=1
        for argument in "$@"; do
            case "$argument" in
                -c|-E|-S|-fsyntax-only|--version|-dumpversion|-dumpmachine) link_step=0 ;;
            esac
        done
        # The C driver does not add the C++ standard library either. The C++
        # UBSan runtime needs its RTTI helpers even for a pure C program.
        if [ "$link_step" = 1 ]; then extra+=(-lstdc++); fi
        ;;
esac
exec "$compiler" "$@" "-fsanitize=$sanitizers" "${extra[@]}" -fno-omit-frame-pointer -fno-pie -no-pie
