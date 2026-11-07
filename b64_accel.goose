// SPDX-License-Identifier: Apache-2.0
// The optional native backend of goose-base64: the same contract as `b64`,
// decoded and encoded by simdutf instead of by Goose.
//
// This is a package of its own, not a module of `b64`. `import b64` does not
// build, link or load any of it; a program that wants the accelerated path
// imports `b64_accel` explicitly and pays the C++ toolchain and the vendored
// dependency only then. Both packages come from the same source, so the
// `Policy` and `Error` types below are `b64`'s own, not copies.
namespace b64_accel;
import std;
import b64 from ".";

// Native status: 0 means exactly the expected number of bytes was appended,
// 1 means the text was refused and the caller must fall back to `b64::decode`
// for the precise error. The native part never reports an error code of its
// own: the contract, and every diagnostic, stays in Goose.
extern fn b64_accel_decode(out: u8[>..]&, src: const u8[:], alphabet: i64, need: i64) -> i64;
extern fn b64_accel_encode(out: u8[>..]&, src: const u8[:], alphabet: i64, padding: i64, need: i64) -> i64;

fn alphabet_code(a: b64::Alphabet) -> i64 {
    if a == b64::Alphabet.Standard { return 0; }
    return 1;
}

// Append the text of `src` to `out` under `policy`. Appends exactly
// `b64::encoded_len(src.len, policy.padding)` bytes, or nothing on failure.
//
// Encoding has no failure mode past the budget, so the native part is used for
// every policy and the Goose implementation is not consulted on the success
// path. `need` is passed to the native part, which checks its own length against
// it before writing and the number of bytes it wrote against it before
// committing; it returns 0 only when it appended exactly `need` bytes. The
// `== 0` test here is therefore the whole protocol, and a native part that
// disagreed with this side about the length appends nothing and falls back
// instead of appending twice.
fn encode(out: u8[>..]&, src: const u8[:], policy: b64::Policy) -> b64::Error {
    let need = b64::encoded_len(src.len, policy.padding);
    if need < 0 || policy.max_out < 0 || need > policy.max_out { return b64::Error.OutputBudget; }
    if need == 0 { return b64::Error.None; }
    let padding = if policy.padding == b64::Padding.Padded { 0 } else { 1 };
    if b64_accel_encode(out, src, alphabet_code(policy.alphabet), padding, need) == 0 {
        return b64::Error.None;
    }
    return b64::encode(out, src, policy);
}

// Append the bytes `src` encodes to `out` under `policy`, or nothing on
// failure.
//
// Atomicity here is logical, not "no byte was written". The native part decodes
// straight into the builder's free region above `out.len` and commits — moves
// the stack top and the count together — only after simdutf reported success
// and the produced length matched `need`. A rejected text may therefore have
// left bytes above `out.len`, where the next append overwrites them; nothing a
// caller can observe changes, because `out.len` and `out[0..len)` are the same
// before and after. `b64::decode`, by contrast, validates the whole text before
// its first write. Both satisfy the documented contract, which is about the
// caller's buffer, not about the free region.
//
// The native part is used only for the padded policy. simdutf's strict last
// chunk rejects a partial final group, which is exactly what the padded policy
// requires, and it rejects non-zero trailing bits, which is the canonicality
// rule; but the same strict mode also rejects the partial final group that the
// unpadded policy *accepts*, and simdutf has no mode that accepts the group and
// still checks the trailing bits. Unpadded text therefore goes to `b64::decode`
// unchanged. That is a scope limit of this backend, not a contract change.
fn decode(out: u8[>..]&, src: const u8[:], policy: b64::Policy) -> b64::Error {
    if policy.max_out < 0 { return b64::Error.OutputBudget; }
    // Shape and budget first, in the same order as `b64::decode`, so the two
    // agree on which error a text that fails several checks reports.
    let need = b64::decoded_len(src, policy.padding);
    if need < 0 { return b64::Error.InvalidLength; }
    if need > policy.max_out { return b64::Error.OutputBudget; }
    if need == 0 { return b64::Error.None; }
    if policy.padding == b64::Padding.Padded {
        if b64_accel_decode(out, src, alphabet_code(policy.alphabet), need) == 0 {
            return b64::Error.None;
        }
    }
    return b64::decode(out, src, policy);
}
