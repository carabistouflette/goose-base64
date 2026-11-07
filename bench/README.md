# Base64 benchmarks

**No measurement has been recorded yet.** The harness is written and compiles;
it has deliberately not been run, because measurements are taken one at a time
with no other CPU work in flight. Nothing in this repository makes a performance
claim.

## What is compared

This module against the pinned standard library's `base64` module. The standard
library is the maintained competitor and the code this module reuses on the
compatible path, so the comparison is against the thing it replaces rather than
against an abandoned alternative.

## Fairness rules

The harness enforces these and records them in every row:

- **Equal call shapes.** Both implementations append to a caller-owned
  `u8[>..]` buffer and take a `const u8[:]` input. Neither is given a
  preallocated fixed buffer the other cannot use.
- **A `comparable` column.** It is `1` only where both do the same work. The
  `reject` rows are `0`: this module adds the canonicality check and the budget,
  so it does strictly more work there and no ratio is computed.
- **Allocation is explicit, not hidden.** Reused-buffer rows (`b64`, `stdlib`)
  amortise allocation, so they measure the codec. `b64_fresh` and
  `stdlib_fresh` rows allocate a new output buffer per call, so the allocation
  and ownership cost is visible. Both are reported; neither is presented alone.
- **Inputs are built outside the timed loop.** Inside it, a three-byte content
  sample keeps each call live without adding O(n) work that would dilute the
  ratio. The full output content is summed outside the loop, so a
  wrong-but-same-length result cannot pass. Both are identical work for both
  implementations, so they inflate both equally.
- **Varied sizes.** 0, 1, 2, 3, 4, 16, 64, 256, 1024, 4096 and 65536 bytes,
  which covers every group-boundary case and three orders of magnitude.
- **Invalid inputs.** Non-canonical trailing bits, an invalid character,
  embedded whitespace, wrong padding and URL-safe unpadded text.

## Running it

Run alone, with no other CPU work on the machine:

```sh
make bench BENCH_ITERATIONS=1000
```

This builds `.build/bench` and runs `bench/measure.py`, which:

- pins the process to one CPU with `sched_setaffinity`;
- runs 21 processes, discards one warmup and keeps **20 measured runs**; fewer
  than 21 is refused;
- asserts the row structure, and that both the liveness checksum and the full
  content checksum are identical across all 21 processes, so the work and the
  output are deterministic;
- reports the median of the per-process averages, not a median of individual
  calls;
- records platform, CPU model, affinity CPU, iterations, samples, compiler
  revision, C compiler and version, build flags and the benchmark binary
  SHA-256;
- records the **effective** source identity: the repository root Git resolves
  here, whether that root is this directory, its HEAD, the SHA-256 of every
  measured source file, and whether the tree is dirty. This directory can be
  nested inside another repository, so an enclosing HEAD is not the identity of
  the code under test; `repo_root_is_library` makes that visible instead of
  silently attributing results to the wrong commit;
- writes `.build/benchmark.json` and prints the medians and the
  `b64_over_stdlib` ratios.

Keep the JSON with its provenance. A number without the record is not a result.

## What the numbers will and will not mean

They will be warm-process medians of repeated calls on prebuilt inputs, on one
machine, without exclusive CPU isolation. They will not be cold latency,
allocation counts, a confidence interval, or a universal ranking. The
`b64_over_stdlib` ratio is a ratio of medians, not a median of pairwise ratios.

Two results are expected and are not defects:

- On the compatible path, `encode` should be close to the standard library,
  because whole 3-byte groups are delegated to it; the difference is the final
  group and the URL-alphabet rewrite.
- `decode` should be slower than the standard library, because it validates the
  input completely before writing and then writes, while the standard library
  writes as it validates. That is the cost of rejection before mutation, and it
  is a documented contract rather than an accident.
