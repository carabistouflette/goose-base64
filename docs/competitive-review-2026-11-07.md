# Competitive review: goose-base64 against maintained Base64 implementations

Status: implementation and measurement in progress. **No SOTA designation is
claimed, and none is supported by the numbers below.** This document records the
pinned sources, the contract each one actually offers, the cost of adapting it to
this library's contract, and where the measured numbers live. The numbers
themselves are in the campaign JSON files named in *Measured results*.

## Method

Every claim about a competitor is read from its own source at a pinned commit,
fetched from the project's official repository, not from a summary:

| Library | Repository | Pinned commit | Date | Version |
| --- | --- | --- | --- | --- |
| simdutf | https://github.com/simdutf/simdutf | `4ab2be54f0b41536d5258675ffad7ba5d10fe384` | 2026-11-03 | 9.3.3 |
| aklomp/base64 | https://github.com/aklomp/base64 | `5d5074cb856b9a53fe64f04ddf47812a85f4fb5a` | 2026-10-10 | — |
| Goose standard library | https://github.com/aardappel/goose | `eadca409f68210893f366e60d0c2f0dc29a339be` | pinned by `GOOSE_REVISION` | — |

`bench/ext/build.sh` fetches the two external libraries at exactly those commits,
builds them, and writes `.build/ext/identity.json` with the resolved `HEAD`, the
amalgamation and object hashes, and the compiler. The Goose standard library is
hashed in place from the compiler's own tree by `bench/measure.py`.

## Candidates and why each is here

**The Goose standard library (`base64`)** is the real Goose alternative: it is
maintained, it ships with the compiler, and this library already reuses its
encoder for whole 3-byte groups. It is not sufficient on its own, and
`docs/design.md` quotes the four reasons from `docs/stdlib.md` §base64. It is
measured as a **lower bound**, never as a race, because it does strictly less
work.

**`bench/strict.goose`** is the equal-contract Goose competitor: the standard
library's codec plus the policy layer a caller has to write today to get this
contract. It is the only Goose implementation that does the same work, so it is
the fair Goose race. It is benchmark code, not a second library to ship.

**simdutf** is the strongest maintained C++ implementation with an API that
natively expresses most of this contract. It is the primary external reference.

**aklomp/base64** is the other widely used C implementation, and it is the
instructive one: its API expresses *less* of this contract than simdutf's, so the
adaptation cost is visible and measurable rather than assumed.

A wrapper around our own standard library is not enough on its own, which is why
the two external libraries are here.

## Contract matrix

`✓` means the library enforces it natively. `adapt` means the harness has to
supply it. `✗` means it cannot be expressed.

| Guarantee | goose-base64 | Goose stdlib | simdutf | aklomp/base64 |
| --- | --- | --- | --- | --- |
| Standard alphabet | ✓ | ✓ | ✓ `base64_default` | ✓ |
| URL-safe alphabet | ✓ | ✗ | ✓ `base64_url` | ✗ (no mention of `url` anywhere in `README.md`, `include/libbase64.h` or `lib/lib.c`) |
| Padded text | ✓ | ✓ | ✓ `base64_default` | ✓ |
| Unpadded text | ✓ | ✗ | ✗ under `strict` (see below) | ✗ (`base64_decode` returns 0 when `state.bytes != 0`) |
| Rejects non-zero trailing bits | ✓ `NonCanonical` | ✗ ("It does not require the bits left over before the padding to be zero, so `Zh==` decodes the same as `Zg==`") | ✓ `BASE64_EXTRA_BITS` under `strict` | ✗ (no trailing-bit test in `lib/arch/generic/dec_tail.c`) |
| Rejects whitespace | ✓ `InvalidCharacter` | ✓ ("It rejects line breaks, white space") | ✗ (see below) | ✓ |
| Rejects the other alphabet's two characters | ✓ | ✓ | ✓ | ✓ (only one alphabet exists) |
| Output budget | ✓ `max_out` | ✗ | ✓ `OUTPUT_BUFFER_TOO_SMALL` | ✗ (caller allocates 3/4) |
| Failure leaves the caller's buffer unchanged | ✓ | ✓ ("leaves `out` as it was") | ✗ (writes as it goes) | ✗ (writes as it goes) |
| Distinguishes padding from character errors | ✓ | ✗ (one `bool`) | ✓ (`INVALID_BASE64_CHARACTER` covers both) | ✗ (one `int`) |

