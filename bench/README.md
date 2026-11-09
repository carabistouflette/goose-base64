# Base64 benchmarks

The harness measures this module against the frozen published baseline, the
equal-contract Goose competitor, the permissive standard library, and two
maintained external implementations. The recorded campaigns are in `.build/c1/`
and are reproduced by `bench/campaign.sh`.

Nothing here supports a claim of being state of the art. The numbers say the
pure-Goose `b64` is about four times faster at decoding than its own previous
release and about twice as fast as the equal-contract Goose competitor, and that
a SIMD codec is still an order of magnitude ahead of it. The optional
`b64_accel` package closes most of that distance without changing the contract;
it is measured here rather than argued about. See
[the competitive review](../docs/competitive-review-2026-11-07.md) for the
contract each comparator actually offers.

## What is compared

| Column | What it is | Classable |
| --- | --- | --- |
| `b64` | This module, pure Goose. | — |
| `b64_accel` | The optional native backend (`b64_accel.goose`), same contract, same `Policy`/`Error`, simdutf underneath. | **Yes** |
| `b64_old` | The published revision, built from the immutable source archive with the **current** harness. | **Yes** |
| `strict` | The equal-contract Goose competitor: the pinned standard library's `base64` plus the policy layer a caller has to write today to get this contract (`bench/strict.goose`). | **Yes** |
| `simdutf` | simdutf at a pinned commit, through `bench/ext/bench_ext.cpp`. | **Yes, on the padded policy** |
| `aklomp` | aklomp/base64 at a pinned commit, adapted to this contract by the harness. | **Yes, adapted** |
| `stdlib` | The pinned standard library alone. | **No** |

`b64_old` is the honest before/after. It is extracted from
`.build/baseline/baseline-src.tar.gz`, its SHA-256 is checked against
`.build/baseline/manifest.json` before it is built, and it is built with the
current harness so old and new are timed by the same fixtures, the same columns
and the same loop shape. Only the library differs. The frozen binary
`.build/baseline/bench_o2` is never overwritten; it remains the executable
identity of the published revision.

`b64_accel` is the same library with the optional native backend imported. It is
a fair race because it is the same contract: `bench/measure.py` asserts that its
content checksum equals `b64`'s on every fixture, including the rejected ones,
before any ratio is computed. Its rows are what the contract costs when the
codec underneath is SIMD; `b64`'s rows are what it costs in pure Goose.

`strict` is the fair Goose race: the same four policies, the same bytes.
`bench/strict_equivalence.goose` proves byte-for-byte agreement before any number
is recorded, and `bench/campaign.sh` runs it first.

`stdlib` is **permissive**: no URL alphabet, no unpadded text, no canonicality
check, no budget. It does strictly less work, so its rows carry `comparable` 0
and no ratio is computed from them. It is a lower bound and is labelled as one.

`simdutf` and `aklomp` are fetched at pinned commits by `bench/ext/build.sh` into
`.build/ext-src`, which is not tracked. Nothing in this repository links them.
Their contract differences are recorded in the competitive review; the short
version is that `simdutf` accepts ASCII whitespace this module rejects and cannot
express unpadded text under `strict`, and that `aklomp` has no URL alphabet, no
canonicality check and no budget, so the harness supplies all three and that
adaptation is part of the measured cost.

## Fairness rules

The harness enforces these and records them in every row:

- **One CPU, chosen once.** The measured CPU is selected by the gate below and
  then used by every implementation and every campaign. It is never re-chosen per
  implementation, because that would let each one be timed on a differently
  loaded core.
- **Equal call shapes.** Every implementation appends to a caller-owned `u8[>..]`
  buffer and takes a `const u8[:]` input. None gets a preallocated fixed buffer
  the others cannot use.
- **A `comparable` column.** `1` only where the implementation does the same work
  as `b64`.
- **Allocation is explicit, not hidden.** Reused-buffer rows amortise allocation,
  so they measure the codec. `*_fresh` rows allocate a new output buffer per
  call, so allocation and ownership cost is visible. Both are reported.
- **Inputs are built outside the timed loop.** Inside it, a three-byte content
  sample keeps each call live without adding O(n) work that would dilute the
  ratio. The full output is checksummed with FNV-1a outside the loop, so a
  wrong-but-same-length result cannot pass. A length alone would not detect it.
- **The implementation is selected once, before the loop**, into an integer, so
  the per-call dispatch is an integer compare rather than a string compare. All
  implementations pay it equally.
- **Varied sizes.** 0, 1, 2, 3, 4, 16, 64, 256, 1024, 4096 and 65536 bytes, which
  covers every group-boundary case and three orders of magnitude. No row is
  reported on length alone: every row carries its content checksum.
- **Invalid and pathological inputs.** Non-canonical trailing bits, an invalid
  character, embedded whitespace, wrong padding, URL-safe unpadded text, a 64 KiB
  text whose last byte is invalid (forces full validation before rejection), and
  64 KiB of `A` (valid, worst case for the validating decoder).
- **The consumer end of the path.** An HTTP Basic header value (RFC 7617 §2),
  built end to end, for both implementations that offer this contract.

## The contention gate

The previous protocol refused to measure when the machine's absolute load
average exceeded 0.5. On an eight-core machine that is not a test of contention:
a load average of 3.5 can leave the measured core idle, and a load average of 0.4
can leave it busy. The old rule is preserved in
[benchmark-protocol.md](../docs/benchmark-protocol.md) as superseded, with the
reason.

