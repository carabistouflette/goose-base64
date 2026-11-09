#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# One benchmark campaign: the frozen baseline, the current library, the
# equal-contract Goose competitor, the permissive standard library, and the two
# external comparators, all on one fixed CPU.
#
# Run this alone, with no other CPU work on the machine, and keep the recorded
# JSON with its provenance. The contention gate inside bench/measure.py decides
# whether the run is evidence or a labelled diagnostic.
#
# Usage: bench/campaign.sh <output.json> [extra measure.py options]
set -euo pipefail

# This shell inherits a tool-specific libstdc++ that is older than the system
# one, which makes clang fail to start with a GLIBCXX version error. That is a
# property of the shell, not of the library, so the campaign drops it rather
# than requiring every caller to remember `env -u LD_LIBRARY_PATH`.
unset LD_LIBRARY_PATH

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

output=${1:?usage: bench/campaign.sh <output.json> [options]}
shift || true

GOOSE=${GOOSE:-.build/goose}
CC=${CC:-gcc}
ITERATIONS=${BENCH_ITERATIONS:-1000}
SAMPLES=${BENCH_SAMPLES:-21}
CPU=${BENCH_CPU:-}

# The frozen baseline must still be the frozen baseline. Measuring it after it
# was overwritten would compare the current code with itself.
( cd .build/baseline && sha256sum -c MANIFEST.sha256 >/dev/null )
echo "baseline manifest verified"

mkdir -p .build

# The old implementation is taken from the frozen source archive, not from the
# working tree, and its hash is checked against the manifest before it is built.
# It is then built with the *current* harness, so old and new are timed by the
# same fixtures, the same columns and the same loop shape; only the library
# differs. The frozen binary .build/baseline/bench_o2 is left untouched and is
# still the executable identity of the published revision.
old=.build/old-harness
rm -rf "$old"
mkdir -p "$old/bench"
tar -xzf .build/baseline/baseline-src.tar.gz -C "$old" b64.goose
expected=$(python3 -c 'import json;print(json.load(open(".build/baseline/manifest.json"))["tracked_files"]["b64.goose"]["worktree_sha256"])')
actual=$(sha256sum "$old/b64.goose" | cut -d" " -f1)
if [ "$expected" != "$actual" ]; then
    echo "the archived b64.goose is $actual, the manifest says $expected" >&2
    exit 1
fi
echo "archived b64.goose verified: $actual"
cp GOOSE_REVISION "$old/"
# The current harness imports the optional native backend, so the old tree needs
# that package too. It is copied unchanged and its own `import b64 from "."`
# then resolves to the archived b64.goose, which is what the old rows measure.
cp b64_accel.goose b64_accel.build b64_accel.cpp "$old/"
cp -r vendor "$old/"
cp bench/bench.goose bench/strict.goose "$old/bench/"
"$GOOSE" build "$old/bench/bench.goose" --cc "$CC" -O2 -o "$old/bench-old"

# The equal-contract competitor must agree with the library byte for byte before
# any number is recorded.
"$GOOSE" build bench/strict_equivalence.goose --cc "$CC" -O2 -o .build/strict-equivalence
./.build/strict-equivalence

"$GOOSE" build bench/bench.goose --cc "$CC" -O2 -o .build/bench
./bench/ext/build.sh

cpu_args=()
if [ -n "$CPU" ]; then cpu_args=(--cpu "$CPU"); fi

BENCH_CC="$CC" python3 bench/measure.py \
    --binary .build/bench \
    --external-binary .build/ext/bench-ext \
    --external-identity .build/ext/identity.json \
    --alias "b64_old=$old/bench-old:b64" \
    --iterations "$ITERATIONS" \
    --samples "$SAMPLES" \
    --goose "$GOOSE" \
    --output "$output" \
    "${cpu_args[@]}" "$@"
