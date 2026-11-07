# Base64 benchmarks

**No measurement has been recorded yet.** The harness is written, compiles, and
has been smoke-tested for structure and content only. It has deliberately not
been run for timing, because measurements are taken one at a time with no other
CPU work in flight. Nothing in this repository makes a performance claim.

## What is compared

Three implementations, one row each:

| Column | What it is | Classable |
| --- | --- | --- |
| `b64` | This module. | — |
| `strict` | The equal-contract competitor: the pinned standard library's `base64` plus the policy layer a caller has to write today to get this contract (`bench/strict.goose`). | **Yes** |
| `stdlib` | The pinned standard library alone. | **No** |

`strict` is the only fair race. It is the standard library's codec wrapped in the
same four policies this module implements — standard/URL alphabet, padded and
unpadded text, canonicality, and the output budget — so both sides do the same
work and produce the same bytes. `bench/strict_equivalence.goose` proves that
byte-for-byte agreement before any number is recorded, and `make bench` runs it
first.

`stdlib` is the maintained, fast codec, and it is the code this module reuses on
the compatible path. But it is **permissive**: no URL alphabet, no unpadded text,
no canonicality check, no budget. It does strictly less work, so its rows carry
`comparable` 0 and no ratio is computed from them. It is reported as a lower
bound and labelled as such. Racing it and calling the result a win would be
comparing a parser to a DOM.

The harness makes that difference visible rather than asserting it. On the
current fixtures `b64` and `strict` agree on every `(input_len, output_len,
content checksum)`, and `stdlib` agrees on every valid input — so the codec
really is the same work there — and diverges on exactly one fixture,
`reject/noncanonical`, where it accepts `Zh==` and this module refuses it.

## Fairness rules

The harness enforces these and records them in every row:

- **Equal call shapes.** All three append to a caller-owned `u8[>..]` buffer and
  take a `const u8[:]` input. None is given a preallocated fixed buffer the
  others cannot use.
- **A `comparable` column.** It is `1` only where the implementation does the
  same work as `b64`, so only `strict` rows produce a ratio.
- **Allocation is explicit, not hidden.** Reused-buffer rows (`b64`, `strict`,
  `stdlib`) amortise allocation, so they measure the codec. `*_fresh` rows
  allocate a new output buffer per call, so allocation and ownership cost is
  visible. Both are reported; neither is presented alone.
- **Inputs are built outside the timed loop.** Inside it, a three-byte content
  sample keeps each call live without adding O(n) work that would dilute the
  ratio. The full output is checksummed with FNV-1a outside the loop, so a
  wrong-but-same-length result cannot pass. A length alone would not detect it.
- **The implementation is selected once, before the loop**, into an integer, so
  the per-call dispatch is an integer compare rather than a string compare. All
  three pay it equally.
- **Varied sizes.** 0, 1, 2, 3, 4, 16, 64, 256, 1024, 4096 and 65536 bytes,
  which covers every group-boundary case and three orders of magnitude.
- **Invalid and pathological inputs.** Non-canonical trailing bits, an invalid
  character, embedded whitespace, wrong padding, URL-safe unpadded text, a
  64 KiB text whose last byte is invalid (forces full validation before
  rejection), and 64 KiB of `A` (valid, worst case for the validating decoder).
- **The consumer end of the path.** An HTTP Basic header value (RFC 7617 §2),
  built end to end, for both implementations that offer this contract.

## Running it

Run alone, with no other CPU work on the machine:

```sh
make bench BENCH_ITERATIONS=1000
```

This builds and runs the equivalence check, builds `.build/bench`, then runs
`bench/measure.py`, which:

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
- reports **peak RSS per implementation**, taken from the child's own
  `ru_maxrss` via `os.wait4`, so the memory figure belongs to that
  implementation rather than being the maximum over every child;
- reports both a **ratio of medians** and a **median of paired per-sample
  ratios**, the latter being more robust to drift;
- records full provenance: platform, CPU model, affinity CPU, Python version,
  iterations, samples, the order policy and the actual order used, compiler
  revision and **compiler binary SHA-256**, C compiler and version, build flags,
  benchmark binary SHA-256, the effective source identity (repository root,
  whether that root is this directory, HEAD, SHA-256 of every measured source
  file, dirty flag), the **competitor's** `base64.goose` and `std.goose`
  SHA-256, and the **runtime header** SHA-256s — there is no shared libgoose, the
  runtime is inlined into the generated C, so those hashes are part of the
  identity of the measured binary;
- keeps every **raw sample** in the JSON, not just the summary;
- writes `.build/benchmark.json` and prints the ratios.

Keep the JSON with its provenance. A number without the record is not a result.

## What the numbers will and will not mean

They will be warm-process medians of repeated calls on prebuilt inputs, on one
machine, without exclusive CPU isolation. They will not be cold latency,
allocation counts, a confidence interval, or a universal ranking.

Two results are expected and are not defects:

- On the compatible path, `encode` should be close to `strict`, because both
  delegate whole 3-byte groups to the same codec; the difference is the final
  group and the URL-alphabet rewrite.
- `decode` should be slower than `strict` only if the validation pass costs more
  than the policy layer it replaces. This module validates the input completely
  before writing and then writes, so a refusal never mutates the output; that is
  the cost of rejection before mutation, and it is a documented contract rather
  than an accident. Whether it is worth paying is a question for the recorded
  numbers, not for this file.

No claim of being state of the art follows from these numbers. They compare one
contract against one equal-contract competitor and one labelled lower bound on
one machine.
