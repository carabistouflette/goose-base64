// SPDX-License-Identifier: Apache-2.0
// Public API tests: RFC 4648 vectors, all four policy combinations, the error
// taxonomy and its precedence, budget boundaries and failure atomicity.
import b64 from "..";
import std;

const STANDARD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

fn policy(alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) -> b64::Policy {
    return b64::Policy { alphabet: alphabet, padding: padding, max_out: max_out };
}

// Encode `src` into a fresh buffer and return the text.
fn text_of(src: u8[:], alphabet: b64::Alphabet, padding: b64::Padding) -> u8[>..] {
    var out: u8[>..] = [];
    let error = b64::encode(out, src, policy(alphabet, padding, 4096));
    assert(error == b64::Error.None);
    assert(out.len == b64::encoded_len(src.len, padding));
    return out;
}

// Assert that decoding `text` under `alphabet`/`padding` yields `want`.
fn decodes(text: u8[:], alphabet: b64::Alphabet, padding: b64::Padding, want: u8[:]) {
    var out: u8[>..] = [];
    let error = b64::decode(out, text, policy(alphabet, padding, 4096));
    assert(error == b64::Error.None);
    assert(out == want);
    assert(out.len == b64::decoded_len(text, padding));
}

// Assert that decoding `text` fails with `want`, leaving a prefixed buffer alone.
fn rejects(text: u8[:], alphabet: b64::Alphabet, padding: b64::Padding, want: b64::Error) {
    var out = str("prefix");
    let error = b64::decode(out, text, policy(alphabet, padding, 4096));
    assert(error == want);
    assert(out == "prefix");
}

fn rejects_encode(src: u8[:], alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) {
    var out = str("prefix");
    let error = b64::encode(out, src, policy(alphabet, padding, max_out));
    assert(error == b64::Error.OutputBudget);
    assert(out == "prefix");
}

