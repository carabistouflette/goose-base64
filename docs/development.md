# Development commands

Run everything from the library root. `GOOSE` defaults to
`.toolchain/goose/build/goose`, which `make setup` builds from
[GOOSE_REVISION](../GOOSE_REVISION). To reuse a compiler you already trust,
pass it explicitly and verify it matches the pin:

```sh
make check test GOOSE=/absolute/path/to/goose
```

| Target | What it does |
| --- | --- |
| `make setup` | Fetch and build the pinned compiler into `.toolchain` |
| `make format` | Rewrite Goose files in the standard layout |
| `make check` | Format check, typecheck every Goose file, compile the Python files, `git diff --check` |
| `make test` | API tests, standard-library parity, both examples, JIT and native builds, the aliasing compile test, the differential corpus |
| `make property` | The differential corpus and the parity test against a `--debug --no-bce` build |
| `make sanitize` | ASan + UBSan builds of the API test, the corpus, both examples and the aliased-decode lifetime test |
| `make fuzz` | libFuzzer + ASan + UBSan on the real API: proves both failure paths, then runs two seeds for 120 s each and a coverage pass |
| `make mutation` | Mutation-tests the documented guarantees; a surviving mutant fails the target |
| `make bench-smoke` | CI: validate the current comparison harness and equal-contract result digests without a local frozen baseline; no performance qualification |
| `make bench` | Build and record the benchmark. Run it alone; see [bench/README.md](../bench/README.md) |

`make sanitize` takes `SANITIZER_CC=gcc` or `SANITIZER_CC=clang`. If your shell
exports a `LD_LIBRARY_PATH` that shadows the system C++ runtime, unset it for
the sanitizer and fuzz runs: `env -u LD_LIBRARY_PATH make sanitize`.

The sanitizer target proves mixed C/C++ linkage and a real invalid-vptr
diagnostic before running the API suite. Clang's C driver links the C++
sanitizer runtime explicitly, and requests `vptr` separately because newer
Clang versions omit it from the `undefined` group. See the
[Clang18 UBSan documentation](https://releases.llvm.org/18.1.1/tools/clang/docs/UndefinedBehaviorSanitizer.html)
and the [current check groups](https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html).

`make fuzz` takes `FUZZ_SECONDS`, `FUZZ_RUNS`, `FUZZ_SEEDS` and `FUZZ_CC`
(default `clang`). It refuses to report a campaign unless both negative controls
fire first: a forced Goose assertion retained by the fuzzer, and a deliberate
overread caught by ASan. Keep `.build/fuzz/campaign.json` with its corpus and
logs.

## Adding a test

Behaviour changes need a public API regression in `tests/api.goose` and, where
the change touches the codec, a case in `tests/oracle.py`. The corpus is
deterministic; add cases to an existing group rather than introducing a new
random source, and keep the group breakdown printed by the run accurate.

If a change alters the compatible path, `tests/stdlib_parity.goose` must still
pass: the standard library is the reference for standard-alphabet padded
encoding and decoding.

## Compiler changes

A new `GOOSE_REVISION` requires the full matrix: `make check test property`,
both sanitizer compilers, and a fresh benchmark record. Re-read the pinned
`docs/stdlib.md` §base64 first: if the standard library gains the URL alphabet,
unpadded output, canonicality or a budget, the justification in
[design.md](design.md) changes and this module should shrink or disappear.
