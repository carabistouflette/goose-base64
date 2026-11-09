// SPDX-License-Identifier: Apache-2.0
// Differential test: the optional native backend must be indistinguishable from
// the Goose implementation, not merely fast on valid input.
//
// Every case runs both implementations on the same input and the same policy
// and requires the same `Error`, the same appended bytes, and the same
// untouched prefix when the call fails. The corpus is enumerated rather than
// sampled where that is affordable, because the interesting failures are
// boundary cases: a whitespace byte that simdutf forgives, a '=' in the middle,
// a non-zero trailing bit, a budget one byte short.
import b64 from "..";
import b64_accel from "..";
import std;

fn policy(alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) -> b64::Policy {
    return b64::Policy { alphabet: alphabet, padding: padding, max_out: max_out };
}

const ALPHABETS = [b64::Alphabet.Standard, b64::Alphabet.Url];
const PADDINGS = [b64::Padding.Padded, b64::Padding.Unpadded];

// Both implementations, same input, same policy: same error, same bytes, and
// the same prefix left alone on failure.
fn same_decode(text: u8[:], alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) {
    var want: u8[>..] = [];
    want.push(0xaa);
    var got: u8[>..] = [];
    got.push(0xaa);
    let want_error = b64::decode(want, text, policy(alphabet, padding, max_out));
    let got_error = b64_accel::decode(got, text, policy(alphabet, padding, max_out));
    assert(want_error == got_error);
    assert(want.len == got.len);
    for i in want.len {
        assert(want[i] == got[i]);
    }
}

fn same_encode(src: u8[:], alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) {
    var want: u8[>..] = [];
    want.push(0xaa);
    var got: u8[>..] = [];
    got.push(0xaa);
    let want_error = b64::encode(want, src, policy(alphabet, padding, max_out));
    let got_error = b64_accel::encode(got, src, policy(alphabet, padding, max_out));
    assert(want_error == got_error);
    assert(want.len == got.len);
    for i in want.len {
        assert(want[i] == got[i]);
    }
}

// Every policy, at the exact budget and one byte short of it, so the budget
// check and the write are both exercised on the same input.
fn same_decode_all(text: u8[:]) {
    for alphabet in ALPHABETS {
        for padding in PADDINGS {
            let need = b64::decoded_len(text, padding);
            same_decode(text, alphabet, padding, 65536);
            same_decode(text, alphabet, padding, 0);
            if need > 0 {
                same_decode(text, alphabet, padding, need - 1);
                same_decode(text, alphabet, padding, need);
            }
        }
    }
}

fn same_encode_all(src: u8[:]) {
    for alphabet in ALPHABETS {
        for padding in PADDINGS {
            let need = b64::encoded_len(src.len, padding);
            same_encode(src, alphabet, padding, 65536);
            same_encode(src, alphabet, padding, 0);
            if need > 0 {
                same_encode(src, alphabet, padding, need - 1);
                same_encode(src, alphabet, padding, need);
            }
        }
    }
}

// A text of `n` bytes drawn from `symbols` by counting in base `symbols.len`.
fn text_of(index: i64, n: i64, symbols: u8[:]) -> u8[>..] {
    var text: u8[>..] = [];
    var rest = index;
    for _ in n {
        text.push(symbols[rest % symbols.len]);
        rest = rest / symbols.len;
    }
    return text;
}

fn pow(base: i64, exponent: i64) -> i64 {
    var r: i64 = 1;
    for _ in exponent { r = r * base; }
    return r;
}

// Every text of length `n` over `symbols`. The symbol set mixes both alphabets,
// '=', the three ASCII whitespace bytes simdutf forgives, and a byte outside
// every alphabet, so the enumeration reaches the cases where the two
// implementations could disagree.
fn every_text_of_length(n: i64, symbols: u8[:]) {
    let total = pow(symbols.len, n);
    for index in total {
        same_decode_all(text_of(index, n, symbols));
    }
}

// The whole byte domain in each position of a four-character group: a table
// entry or a native alphabet that is wrong for one byte shows up here.
fn every_byte_in_each_position() {
    for position in 4 {
        for value in 256 {
            var text: u8[>..] = [];
            for i in 4 {
                text.push(if i == position { value as! u8 } else { 'A' });
            }
            same_decode_all(text);
        }
    }
}

// Whitespace injected into a valid text at every position, including inside the
// padding run. simdutf ignores these bytes; this contract rejects them, so the
// length-equality test in the native part is what keeps the two equal.
fn whitespace_never_passes() {
    let valid = ["", "Zg==", "Zm8=", "Zm9v", "Zm9vYg==", "Zm9vYmE=", "Zm9vYmFy", "AAAA", "////", "----", "____"];
    let spaces: u8[5] = [0x20, 0x09, 0x0a, 0x0d, 0x0c];
    for text in valid {
        for space in spaces {
            for position in text.len + 1 {
                var injected: u8[>..] = [];
                for i in text.len + 1 {
                    if i == position { injected.push(space); }
                    if i < text.len { injected.push(text[i]); }
                }
                same_decode_all(injected);
            }
        }
    }
}