### simdutf's `strict` mode is not the same as this library's canonicality rule

`last_chunk_handling_options::strict` is documented in
`include/simdutf/implementation.h` as "error when the last chunk is partial, 2 or
3 chars, and unpadded, or non-zero bit padding". It therefore rejects *valid
unpadded text* as `BASE64_INPUT_REMAINDER` while also rejecting non-zero trailing
bits as `BASE64_EXTRA_BITS`. This library keeps those two decisions separate: an
unpadded 3-character tail is valid, and only its unused bits are checked.

The consequence is precise and it is why the comparison is scoped: **simdutf
matches this contract on the padded policies only.** On `Padding.Unpadded` it
cannot express the contract at all — `loose` accepts non-canonical text and
`strict` rejects valid text. The benchmark therefore races the padded policy,
which is the policy the harness's main rows use.

### simdutf ignores ASCII whitespace

`include/simdutf/scalar/base64.h` classifies a byte through
`tables::base64::to_base64_value`; a code of 64 is the ASCII space class, and the
tail loop's comment says "We have a space or a newline or garbage. We ignore it."
This is not gated on `accept_garbage`. Measured with the pinned build:

```
Zg ==        -> error=0 count=1
Z g==        -> error=0 count=1
Zg=\n=       -> error=0 count=1
Zm9v YmFy    -> error=0 count=6
Zg\t==       -> error=0 count=1
```

This library rejects every one of those as `InvalidCharacter`. So simdutf is
**faster on inputs without whitespace and accepts inputs this library refuses**.
That is a different guarantee, not a faster implementation of the same one, and
the `reject/whitespace` row carries `comparable` 0 for that reason.

## Interop, ownership and API cost

This is the part that decides whether a comparison is fair, so it is stated
before any number.

**simdutf.** C++17, header plus one amalgamated translation unit. The caller owns
both buffers; there is no allocation inside the codec. `binary_to_base64` returns
the number of characters written; `base64_to_binary` returns
`result { error_code, count }`. Two costs are real:

- *Failure atomicity.* simdutf writes into the destination as it decodes, so a
  rejected call has already written bytes. This library writes nothing. The
  harness gives simdutf the tail of the caller's buffer and truncates back to the
  original length on error, which makes the observable buffer identical and
  charges no extra copy. That is the most favourable adaptation available, and it
  is still weaker than "no write at all": the bytes past the logical end were
  touched.
- *Budget.* simdutf has no byte budget; `OUTPUT_BUFFER_TOO_SMALL` is about the
  destination capacity the caller passed. The harness checks `max_out` itself
  before the call, so the check is charged to simdutf rather than skipped.

**aklomp/base64.** C99, one object file, caller-owned buffers, no allocation.
Its API expresses the least of this contract, so the adaptation is the largest:

- No URL alphabet, so URL text needs a normalisation copy before decoding.
- No canonicality check, so the harness supplies one.
- No budget, so the harness supplies one.
- No character validation in the fast path beyond a table that maps invalid
  bytes to 255, so the harness supplies the validation pass.
- Writes as it goes, so the same truncate-back adaptation as simdutf.

The result is that the aklomp row measures *aklomp's decoder plus this library's
validation*, which is exactly what a caller would have to build. It is a fair
race and it is not a like-for-like codec comparison; the row is labelled that way.

**Neither external library is vendored.** `bench/ext/build.sh` fetches them at the
pinned commits into `.build/ext-src`, which is not tracked. Nothing in this
repository links them, and the library itself remains pure Goose.

## Classification

| Row | Class | Why |
| --- | --- | --- |
| `b64` vs `strict` | **ratio** | Same contract, same work, proved byte for byte by `bench/strict_equivalence.goose` and re-checked from the content checksums on every campaign. |
| `b64` vs `b64_old` | **ratio** | The frozen baseline from the immutable archive, built with the current harness. Same contract by construction. |
| `b64` vs `simdutf` | **ratio on the padded policy, ceiling on the rest** | Equal contract on the rows it declares comparable. Its whitespace tolerance and its inability to express unpadded text are recorded, not hidden. |
| `b64` vs `aklomp` | **ratio, adapted** | Equal contract after the harness supplies validation, canonicality and budget. The adaptation is part of the measured cost. |
| `stdlib` | **lower bound, not classable** | Permissive: no URL alphabet, no unpadded text, no canonicality, no budget. It does less work. |

