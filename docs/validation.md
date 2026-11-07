# Validation history

What was executed, with the exact commands and results, and what was not.

## Provenance

| Item | Value |
| --- | --- |
| Goose compiler | `goose eadca40 (runtime 3025e5810379)`, revision `eadca409f68210893f366e60d0c2f0dc29a339be` |
| Compiler binary SHA-256 | `3cad45a18356bf97f4732f1da2012252afd77a652932ddb9c91c5551c04904be` |
| Compiler source | https://github.com/aardappel/goose at `eadca409f68210893f366e60d0c2f0dc29a339be`, reused unmodified and not rebuilt |
| C compiler | `gcc (GCC) 16.2.1 20260810`, `clang version 23.1.4` |
| Platform | `Linux 7.2.11-arch1-1 x86_64` |
| Python | 3.14.9 |
| `b64.goose` SHA-256 | `98e0432e2bf0fc61defc50ab12ceecae243838da1b0f99747dbe7b8519ce1231` |
| `tests/oracle.py` SHA-256 | `11fdff7f03d328730c3c54427f9f6000987bc93170e36f4a3f9fdd793f3a06fe` |
| `tests/fuzz.goose` SHA-256 | `5eb73db5b37be17e1e63e75dd146aff4f7ee4d0863004edba57234f389267f98` |
| `tests/fuzz.c` SHA-256 | `b911d846dbb795df844a78631283526b7761503c0224c7bc04476298d46cb1bc` |
| `bench/strict.goose` SHA-256 | `1732326b7b7c9bdef226069a650d53ad9ede2243c289852f2e563711062e2406` |
| `bench/strict_equivalence.goose` SHA-256 | `e12837750c444c6cc52b420a7dda8c145c605aaf1f92fabd82a29c88237977d8` |

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
  reference to the input, `decoded_len` as a shape-only helper, and truncation
  and corruption.
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

Passed in **32.18 s**, peak RSS 820 MiB. ASan + UBSan, `--standalone --debug
--no-bce`, on the API test, the full 940,496-case differential corpus, both
examples and the aliased-decode lifetime test, with
`ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1`.

### `make sanitize GOOSE=<pinned> SANITIZER_CC=clang`

Passed in **15.19 s**, peak RSS 820 MiB, same targets and options with Clang
23.1.4.

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
| `20261107` | 8,448,664 | 121 | 69,823 | 633 | 2,204 | 475 MiB |
| `20261108` | 7,905,697 | 121 | 65,336 | 633 | 2,204 | 444 MiB |

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

## Mutation testing

`scripts/mutation-test.py` applies one targeted change at a time to `b64.goose`
and runs `make test` against it. The suite must pass on the pristine tree and
fail on every mutant; a survivor is a test gap and fails the target.

Pristine `b64.goose` SHA-256 `98e0432e…` passes. **9 mutants, 9 detected, 0
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
| `alphabets_not_separated` | `+`/`/` and `-`/`_` are not interchangeable | `tests/api.goose:36` |

The full diff, mutated-file SHA-256, command and diagnostic for each mutant are
kept in `.build/mutation/mutation.json`.

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

- **Qualified performance measurements.** No comparative campaign has been
  accepted. The harness has been smoke-tested for row structure and content
  checksums only, with `--iterations 1`; those timings are discarded and no
  performance claim is made anywhere in this repository. See
  [bench/README.md](../bench/README.md) for the prepared campaign.
- **`make setup`.** The pinned compiler was reused from a shared toolchain
  rather than rebuilt, to avoid a heavy concurrent build. The standalone-clone
  quickstart therefore has not been exercised end to end here.
- **Other platforms and compiler revisions.** Only Linux x86-64 with the pinned
  revision was tested.
- **The standard library's SIMD paths.** The build is not compiled with
  `-mavx2`, so those generated lines are never selected and are not covered.
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
make mutation                    # 9 mutants, about 2 minutes
```

`make bench` is deliberately separate and must be run alone; see
[bench/README.md](../bench/README.md).
