#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# `src` must not alias `out`. This script pins what the compiler actually
# enforces, per function, so the documented guarantee is checked rather than
# assumed.
#
#   encode: the compiler rejects the call statically (§5.1), because the
#           delegated standard-library encoder resizes `out` while `src` is
#           still live.
#   decode: the compiler accepts it. The write pass grows `out` with `push`,
#           which the §5.1 check does not flag, so non-aliasing is a caller
#           requirement there and not a compile-time guarantee.
#
# If either behaviour changes, this script fails and the README, docs/design.md
# and this comment must be updated together.
set -euo pipefail
cd "$(dirname "$0")/.."
goose=${GOOSE:-.toolchain/goose/build/goose}
work=.build/alias
mkdir -p "$work"

# Write a probe that passes a slice of the buffer being grown as the source.
probe() {
    local function=$1 path=$2
    cat > "$path" <<EOF
import b64 from "../..";
import std;
fn main() {
    var buffer: u8[>..] = [];
    for i in 8 { buffer.push(0x41); }
    // \`buffer[..]\` is a slice into the same resizable buffer the call grows.
    b64::$function(buffer, buffer[..], b64::Policy { max_out: 64 });
}
EOF
}

probe encode "$work/alias_encode.goose"
if output=$("$goose" check "$work/alias_encode.goose" 2>&1); then
    echo "FAIL: the compiler accepted encode() with a source that aliases the output buffer" >&2
    exit 1
fi
case "$output" in
    *"cannot resize out while src is still used"*) ;;
    *)
        echo "FAIL: unexpected diagnostic for the aliasing encode() case:" >&2
        echo "$output" >&2
        exit 1
        ;;
esac
echo "encode: aliasing is rejected at compile time"

probe decode "$work/alias_decode.goose"
if output=$("$goose" check "$work/alias_decode.goose" 2>&1); then
    echo "decode: aliasing is accepted by the compiler, so non-aliasing is a"
    echo "        documented caller requirement rather than a static guarantee"
else
    echo "FAIL: the compiler now rejects decode() aliasing, which is an improvement," >&2
    echo "      but the documentation still says only encode() is enforced." >&2
    echo "      Update README.md, docs/design.md and this script together:" >&2
    echo "$output" >&2
    exit 1
fi