## Measured results

The campaigns are recorded in `.build/c1/` and are reproduced by
`bench/campaign.sh`. Each is 21 samples (one warmup, 20 measured), alternating
implementation order, all implementations on one fixed CPU, with the contention
gate and the identity snapshots described in `bench/measure.py`.

| Campaign | Compiler | CPU | Status |
| --- | --- | --- | --- |
| `campaign-1.json` | gcc 16.2.1 | 2 | first campaign; superseded by the confirmation run |
| `campaign-confirm.json` | gcc 16.2.1 | 2 | **accepted**; independent of the first |
| `campaign-clang.json` | clang 23.1.4 | 2 | portability vs native: the stdlib's `simd fn` versions exist only here |

The numbers, the dispersion, the bootstrap intervals and the raw per-sample
observations are in those files. `docs/validation.md` quotes the ones that
support a claim, with their intervals.

Decode, gcc, `campaign-confirm.json`, ratio `b64 / comparator` (below 1 is
faster):

| Row | vs `b64_old` | vs `strict` | vs `simdutf` | vs `aklomp` |
| --- | --- | --- | --- | --- |
| 1 KiB | 0.246 | 0.505 | 12.895 | 1.450 |
| 4 KiB | 0.236 | 0.504 | 15.595 | 1.437 |
| 64 KiB | 0.239 | 0.499 | 14.989 | 1.439 |

Encode, gcc, `campaign-confirm.json`:

| Row | vs `b64_old` | vs `strict` | vs `simdutf` | vs `aklomp` |
| --- | --- | --- | --- | --- |
| 1 KiB | 0.950 | 0.977 (unresolved) | 18.790 | 6.374 |
| 64 KiB | 0.987 (unresolved) | 1.014 (unresolved) | 15.636 | 5.699 |

The two gcc campaigns agree within their intervals on every row that matters.

## What the numbers say, and what they do not

The change described in `docs/validation.md` makes decoding about four times
faster than the frozen baseline on inputs of 1 KiB and larger. That is a real
improvement against this library's own previous behaviour and against the
equal-contract Goose competitor.

It does **not** make this library competitive with a SIMD codec. On the same
workload, on the same CPU, in the same campaign, simdutf decodes roughly an order
of magnitude faster and encodes roughly an order of magnitude faster. aklomp's
adapted decoder is also faster. Those rows are reported with their intervals and
are not hidden.

### Decomposing the gap

That last sentence is true and it is also misleading if left there, so here is
the decomposition. Absolute medians from `campaign-confirm.json`, decode, reused
buffer:

| Row | 1 KiB | 64 KiB | ns/byte at 64 KiB |
| --- | --- | --- | --- |
| `simdutf` | 65.4 ns | 3,476.7 ns | 0.053 |
| `aklomp` (adapted) | 610.1 ns | 36,725.3 ns | 0.560 |
| `b64` | 845.6 ns | 51,653.6 ns | 0.788 |
| `stdlib` | 1,107.6 ns | 69,565.7 ns | 1.062 |
| `strict` | 1,677.0 ns | 104,478.3 ns | 1.594 |
| `b64_old` | 3,436.7 ns | 216,792.1 ns | 3.308 |

`simdutf`'s 65 ns is a **ceiling, not an equal-contract result**. It does not
validate against this contract: it accepts ASCII whitespace, and its `strict`
mode cannot express unpadded text. Its number is what a codec costs when the
caller has already decided the input is acceptable, or does not care.

`aklomp`'s 610 ns is the cost of **one particular adaptation**: this library's
validation pass written as a scalar C++ loop over the same table, then aklomp's
SIMD decoder. It is not a lower bound on what the contract costs, and it must not
be read as one. A scalar validation loop is one way to implement the predicate;
it is not the only way, and it is not the cheapest way.

The prototype in `bench/ext/bench_ext.cpp` (`simdutf_fast`) is the cheaper way,
and its measured number is the one that decides whether a native backend is
worth its dependency. It is **139.6 ns** at 1 KiB against `aklomp`'s 866.4 ns in
the same campaign. See *The fast-path prototype* below.

## The fast-path prototype

The design the coordinator asked for, implemented in `bench/ext/bench_ext.cpp` as
`simdutf_fast` and measured in the same campaign as everything else:

1. **O(1) shape check.** `decoded_len` gives the exact appended count or `-1`,
   and the budget is checked, both before any byte is examined.