// A valid text with one character replaced by every byte value, at the start,
// the middle and the end: the error taxonomy has to agree position by position.
fn single_byte_mutations() {
    let valid = ["Zg==", "Zm8=", "Zm9vYmFy", "AAECAwQFBgc="];
    for text in valid {
        for position in text.len {
            for value in 256 {
                var mutated: u8[>..] = [];
                for i in text.len {
                    mutated.push(if i == position { value as! u8 } else { text[i] });
                }
                same_decode_all(mutated);
            }
        }
    }
}

// Trailing-bit canonicality: the last data character of a 2- or 3-character
// tail must have zero unused bits, and the two implementations must agree on
// every one of the 64 values that character can take.
fn trailing_bits_agree() {
    let symbols = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for last in 64 {
        var two: u8[>..] = [];
        two.push('A');
        two.push(symbols[last]);
        same_decode_all(two);
        var three: u8[>..] = [];
        three.push('A');
        three.push('A');
        three.push(symbols[last]);
        same_decode_all(three);
        var padded: u8[>..] = [];
        padded.push('A');
        padded.push(symbols[last]);
        padded.push('=');
        padded.push('=');
        same_decode_all(padded);
    }
}

// Encoding: every source of length 0, 1 and 2 over the whole byte domain, then
// longer sources that cross the group boundaries and the tail cases.
fn encode_agrees() {
    same_encode_all("");
    for a in 256 {
        var one: u8[>..] = [];
        one.push(a as! u8);
        same_encode_all(one);
        for b in 256 {
            var two: u8[>..] = [];
            two.push(a as! u8);
            two.push(b as! u8);
            same_encode_all(two);
        }
    }
    for n in 0..40 {
        var src: u8[>..] = [];
        for i in n { src.push((i * 37 + 11) as! u8); }
        same_encode_all(src);
    }
}

// The encode protocol, checked as a protocol rather than as a single call. The
// native part is handed `need` and must append exactly that many bytes or
// nothing; a native part that appended its own count and then let the Goose side
// fall back would append twice, and the length would drift on the second call.
// Three calls on one buffer, every policy, every tail shape, is what catches
// that: the growth is asserted to be exactly `need` each time, and the bytes are
// asserted to equal the Goose implementation's.
fn encode_appends_exactly_once() {
    for alphabet in ALPHABETS {
        for padding in PADDINGS {
            for n in 0..40 {
                var src: u8[>..] = [];
                for i in n { src.push((i * 53 + 3) as! u8); }
                let need = b64::encoded_len(n, padding);
                var want: u8[>..] = [];
                assert(b64::encode(want, src, policy(alphabet, padding, 65536)) == b64::Error.None);
                var got: u8[>..] = [];
                got.push(0xaa);
                for round in 3 {
                    let before = got.len;
                    assert(b64_accel::encode(got, src, policy(alphabet, padding, 65536)) == b64::Error.None);
                    assert(got.len == before + need);
                    assert(got[0] == 0xaa);
                    for i in need {
                        assert(got[before + i] == want[i]);
                    }
                }
                // A budget one byte short is refused and appends nothing, on a
                // buffer that already holds three encodings.
                let held = got.len;
                assert(b64_accel::encode(got, src, policy(alphabet, padding, need - 1)) == b64::Error.OutputBudget);
                assert(got.len == held);
            }
        }
    }
}

// Round trip through the accelerated path only: encode with the native part,
// decode with the native part, and require the original bytes back. This is the
// property a caller actually relies on, and it is checked for every length that
// has a distinct tail shape.
fn round_trips() {
    for alphabet in ALPHABETS {
        for padding in PADDINGS {
            for n in 0..200 {
                var src: u8[>..] = [];
                for i in n { src.push((i * 91 + 7) as! u8); }
                var text: u8[>..] = [];
                assert(b64_accel::encode(text, src, policy(alphabet, padding, 65536)) == b64::Error.None);
                assert(text.len == b64::encoded_len(n, padding));
                var back: u8[>..] = [];
                assert(b64_accel::decode(back, text, policy(alphabet, padding, 65536)) == b64::Error.None);
                assert(back.len == n);
                for i in n { assert(back[i] == src[i]); }
            }
        }
    }
}

fn main() {
    // Lengths 0 to 4 over a set that mixes both alphabets, '=', whitespace and
    // a byte outside every alphabet.
    let mixed: u8[13] = [0x41, 0x42, 0x2f, 0x2b, 0x2d, 0x5f, 0x3d, 0x20, 0x0a, 0x09, 0x21, 0x30, 0x7a];
    for n in 0..5 {
        every_text_of_length(n, mixed);
    }
    // Longer texts over a smaller set, where the whitespace and padding
    // interaction needs more than four characters to show.
    let narrow: u8[5] = [0x41, 0x42, 0x20, 0x3d, 0x2f];
    for n in 5..8 {
        every_text_of_length(n, narrow);
    }
    every_byte_in_each_position();
    whitespace_never_passes();
    single_byte_mutations();
    trailing_bits_agree();
    encode_agrees();
    encode_appends_exactly_once();
    round_trips();
    print("accelerated differential passed\n");
}
