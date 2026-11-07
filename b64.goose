// SPDX-License-Identifier: Apache-2.0
// Strict, bounded RFC 4648 Base64 and Base64url with an explicit padding
// policy, canonical trailing-bit rejection and caller-supplied output budgets.
//
// The namespace is `b64`, not `base64`: the pinned standard library already
// owns `base64` (stdlib/base64.goose), and this module imports it.
namespace b64;
import std;
import base64;

// RFC 4648 §4 (standard) or §5 (URL and filename safe) alphabet.
enum Alphabet { Standard, Url }
// RFC 4648 §3.2 padding: '=' to a multiple of four, or omitted entirely.
enum Padding { Padded, Unpadded }

// Every function returns Error; only Error.None means success. A failure never
// changes the caller's output buffer.
enum Error {
    None,
    // The text length cannot be a whole number of groups under the policy.
    InvalidLength,
    // A byte outside the selected alphabet, including the other alphabet's
    // two extra characters and every whitespace byte.
    InvalidCharacter,
    // '=' where the policy forbids it, or in a position other than the end.
    InvalidPadding,
    // The unused low bits of the final data character are not zero
    // (RFC 4648 §3.5), so a different text would decode to the same bytes.
    NonCanonical,
    // The call would append more than `max_out` bytes.
    OutputBudget,
}

// What `value_of` returns for a byte outside the selected alphabet.
const INVALID: u8 = 255;
// Largest input length whose encoded length is representable in i64.
const MAX_INPUT: i64 = 2305843009213693951;

// Encoding and decoding policy. `max_out` is required: it is the maximum
// number of bytes one call may append to the caller's buffer.
struct Policy {
    alphabet: Alphabet = Alphabet.Standard,
    padding:  Padding  = Padding.Padded,
    max_out:  i64,
}

// Bytes `encode` appends for `src_len` input bytes, or -1 when `src_len` is
// negative or exceeds MAX_INPUT.
fn encoded_len(src_len: i64, padding: Padding) -> i64 {
    if src_len < 0 || src_len > MAX_INPUT { return -1; }
    let groups = src_len / 3;
    let rest = src_len % 3;
    if padding == Padding.Padded { return groups * 4 + (if rest == 0 { 0 } else { 4 }); }
    return groups * 4 + (if rest == 0 { 0 } else { rest + 1 });
}

// Trailing '=' count, capped at two. Only meaningful for Padding.Padded.
fn padding_of(src: const u8[:]) -> i64 {
    let n = src.len;
    if n == 0 || src[n - 1] != '=' { return 0; }
    if n >= 2 && src[n - 2] == '=' { return 2; }
    return 1;
}

// Bytes `decode` appends for this text, or -1 when its length and padding
// cannot be valid under the policy. This reads only the trailing '='; it does
// not validate the characters.
fn decoded_len(src: const u8[:], padding: Padding) -> i64 {
    let n = src.len;
    if padding == Padding.Padded {
        if n % 4 != 0 { return -1; }
        let padlen = padding_of(src);
        if padlen > 0 && n < 4 { return -1; }
        return n / 4 * 3 - padlen;
    }
    let rest = n % 4;
    // One leftover character carries six bits, which is not a whole byte.
    if rest == 1 { return -1; }
    return n / 4 * 3 + (if rest == 0 { 0 } else { rest - 1 });
}

// The 6-bit value of `c` in `alphabet`, or INVALID. The other alphabet's two
// extra characters are INVALID, as is every byte outside both alphabets.
fn value_of(c: u8, alphabet: Alphabet) -> u8 {
    if c - 'A' < 26 { return c - 'A'; }
    if c - 'a' < 26 { return c - 'a' + 26; }
    if c - '0' < 10 { return c - '0' + 52; }
    if alphabet == Alphabet.Standard {
        if c == '+' { return 62; }
        if c == '/' { return 63; }
    } else {
        if c == '-' { return 62; }
        if c == '_' { return 63; }
    }
    return INVALID;
}

// The character of a 6-bit value in `alphabet` (RFC 4648, table 1). The two
// alphabets share A-Z, a-z and 0-9 and differ only in values 62 and 63.
fn symbol(v: u8, alphabet: Alphabet) -> u8 {
    if v < 26 { return 'A' + v; }
    if v < 52 { return 'a' + (v - 26); }
    if v < 62 { return '0' + (v - 52); }
    if alphabet == Alphabet.Standard { return if v == 62 { '+' } else { '/' }; }
    return if v == 62 { '-' } else { '_' };
}