2. **Native decode into a scratch buffer** with simdutf `strict`.
3. **Equality test on the produced length.** If the call succeeded *and* wrote
   exactly `need` bytes, the input is accepted and the scratch is appended to the
   caller's buffer.
4. **Goose validator on every other outcome**, to produce the precise error.

### Why the length equality is enough for the padded policy

Our shape check requires `n % 4 == 0`. simdutf ignores ASCII whitespace, so with
`w` whitespace bytes its effective length is `n - w`, and `strict` requires
`(n - w) % 4 == 0`; with `n % 4 == 0` that gives `w % 4 == 0`. Its produced count
is `(n - w)/4*3 - p'`, where `p'` is the padding it saw, while our `need` is
`n/4*3 - padlen`. So `count == need` implies `padlen - p' = 3w/4`. Since
`padlen <= 2` and `p' >= 0`, that needs `3w/4 <= 2`, hence `w <= 2`; combined
with `w % 4 == 0` it forces `w == 0`.

**A success whose count equals `need` cannot have contained whitespace.** That is
why the fast path does not need to re-scan for whitespace, and why it does not
need to trust simdutf's weaker predicate.

This is an argument, not evidence, so `bench-ext --probe-differential` checks it
exhaustively: every text of length 0..6 over a pool containing both alphabets'
extra characters, `=`, three whitespace bytes, an invalid byte and NUL, plus
every valid text of length 4, 8 and 12 with one and two whitespace bytes inserted
at every position. The fast path must agree with the validator on every case, and
a success must produce exactly `need` bytes. A single disagreement is a
counterexample and fails the probe.

### The measured result

`campaign-fastpath2.json`, gcc 16.2.1, cpu2, accepted, decode, reused buffer.
This is the **safe** implementation, after the buffer-overrun defect below was
found and fixed:

| Row | 1 KiB | 4 KiB | 64 KiB |
| --- | --- | --- | --- |
| `simdutf` (ceiling, weaker predicate) | 93.5 ns | 317.8 ns | 5,070.0 ns |
| **`simdutf_fast` (this contract)** | **139.6 ns** | **364.9 ns** | **5,691.2 ns** |
| `aklomp` (scalar-validation adapter) | 866.4 ns | 3,361.2 ns | 52,817.9 ns |
| `b64` | 1,262.2 ns | 4,836.2 ns | 77,064.9 ns |

Ratio `b64 / simdutf_fast`: **9.082** [8.880, 9.161] at 1 KiB and **13.577**
[13.477, 13.628] at 64 KiB.

The fast path costs **49% over simdutf at 1 KiB, 15% at 4 KiB and 12% at 64 KiB**.
That is the scratch copy plus the safe call's bookkeeping, and it is the entire
price of the contract on the success path. The validation pass is gone, not
because the contract was weakened, but because the length-equality test replaces
it.

For comparison, the first, unsafe prototype measured 100.1 ns at 1 KiB — 3.7%
over simdutf. The difference between 100.1 and 139.6 ns is what buffer safety
costs at that size, and it is the reason the unsafe number is not the one quoted.

**This refutes the earlier reading of the `aklomp` row.** The 610 ns that row
showed was the cost of *that adapter's* scalar validation loop, not a lower bound
on what the contract costs. The contract costs almost nothing on the success
path; a scalar implementation of it costs a lot. The difference between those two
statements is the whole decision, and it is why the prototype had to be built
rather than argued.

The absolute `b64` number in this campaign (1,265.2 ns) is higher than in
`campaign-confirm.json` (845.6 ns) because the machine was busier; the ratios are
consistent across the two campaigns (`b64_over_b64_old` 0.254 vs 0.246,
`b64_over_strict` 0.514 vs 0.505), which is why ratios and not absolute times are
compared.

The prototype's numbers are superseded by the shipped package's, in
`campaign-accel.json` on the same CPU: `b64_accel` reaches **142.2 ns** at 1 KiB
and **4,138.3 ns** at 64 KiB, against the prototype's 139.6 ns and 5,691.2 ns.
The 1 KiB figure is a wash; the 64 KiB figure is 27% better, because the shipped
backend writes into the builder's free region instead of a scratch plus a copy.
The prototype is kept in this document as the record of the design decision, not
as the current number.

### What this means for the decision

