# Contributing

Keep the API small, pure, explicit and strict. Applications own I/O and resource
limits. Preserve caller-owned output, rejection before mutation, the fixed error
precedence and the exact appended counts. Prefer the standard library where its
semantics match: whole 3-byte groups are delegated to it, and that delegation is
tested rather than assumed.

Do not add streaming, MIME folding, `base32`/`base16`, alphabet detection,
whitespace tolerance, native acceleration or a second codec without a concrete
need and design review. If the pinned standard library gains the URL alphabet,
unpadded output, canonicality or a budget, shrink this module instead of
duplicating it.

Use focused branches (`feat/...`, `fix/...`, `docs/...`) and Conventional
Commits: `feat: add ...`, `fix: reject ...`, `docs: clarify ...`,
`test: cover ...`, `chore: update ...`. Subjects are imperative; each commit
contains one coherent change. No stability guarantee before 1.0; use semantic
versions when a reviewed release is ready.

Behaviour changes require public API regressions, independent review, and fixes
for actionable findings. Run `make format`, `make check test property`, both
`make sanitize` compilers and `git diff --check`. Test malformed input, length
and budget extremes, failure atomicity and the four policy combinations. Keep CI
passing. Never commit credentials, generated compiler output or private
workspace notes.

After changing the optional native adapter or its vendored headers, run
`make format` to refresh the fingerprint in `b64_accel.build`. The pinned Goose
compiler does not track included headers in its package cache stamp. `make check`
rejects a stale fingerprint; `make test` reproduces that cache behavior in an
isolated fixture and verifies that refreshing the fingerprint rebuilds it.

Pin a reviewed full upstream commit in `GOOSE_REVISION`; compiler changes require
full validation. Profile before optimizing, preserve the safety contracts, run
every benchmark fixture, and retain raw samples plus compiler, hardware, flags
and source revision. Do not claim universal performance rankings. Report
potential vulnerabilities privately through GitHub advisory reporting when
enabled.
