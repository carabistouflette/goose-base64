# Validation history

What was executed, with the exact commands and results, and what was not.

## Provenance

| Item | Value |
| --- | --- |
| Goose compiler | `goose eadca40 (runtime 3025e5810379)`, revision `eadca409f68210893f366e60d0c2f0dc29a339be` |
| Compiler source | https://github.com/aardappel/goose at `eadca409f68210893f366e60d0c2f0dc29a339be`, reused unmodified and not rebuilt |
| C compiler | `gcc (GCC) 16.2.1 20260810`, `clang version 23.1.4` |
| Platform | `Linux 7.2.11-arch1-1 x86_64` |
| Python | 3.14.9 |
| `b64.goose` SHA-256 | `299d74f910ba7769af3c087bcebea12a96e71da8069d9f9d84b889304bbfb8fb` |
| `tests/oracle.py` SHA-256 | `11fdff7f03d328730c3c54427f9f6000987bc93170e36f4a3f9fdd793f3a06fe` |

The compiler was not rebuilt. `make setup` was not run in this workspace, so the
standalone-clone quickstart's compiler build is unverified here; every command
below passed an explicit `GOOSE=` pointing at the shared pinned binary.

## Executed

All commands ran from the library root.

### `make check GOOSE=./.build/goose`

Passed. `goose format --check` over `b64.goose`, `tests`, `examples` and `bench`;
`goose check` on all seven Goose files; `python3 -m py_compile` on both Python
files; `git diff --check`.

### `make test GOOSE=./.build/goose`

Passed in 10.8 s. In order:

- `goose run tests/api.goose` — public API, RFC 4648 §10 vectors, all four
  policy combinations, the error taxonomy and its precedence, budget
  boundaries, failure atomicity, exhaustive trailing-bit acceptance counts.
- `goose run tests/stdlib_parity.goose` — byte-identical encode and decode
  against the standard library for every length 0..299, plus the divergence
  counts (standard library accepts 64 of 64 final characters, this module 4 for
  a two-character tail and 16 for a three-character tail).
- `goose run examples/basic_auth.goose` and `examples/json_binary.goose`.
- `goose build tests/api.goose -O2` and `--debug --no-bce`, both executed.
- `tests/alias_rejected.sh` — the compiler rejects a call whose source slice
  aliases the output buffer, with "cannot resize out while src is still used".
- `goose build tests/oracle.goose -O2` then `python3 tests/oracle.py`:
  **940,496 differential cases passed**.

### `make property GOOSE=./.build/goose`

Passed in 14.2 s. The same 940,496 cases against a `--debug --no-bce` build
(bounds checks kept, overflow and range checks on), plus the parity test built
the same way.

### `env -u LD_LIBRARY_PATH make sanitize GOOSE=./.build/goose SANITIZER_CC=gcc`

Passed in 28.0 s. ASan + UBSan, `--standalone --debug --no-bce`, on the API
test, the full 940,496-case differential corpus and both examples, with
`ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1`.

### `env -u LD_LIBRARY_PATH make sanitize GOOSE=./.build/goose SANITIZER_CC=clang`

Passed in 14.2 s, same targets and options with Clang 23.1.4.

`LD_LIBRARY_PATH` is unset in these two commands because this shell inherits a
tool-specific `libstdc++` that is older than the system sanitizer runtimes. That
is a property of the shell, not of the library.

### Regression: the alphabet and the padding policy are independent

An earlier revision rewrote `+` and `/` to `-` and `_` whenever the padding
policy was `Unpadded`, even with the standard alphabet, so `0xfb 0xff` encoded
to `-_8` instead of `+/8`. The fix separates the two decisions: the alphabet
selects the two extra characters, the padding policy selects whether `=` is
written.

The vector is now part of this repository's own suite, so the regression is
caught by `make test` in a standalone clone with no external harness:

- `tests/api.goose` asserts all four combinations on `0xfb 0xff` (`+/8=`,
  `+/8`, `-_8=`, `-_8`) and on `0xff 0xff 0xff` (`////`, `____`), and decodes
  `+/8=` and `-_8` back to the same bytes.
- `tests/oracle.py` covers every 1-byte and 2-byte input under all four
  policies, which includes every input that produces `+`, `/`, `-` or `_`.

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
rather than transcribed.

The corpus is deterministic: `random.Random(20261107)`, no wall-clock or
environment input. Re-running it reproduces the same 940,496 cases.

## Not executed

- **Performance measurements.** `bench/bench.goose` and `bench/measure.py` are
  written and the harness compiles (`goose check bench/bench.goose`), but no
  timing run was made. Measurements are taken one at a time with no other CPU
  work in flight. No performance claim is made anywhere in this repository.
- **`make setup`.** The pinned compiler was reused from a shared toolchain
  rather than rebuilt, to avoid a heavy concurrent build. The standalone-clone
  quickstart therefore has not been exercised end to end here.
- **Other platforms and compiler revisions.** Only Linux x86-64 with the pinned
  revision was tested.
- **Fuzzing.** No coverage-guided fuzzer was run. The differential corpus is
  deterministic and exhaustive over short inputs rather than random over long
  ones.
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
```

`make bench` is deliberately separate and must be run alone; see
[bench/README.md](../bench/README.md).