A native backend is **justified by the measurement**, not refuted by it. The
prototype's 9-14x is what the design was expected to buy; the shipped package
delivers 8.9x / 14.4x / 18.6x on decode and 20.3x / 21.7x / 23.7x on encode
against the pure-Goose library, and it is measured in the Goose harness rather
than modelled in C++. The remaining question was packaging and cost, not speed,
and both are answered in *The shipped backend* below:

- The dependency is a C++ toolchain and a vendored simdutf for consumers of the
  accelerated package. It is optional by being a separate package, so the pure
  Goose package stays the default and keeps its no-native-code property.
- The unpadded policy is not covered by the length-equality argument as stated.
  For `Padding.Unpadded`, simdutf `strict` rejects the partial final chunk this
  library accepts, so the design there is native `strict` over the whole groups
  plus a constant-size Goose tail. That is a smaller win and it is the next
  thing to measure, not something this campaign establishes. The URL alphabet
  *is* covered, because simdutf has `base64_url_with_padding`.

### Buffer safety, and a defect the first prototype had

The first version of this prototype sized the scratch buffer to `need` and called
`simdutf::base64_to_binary`. That is a **buffer overrun hazard**, and simdutf's
own documentation says so: the output buffer must be at least
`maximal_binary_length_from_base64(input, length)` bytes, which is larger than
`need`, because simdutf may write a partial group before it discovers an error.
"If you fail to provide that much space, the function may cause a buffer
overflow."

The prototype now uses `base64_to_binary_safe` with an explicit `outlen`
capacity, which cannot write past the buffer. simdutf documents negligible
overhead for it when the input has no ignorable characters — which is exactly the
fast path, since a success there implies no whitespace. The measured cost of the
safe call is included in the numbers above.

Two further defects were fixed at the same time:

- **Success without output.** If the native call refused an input the validator
  accepted, the first version returned `E_NONE` having appended nothing — a
  silent wrong answer. It now runs the scalar write pass in that case, so a
  success always produces the bytes. The differential probe checks that a success
  produces exactly `need` bytes and a rejection produces none.
- **Global mutable state.** The scratch is a function-local `static`, reused
  across calls. That is acceptable for a single-threaded prototype and models
  Goose's bump allocator, but it is global mutable state and must not be carried
  into the library.

### Evidence

`bench-ext --probe-differential` walks every text of length 0..6 over a pool
containing both alphabets' extra characters, `=`, three whitespace bytes, an
invalid byte and NUL; every valid text of length 4, 8 and 12 with one and two
whitespace bytes inserted at every position; and 448 malformed long inputs (a
valid text with one byte corrupted at a random position, at sizes 4 to 65536,
where simdutf's vector path is active). The fast path must agree with the
validator on every case, a success must produce exactly `need` bytes, and a
rejection must produce none.

Result: **3,258,269 cases, 0 disagreements**, both in the plain build and in the
sanitizer build.

`bench-ext --probe-asan` calls the fast path with a **fresh, exactly sized**
output buffer on every call, so a sanitizer sees an overrun that a retained
vector's spare capacity would hide. It is built with
`-fsanitize=address,undefined -fno-sanitize-recover=all` and run with
`ASAN_OPTIONS=detect_leaks=1:abort_on_error=1` and `UBSAN_OPTIONS=halt_on_error=1`.
Result: **64 exact-capacity calls, no overrun**, exit 0.

`bench-ext --probe-asan-negative` is the control that proves the sanitizer is
actually instrumented, and it is also the concrete counterexample for the defect.
It calls the **unsafe** `base64_to_binary` with a buffer one byte too small, and
ASan reports:

```
ERROR: AddressSanitizer: heap-buffer-overflow
WRITE of size 4
  #0 base64_decode<true>            simdutf.cpp:34661
  #1 base64_decode_block<true>      simdutf.cpp:34727
  #2 compress_decode_base64<...>    simdutf.cpp:38059
  #3 simdutf::haswell::implementation::base64_to_binary
  #6 probe_asan_negative            bench_ext.cpp:597
```

So the first prototype's `scratch.resize(need)` really was a four-byte overrun on
a 1 KiB input, not a theoretical concern. The safe call refuses the same buffer
with `OUTPUT_BUFFER_TOO_SMALL` instead of writing past it, which is why the fast
path uses it.

### What this does not establish

The scratch is a `std::vector` in C++, and reusing it models Goose's bump
allocator rather than measuring it. That limit is now closed: the backend was
built as a real Goose package and measured in the Goose harness, and the numbers
in *The shipped backend* below are the in-process ones. The prototype's numbers
are kept only as the record of what the design was expected to buy.

### Unpadded and URL policies

The length-equality argument is stated for the padded policy, and it is not
assumed for the others. For `Padding.Unpadded`, simdutf `strict` rejects a
partial final chunk, which is exactly the shape this library accepts, so the
native call cannot be the fast path for a 2- or 3-character tail. The design
there is: native `strict` over the whole groups, and the constant-size tail
handled by Goose. That is a smaller win and it is not implemented; it is named
as the next step rather than claimed. The URL alphabet *is* covered, because
simdutf has `base64_url_with_padding` and the padded argument is
alphabet-independent.

## The shipped backend: `b64_accel`

The prototype above is now a package in this repository, and it is the answer to
"is the gap the contract, or is it the code". It is not the contract.

### What it is

`b64_accel.goose` is a package of its own, beside `b64.goose` and not a module
of it. `b64_accel.build` is its sidecar, so the compiler looks for
`b64_accel.build` only when a program imports `b64_accel`; `import b64` finds no
sidecar and builds no C. The two packages come from the same source, so
`b64_accel` uses `b64::Policy` and `b64::Error` themselves — not copies, not a
parallel enum that could drift.

The native part is `b64_accel.cpp` plus simdutf's own single-header
amalgamation, vendored at the pinned commit recorded in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). It exposes exactly two
functions:

