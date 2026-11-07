#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# The compiler must reject a call whose source slice aliases the buffer the
# call grows. This is a compile-time guarantee (§5.1), not a runtime check, so
# the library documents it instead of paying for an overlap test.
set -euo pipefail
cd "$(dirname "$0")/.."
goose=${GOOSE:-.toolchain/goose/build/goose}
work=.build/alias
mkdir -p "$work"
cat > "$work/alias.goose" <<'EOF'
import b64 from "../..";
import std;
fn main() {
    var buffer: u8[>..] = [];
    for i in 8 { buffer.push(0xfb); }
    // `buffer[..]` is a slice into the same resizable buffer that encode grows.
    b64::encode(buffer, buffer[..], b64::Policy { max_out: 64 });
}
EOF
if output=$("$goose" check "$work/alias.goose" 2>&1); then
    echo "FAIL: the compiler accepted a call whose source aliases the output buffer" >&2
    exit 1
fi
case "$output" in
    *"cannot resize out while src is still used"*) ;;
    *)
        echo "FAIL: unexpected diagnostic for the aliasing case:" >&2
        echo "$output" >&2
        exit 1
        ;;
esac
echo "Aliasing is rejected at compile time"
