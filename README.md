# goose-base64

Strict, bounded RFC 4648 Base64 and Base64url for the
[Goose programming language](https://github.com/aardappel/goose). Choose the
standard or URL-safe alphabet, choose padded or unpadded output, cap the bytes
one call may append, and reject text whose unused trailing bits are not zero.

Apache-2.0. Experimental, with no stable release yet. The import below pins the
reviewed implementation; only Linux x86-64 with the recorded compiler revision
has been validated.

## Quickstart

Requires Git, Make, CMake 3.27+, a C compiler and a C++20 compiler. Setup builds
the Goose compiler pinned in [GOOSE_REVISION](GOOSE_REVISION).

```sh
git clone https://github.com/carabistouflette/goose-base64.git
cd goose-base64
make setup
.toolchain/goose/build/goose run examples/basic_auth.goose
```

The example prints the `Authorization` header value for an HTTP Basic
credential and checks it against RFC 7617's own example:

```
Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==
Basic dXNlcjpwYXNz
Basic w6k6cA==
goose-http Basic authorization example passed
```

To use the library in your own application, save this as `app.goose` and run
`goose run app.goose` with that compiler on your `PATH`:

```goose
import b64 from "carabistouflette/goose-base64@334e708d4d02448ae9caeb8767d773516a1f99ed";
import std;

fn main() {
    var text: u8[>..] = [];
    let error = b64::encode(text, "\xfb\xff", b64::Policy {
        alphabet: b64::Alphabet.Url,
        padding: b64::Padding.Unpadded,
        max_out: 64,
    });
    if error != b64::Error.None { print("encode failed: ", error); return; }
    print(text);                       // -_8

    var bytes: u8[>..] = [];
    if b64::decode(bytes, text, b64::Policy {
        alphabet: b64::Alphabet.Url,
        padding: b64::Padding.Unpadded,
        max_out: 64,
    }) != b64::Error.None { print("decode failed"); return; }
    print(bytes.len);                  // 2
}
```

Declare the package import in the application's root source. For a sibling local
checkout, use `import b64 from "../goose-base64";` instead.

The namespace is `b64`, not `base64`: the pinned standard library already owns
`base64`, and this module imports it.

### The optional accelerated package

`b64_accel` is a second package in the same repository with the same contract
and a SIMD codec underneath. It is a separate import, so nothing is paid for it
unless it is asked for:

```goose
import b64 from "carabistouflette/goose-base64@<ref>";
import b64_accel from "carabistouflette/goose-base64@<ref>";
import std;

fn main() {
    var text: u8[>..] = [];
    let policy = b64::Policy { max_out: 64 };
    // Same Policy, same Error, same bytes; simdutf does the work.
    if b64_accel::encode(text, "foobar", policy) != b64::Error.None { return; }
    print(text);                       // Zm9vYmFy
}
```

Both imports name the same source, so `b64_accel` uses `b64::Policy` and
`b64::Error` themselves rather than copies. Importing `b64` alone builds no C
and links no C++ runtime: the compiler looks for `<name>.build` beside
`<name>.goose`, and there is no `b64.build`. Importing `b64_accel` compiles the
vendored simdutf once per C compiler and links it statically. The native decode
covers the padded policy; unpadded text falls back to the Goose decoder.

## API and limits

| Function | Result |
| --- | --- |
| `encode(out, src, policy)` | Append the text of `src`; `Error.None` on success |
| `decode(out, src, policy)` | Append the bytes `src` encodes; `Error.None` on success |
| `encoded_len(src_len, padding)` | Exact appended bytes for a byte count, or `-1` |
| `decoded_len(src, padding)` | Exact appended bytes for a text, or `-1` |

`policy` is `b64::Policy { alphabet, padding, max_out }`. `alphabet` defaults to
`Alphabet.Standard` and `padding` to `Padding.Padded`; `max_out` is required and
is the maximum number of bytes one call may append. `out` is a caller-owned
growable byte buffer (`u8[>..]&`); `src` is a `const u8[:]`.

Errors are `None`, `InvalidLength`, `InvalidCharacter`, `InvalidPadding`,
`NonCanonical` and `OutputBudget`. A failure never changes the caller's buffer.
The precedence is fixed: a negative budget, then the length and padding shape,
then the budget, then the first offending byte in text order, then the trailing
bits.

The four policy combinations are independent. `0xfb 0xff` encodes to `+/8=`,
`+/8`, `-_8=` and `-_8` for standard/padded, standard/unpadded, URL/padded and
URL/unpadded.

Whitespace is rejected in every policy, as are the other alphabet's two extra
characters. `NonCanonical` means the unused low bits of the final data character
are not zero (RFC 4648 §3.5), so a different text would decode to the same
bytes. Of the 64 possible final characters, 4 are canonical for a two-character
tail and 16 for a three-character tail.

Encoding and decoding take O(n) time and O(1) extra space beyond the output.
The logical output grows by exactly the appended count; the runtime controls
the buffer's allocation capacity. `max_out` limits appended bytes, not allocator
overhead or retained capacity. There is no library input-size cap: callers must
bound the read, the write and total work.

Decoding classifies each byte through a 256-entry table per alphabet, so the
module carries 512 bytes of static data. That is the whole of its state: there
is no allocation, no cache and no initialisation step. The table replaced a
range-test chain whose compiled form was a branch tree; see
[the design contract](docs/design.md) for the disassembly evidence and
[the competitive review](docs/competitive-review-2026-11-07.md) for what the
change does and does not buy against a SIMD codec.

`src` must not alias `out`. The compiler rejects that statically for `encode`,
with "cannot resize out while src is still used" (§5.1). For `decode` it is a
caller requirement rather than a compile-time guarantee: the write pass grows
the buffer with `push`, which the §5.1 check does not flag. Such a call is not a
memory-safety hazard — data stacks are fixed reserved regions grown by bump
pointer and never reallocated, so the source bytes stay valid — but it appends
the decoding after the text, which is outside the contract.
`tests/alias_rejected.sh` pins the compile-time behaviour and
`tests/alias_decode_lifetime.goose` pins the runtime behaviour, so both are
checked rather than assumed.

The library does not provide streaming, MIME line folding, `base32`/`base16`,
alphabet detection, whitespace tolerance or I/O. Decoding is not constant-time
and must not be used to compare secrets.

## Performance

Two numbers, because there are two things to say.

**The pure-Goose library.** Decoding is about four times faster than the
previous release on inputs of 1 KiB and larger, and about twice as fast as the
equal-contract Goose competitor in `bench/strict.goose`. Encoding is unchanged.
That is the whole of what changed in `b64.goose`: `value_of` classifies a byte
through a 256-entry table instead of a chain of range tests.

**The optional native backend.** `b64_accel` is a separate package in this
repository that keeps the same `Policy`, the same `Error` and the same
atomicity, and decodes and encodes with simdutf. It is opt-in: `import b64`
builds no C and links no C++ runtime. With it, decoding is **8.9x / 14.4x /
18.6x** faster than the pure-Goose library at 1 KiB / 4 KiB / 64 KiB, and
encoding is **20.3x / 21.7x / 23.7x** faster in that CPU2 campaign. These
headline multipliers are medians of the per-round paired ratios. They are not
ratios of the marginal medians shown in the tables below; for encoding those
ratios are 20.0x / 21.5x / 23.7x.

Marginal medians in ns per call, gcc 16.2.1, one fixed CPU (cpu2), 20 paired samples,
alternating order, identity snapshots stable before and after:

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

A second retained campaign of the same measured codec on CPU7 reports the
following ratios of marginal medians. These describe two recorded campaigns,
not an isolated causal experiment on core type. CPU2 and CPU7 have different
reported capacity classes (1005 and 676); frequency, load and other conditions
can also differ. The harness can choose a least-busy CPU automatically, so
reproduction must set `BENCH_CPU` explicitly and record its class.

| operation | bytes | CPU2 | CPU7 |
| --- | ---: | ---: | ---: |
| decode | 1024 | 8.86x | 7.31x |
| decode | 4096 | 14.43x | 9.31x |
| decode | 65536 | 18.56x | 10.19x |
| encode | 1024 | 19.99x | 13.05x |
| encode | 4096 | 21.53x | 14.23x |
| encode | 65536 | 23.68x | 14.37x |

Sources: `campaign-accel.json` (CPU2) and the retained `benchmark.json` (CPU7),
with raw rounds and identity snapshots. Their gate status does not make either
campaign a platform-wide performance promise.

`b64_old` is the published revision built from its immutable source archive with
the current harness. `strict` is the equal-contract Goose competitor.
`simdutf_fast` is the safe prototype in `bench/ext/bench_ext.cpp`: simdutf into a
scratch, then a copy. `simdutf` is simdutf writing straight into the output
buffer, which is the ceiling for this workload.

What the numbers say, and what they do not:

- The contract is **not** what costs 9-14x. A backend that keeps it exactly —
  same `Policy`, same `Error`, same atomicity, checked against the Goose
  implementation on an enumerated differential corpus — takes about 1.51 times the raw
  simdutf row at 1 KiB in the CPU2 campaign and **ahead of it at 64 KiB**, because the C++ harness
  zero-fills its output vector and `b64_accel` writes into the builder's free
  region without a fill.
- The 1 KiB gap includes shape/budget checks, the Goose call and fixed codec
  costs; this experiment does not isolate their individual contributions.
- This is **not** a claim of being state of the art. It is a claim that the
  pure-Goose path is 4x better than it was, and that the gap to a SIMD codec is
  available to anyone who wants it, at the price of a 3.6 MB vendored dependency
  and a C++ toolchain, in a package they have to import on purpose.
- The native decode covers the padded policy only. Unpadded text still goes
  through the Goose decoder; that is the next patch, and it is named in
  [the competitive review](docs/competitive-review-2026-11-07.md#next-iteration).

The design, the contract argument, the differential corpus, the negative
controls and the dependency cost are in
[the competitive review](docs/competitive-review-2026-11-07.md). The raw
campaigns are reproduced by `bench/campaign.sh` and described in
[benchmark scope](bench/README.md).

## Why not the standard library

The pinned compiler ships `base64`, and this module reuses its encoder for whole
3-byte groups. It is not sufficient for four reasons, each quoted from the
pinned `docs/stdlib.md`:

- It rejects "other alphabets (the `-` and `_` of the URL-safe alphabet are
  invalid)", which RFC 4648 §5 and RFC 7515 §2 require.
- It always pads and rejects "unpadded text", which RFC 7515 §2 forbids.
- "It does not require the bits left over before the padding to be zero, so
  `Zh==` decodes the same as `Zg==`". This module rejects that as
  `NonCanonical`.
- It has no output budget: it grows the caller's buffer to whatever the input
  implies.

`tests/stdlib_parity.goose` proves the two agree byte for byte on the compatible
path and differ exactly where the policy is added. See
[the design contract](docs/design.md) for the full argument.

## Consumers

**goose-http, HTTP Basic.** goose-http sends an explicit caller-supplied
`Authorization` header's bytes unchanged and performs no authentication
negotiation. RFC 7617 §2 defines the value as `Basic ` plus the padded
standard-alphabet Base64 of `user-id ":" password`. `examples/basic_auth.goose`
builds that value, rejects a user-id containing the separator, and checks the
RFC's own example. The standard library alone is sufficient for this case; the
example uses this module because it is already present.

**JSON and protocol fields.** JSON has no byte string, so protocols that embed
binary in JSON encode it as Base64. JOSE (RFC 7515 §2) and its descendants use
the URL-safe alphabet with the padding omitted and require canonical encoding.
`examples/json_binary.goose` decodes such a field with a byte budget and shows
why canonicality matters: `-_8` and `-_9` are different strings that a
permissive decoder turns into the same two bytes, so a key identifier or a
detached signature compared as text and as bytes can disagree.

Neither consumer is modified by this repository, and neither has adopted this
library. The examples state the contract each would need; adoption is a separate
decision for those projects.

## Support and development

Validated on Linux x86-64 with the pinned Goose compiler, GCC and Clang; CI runs
on Ubuntu 24.04. The library is pure Goose and makes no OS calls. Other
platforms and compiler revisions have not been verified. Tests need Python 3.11+.

Run `make check test` after setup, and `make fuzz mutation` before claiming a
behaviour change is proven. See [development commands](docs/development.md),
[validation history](docs/validation.md) and
[benchmark scope](bench/README.md). CI checks that the benchmark harness builds
and runs, without timing thresholds. See [contributing](CONTRIBUTING.md),
[security reporting](SECURITY.md), [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md).