```c
int64_t b64_accel_decode(gs_rref out, SliceU8 src, int64_t alphabet, int64_t need);
int64_t b64_accel_encode(gs_rref out, SliceU8 src, int64_t alphabet,
                         int64_t padding, int64_t need);
```

`SliceU8` is `{ uint8_t *data; int64_t len; }`, the layout the compiler emits for
a `u8[:]`; the package declares it itself because `goose.h` does not carry the
slice types.

`gs_rref` and `gs_bld_append` are the documented way for a package's C to append
to a Goose builder (`docs/packages.md` §4, `src/runtime/goose.h`). A Goose
`u8[:]` crosses as a struct by value, not as two parameters: spec §7.10 and C.2,
"Slice: `{ data: T*, len: int64 }`". The generated C for a program that imports
this package declares

```c
typedef struct { uint8_t *data; int64_t len; } sl_u8;
gs_i64 b64_accel_decode(gs_rref, sl_u8, gs_i64, gs_i64);
```

so the package declares the same plain struct itself (`goose.h` does not carry
the slice types) rather than taking a pointer and a length as separate
arguments. The first version of this file did take them separately and worked,
but only because two eightbyte members and two integer arguments land in the
same registers under the SysV x86-64 convention; that is an accident of one ABI,
not a declaration of it.

The backend does not use `gs_bld_append` for the decode. It writes at
`out.stk->top` and moves the top and the header's count together only after
simdutf reported success, which is the same operation with the commit deferred,
and it costs no copy and no allocation.

### The transaction, and its limits

This is **not** a separate scratch buffer, and the atomicity it gives is
logical, not "no byte was written":

* simdutf decodes straight into the builder's free region,
  `[out.stk->top, out.stk->top + need)`. It writes as it decodes, so a rejected
  text may already have left bytes there before the error is reported.
* The commit — moving `out.stk->top` and `out.hdr->len` together — happens only
  after `SUCCESS` and only after `outlen == need`. On refusal neither moves.
* So on refusal the caller's buffer is unchanged in every way it can observe:
  `out.len` is the same, `out[0..len)` is the same bytes, and the bytes above
  the top are overwritten by the next append. Nothing can read them: a slice of
  a builder is bounded by its length.
* The one effect a refused call does have is that the pages it touched are now
  committed to the data stack. That is a resource effect, not a change to any
  value, and it is the price of not copying.

`b64::decode` is stronger: it validates the whole text before its first write.
Both satisfy the documented contract, which is about the caller's buffer. The
difference is stated here rather than hidden, because a caller that reads the
free region of a builder — which the language does not let it do — would see it.

### Where the contract lives

Every decision stays in Goose. `b64_accel::decode` computes the shape and the
budget with `b64::decoded_len` and `policy.max_out` *before* calling C, in the
same order as `b64::decode`, so the two agree on which error a text that fails
several checks reports. The native part returns only `0` (appended exactly
`need` bytes) or `1` (refused); on `1` the Goose side calls `b64::decode`, which
produces the precise `Error` and the precise atomicity. There is no path on
which the native part reports success and nothing is appended: the Goose side
compares the returned count with `need` and falls back if they differ.