fn main() {
    // RFC 4648 §10 test vectors, both alphabets, both padding policies.
    let sources = ["", "f", "fo", "foo", "foob", "fooba", "foobar"];
    let unpadded_vectors = ["", "Zg", "Zm8", "Zm9v", "Zm9vYg", "Zm9vYmE", "Zm9vYmFy"];
    for index in sources.len {
        let source = sources[index];
        let unpadded = unpadded_vectors[index];
        let padded = str(unpadded);
        while padded.len % 4 != 0 { padded.push('='); }
        assert(text_of(source, b64::Alphabet.Standard, b64::Padding.Padded) == padded);
        assert(text_of(source, b64::Alphabet.Standard, b64::Padding.Unpadded) == unpadded);
        assert(text_of(source, b64::Alphabet.Url, b64::Padding.Padded) == padded);
        assert(text_of(source, b64::Alphabet.Url, b64::Padding.Unpadded) == unpadded);
        decodes(padded, b64::Alphabet.Standard, b64::Padding.Padded, source);
        decodes(unpadded, b64::Alphabet.Standard, b64::Padding.Unpadded, source);
        decodes(padded, b64::Alphabet.Url, b64::Padding.Padded, source);
        decodes(unpadded, b64::Alphabet.Url, b64::Padding.Unpadded, source);
    }

    // The four combinations must not leak the alphabet into the padding policy
    // or the padding policy into the alphabet: 0xfb 0xff is "+/8" in the
    // standard alphabet and "-_8" in the URL alphabet, padded or not.
    let high: u8[2] = [0xfb, 0xff];
    assert(text_of(high[..], b64::Alphabet.Standard, b64::Padding.Padded) == "+/8=");
    assert(text_of(high[..], b64::Alphabet.Standard, b64::Padding.Unpadded) == "+/8");
    assert(text_of(high[..], b64::Alphabet.Url, b64::Padding.Padded) == "-_8=");
    assert(text_of(high[..], b64::Alphabet.Url, b64::Padding.Unpadded) == "-_8");
    let slashes: u8[3] = [0xff, 0xff, 0xff];
    assert(text_of(slashes[..], b64::Alphabet.Standard, b64::Padding.Unpadded) == "////");
    assert(text_of(slashes[..], b64::Alphabet.Url, b64::Padding.Unpadded) == "____");
    decodes("+/8=", b64::Alphabet.Standard, b64::Padding.Padded, high[..]);
    decodes("-_8", b64::Alphabet.Url, b64::Padding.Unpadded, high[..]);

    // Empty input is valid everywhere and appends nothing.
    for alphabet in [b64::Alphabet.Standard, b64::Alphabet.Url] {
        for padding in [b64::Padding.Padded, b64::Padding.Unpadded] {
            var out = str("keep");
            assert(b64::encode(out, "", policy(alphabet, padding, 0)) == b64::Error.None);
            assert(out == "keep");
            assert(b64::decode(out, "", policy(alphabet, padding, 0)) == b64::Error.None);
            assert(out == "keep");
        }
    }

    // Round-trip every length across the group boundaries, with a prefix kept.
    for size in 0..65 {
        var source: u8[>..] = [];
        for i in size { source.push((i * 37 + 11) as! u8); }
        for alphabet in [b64::Alphabet.Standard, b64::Alphabet.Url] {
            for padding in [b64::Padding.Padded, b64::Padding.Unpadded] {
                var encoded = str("keep");
                assert(b64::encode(encoded, source, policy(alphabet, padding, 4096)) == b64::Error.None);
                assert(encoded[..4] == "keep");
                assert(encoded.len == 4 + b64::encoded_len(size, padding));
                var decoded = str("keep");
                assert(b64::decode(decoded, encoded[4..], policy(alphabet, padding, 4096)) == b64::Error.None);
                assert(decoded[4..] == source);
            }
        }
    }

    // InvalidLength: the text cannot be a whole number of groups.
    rejects("Z", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("Zg=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("Zg==Zg=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("==", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("A==", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("A", b64::Alphabet.Standard, b64::Padding.Unpadded, b64::Error.InvalidLength);
    rejects("AAAAA", b64::Alphabet.Standard, b64::Padding.Unpadded, b64::Error.InvalidLength);
    rejects("AAAAA", b64::Alphabet.Url, b64::Padding.Unpadded, b64::Error.InvalidLength);

    // InvalidPadding: '=' where the policy forbids it, or not at the end.
    rejects("Zg==", b64::Alphabet.Standard, b64::Padding.Unpadded, b64::Error.InvalidPadding);
    rejects("Zg", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("Z=g=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidPadding);
    rejects("=Zg=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidPadding);
    rejects("====", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidPadding);
    rejects("A===", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidPadding);
    rejects("Zg===", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidLength);
    rejects("Zg=", b64::Alphabet.Url, b64::Padding.Unpadded, b64::Error.InvalidPadding);

    // InvalidCharacter: the other alphabet's two extra characters, whitespace,
    // control bytes and every byte outside both alphabets. Each text below is
    // four characters, so the length is valid and the byte decides.
    rejects("+AAA", b64::Alphabet.Url, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("/AAA", b64::Alphabet.Url, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("-AAA", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("_AAA", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Z ==", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg =", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg\n=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg\r\n", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg\t=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg\x00=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg\xff=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg.A", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg+A", b64::Alphabet.Url, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg/A", b64::Alphabet.Url, b64::Padding.Padded, b64::Error.InvalidCharacter);
    rejects("Zg+A", b64::Alphabet.Url, b64::Padding.Unpadded, b64::Error.InvalidCharacter);
    // The two extra characters are accepted by their own alphabet only.
    decodes("Zg-A", b64::Alphabet.Url, b64::Padding.Padded, "f\x0f\x80");
    decodes("Zg_A", b64::Alphabet.Url, b64::Padding.Padded, "f\x0f\xc0");
    decodes("Zg+A", b64::Alphabet.Standard, b64::Padding.Padded, "f\x0f\x80");
    decodes("Zg/A", b64::Alphabet.Standard, b64::Padding.Padded, "f\x0f\xc0");

    // NonCanonical: the standard library accepts these, this module does not.
    rejects("Zh==", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.NonCanonical);
    rejects("Zh", b64::Alphabet.Standard, b64::Padding.Unpadded, b64::Error.NonCanonical);
    rejects("Zm9=", b64::Alphabet.Standard, b64::Padding.Padded, b64::Error.NonCanonical);
    rejects("Zm9", b64::Alphabet.Standard, b64::Padding.Unpadded, b64::Error.NonCanonical);
    rejects("Zh==", b64::Alphabet.Url, b64::Padding.Padded, b64::Error.NonCanonical);
    decodes("Zg==", b64::Alphabet.Standard, b64::Padding.Padded, "f");
    decodes("Zm8=", b64::Alphabet.Standard, b64::Padding.Padded, "fo");

    // Exhaustive trailing-bit check: of the 64 possible final characters, only
    // those whose unused low bits are zero may be accepted.
    for alphabet in [b64::Alphabet.Standard, b64::Alphabet.Url] {
        let symbols = if alphabet == b64::Alphabet.Standard { STANDARD } else { URL };
        var accepted = 0;
        for v in 64 {
            var text = str("Z");
            text.push(symbols[v]);
            var out: u8[>..] = [];
            let error = b64::decode(out, text, policy(alphabet, b64::Padding.Unpadded, 8));
            if error == b64::Error.None { accepted++; assert(out.len == 1); }
            else { assert(error == b64::Error.NonCanonical); }
        }
        assert(accepted == 4);
        accepted = 0;
        for v in 64 {
            var text = str("Zm");
            text.push(symbols[v]);
            var out: u8[>..] = [];
            let error = b64::decode(out, text, policy(alphabet, b64::Padding.Unpadded, 8));
            if error == b64::Error.None { accepted++; assert(out.len == 2); }
            else { assert(error == b64::Error.NonCanonical); }
        }
        assert(accepted == 16);
    }

    // OutputBudget: the exact requirement is accepted, one byte less is not.
    for size in 0..10 {
        var source: u8[>..] = [];
        for i in size { source.push(0x5a); }
        for padding in [b64::Padding.Padded, b64::Padding.Unpadded] {
            let need = b64::encoded_len(size, padding);
            var out: u8[>..] = [];
            assert(b64::encode(out, source, policy(b64::Alphabet.Standard, padding, need)) == b64::Error.None);
            assert(out.len == need);
            if need > 0 { rejects_encode(source, b64::Alphabet.Standard, padding, need - 1); }
            rejects_encode(source, b64::Alphabet.Standard, padding, -1);
            rejects_encode(source, b64::Alphabet.Standard, padding, -9223372036854775807 - 1);
        }
    }
    // A negative budget is reported before any input is examined.
    rejects_encode("", b64::Alphabet.Standard, b64::Padding.Padded, -1);
    var untouched = str("prefix");
    assert(b64::decode(untouched, "!!!!", policy(b64::Alphabet.Standard, b64::Padding.Padded, -1)) == b64::Error.OutputBudget);
    assert(untouched == "prefix");
    // The shape is reported before the budget, and the budget before the bytes.
    assert(b64::decode(untouched, "Z", policy(b64::Alphabet.Standard, b64::Padding.Padded, -1)) == b64::Error.OutputBudget);
    assert(b64::decode(untouched, "Z", policy(b64::Alphabet.Standard, b64::Padding.Padded, 8)) == b64::Error.InvalidLength);
    assert(b64::decode(untouched, "!!!!", policy(b64::Alphabet.Standard, b64::Padding.Padded, 0)) == b64::Error.OutputBudget);
    assert(b64::decode(untouched, "!!!!", policy(b64::Alphabet.Standard, b64::Padding.Padded, 8)) == b64::Error.InvalidCharacter);
    // The first offending byte in text order decides between padding and character.
    assert(b64::decode(untouched, "Z=g!", policy(b64::Alphabet.Standard, b64::Padding.Padded, 8)) == b64::Error.InvalidPadding);
    assert(b64::decode(untouched, "Z!g=", policy(b64::Alphabet.Standard, b64::Padding.Padded, 8)) == b64::Error.InvalidCharacter);
    assert(untouched == "prefix");
    // Decode budgets: exact, one less, and zero for a non-empty result.
    for size in 0..10 {
        var source: u8[>..] = [];
        for i in size { source.push(0xa5); }
        let text = text_of(source, b64::Alphabet.Standard, b64::Padding.Padded);
        var out: u8[>..] = [];
        assert(b64::decode(out, text, policy(b64::Alphabet.Standard, b64::Padding.Padded, size)) == b64::Error.None);
        assert(out == source);
        if size > 0 {
            var short = str("prefix");
            assert(b64::decode(short, text, policy(b64::Alphabet.Standard, b64::Padding.Padded, size - 1)) == b64::Error.OutputBudget);
            assert(short == "prefix");
        }
    }

    // Length helpers agree with the codec and reject impossible lengths.
    assert(b64::encoded_len(0, b64::Padding.Padded) == 0);
    assert(b64::encoded_len(1, b64::Padding.Padded) == 4);
    assert(b64::encoded_len(1, b64::Padding.Unpadded) == 2);
    assert(b64::encoded_len(2, b64::Padding.Unpadded) == 3);
    assert(b64::encoded_len(3, b64::Padding.Unpadded) == 4);
    assert(b64::encoded_len(-1, b64::Padding.Padded) == -1);
    assert(b64::encoded_len(2305843009213693951, b64::Padding.Padded) > 0);
    assert(b64::encoded_len(2305843009213693952, b64::Padding.Padded) == -1);
    assert(b64::encoded_len(9223372036854775807, b64::Padding.Padded) == -1);
    assert(b64::decoded_len("", b64::Padding.Padded) == 0);
    assert(b64::decoded_len("Zg==", b64::Padding.Padded) == 1);
    assert(b64::decoded_len("Zm8=", b64::Padding.Padded) == 2);
    assert(b64::decoded_len("Zm9v", b64::Padding.Padded) == 3);
    assert(b64::decoded_len("Zg", b64::Padding.Unpadded) == 1);
    assert(b64::decoded_len("Zm8", b64::Padding.Unpadded) == 2);
    assert(b64::decoded_len("Z", b64::Padding.Unpadded) == -1);
    assert(b64::decoded_len("Zg=", b64::Padding.Padded) == -1);
    assert(b64::decoded_len("=", b64::Padding.Padded) == -1);
    assert(b64::decoded_len("A==", b64::Padding.Padded) == -1);

    print("Base64 public API tests passed");
}
