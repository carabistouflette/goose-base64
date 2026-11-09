#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Build the external comparators at their pinned revisions.
#
# Nothing here is vendored into this repository: the sources are fetched at the
# exact commits recorded in bench/ext/README.md, built, and hashed into
# .build/ext-identity.json so a report can name what it raced.
#
# Usage: bench/ext/build.sh [--sanitize]
set -euo pipefail

# The external comparators are a fixed reference, not part of the portability
# comparison, so they are always built with the same compiler regardless of the
# campaign's CC. Inheriting CC=clang here would rebuild them differently in the
# clang campaign and make the two campaigns incomparable.
unset LD_LIBRARY_PATH
CC=gcc
CXX=g++
export CC CXX

# The sanitizer build exists to prove the fast path's output buffer is sized
# correctly. It is a separate binary so the measured one stays uninstrumented.
SANITIZE=0
for arg in "$@"; do
    case "$arg" in
        --sanitize) SANITIZE=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done
SAN_FLAGS=()
OUT_NAME=bench-ext
if [ "$SANITIZE" = 1 ]; then
    SAN_FLAGS=(-fsanitize=address,undefined -fno-sanitize-recover=all -g -O1)
    OUT_NAME=bench-ext-sanitize
fi

SIMDUTF_COMMIT=4ab2be54f0b41536d5258675ffad7ba5d10fe384
AKLOMP_COMMIT=5d5074cb856b9a53fe64f04ddf47812a85f4fb5a

root=$(cd "$(dirname "$0")/../.." && pwd)
work="$root/.build/ext-src"
out="$root/.build/ext"
mkdir -p "$work" "$out"

fetch() {
    local url=$1 commit=$2 dir=$3
    if [ ! -d "$work/$dir/.git" ]; then
        git clone --filter=blob:none "$url" "$work/$dir"
    fi
    git -C "$work/$dir" fetch --quiet origin "$commit" 2>/dev/null || true
    git -C "$work/$dir" checkout --quiet "$commit"
    test "$(git -C "$work/$dir" rev-parse HEAD)" = "$commit"
}

fetch https://github.com/simdutf/simdutf.git "$SIMDUTF_COMMIT" simdutf
fetch https://github.com/aklomp/base64.git "$AKLOMP_COMMIT" aklomp

# simdutf's own amalgamation, so the build is one translation unit.
( cd "$work/simdutf" && python3 singleheader/amalgamate.py >/dev/null )

# aklomp's own Makefile, so each architecture codec is built with the flags it
# needs (the AVX2 and AVX-512 codecs are separate objects).
( cd "$work/aklomp" && make -j1 lib/libbase64.o >/dev/null )

g++ -std=c++17 -O2 "${SAN_FLAGS[@]}" \
    -I"$work/simdutf/singleheader" -I"$work/aklomp/include" \
    "$root/bench/ext/bench_ext.cpp" \
    "$work/simdutf/singleheader/simdutf.cpp" \
    "$work/aklomp/lib/libbase64.o" \
    -o "$out/$OUT_NAME" -pthread

python3 - "$work" "$out" "$SIMDUTF_COMMIT" "$AKLOMP_COMMIT" "$OUT_NAME" <<'PY'
import hashlib, json, pathlib, subprocess, sys
work, out, simdutf_commit, aklomp_commit, out_name = sys.argv[1:6]

def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

def head(directory):
    return subprocess.check_output(["git", "-C", directory, "rev-parse", "HEAD"],
                                   text=True).strip()

identity = {
    "simdutf": {
        "url": "https://github.com/simdutf/simdutf",
        "commit": head(f"{work}/simdutf"),
        "requested_commit": simdutf_commit,
        "version": "9.3.3",
        "amalgamation_sha256": sha256(f"{work}/simdutf/singleheader/simdutf.cpp"),
        "header_sha256": sha256(f"{work}/simdutf/singleheader/simdutf.h"),
        "options": {
            "encode": "base64_default (standard alphabet, padded)",
            "decode": "base64_default + last_chunk_handling_options::strict",
            "strict_means": "rejects non-zero trailing bits (BASE64_EXTRA_BITS) "
                            "and a partial final chunk (BASE64_INPUT_REMAINDER)",
        },
    },
    "aklomp": {
        "url": "https://github.com/aklomp/base64",
        "commit": head(f"{work}/aklomp"),
        "requested_commit": aklomp_commit,
        "object_sha256": sha256(f"{work}/aklomp/lib/libbase64.o"),
        "options": {
            "encode": "base64_encode, flags 0 (runtime codec choice)",
            "decode": "base64_decode, flags 0, after this harness's own "
                      "validation, canonicality check and budget",
        },
    },
    "harness": {
        "source_sha256": sha256("bench/ext/bench_ext.cpp"),
        "binary_sha256": sha256(f"{out}/{out_name}"),
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "flags": "-std=c++17 -O2",
    },
}
pathlib.Path(f"{out}/identity.json").write_text(json.dumps(identity, indent=2) + "\n")
print(f"wrote {out}/identity.json")
PY

echo "built $out/$OUT_NAME"