The one thing the native part decides is whether simdutf's answer is
trustworthy, and it decides that with a length equality rather than a
character-class re-check:

* simdutf ignores ASCII whitespace even when it rejects garbage, so a text with
  whitespace can decode successfully. It then produces fewer bytes than `need`,
  because the whitespace replaced data characters.
* Under the padded policy the text length is a multiple of four, and simdutf
  requires the data characters to form whole groups, so the whitespace count is
  a multiple of four too. A shortfall of `padlen - p'` bytes with `padlen <= 2`
  cannot be a positive multiple of four.
* Therefore a success with `outlen == need` cannot have contained whitespace.

That is an argument, not a measurement, so it is also measured: see the
differential test below, which enumerates every text of length 0-4 over a set
that includes `' '`, `'\t'`, `'\n'`, `'='` and both alphabets' extra
characters, and every text of length 5-7 over a set built to reach the
whitespace/padding interaction.

### Scope: padded only

The native decode is used only for `Padding.Padded`. simdutf's `strict` last
chunk rejects a partial final group, which is what the padded policy requires,
and rejects non-zero trailing bits, which is the canonicality rule; but the same
mode also rejects the partial final group that the *unpadded* policy accepts,
and simdutf has no mode that accepts the group and still checks the trailing
bits. Unpadded text therefore goes to `b64::decode` unchanged. That is a scope
limit of this backend, not a contract change, and it is visible in the code as
the `if policy.padding == b64::Padding.Padded` guard.

Encoding has no failure mode past the budget, so the native part is used for
every policy. It is handed `need` — `b64::encoded_len(src.len, policy.padding)` —
and checks it on both sides of the write: simdutf's own length for this source
and these options must equal `need` before anything is written, and the number of
bytes it actually wrote must equal `need` before the commit. It returns `0` only
when it appended exactly `need` bytes.

Both checks are load-bearing. Without the first, a native part whose length
disagreed with the Goose side's would commit its own count and then the Goose
side would fall back and append again — a double append. Without the second, a
short write would be committed as a full one. With both, the Goose side's `== 0`
test is the whole protocol, and the third negative control below is the proof
that the differential test catches the double append if the protocol is broken.

### Differential evidence

`tests/accelerated.goose` runs both implementations on the same input and the
same policy and requires the same `Error`, the same appended bytes, and the same
untouched prefix when the call fails. It is enumerated, not sampled:

| corpus | cases |
|---|---|
| every text of length 0-4 over 13 symbols (both alphabets, `=`, `' '`, `\t`, `\n`, `!`, `0`, `z`) | 30,941 texts |
| every text of length 5-7 over 5 symbols (`A`, `B`, `' '`, `=`, `/`) | 96,875 texts |
| every byte value in each of the four positions of a group | 1,024 texts |
| whitespace injected at every position of 11 valid texts, 5 whitespace bytes | 550 texts |
| one byte replaced by every value, at start/middle/end of 4 valid texts | 7,168 texts |
| every trailing-bit value of a 2- and a 3-character tail, padded and not | 192 texts |
| every source of length 0-2 over the whole byte domain, plus lengths 0-39 | 65,833 sources |
| round trip through the accelerated path, lengths 0-199, all four policies | 800 |

Each text is checked under all four policies and at four budgets (unbounded,
zero, `need - 1`, `need`), so the budget boundary and the write are exercised on
the same input. The run is `make test`; it prints
`accelerated differential passed`.

Two negative controls were run against the real harness, and both were caught:

| control | result |
|---|---|
| native part reports success without appending | `assert failed (tests/accelerated.goose:32)` — the length comparison |
| native part uses `loose` and drops the length equality | `assert failed (tests/accelerated.goose:31)` — the `Error` comparison, on a whitespace or non-canonical text |
| native encode commits and then reports refusal | `assert failed (tests/accelerated.goose:46)` — the length comparison in `same_encode` |

The second is the control for the claim that the length equality is what keeps
simdutf's forgiving behaviour out of this contract. The third is the control for
the encode protocol: it is the double append that a native part which committed
and then reported refusal would cause.

### Measured, in the Goose harness