// Append the text of `src` to `out` under `policy`. Appends exactly
// encoded_len(src.len, policy.padding) bytes, or nothing on failure.
fn encode(out: u8[>..]&, src: const u8[:], policy: Policy) -> Error {
    let need = encoded_len(src.len, policy.padding);
    if need < 0 || policy.max_out < 0 || need > policy.max_out { return Error.OutputBudget; }
    let full = src.len / 3 * 3;
    let start = out.len;
    // Whole groups are the standard library's compatible path: four characters
    // per three bytes, no padding, and the same A-Z a-z 0-9 for both alphabets.
    base64::encode(out, src[..full]);
    if policy.alphabet == Alphabet.Url {
        for i in start..start + full / 3 * 4 {
            let c = out[i];
            if c == '+' { out[i] = '-'; }
            else if c == '/' { out[i] = '_'; }
        }
    }
    // The final 1-2 byte group is written here: the standard library always
    // pads and always uses the standard alphabet. Writing it directly keeps
    // the appended count exact, so no temporary padding is ever allocated.
    let rest = src.len - full;
    if rest > 0 {
        let b1: u8 = if rest == 2 { src[full + 1] } else { 0 };
        out.push(symbol(src[full] >> 2, policy.alphabet));
        out.push(symbol(((src[full] & 3) << 4) | (b1 >> 4), policy.alphabet));
        if rest == 2 { out.push(symbol((b1 & 15) << 2, policy.alphabet)); }
        if policy.padding == Padding.Padded {
            out.push('=');
            if rest == 1 { out.push('='); }
        }
    }
    return Error.None;
}

// Append the bytes `src` encodes to `out` under `policy`, or nothing on
// failure. The whole input is validated before the first write, so a rejected
// call never mutates the caller's buffer.
//
// Error precedence is fixed and testable: a negative budget, then the length
// and padding shape, then the budget, then the first offending byte in text
// order, then the trailing bits.
fn decode(out: u8[>..]&, src: const u8[:], policy: Policy) -> Error {
    if policy.max_out < 0 { return Error.OutputBudget; }
    let n = src.len;
    let padlen = if policy.padding == Padding.Padded { padding_of(src) } else { 0 };
    let body = n - padlen;
    // Shape first: it is O(1) and decides whether the tail below is reachable.
    let need = decoded_len(src, policy.padding);
    if need < 0 { return Error.InvalidLength; }
    if need > policy.max_out { return Error.OutputBudget; }
    // `body` excludes the trailing '=' run, so a '=' inside it is misplaced.
    for i in body {
        let c = src[i];
        if c == '=' { return Error.InvalidPadding; }
        if value_of(c, policy.alphabet) == INVALID { return Error.InvalidCharacter; }
    }
    // RFC 4648 §3.5: the unused low bits of the final data character must be
    // zero, otherwise a second text decodes to the same bytes.
    let rest = body % 4;
    if rest == 2 {
        if (value_of(src[body - 1], policy.alphabet) & 15) != 0 { return Error.NonCanonical; }
    } else if rest == 3 {
        if (value_of(src[body - 1], policy.alphabet) & 3) != 0 { return Error.NonCanonical; }
    }
    // Write pass: every byte is now known valid.
    var i = 0;
    while i + 4 <= body {
        let a = value_of(src[i], policy.alphabet);
        let b = value_of(src[i + 1], policy.alphabet);
        let c = value_of(src[i + 2], policy.alphabet);
        let d = value_of(src[i + 3], policy.alphabet);
        out.push((a << 2) | (b >> 4));
        out.push((b << 4) | (c >> 2));
        out.push((c << 6) | d);
        i += 4;
    }
    if rest == 2 {
        let a = value_of(src[i], policy.alphabet);
        let b = value_of(src[i + 1], policy.alphabet);
        out.push((a << 2) | (b >> 4));
    } else if rest == 3 {
        let a = value_of(src[i], policy.alphabet);
        let b = value_of(src[i + 1], policy.alphabet);
        let c = value_of(src[i + 2], policy.alphabet);
        out.push((a << 2) | (b >> 4));
        out.push((b << 4) | (c >> 2));
    }
    return Error.None;
}
