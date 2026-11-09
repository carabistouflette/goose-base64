# Validation history

What was executed, with the exact commands and results, and what was not.

The performance campaigns cited here are historical dirty-tree observations.
Their `accepted` status is a runner outcome, not a clean-source qualification.
See the [attribution limits](competitive-review-2026-11-07.md#historical-dirty-tree-scope)
before applying their ratios to a checkout or release. A named `source_revision`
alone does not reconstruct the measured inputs; no new timing is reported here.

## Provenance

| Item | Value |
| --- | --- |
| Goose compiler | `goose eadca40 (runtime 3025e5810379)`, revision `eadca409f68210893f366e60d0c2f0dc29a339be` |
| Compiler binary SHA-256 | `3cad45a18356bf97f4732f1da2012252afd77a652932ddb9c91c5551c04904be` |
| Compiler source | https://github.com/aardappel/goose at `eadca409f68210893f366e60d0c2f0dc29a339be`, reused unmodified and not rebuilt |
| C compiler | `gcc (GCC) 16.2.1 20260810`, `clang version 23.1.4` |
| Platform | `Linux 7.2.11-arch1-1 x86_64` |
| Python | 3.14.9 |
| `b64.goose` SHA-256 | `9e837f5f87497f035c21803818f415d32c39b64cd7bb1579b3bc7ae4813f84b4` |
| `b64_accel.goose` SHA-256 | `605eae0f6f0f6cb35acbd705903bfe29cdad0f527f86d7fc7f6157d7196ffd4f` |
| `b64_accel.build` SHA-256 | `9a7d7fce376f00e1e377b570ae7fafd626e57f6246ddd6d0188caa33d1ba2329` |
| `b64_accel.cpp` SHA-256 | `667a3a7b16693542b465ef05414064b353f36d106f785c8e78216c51a08b86ac` |
| `vendor/simdutf/simdutf.cpp` SHA-256 | `4bde76376475d5730c73eb93dee340533c0eea82ea5f33855d6ba216d98f6377` |
| `vendor/simdutf/simdutf.h` SHA-256 | `f49d70bedaa6814c36e1edd1866699d01472669eeaafa1729cf02607578b79b3` |
| `tests/accelerated.goose` SHA-256 | `771b5790cb2b9e2a5f8ca4f63aec2abafa84769e1c8950f780496987d87b1fbb` |
| `tests/oracle.py` SHA-256 | `11fdff7f03d328730c3c54427f9f6000987bc93170e36f4a3f9fdd793f3a06fe` |
| `tests/fuzz.goose` SHA-256 | `5eb73db5b37be17e1e63e75dd146aff4f7ee4d0863004edba57234f389267f98` |
| `tests/fuzz.c` SHA-256 | `b911d846dbb795df844a78631283526b7761503c0224c7bc04476298d46cb1bc` |
| `tests/api.goose` SHA-256 | `ff3f446ea021163cc8f48b079c13e5714a96dacbb39e7a74fafde71a5e4f34bc` |
| `bench/bench.goose` SHA-256 | `ad23667bbd6554ac28c0ab726c5e1a2577a4798416e6fc15d296f7df470e03a2` |
| `bench/strict.goose` SHA-256 | `2ba31ff04457a7bc7631a75a3379d33b696dd4afa7bbbbfc0ec3e19c8b41ec8c` |
| `bench/strict_equivalence.goose` SHA-256 | `e12837750c444c6cc52b420a7dda8c145c605aaf1f92fabd82a29c88237977d8` |
| `bench/measure.py` SHA-256 | `4bb405cfe5e1404c084e2d2afa73b82aeceb84204ae9a3be373887377292b27c` |
| `bench/campaign.sh` SHA-256 | `fea23b02c0206a07bedcc6c346984f9f3bf1c5381929c9287ca133eecc122570` |
| `bench/ext/bench_ext.cpp` SHA-256 | `511f9e305dc488e99bdc7a2bf11c36bb7c83f983641ddfa79a8fc1cc011acab1` |
| `bench/ext/build.sh` SHA-256 | `8000c1658fa10222ef1be05730c5948014b75273b826e27023c340fb14fec641` |
| `scripts/mutation-test.py` SHA-256 | `12dd0ffc949bcb1ebb735442cc2f638e64a3366166a7b0472b3bdcfccb77a6a3` |
| `scripts/fuzz.py` SHA-256 | `a516377bec3b2b2d53e6808286268fc4f1469f778f56195bb4dcf41c82d6e41a` |
| `Makefile` SHA-256 | `c24d545f41f82e3acf27b6c6e5cdee245f0518886ee70c7074ea2962edf64814` |

The published baseline `b64.goose` is `98e0432e2bf0fc61defc50ab12ceecae243838da1b0f99747dbe7b8519ce1231`,
which is the hash recorded in `.build/baseline/MANIFEST.sha256`. The current file
is `9e837f5f…`; the difference is the `value_of` table described in
[design.md](design.md#decoding-shape).

The compiler was not rebuilt. `make setup` was not run in this workspace, so the
standalone-clone quickstart's compiler build is unverified here; every command
below passed an explicit `GOOSE=` pointing at the shared pinned binary.

There is no shared `libgoose`. The generated C includes the runtime headers
directly, so those headers are part of the identity of every binary measured or
fuzzed here: `goose.h 51234daf…`, `runtime.h 5e744690…`, `runtime_impl.h
f95d3d33…`, `runtime_os.h 196308b8…`, `runtime_ext.h d50f3c7e…`,
`runtime_threads.h f7540e51…`, `runtime_inline.h 94e4e629…`. `ldd` on the
benchmark binary reports only `linux-vdso.so.1`, `libm.so.6`, `libc.so.6` and
`/lib64/ld-linux-x86-64.so.2`.

## Executed

All commands ran from the library root, with `env -u LD_LIBRARY_PATH` because
this shell inherits a tool-specific `libstdc++` older than the system sanitizer
runtimes. That is a property of the shell, not of the library.

### `make check GOOSE=<pinned>`

Passed. `goose format --check` over `b64.goose`, `tests`, `examples` and `bench`;
`goose check` on all ten Goose files, including `bench/strict.goose` and
`bench/strict_equivalence.goose`; `python3 -m py_compile` on `tests/oracle.py`,
`bench/measure.py` and every `scripts/*.py`; `git diff --check`.

### `make test GOOSE=<pinned>`

Passed in **10.92 s**, peak RSS 762 MiB. In order:

- `goose run tests/api.goose` — public API, RFC 4648 §10 vectors, all four
  policy combinations, the error taxonomy and its precedence, budget
  boundaries, failure atomicity, exhaustive trailing-bit acceptance counts,
  append accumulation, budget counting appended bytes only, no retained
  reference to the input, `decoded_len` as a shape-only helper, truncation
  and corruption, and `every_byte_is_classified` — all 256 byte values under
  both alphabets, asserting that exactly the 64 characters of the selected
  alphabet are accepted and every other byte is rejected as
  `InvalidCharacter` or `InvalidPadding`. That test exists because the value
  table is now data: a wrong entry is a silent acceptance, and no generated
  corpus reaches a byte outside its own pool.
- `goose run tests/stdlib_parity.goose` — byte-identical encode and decode
  against the standard library for every length 0..299, plus the divergence
  counts (standard library accepts 64 of 64 final characters, this module 4 for
  a two-character tail and 16 for a three-character tail).
- `goose run tests/alias_decode_lifetime.goose` — aliased `decode` with a
  growth-forcing input.
- `goose run examples/basic_auth.goose` and `examples/json_binary.goose`.
- `goose build tests/api.goose -O2` and `--debug --no-bce`, both executed.
- `tests/alias_rejected.sh` — see *Aliasing* below.
- `goose build tests/oracle.goose -O2` then `python3 tests/oracle.py`:
  **940,496 differential cases passed**.

### `make property GOOSE=<pinned>`

Passed in **13.39 s**, peak RSS 820 MiB. The same 940,496 cases against a
`--debug --no-bce` build (bounds checks kept, overflow and range checks on),
plus the parity test built the same way.

### `make sanitize GOOSE=<pinned> SANITIZER_CC=gcc`

Passed. ASan + UBSan, `--standalone --debug --no-bce`, on the API test, the full
940,496-case differential corpus, both examples, the aliased-decode lifetime
test, and the accelerated differential (`tests/accelerated.goose`, built
`--standalone -O1 --no-bce` so the vendored simdutf is instrumented too), with
`ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1`. Log: `.build/c1/verify-sanitize.log`.

### `make sanitize GOOSE=<pinned> SANITIZER_CC=clang`

Passed, same targets and options with Clang 23.1.4. Log:
`.build/c1/verify-sanitize.log`.

The accelerated differential is the one that matters for the native part: it is
the only run in which simdutf's own writes into the builder's free region are
instrumented, and it covers the exact-capacity case (the builder's top is the
output buffer, `outlen == need`) rather than a padded scratch.

### Extended differential probe

Beyond the committed corpus, a separate probe ran **1,968,428 further cases**
against the same oracle in 5.82 s with **0 mismatches**:

| Group | Cases |
| --- | --- |
| `all_2_byte_decode` — every 2-byte text over each alphabet plus outsiders, all four policies | 262,144 |
| `wide_3_byte_decode` — a wide 3-byte pool over each alphabet | 1,687,500 |
| `equals_positions_4` — `=` in every position of 4-byte texts | 16,000 |
| `long_invalid_positions` — 256/1024/4096/65536-byte texts with an invalid byte at the beginning, middle and end, plus truncations | 464 |
| `budget_sweep` — budget from 0 to need+2 on every policy | 720 |
| `length_agreement` — `decoded_len` against the real decoded length, 0..399 | 1,600 |

Combined with the committed corpus that is **2,908,924 differential cases with
zero mismatches**.

## Differential corpus

`tests/oracle.py` builds 940,496 cases and compares every result against an
independent Python computation: Python's own `base64` module for the bit work,
plus a separate canonicality check that re-encodes the decoded bytes and
requires the text to be reproduced exactly.

| Group | Cases |
| --- | --- |
| `exhaustive_1_2_byte_encode` — every 1-byte and 2-byte input, all four policies | 263,168 |
| `group_boundary_encode` — sizes 0-13 across group boundaries, all four policies | 52 |
| `random_length_encode` — random lengths 0-5000 | 4,000 |
| `encode_budget_boundaries` — `need-1`, `need`, `need+1`, 0, -1, i64 min/max | 280 |
| `roundtrip_and_mutations` — valid round-trips, decode budget boundaries, single-byte and length mutations, every non-canonical trailing-bit value | 487,592 |
| `exhaustive_short_decode` — every 1-, 2- and 3-character text over each alphabet plus outsiders | 185,136 |
| `whitespace_positions` — whitespace and control bytes at every position of a valid text | 252 |
| `long_texts` — long valid texts and their truncations | 16 |
| **Total** | **940,496** |

The breakdown is printed by `tests/oracle.py` on every run, so it is checked
rather than transcribed. The corpus is deterministic: `random.Random(20261107)`,
no wall-clock or environment input.

## Fuzzing

`tests/fuzz.goose` is a libFuzzer target that calls the **real Goose API** —
`b64::encode`, `b64::decode` and the length helper — not the C backend and not a
reimplementation. `tests/fuzz.c` is the driver; `scripts/fuzz.py` builds and
runs it.

The target asserts, on every input: exact output counts, round-trip identity,
canonicality by re-encoding, that a rejection leaves the output buffer empty,
error precedence, byte parity with the standard library on the compatible path,
and separation of the two alphabets.

### Negative controls, both required before any campaign

1. **A Goose assertion must be retained by the fuzzer.** `GOOSE_FUZZ_SELF_TEST`
   forces an assertion failure; the fuzzer reports it and writes a 38-byte
   artifact, SHA-256
   `073cdbca56789aeb8a381d17f5683c887ec15e3dbcc296b64f7e86fc5e59776a`.
2. **A sanitizer must catch an injected defect.** `NEGATIVE_CONTROL` performs a
   deliberate one-byte overread; ASan reports `heap-buffer-overflow`.

Both are re-proved on every `make fuzz` run, so a silently disabled sanitizer or
a swallowed assertion fails the target instead of passing it.

### Campaigns

Built with `clang -O1 -g -fsanitize=fuzzer,address,undefined
-fno-sanitize-recover=all`, `-max_len=4096`, `-timeout=5`,
`-rss_limit_mb=1024`.

| Seed | Runs | Seconds | Exec/s | Edges | Features | Peak RSS |
| --- | --- | --- | --- | --- | --- | --- |
| `20261107` | 29,056,079 | 121 | 240,133 | 531 | 1,653 | 514 MiB |
| `20261108` | 21,137,423 | 121 | 174,689 | 531 | 1,652 | 478 MiB |

These are the numbers from the campaign re-run after the `value_of` change and
the accelerated package, which is why the edge count differs from the earlier
run: the generated C changed. Log: `.build/c1/verify-fuzz.log`.

Both seeds exceed the 100,000-execution and 120-second floors by two orders of
magnitude. No crash, no timeout, no artifact. The retained corpus is 1,245 units
(4.9 MB) and is reused between seeds, which is why the second seed starts from
more units.

### Coverage

`llvm-cov show` on the generated C, mapped back through the `gs_file1` line
references: **all 43 `b64.goose` lines named by the generated code are covered,
0 uncovered.** The uncovered generated lines are the standard library's SIMD
variants, which this build does not select because it is not compiled with
`-mavx2`, and specialized instantiations that only ever see exact budgets. That
is a limit of the build, not of the corpus, and it is recorded rather than
papered over.

### A defect this campaign found in the harness

`scripts/fuzz.py`'s negative control ran libFuzzer without `-artifact_prefix`, so
libFuzzer wrote its crash artifact into the working directory — the repository
root — leaving a `crash-<hash>` file behind on every `make fuzz`. The script's own
docstring says artifacts stay under `.build/fuzz/`, so this was a real
contradiction, not a cosmetic one: a `git add -A` would have committed a fuzz
artifact. The control now passes `-artifact_prefix` into
`.build/fuzz/artifacts/`, and the stray file was removed. The re-run below is the
verification.

## Mutation testing

`scripts/mutation-test.py` applies one targeted change at a time to `b64.goose`
and runs `make test` against it. The suite must pass on the pristine tree and
fail on every mutant; a survivor is a test gap and fails the target.

Pristine `b64.goose` SHA-256 `9e837f5f…` passes. **10 mutants, 10 detected, 0
survivors.** Each targets a real documented guarantee, not a syntax error and
not an always-fail mutation:

| Mutant | Guarantee it breaks | Diagnostic |
| --- | --- | --- |
| `url_rewrite_ignores_alphabet` | the alphabet and the padding policy are independent | `tests/api.goose:204` |
| `canonicality_check_removed` | non-canonical trailing bits are rejected | `tests/api.goose:36` |
| `trailing_bit_mask_too_narrow` | exactly 4 of 64 final characters are canonical for a 2-char tail | `tests/api.goose:311` |
| `decode_budget_off_by_one` | the budget is exact, not approximate | `tests/api.goose:215` |
| `padding_precedence_lost` | padding errors take precedence over canonicality | `tests/api.goose:36` |
| `unpadded_policy_always_pads` | `Unpadded` never writes `=` | `tests/api.goose:19` |
| `unpadded_single_character_accepted` | a 1-character text is never valid | `tests/api.goose:36` |
| `padding_run_capped_at_one` | at most two `=` may appear, and only at the end | `tests/api.goose:27` |
| `alphabets_not_separated` | `+`/`/` and `-`/`_` are not interchangeable | `tests/api.goose:27` |
| `table_entry_outside_alphabet_accepted` | the value table maps only the 64 characters of its own alphabet | `tests/api.goose:148` |

The last two were rewritten and added for the table change. `alphabets_not_separated`
now mutates a table entry rather than a range test, and
`table_entry_outside_alphabet_accepted` maps `@` to 0 in `STANDARD_VALUES`. `@`
is outside every pool the oracle generates, so only the new
`every_byte_is_classified` test catches it — which is why that test exists.

The full diff, mutated-file SHA-256, command and diagnostic for each mutant are
kept in `.build/mutation/mutation.json`.

## The optional native backend (`b64_accel`)

`b64_accel` is a package of its own, not a module of `b64`. `import b64` finds no
`b64.build` sidecar and therefore compiles no C and links no C++ runtime; only a
program that imports `b64_accel` pays for it. The design and the contract
argument are in
[the competitive review](competitive-review-2026-11-07.md#the-shipped-backend-b64_accel);
this section records what was executed.

### The ABI, checked against the generated C

A Goose `u8[:]` crosses the boundary as a struct by value, not as two
parameters. The generated C for `tests/accelerated.goose` declares

```c
typedef struct { uint8_t *data; int64_t len; } sl_u8;
gs_i64 b64_accel_decode(gs_rref, sl_u8, gs_i64, gs_i64);
gs_i64 b64_accel_encode(gs_rref, sl_u8, gs_i64, gs_i64, gs_i64);
```

and `b64_accel.cpp` declares the same plain struct, with `static_assert`s on its
size and member offsets so a future change to the layout fails to compile
instead of silently reading the wrong register. The first version of the file
took a pointer and a length as separate arguments; it worked, but only because
two eightbyte members and two integer arguments land in the same registers under
the SysV x86-64 convention. That is an accident of one ABI, and it was replaced.

### The differential test

`tests/accelerated.goose` runs `b64::decode`/`b64::encode` and
`b64_accel::decode`/`b64_accel::encode` on the same input and the same policy and
requires the same `Error`, the same appended bytes, and the same untouched
prefix on failure. It is enumerated, not sampled:

| Corpus | Cases |
| --- | --- |
| every text of length 0-4 over 13 symbols (both alphabets, `=`, `' '`, `\t`, `\n`, `!`, `0`, `z`) | 30,941 |
| every text of length 5-7 over 5 symbols (`A`, `B`, `' '`, `=`, `/`) | 96,875 |
| every byte value in each of the four positions of a group | 1,024 |
| whitespace injected at every position of 11 valid texts, 5 whitespace bytes | 550 |
| one byte replaced by every value, at start/middle/end of 4 valid texts | 7,168 |
| every trailing-bit value of a 2- and a 3-character tail, padded and not | 192 |
| every source of length 0-2 over the whole byte domain, plus lengths 0-39 | 65,833 |
| round trip through the accelerated path, lengths 0-199, all four policies | 800 |
| encode protocol: three calls on one buffer, lengths 0-39, all four policies, growth and bytes asserted, then a refused call | 640 |

Each text is checked under all four policies and at four budgets (unbounded,
zero, `need - 1`, `need`). The run is part of `make test` and prints
`accelerated differential passed`; it also runs under ASan + UBSan in
`make sanitize` for both compilers.

### Negative controls

Both were run against the real harness, with the fixed ABI, and both were caught:

| Control | Result |
| --- | --- |
| native part reports success without appending | `assert failed (tests/accelerated.goose:32)` — the length comparison |
| native part uses `loose` and drops the length equality | `assert failed (tests/accelerated.goose:31)` — the `Error` comparison, on a whitespace or non-canonical text |
| native encode commits and then reports refusal, so the Goose side falls back and appends again | `assert failed (tests/accelerated.goose:46)` — the length comparison in `same_encode` |

The second is the control for the claim that the length equality is what keeps
simdutf's forgiving behaviour out of this contract. The first is the control for
"never a success without an append". The third is the control for the encode
protocol: it is the double append that a native part which committed and then
reported refusal would cause, and it is why the native encode is handed `need`
and checks it on both sides of the write rather than returning a count for the
Goose side to compare after the fact.

### What the native part does not do

It does not validate before writing. simdutf decodes straight into the builder's
free region above `out.len` and the commit — moving the stack top and the count
together — happens only after success and only after the produced length matched
`need`. A refused text may therefore have left bytes above `out.len`, where the
next append overwrites them; `out.len` and `out[0..len)` are unchanged, which is
what the contract promises. `b64::decode` is stronger (it validates the whole
text before its first write) and both satisfy the documented contract. The
difference is stated rather than hidden.

## Performance: the `value_of` change

`decode` classifies bytes through a 256-entry table per alphabet instead of a
chain of range tests. The mechanism and its disassembly evidence are in
[design.md](design.md#decoding-shape); this section records what was measured.

### What the compiled code shows

With gcc 16.2.1 at `-O2` for the generic x86-64 target, the range-test chain
appears inside the inlined `b64_decode` as `lea -0x41(%reg),%reg` /
`cmp $0x19,%reg8` pairs — compares with conditional branches. The table form
appears at the same sites as `movzbl 0x0(%rbp,%rdi,1),%edi` and its three
neighbours. The total branch count across the `b64_decode` specializations
(excluding `b64_decoded_len`) falls from **242 to 122**; conditional branches
alone fall from **162 to 92**.

No hardware performance counter was read. No branch-misprediction count, no IPC
figure and no vectorisation claim is made anywhere in this repository. The
instruction forms above are observed; the causal link to the wall-clock
difference is offered as the plausible mechanism, not as a measured one, and it
is compiler- and ISA-dependent.

The two binaries, their SHA-256 and the toolchain identity are in
`.build/c1/disassembly/`.

### Campaigns

`bench/campaign.sh` builds the frozen baseline from the immutable archive, builds
the current library, builds the equal-contract Goose competitor and the two
external comparators, and runs `bench/measure.py`. Every implementation runs on
one fixed CPU chosen once per campaign, never per implementation. The gate, the
identity snapshots and the statistics are described in
[bench/README.md](../bench/README.md).

| Campaign | Compiler | CPU | Samples | Status |
| --- | --- | --- | --- | --- |
| `campaign-1.json` | gcc 16.2.1 | 2 | 21 (1 warmup + 20) | first campaign, exploratory |
| `campaign-confirm.json` | gcc 16.2.1 | 2 | 21 (1 warmup + 20) | **accepted**, independent of the first |
| `campaign-clang.json` | clang 23.1.4 | 2 | 21 (1 warmup + 20) | **accepted**, portability vs native |
| `campaign-fastpath2.json` | gcc 16.2.1 | 2 | 21 (1 warmup + 20) | **accepted**, the native fast-path prototype |
| `campaign-accel.json` | gcc 16.2.1 | 2 | 21 (1 warmup + 20) | **accepted**, the shipped `b64_accel` package |
| `campaign-accel-cpu0.json` | gcc 16.2.1 | 0 | 21 (1 warmup + 20) | **accepted on its own CPU, not comparable across campaigns** |

The first five use the same CPU, chosen once and never re-chosen per
implementation. `campaign-accel-cpu0.json` is kept as evidence of why the CPU is
pinned: the gate's least-busy choice picked cpu0 on that run, and a campaign on a
different core cannot be compared with one on cpu2. It is `accepted` on its own
terms and is not used for any cross-campaign claim.
The confirmation campaign passed the gate at both ends: busy fraction 0.202
against a least-busy core at 0.177 (within the 0.05 margin), PSI `some avg60`
below 5.0, jitter CV **0.0316 before and 0.0110 after**, and the identity
snapshots before and after agree.

Ratios are `b64 / comparator`, so **below 1 means this library is faster**. Each
is the median of 20 paired samples with a bootstrap 95% interval; `resolved`
means the interval excludes 1.0.

Decode, gcc, `campaign-confirm.json` (the accepted campaign):

| Row | vs `b64_old` | vs `strict` | vs `simdutf` | vs `aklomp` |
| --- | --- | --- | --- | --- |
| 1 KiB | **0.246** [0.230, 0.251] | **0.505** [0.496, 0.525] | 12.895 [12.413, 13.672] | 1.450 [1.346, 1.508] |
| 4 KiB | **0.236** [0.231, 0.245] | **0.504** [0.494, 0.518] | 15.595 [14.752, 16.387] | 1.437 [1.359, 1.493] |
| 64 KiB | **0.239** [0.234, 0.243] | **0.499** [0.494, 0.508] | 14.989 [14.547, 15.200] | 1.439 [1.404, 1.464] |

Encode, gcc, `campaign-confirm.json` (unchanged by this work, as expected):

| Row | vs `b64_old` | vs `strict` | vs `simdutf` | vs `aklomp` |
| --- | --- | --- | --- | --- |
| 1 KiB | 0.950 [0.926, 1.000] | 0.977 [0.926, 1.043] unresolved | 18.790 [17.826, 19.997] | 6.374 [5.971, 6.618] |
| 64 KiB | 0.987 [0.958, 1.008] unresolved | 1.014 [0.994, 1.028] unresolved | 15.636 [14.839, 16.012] | 5.699 [5.485, 5.769] |

The two campaigns agree within their intervals on every row that matters, which
is what an independent repeat is for. `campaign-1.json` gave 0.249 / 0.246 /
0.246 against `b64_old`; the confirmation gives 0.246 / 0.236 / 0.239. The
encode rows against `b64_old` and `strict` are **unresolved** in both: their
intervals contain 1.0, which is the correct outcome for code that did not
change. They are reported as unresolved rather than as "no difference", because
the campaign cannot distinguish a small difference from none.

### The shipped backend, `campaign-accel.json`

Same CPU (cpu2), same compiler, same harness, with `b64_accel` added as a
comparable implementation. Gate: busy fraction 0.054 against a least-busy core
at 0.025 (within the 0.05 margin), jitter CV **0.0046 before and 0.0019 after**,
identity snapshots before and after agree, 20 measured samples, order alternating
forward/reverse between samples.

Medians in ns per call:

| decode | `b64` | `b64_accel` | `b64_old` | `strict` | `simdutf` | `simdutf_fast` | `aklomp` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 KiB | 1260.1 | **142.2** | 5037.6 | 2426.6 | 93.9 | 138.1 | 868.0 |
| 4 KiB | 4846.1 | **335.7** | 19742.3 | 9491.9 | 317.3 | 364.5 | 3383.6 |
| 64 KiB | 76813.4 | **4138.3** | 315084.4 | 151728.7 | 5043.2 | 5680.1 | 52778.2 |

| encode | `b64` | `b64_accel` | `b64_old` | `strict` | `simdutf` | `simdutf_fast` | `aklomp` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 KiB | 1237.3 | **61.9** | 1217.4 | 1234.5 | 61.8 | 63.6 | 191.5 |
| 4 KiB | 4523.0 | **210.1** | 4485.4 | 4483.9 | 243.0 | 242.1 | 726.2 |
| 64 KiB | 71957.2 | **3038.2** | 72008.8 | 71826.5 | 4571.4 | 4708.3 | 12709.9 |

Paired ratios, median of 20 with a bootstrap 95% interval:

| Row | `b64 / b64_accel` | `b64 / b64_old` | `b64 / simdutf` | `b64_accel / simdutf_fast` |
| --- | --- | --- | --- | --- |
| decode 1 KiB | **8.872** [8.762, 9.029] | **0.250** [0.248, 0.253] | 13.418 | **1.018** [1.005, 1.044] |
| decode 4 KiB | **14.380** [14.336, 14.437] | **0.245** [0.243, 0.247] | 15.272 | **0.926** [0.916, 0.932] |
| decode 64 KiB | **18.589** [18.552, 18.613] | **0.244** [0.242, 0.245] | 15.232 | **0.729** [0.723, 0.736] |
| encode 1 KiB | **20.308** [19.746, 20.594] | 1.021 [0.977, 1.039] unresolved | 20.020 | 0.971 [0.943, 1.019] unresolved |
| encode 4 KiB | **21.733** [21.379, 21.858] | 1.012 [1.007, 1.021] | 21.529 | **0.874** [0.864, 0.882] |
| encode 64 KiB | **23.726** [23.624, 23.841] | 1.001 [0.992, 1.005] unresolved | 23.684 | **0.646** [0.628, 0.654] |

Three things are worth reading carefully.

1. **`b64_accel` is ahead of `simdutf` at 64 KiB** (4138.3 ns against 5043.2 ns),
   and the reason is not the codec. `bench/ext/bench_ext.cpp` writes into a
   `std::vector` resized to the output length, which zero-fills; `b64_accel`
   writes into the builder's free region, which is already committed address
   space and is not filled. The difference is the fill, and it is a property of
   the harness's output model, not of simdutf. `simdutf` is therefore reported as
   the ceiling *for that model*, and `b64_accel` beating it is reported rather
   than suppressed.
2. **`b64_accel` against `simdutf_fast`** — the safe prototype that decodes into
   a scratch and then copies — is 1.026 at 1 KiB (unresolved), 0.928 at 4 KiB
   and 0.731 at 64 KiB. The shipped backend is faster because it does not copy.
   The prototype's numbers were never the contract's cost; this is the
   measurement that replaces them.
3. **The pure-Goose rows are unchanged** from `campaign-confirm.json` within
   their intervals: `b64 / b64_old` 0.250 / 0.245 / 0.244 here against 0.246 /
   0.236 / 0.239 there, and the encode rows against `b64_old` and `strict` are
   still unresolved. That is the independent repeat the earlier campaign needed,
   and it agrees. This campaign was re-run after the encode protocol was
   hardened, and the numbers moved by less than the intervals: the extra
   comparison before the write costs nothing measurable.

### Portability: gcc versus clang

`campaign-clang.json` is the same campaign with `CC=clang`, on the same CPU. It
is not a second opinion on the gcc numbers; it answers a different question,
because the standard library's `simd fn` versions exist only under clang.

| decode, 1 KiB | gcc | clang |
| --- | --- | --- |
| `b64` | 845.6 ns | 1,118.0 ns |
| `stdlib` | 1,107.6 ns | **616.1 ns** |
| `b64_old` | 3,436.7 ns | 2,170.0 ns |
| `b64 / b64_old` | 0.246 | 0.518 |
| `b64 / strict` | 0.505 | 0.845 |

Two things follow, and both are reported rather than smoothed over:

- This library is **slower under clang** than under gcc (1,118.0 vs 845.6 ns), so
  the improvement over the baseline is 1.93x under clang rather than 4.07x. The
  change is still a clear win on both compilers, but the size of the win is
  compiler-dependent, which is what the coordinator's review asked to be stated
  rather than assumed.
- The standard library is **faster under clang** (616.1 vs 1,107.6 ns) because
  its `simd fn` AVX2 decoder is selected there and not under gcc. That is a
  pure-Goose implementation on this CPU reaching 1.81x this library's clang
  number, with a weaker contract. It is the measured ceiling for a pure-Goose
  `simd fn` decoder, and it is the reason that path is the first next step.

### The native fast-path prototype

`campaign-fastpath2.json` adds `simdutf_fast`, the prototype described in
[the competitive review](competitive-review-2026-11-07.md#the-fast-path-prototype):
an O(1) shape check, simdutf `strict` into a scratch buffer, an equality test on
the produced length, and this library's validator only on the rejection path.

| decode | 1 KiB | 4 KiB | 64 KiB |
| --- | --- | --- | --- |
| `simdutf` (ceiling) | 93.5 ns | 317.8 ns | 5,070.0 ns |
| `simdutf_fast` (this contract) | 139.6 ns | 364.9 ns | 5,691.2 ns |
| `b64` | 1,262.2 ns | 4,836.2 ns | 77,064.9 ns |
| `b64 / simdutf_fast` | **9.082** [8.880, 9.161] | — | **13.577** [13.477, 13.628] |

The prototype is 9.1x faster than this library at 1 KiB and 13.6x at 64 KiB while
preserving the exact contract, which is proved by 3,258,269 differential cases
with zero disagreements, in both the plain and the ASan+UBSan builds. It is a
prototype in the benchmark harness, not a shipped backend: it is C++, its scratch
buffer is a `std::vector` that models Goose's bump allocator rather than
measuring it, and the unpadded and URL policies are not covered by the
length-equality argument. See the competitive review for the full analysis,
including the explicit-capacity API choice and the independent refutation of
the earlier buffer-overrun allegation for these padded fixtures.

### What these numbers do and do not establish

They establish that decoding is about four times faster than the frozen baseline
on inputs of 1 KiB and larger, and about twice as fast as the equal-contract
Goose competitor, with intervals that exclude 1.0.

They do **not** establish competitiveness with a SIMD codec, and the headline
ratio against one needs decomposing rather than quoting. Absolute medians from
`campaign-confirm.json`, decode, reused buffer:

| Row | 1 KiB | 64 KiB |
| --- | --- | --- |
| `simdutf` | 65.4 ns | 3,476.7 ns |
| `aklomp` (adapted) | 610.1 ns | 36,725.3 ns |
| `b64` | 845.6 ns | 51,653.6 ns |
| `strict` | 1,677.0 ns | 104,478.3 ns |
| `b64_old` | 3,436.7 ns | 216,792.1 ns |

`simdutf`'s 65 ns is a **ceiling, not an equal-contract result**: it accepts ASCII
whitespace and its `strict` mode cannot express unpadded text, so it does not
implement this contract. `aklomp`'s 610 ns is the equal-contract native design —
the harness runs this library's own validation pass, canonicality check and
budget in C++ over the same table, then calls aklomp's SIMD decoder for the bit
work. That is the same two-pass structure with the second pass in SIMD.

So of the 13-15x gap to `simdutf`, roughly **9x is the contract** (validation,
canonicality, budget, refusal semantics) and roughly **1.4x is the codec**
(845.6 / 610.1 = 1.386 at 1 KiB, 51,653.6 / 36,725.3 = 1.406 at 64 KiB). The
ratio is stable across three orders of magnitude, which is what makes it a
structural figure rather than an artefact. The full argument, and why the 1.4x
does not justify a native backend, is in
[the competitive review](competitive-review-2026-11-07.md#the-gap-is-mostly-the-contract-not-the-codec).

The comparison is also scoped by contract, not just by speed: `simdutf` accepts
ASCII whitespace that this library rejects, and its `strict` mode rejects valid
unpadded text that this library accepts. The full matrix, the pinned commits and
the interop costs are in
[the competitive review](competitive-review-2026-11-07.md).

## Aliasing

An earlier revision of this document stated without qualification that the
compiler rejects a call whose source slice aliases the output buffer. That is
true for `encode` and **false for `decode`**: `goose check` accepts
`b64::decode(buffer, buffer[..], policy)`.

The guarantee is therefore split by function, and `tests/alias_rejected.sh` pins
both halves so the difference cannot silently change:

- `encode`: rejected at compile time, "cannot resize out while src is still
  used".
- `decode`: accepted by the compiler, so non-aliasing is a **documented caller
  requirement**, not a static guarantee.

This is a documentation defect, not a memory-safety defect, and the distinction
matters. `decode` is memory-safe under aliasing because the runtime does not
reallocate: `gs_stack` is a bump pointer into a fixed `mmap` region reserved once
by `gs_reserve_region`, and the generated write pass stores through
`out_g.stk->top` rather than calling `push`. `tests/alias_decode_lifetime.goose`
exercises this with growth-forcing sizes under ASan + UBSan: the text is
preserved, the decoding is appended, and no diagnostic is produced. That is
evidence about the current runtime, not a licence to alias — the contract still
says not to.

## Regression: the alphabet and the padding policy are independent

An earlier revision rewrote `+` and `/` to `-` and `_` whenever the padding
policy was `Unpadded`, even with the standard alphabet, so `0xfb 0xff` encoded
to `-_8` instead of `+/8`. The fix separates the two decisions: the alphabet
selects the two extra characters, the padding policy selects whether `=` is
written.

The vector is part of this repository's own suite, so the regression is caught by
`make test` in a standalone clone with no external harness:

- `tests/api.goose` asserts all four combinations on `0xfb 0xff` (`+/8=`,
  `+/8`, `-_8=`, `-_8`) and on `0xff 0xff 0xff` (`////`, `____`), and decodes
  `+/8=` and `-_8` back to the same bytes.
- `tests/oracle.py` covers every 1-byte and 2-byte input under all four
  policies, which includes every input that produces `+`, `/`, `-` or `_`.
- `url_rewrite_ignores_alphabet` is one of the mutants above, so the vector is
  proven to be load-bearing rather than merely present.

## Not executed

- **The unpadded policy on the native path.** The length-equality argument is
  stated and proved for the padded policy only. For `Unpadded`, simdutf `strict`
  rejects the partial final chunk this library accepts, so the design is native
  `strict` over the whole groups plus a constant-size Goose tail. That is not
  implemented; unpadded text falls back to `b64::decode`. The URL alphabet *is*
  covered, because simdutf has `base64_url_with_padding`.
- **A native backend on any platform other than Linux x86-64.** simdutf selects
  its kernel at compile time and the Goose side is platform-independent, but only
  this platform was built and measured.
- **A `b64_accel` campaign under clang.** The accelerated package was built and
  its differential test run under clang (in `make sanitize`), but no timing
  campaign was recorded with `CC=clang`. The gcc campaign is the recorded one.
- **`simd fn` on the decoder.** Goose's `simd fn` is the dependency-free way to
  reach the same instruction sets, and it is not used here. It is blocked on the
  value table: a 256-entry lookup is a gather, and the vectorizable alternative
  is the range-test form that measured slower in scalar code. The measured
  ceiling is the standard library's own `simd fn` decoder under clang: 616.1 ns
  at 1 KiB against this library's 1,118.0 ns.
- **Hardware performance counters.** No `perf` run was made, so no
  branch-misprediction, cache-miss or IPC figure is claimed. The disassembly
  evidence is instruction-form evidence only.
- **`make setup`.** The pinned compiler was reused from a shared toolchain
  rather than rebuilt, to avoid a heavy concurrent build. The standalone-clone
  quickstart therefore has not been exercised end to end here.
- **Other platforms and compiler revisions.** Only Linux x86-64 with the pinned
  revision was tested.
- **The standard library's SIMD paths under gcc.** The gcc build is not compiled
  with `-mavx2`, so those generated lines are never selected and are not covered
  there. `campaign-clang.json` measures them under clang, which is where they
  exist.
- **Consumer integration.** Neither goose-http nor any JSON consumer was
  modified or built against this library. The examples state the contract; they
  do not demonstrate adoption.

## Reproducing

```sh
make setup                       # or supply GOOSE=/path/to/pinned/goose
make check test
make property
make sanitize SANITIZER_CC=gcc
make sanitize SANITIZER_CC=clang
make fuzz                        # 2 x 120 s plus a 30 s coverage pass
make mutation                    # 10 selected mutants
```

`make bench` is deliberately separate and must be run alone; see
[bench/README.md](../bench/README.md).

### Post-review scope clarification

The CPU7 `benchmark.json` campaign is also retained and is disclosed beside
CPU2 in the README. A campaign gate does not justify a universal ratio across
CPU classes or prove a causal core-type effect. The headline CPU2 encoding
multipliers use median paired ratios; the table contains marginal medians.
Both estimates remain available and are now labelled separately. No codec
source or recorded measurements changed in this documentation follow-up.