`campaign-accel.json`, gcc 16.2.1, cpu2, accepted, 20 paired samples, identity
snapshots stable. Medians in ns per call:

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

| Row | `b64 / b64_accel` | `b64_accel / simdutf_fast` | `b64_accel / simdutf` |
| --- | --- | --- | --- |
| decode 1 KiB | **8.872** [8.762, 9.029] | **1.018** [1.005, 1.044] | 1.514 |
| decode 4 KiB | **14.380** [14.336, 14.437] | **0.926** [0.916, 0.932] | 1.058 |
| decode 64 KiB | **18.589** [18.552, 18.613] | **0.729** [0.723, 0.736] | **0.821** |
| encode 1 KiB | **20.308** [19.746, 20.594] | 0.971 [0.943, 1.019] unresolved | 1.002 |
| encode 4 KiB | **21.733** [21.379, 21.858] | **0.874** [0.864, 0.882] | **0.865** |
| encode 64 KiB | **23.726** [23.624, 23.841] | **0.646** [0.628, 0.654] | **0.665** |

`b64_accel / simdutf` is derived from the two medians rather than from a paired
ratio, because `simdutf` is not in `COMPARABLE_PAIRS` against `b64_accel`; it is
given to one place and should be read as an indication.

The last column is the interesting one and it needs care. `b64_accel` is **ahead
of raw simdutf at 64 KiB** (0.821) and behind it at 1 KiB (1.514). The 64 KiB
advantage is not the codec: `bench/ext/bench_ext.cpp` writes into a `std::vector`
resized to the output length, which zero-fills, while `b64_accel` writes into the
builder's free region, which is already committed address space and is not
filled. The difference is the fill. `simdutf` is therefore the ceiling *for that
output model*, and `b64_accel` beating it is reported rather than suppressed.

The 1 KiB gap is the shape check, the budget check, the Goose call and simdutf's
own fixed cost on a short input. It is 1.51x, not 9x, and it is the honest
statement of what the contract costs on the success path.

### Dependency and portability cost

| cost | value |
|---|---|
| vendored source | 3.6 MB (`simdutf.cpp` 3,034,912 B, `simdutf.h` 615,770 B) |
| licence | Apache-2.0 OR MIT; taken under Apache-2.0, both texts vendored |
| build | one C++ translation unit, `-O2`, compiled once per C compiler under `~/.goose/build`; 17 s cold on this machine |
| link | `-lstdc++`; the native part is linked statically into the program |
| runtime | none: no shared library, no `dlopen`, no initialisation |
| platforms | simdutf selects a kernel at compile time for x86-64, ARM64, RISC-V, PPC64 and s390x, and falls back to its own scalar code elsewhere; the Goose side is unchanged |
| who pays | only a program that imports `b64_accel`. `import b64` compiles no C++ and links no C++ runtime |

The alternative — a `cmake_target` that fetches simdutf at configure time — was
rejected because it makes the build need the network and makes the measured
identity depend on a fetch. Vendoring is the cost of a reproducible identity.

### What this does not establish

It does not establish that this library is state of the art. It establishes that
the *contract* is not what costs 9-14x: a backend that keeps the contract
exactly, and is checked against the Goose implementation on the corpus above,
closes most of the gap. The remaining distance to raw simdutf is the price of
the shape check, the budget check, the fallback call and the Goose call
overhead, and it is reported rather than argued away.

It also does not establish that the unpadded policy can be accelerated the same
way. That is the next patch, and it is named below.

## Next iteration

1. **Unpadded decode.** Native `strict` over the whole groups with
   `only_full_chunks`, and the 2- or 3-character tail decoded by Goose after the
   tail's canonicality has been checked in Goose. The tail is constant-size, so
   the extra work is O(1). This is the only policy still on the scalar path.
2. **A pure-Goose `simd fn` decoder.** Still the KISS option and still
   dependency-free. `campaign-clang.json` shows the standard library's own
   `simd fn` decoder at **616.1 ns** at 1 KiB against this library's 1,118.0 ns
   under clang, with a weaker contract — a target, not a result. It is blocked
   on the same thing as before: a 256-entry table is a gather, and a gather is
   not faster than the scalar loads it replaces, so a vectorizable value
   extraction would have to replace the table first.
3. **Encode.** The native encode is already used for every policy; the remaining
   question is whether the Goose `encode` should keep delegating whole groups to
   the standard library or write them itself, which is a measurement on the
   scalar path and not a contract question.