The gate now decides from the measured core itself:

1. **Choose the CPU once**, as the least busy over a 2 s `/proc/stat` window,
   unless `--cpu` names one. The choice and every core's busy fraction are
   recorded.
2. **Chosen-CPU busy fraction ≤ 0.30** — an absolute ceiling that catches a
   genuinely loaded core.
3. **Chosen-CPU busy fraction within 0.05 of the least busy CPU** — the criterion
   that actually decides. It is relative on purpose: on this host every core
   carries the desktop's own work, so the floor is around 0.11 and an absolute
   threshold of 0.10 is unsatisfiable even on an otherwise idle machine.
4. **PSI `cpu some avg60` ≤ 5.0**, so the machine as a whole is not stalled.
5. **Jitter calibration CV ≤ 0.10.** A calibration workload runs before the
   samples and its coefficient of variation must be at or below the threshold.
   This is the direct test the load average was standing in for: it measures the
   timing noise the campaign will actually experience. The busy fraction is a
   proxy for that noise; the calibration measures it.

The busy-fraction criteria and the 0.10 CV are **practical resolution thresholds,
not statistical guarantees**. They say "this campaign can resolve the differences
it reports"; they do not say the ratios are exact, and a stricter threshold would
not make them exact. The calibration is taken again after the samples, and both
endpoints are recorded, because a machine that was quiet at the start and busy at
the end produces a campaign that looks fine and is not. The endpoint limitation is
named rather than hidden: two calibration points bound the noise at the ends of
the run, not continuously.

A run that fails the gate is still written, with `status: "rejected"` and its raw
samples kept, so a failed campaign is evidence about the machine rather than a
lost file. `--exploratory` records a run that fails the gate as a labelled
diagnostic.

## Identity snapshots

Every campaign snapshots the identity of everything it measures **before** the
first sample and again **after** the last:

- the effective source identity: repository root, whether that root is this
  directory, HEAD, and the SHA-256 of every measured source file;
- the compiler revision and the **compiler binary** SHA-256;
- the SHA-256 of every measured binary, including the `--alias` frozen baseline;
- the **runtime header** SHA-256s — there is no shared libgoose, the runtime is
  inlined into the generated C, so those hashes are part of the identity of the
  measured binary;
- the competitor's `base64.goose` and `std.goose` SHA-256;
- the external comparators' identity from `.build/ext/identity.json`;
- the ISA feature set and the CPU topology.

If the before and after snapshots differ, the raw samples are kept and the
campaign is written with `status: "rejected"`. A binary that changed under the
measurement is not a measurement.

## Running it

Run alone, with no other CPU work on the machine:

```sh
bench/campaign.sh .build/c1/campaign-confirm.json
```

Environment: `GOOSE` (default `.build/goose`), `CC` (default `gcc`),
`BENCH_ITERATIONS` (default 1000), `BENCH_SAMPLES` (default 21), `BENCH_CPU`
(default: chosen by the gate).

The script verifies the baseline manifest, extracts and verifies the archived
`b64.goose`, builds the frozen baseline with the current harness, runs the
strict-equivalence check, builds the current library and the external harness,
then runs `bench/measure.py`, which:

- pins the process to one CPU with `sched_setaffinity`;
- runs **21 samples**, discards one warmup and keeps **20 measured samples**;
  fewer than 21 is refused;
- runs **one process per implementation per sample**, and **alternates the order**
  forward and reverse between samples, so no implementation is always measured
  first and charged for cold caches and frequency ramp-up;
- asserts the row structure, that `b64` and `strict` agree on every
  `(input_len, output_len, checksum)`, that `stdlib` agrees wherever it does the
  same work, and that content is identical across all 21 samples — a mismatch is
  fatal, because it would invalidate the comparison;
- reports **dispersion**, not a single number: median, mean, min, max, p10, p90,
  IQR, MAD, standard deviation and coefficient of variation, per row;
- reports both a **ratio of medians** and a **median of paired per-sample
  ratios**, the latter being more robust to drift, with a **bootstrap 95%
  interval** on the paired median and a `resolved` flag that is true only when
  the interval excludes 1.0;
- reports **peak RSS per implementation**, taken from the child's own
  `ru_maxrss` via `os.wait4`, so the memory figure belongs to that implementation
  rather than being the maximum over every child;
- keeps every **raw sample** in the JSON, not just the summary;
- writes the output JSON and prints the ratios.

Keep the JSON with its provenance. A number without the record is not a result.

## What the numbers mean, and what they do not

They are warm-process medians of repeated calls on prebuilt inputs, on one
machine, without exclusive CPU isolation. They are not cold latency, allocation
counts, or a universal ranking.

Two results are expected and are not defects:

- `encode` is unchanged by the `value_of` work, so its rows against `b64_old` and
  `strict` come out **unresolved** — their intervals contain 1.0. That is the
  correct outcome for code that did not change, and it is reported as unresolved
  rather than as "no difference", because the campaign cannot distinguish a small
  difference from none.
- `decode` is faster than `strict` because both now classify bytes through the
  same table, and the difference is structural: this module validates the input
  completely before writing and then writes, while `strict` validates, calls the
  standard library's decoder and then normalises the result. The two-pass shape
  is the price of rejection before mutation, and it is a documented contract
  rather than an accident.

No claim of being state of the art follows from these numbers. They compare one
contract against an equal-contract Goose competitor, a frozen previous release,
two adapted external implementations and one labelled lower bound, on one
machine.
