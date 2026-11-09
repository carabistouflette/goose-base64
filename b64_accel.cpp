// SPDX-License-Identifier: Apache-2.0
// The optional native backend of goose-base64.
//
// This file is not part of the `b64` package. It belongs to the separate
// `b64_accel` package, whose sidecar (`b64_accel.build`) is the only thing that
// compiles it: `import b64` never builds or links any of this.
//
// What it does, and what it deliberately does not do:
//
//   * It decodes and encodes with simdutf, and nothing else. It does not
//     decide the contract: the Goose side has already computed the exact
//     output length from the policy, checked the budget, and will fall back to
//     `b64::decode` for the precise error whenever this returns "refused".
//   * It never allocates. The builder's element region is the output buffer.
//   * It commits (moves the stack top and the header's count together) only
//     after simdutf reported success and the produced length matched the
//     expected one. See the transaction note on `b64_accel_decode` for exactly
//     what that does and does not guarantee.
#include "goose.h"

#include <simdutf.h>

#include <cstddef>
#include <cstdint>

namespace {

// A Goose `u8[:]` crosses the boundary as this struct by value, not as two
// parameters: spec §7.10 and C.2, "Slice: { data: T*, len: int64 }". The
// generated C for a program that imports this package declares exactly
// `typedef struct { uint8_t *data; int64_t len; } sl_u8;` and the extern as
// `gs_i64 b64_accel_decode(gs_rref, sl_u8, gs_i64, gs_i64);`. `goose.h` does
// not carry the slice types, so the package declares the one it uses; the
// layout is the same plain struct the compiler emits, so it matches on every
// platform rather than only where two integer arguments happen to land in the
// same registers.
struct SliceU8 {
    uint8_t *data;
    int64_t len;
};

// The layout the compiler emits for `sl_u8`. If a future Goose changes it, this
// fails to compile instead of silently reading the wrong register.
static_assert(sizeof(SliceU8) == 16, "a u8 slice is a pointer and an int64");
static_assert(offsetof(SliceU8, data) == 0, "a u8 slice starts with its data");
static_assert(offsetof(SliceU8, len) == 8, "a u8 slice's length follows its data");

// The Goose side passes the alphabet as 0 for RFC 4648 §4 and 1 for §5.
simdutf::base64_options PaddedOptions(int64_t alphabet) {
    return alphabet == 0 ? simdutf::base64_default : simdutf::base64_url_with_padding;
}

simdutf::base64_options UnpaddedOptions(int64_t alphabet) {
    return alphabet == 0 ? simdutf::base64_default_no_padding : simdutf::base64_url;
}

}  // namespace

// extern fn b64_accel_decode(out: u8[>..]&, src: const u8[:], alphabet: i64,
//                            need: i64) -> i64;
//
// `need` is the exact number of bytes the Goose side computed for this text
// under the policy. Returns 0 when exactly `need` bytes were appended, 1 when
// the text was refused and the caller must fall back.
//
// The transaction, precisely. This is not a scratch buffer: simdutf decodes
// straight into the builder's free region, `[out.stk->top, out.stk->top +
// need)`, which is the same place `gs_bld_append` writes. simdutf writes as it
// decodes, so on a rejected text it may already have written some bytes there
// before it reports the error. What is deferred is the *commit*: the stack top
// and the header's count move together only after success, so on refusal the
// caller's buffer is unchanged in every way it can observe — `out.len` is the
// same, `out[0..len)` is the same bytes, and the garbage sits above the top
// where the next append overwrites it. That is logical atomicity of the
// observable buffer, not "nothing was written". The one effect a refused call
// does have is that the pages it touched are now committed to the data stack;
// that is a resource effect, not a change to any value.
//
// The length equality is what keeps simdutf's forgiving behaviour out of this
// contract. simdutf ignores ASCII whitespace even when it rejects garbage, so a
// text containing whitespace can decode successfully; it then produces fewer
// bytes than `need`, because the whitespace replaced data characters. Under the
// padded policy the text length is a multiple of four and simdutf requires the
// data characters to form whole groups, so the whitespace count is a multiple
// of four as well; a shortfall of `padlen - p'` bytes with `padlen <= 2` cannot
// be a positive multiple of four. The equality test is therefore not a
// heuristic: a success with `outlen == need` cannot have contained whitespace.
// It is checked empirically as well, by the differential test.
extern "C" int64_t b64_accel_decode(gs_rref out, SliceU8 src, int64_t alphabet, int64_t need) {
    if (src.len <= 0 || need <= 0) return 1;
    char *dst = reinterpret_cast<char *>(out.stk->top);
    size_t outlen = static_cast<size_t>(need);
    simdutf::result r = simdutf::base64_to_binary_safe(
        reinterpret_cast<const char *>(src.data), static_cast<size_t>(src.len), dst, outlen,
        PaddedOptions(alphabet), simdutf::last_chunk_handling_options::strict);
    if (r.error != simdutf::error_code::SUCCESS) return 1;
    if (outlen != static_cast<size_t>(need)) return 1;
    out.stk->top += need;
    out.hdr->len += need;
    return 0;
}

// extern fn b64_accel_encode(out: u8[>..]&, src: const u8[:], alphabet: i64,
//                            padding: i64, need: i64) -> i64;
//
// `need` is the exact number of bytes the Goose side computed for this source
// under the policy. Returns 0 when exactly `need` bytes were appended, -1 when
// the call was refused and the caller must fall back to `b64::encode`.
//
// The transaction is the same shape as the decoder's, and it is checked on both
// sides of the write. simdutf's own length for this source and these options
// must equal `need` *before* anything is written; then the number of bytes it
// actually wrote must equal `need` *before* the commit. Only then do the stack
// top and the header's count move, together, by `need`.
//
// Both checks matter. Without the first, a native part whose length disagreed
// with the Goose side's would commit its own count and then the Goose side would
// fall back and append again — a double append, which is exactly the failure the
// return value is supposed to make impossible. Without the second, a short write
// would be committed as a full one. With both, the native part either appends
// exactly `need` bytes or appends nothing observable, and the Goose side's
// `== 0` test is the whole protocol.
extern "C" int64_t b64_accel_encode(gs_rref out, SliceU8 src, int64_t alphabet,
                                    int64_t padding, int64_t need) {
    if (src.len < 0 || need < 0) return -1;
    simdutf::base64_options opts =
        padding == 0 ? PaddedOptions(alphabet) : UnpaddedOptions(alphabet);
    size_t expected = simdutf::base64_length_from_binary(static_cast<size_t>(src.len), opts);
    if (expected != static_cast<size_t>(need)) return -1;
    char *dst = reinterpret_cast<char *>(out.stk->top);
    size_t written = simdutf::binary_to_base64(reinterpret_cast<const char *>(src.data),
                                               static_cast<size_t>(src.len), dst, opts);
    if (written != static_cast<size_t>(need)) return -1;
    out.stk->top += need;
    out.hdr->len += need;
    return 0;
}
