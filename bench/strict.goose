// SPDX-License-Identifier: Apache-2.0
// The equal-contract competitor for the benchmark.
//
// The pinned standard library's `base64` is the maintained, fast codec, but it
// cannot express this library's contract: no URL alphabet, no unpadded output,
// no canonicality check and no budget. Comparing against it alone would compare
// a strict decoder to a permissive one, which is not a fair race.
//
// This module is what a caller has to write today to get that contract from the
// standard library: the same length rules, the same error precedence, the same
// canonicality check, and the standard library's bit work underneath. It shares
// only the `b64::Error` enum with the library under test; every decision here is
// its own, so the comparison is same-contract, same-codec, different structure.
//
// It is benchmark code, not a second implementation to ship: it is not tested
// for the contract beyond the benchmark's own byte-for-byte checks.
namespace strict;
import std;
import base64;
import b64 from "..";

const INVALID:   u8  = 255;
const MAX_INPUT: i64 = 2305843009213693951;

fn encoded_len(src_len: i64, padding: b64::Padding) -> i64 {
    if src_len < 0 || src_len > MAX_INPUT { return -1; }
    let groups = src_len / 3;
    let rest = src_len % 3;
    if padding == b64::Padding.Padded { return groups * 4 + (if rest == 0 { 0 } else { 4 }); }
    return groups * 4 + (if rest == 0 { 0 } else { rest + 1 });
}

fn padding_of(src: const u8[:]) -> i64 {
    let n = src.len;
    if n == 0 || src[n - 1] != '=' { return 0; }
    if n >= 2 && src[n - 2] == '=' { return 2; }
    return 1;
}

fn decoded_len(src: const u8[:], padding: b64::Padding) -> i64 {
    let n = src.len;
    if padding == b64::Padding.Padded {
        if n % 4 != 0 { return -1; }
        let padlen = padding_of(src);
        if padlen > 0 && n < 4 { return -1; }
        return n / 4 * 3 - padlen;
    }
    let rest = n % 4;
    if rest == 1 { return -1; }
    return n / 4 * 3 + (if rest == 0 { 0 } else { rest - 1 });
}

const STANDARD_VALUES: u8[256] = [
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 62, 255, 255, 255, 63,
    52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 255, 255, 255, 255, 255, 255,
    255, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
    15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 255, 255, 255, 255, 255,
    255, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
    41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
];

const URL_VALUES: u8[256] = [
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 62, 255, 255,
    52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 255, 255, 255, 255, 255, 255,
    255, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
    15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 255, 255, 255, 255, 63,
    255, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
    41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
];

// The 6-bit value of `c` in `alphabet`, or INVALID. A table lookup, because a
// caller writing this layer today would reach for one: it is the same shape the
// library under test uses, so the comparison isolates the structure of the two
// decoders instead of the cost of a range-test chain.
fn value_of(c: u8, alphabet: b64::Alphabet) -> u8 {
    if alphabet == b64::Alphabet.Standard { return STANDARD_VALUES[c]; }
    return URL_VALUES[c];
}

// Append the text of `src`, or nothing on a budget refusal.
fn encode(out: u8[>..]&, src: const u8[:], policy: b64::Policy) -> b64::Error {
    let need = encoded_len(src.len, policy.padding);
    if need < 0 || policy.max_out < 0 || need > policy.max_out { return b64::Error.OutputBudget; }
    let start = out.len;
    // The standard library always pads and always uses the standard alphabet,
    // so the policy is applied afterwards: rewrite the two extra characters,
    // then drop the padding.
    base64::encode(out, src);
    if policy.alphabet == b64::Alphabet.Url {
        for i in start..out.len {
            let c = out[i];
            if c == '+' { out[i] = '-'; }
            else if c == '/' { out[i] = '_'; }
        }
    }
    if policy.padding == b64::Padding.Unpadded {
        while out.len > start && out[out.len - 1] == '=' { out.resize(out.len - 1, 0); }
    }
    return b64::Error.None;
}

// Append the bytes `src` encodes, or nothing on any refusal.
fn decode(out: u8[>..]&, src: const u8[:], policy: b64::Policy) -> b64::Error {
    if policy.max_out < 0 { return b64::Error.OutputBudget; }
    let n = src.len;
    let padlen = if policy.padding == b64::Padding.Padded { padding_of(src) } else { 0 };
    let body = n - padlen;
    let need = decoded_len(src, policy.padding);
    if need < 0 { return b64::Error.InvalidLength; }
    if need > policy.max_out { return b64::Error.OutputBudget; }
    for i in body {
        let c = src[i];
        if c == '=' { return b64::Error.InvalidPadding; }
        if value_of(c, policy.alphabet) == INVALID { return b64::Error.InvalidCharacter; }
    }
    let rest = body % 4;
    if rest == 2 {
        if (value_of(src[body - 1], policy.alphabet) & 15) != 0 { return b64::Error.NonCanonical; }
    } else if rest == 3 {
        if (value_of(src[body - 1], policy.alphabet) & 3) != 0 { return b64::Error.NonCanonical; }
    }
    // The compatible path needs no normalisation: the standard library's
    // decoder takes the text as it is.
    if policy.alphabet == b64::Alphabet.Standard && policy.padding == b64::Padding.Padded {
        if !base64::decode(out, src) { return b64::Error.InvalidCharacter; }
        return b64::Error.None;
    }
    // Otherwise the text has to be normalised into a temporary: translate the
    // two extra characters and restore the padding the policy omitted. That
    // copy is the cost of using the standard library for this contract.
    var normalised: u8[>..] = [];
    normalised.resize(n + 2, 0);
    for i in n {
        let c = src[i];
        if policy.alphabet == b64::Alphabet.Url {
            normalised[i] = if c == '-' { '+' } else if c == '_' { '/' } else { c };
        } else {
            normalised[i] = c;
        }
    }
    var padded = n;
    while padded % 4 != 0 {
        normalised[padded] = '=';
        padded++;
    }
    normalised.resize(padded, 0);
    if !base64::decode(out, normalised) { return b64::Error.InvalidCharacter; }
    return b64::Error.None;
}
