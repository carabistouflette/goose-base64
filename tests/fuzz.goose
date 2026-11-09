// SPDX-License-Identifier: Apache-2.0
// libFuzzer entry point for the public API. The fuzzer drives `b64::encode`
// and `b64::decode` themselves, not a reimplementation and not the C backend,
// and asserts the contract on every input:
//
//   * encode appends exactly encoded_len bytes, or nothing on a budget refusal;
//   * a successful encode round-trips through decode under the same policy;
//   * a successful decode appends exactly decoded_len bytes, and re-encoding
//     those bytes reproduces the text exactly (canonicality);
//   * a rejected call leaves the buffer empty;
//   * the documented error precedence holds: negative budget, then shape, then
//     budget, then the bytes;
//   * on the compatible path the standard library agrees byte for byte;
//   * the two alphabets differ only in values 62 and 63, so a standard text
//     decodes under the URL alphabet exactly when it holds no '+' or '/'.
//
// Input layout: byte 0 selects alphabet, padding and direction; byte 1 selects
// a budget relative to the exact requirement; the rest is the payload.
import b64 from "..";
import std;
import base64;

// A budget relative to the exact requirement, so the boundaries are hit often.
fn budget_of(selector: u8, need: i64) -> i64 {
    let mode = selector % 7;
    if mode == 0 { return need; }
    if mode == 1 { return need - 1; }
    if mode == 2 { return need + 1; }
    if mode == 3 { return 0; }
    if mode == 4 { return -1; }
    if mode == 5 { return 9223372036854775807; }
    return -9223372036854775807 - 1;
}

fn encode_case(payload: const u8[:], alphabet: b64::Alphabet, padding: b64::Padding, selector: u8) {
    let need = b64::encoded_len(payload.len, padding);
    assert(need >= 0);
    let budget = budget_of(selector, need);
    let policy = b64::Policy { alphabet: alphabet, padding: padding, max_out: budget };
    var out: u8[>..] = [];
    let error = b64::encode(out, payload, policy);
    if budget < 0 || need > budget {
        assert(error == b64::Error.OutputBudget);
        assert(out.len == 0);
        return;
    }
    assert(error == b64::Error.None);
    assert(out.len == need);

    // Round-trip under the same policy.
    var back: u8[>..] = [];
    assert(b64::decode(back, out, b64::Policy {
        alphabet: alphabet, padding: padding, max_out: payload.len,
    }) == b64::Error.None);
    assert(back == payload);

    // The compatible path is the standard library's, byte for byte.
    if alphabet == b64::Alphabet.Standard && padding == b64::Padding.Padded {
        var theirs: u8[>..] = [];
        base64::encode(theirs, payload);
        assert(out == theirs);
    }

    // The alphabets differ only in values 62 and 63.
    if alphabet == b64::Alphabet.Standard {
        var has_extra = false;
        for i in out.len {
            if out[i] == '+' || out[i] == '/' { has_extra = true; }
        }
        var cross: u8[>..] = [];
        let cross_error = b64::decode(cross, out, b64::Policy {
            alphabet: b64::Alphabet.Url, padding: padding, max_out: payload.len,
        });
        if has_extra {
            assert(cross_error == b64::Error.InvalidCharacter);
        } else {
            assert(cross_error == b64::Error.None);
            assert(cross == payload);
        }
    }
}

fn decode_case(payload: const u8[:], alphabet: b64::Alphabet, padding: b64::Padding, selector: u8) {
    let need = b64::decoded_len(payload, padding);
    let budget = budget_of(selector, need);
    let policy = b64::Policy { alphabet: alphabet, padding: padding, max_out: budget };
    var out: u8[>..] = [];
    let error = b64::decode(out, payload, policy);
    // Documented precedence: negative budget, then shape, then budget.
    if budget < 0 {
        assert(error == b64::Error.OutputBudget);
        assert(out.len == 0);
        return;
    }
    if need < 0 {
        assert(error == b64::Error.InvalidLength);
        assert(out.len == 0);
        return;
    }
    if need > budget {
        assert(error == b64::Error.OutputBudget);
        assert(out.len == 0);
        return;
    }
    if error != b64::Error.None {
        assert(out.len == 0);
        return;
    }
    assert(out.len == need);

    // Canonicality: the text must be the unique encoding of these bytes.
    var again: u8[>..] = [];
    assert(b64::encode(again, out, b64::Policy {
        alphabet: alphabet, padding: padding,
        max_out:  b64::encoded_len(out.len, padding),
    }) == b64::Error.None);
    assert(again == payload);

    // The standard library accepts everything this module accepts, and agrees.
    if alphabet == b64::Alphabet.Standard && padding == b64::Padding.Padded {
        var theirs: u8[>..] = [];
        assert(base64::decode(theirs, payload));
        assert(theirs == out);
    }
}

// The length helpers, driven with lengths the payload path cannot reach: a
// slice length is always valid, so `encoded_len`'s -1 branch and the exact
// MAX_INPUT boundary need their own input.
fn length_case(data: const u8[:], padding: b64::Padding) {
    // Seven bytes cannot overflow i64, and the sign is chosen separately.
    var n: i64 = 0;
    for i in 0..7 {
        let b = if i < data.len { data[i] as! i64 } else { 0 };
        n = n * 256 + b;
    }
    if data.len > 0 && (data[0] & 1) != 0 { n = -n; }
    // The boundary values, exactly.
    if data.len > 1 {
        let mode = data[1] % 4;
        if mode == 0 { n = 2305843009213693951; }
        else if mode == 1 { n = 2305843009213693952; }
        else if mode == 2 { n = 9223372036854775807; }
        else { n = -9223372036854775807 - 1; }
    }
    let encoded = b64::encoded_len(n, padding);
    if n < 0 || n > 2305843009213693951 {
        assert(encoded == -1);
        return;
    }
    assert(encoded >= 0);
    // The helper must agree with the codec for a real buffer of that size.
    if n <= 4096 {
        var src: u8[>..] = [];
        src.resize(n, 0x41);
        var out: u8[>..] = [];
        assert(b64::encode(out, src, b64::Policy {
            padding: padding, max_out: encoded,
        }) == b64::Error.None);
        assert(out.len == encoded);
        assert(b64::decoded_len(out, padding) == n);
    }
}

export fn fuzz_base64(data: const u8[:]) -> i64 {
    if data.len == 0 { return 0; }
    let flags = data[0];
    let alphabet = if (flags & 1) != 0 { b64::Alphabet.Url } else { b64::Alphabet.Standard };
    let padding = if (flags & 2) != 0 { b64::Padding.Unpadded } else { b64::Padding.Padded };
    let selector = if data.len > 1 { data[1] } else { 0 };
    let payload = if data.len > 2 { data[2..] } else { data[..0] };
    if (flags & 8) != 0 { length_case(payload, padding); }
    else if (flags & 4) != 0 { decode_case(payload, alphabet, padding, selector); }
    else { encode_case(payload, alphabet, padding, selector); }
    return 1;
}

// The driver calls this with a failing value to prove that a Goose assertion
// becomes a libFuzzer crash that retains the exact triggering input.
export fn fuzz_assertion_probe(value: i64) { assert(value != 0); }

fn main() {}
