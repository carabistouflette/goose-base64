// SPDX-License-Identifier: Apache-2.0
// The benchmark compares this library against `strict`, a policy layer over the
// pinned standard library. That comparison is only meaningful if the two
// implement the same contract, so this test proves it byte for byte: same
// error, same appended bytes, for every input and every policy.
//
// It runs before any measurement. A mismatch here invalidates the benchmark
// rather than producing a number.
import b64 from "..";
import strict;
import std;

const STANDARD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

fn policy(alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) -> b64::Policy {
    return b64::Policy { alphabet: alphabet, padding: padding, max_out: max_out };
}

// Both implementations must agree on the error and on every appended byte.
fn same_encode(src: u8[:], alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) {
    var mine:   u8[>..] = [];
    var theirs: u8[>..] = [];
    let a = b64::encode(mine, src, policy(alphabet, padding, max_out));
    let b = strict::encode(theirs, src, policy(alphabet, padding, max_out));
    assert(a == b);
    assert(mine == theirs);
}

fn same_decode(text: u8[:], alphabet: b64::Alphabet, padding: b64::Padding, max_out: i64) {
    var mine:   u8[>..] = [];
    var theirs: u8[>..] = [];
    let a = b64::decode(mine, text, policy(alphabet, padding, max_out));
    let b = strict::decode(theirs, text, policy(alphabet, padding, max_out));
    assert(a == b);
    assert(mine == theirs);
}

fn main() {
    // Goose has no tuples, so the four policy combinations are two arrays.
    let alphabets = [b64::Alphabet.Standard, b64::Alphabet.Standard,
                     b64::Alphabet.Url, b64::Alphabet.Url];
    let paddings = [b64::Padding.Padded, b64::Padding.Unpadded,
                    b64::Padding.Padded, b64::Padding.Unpadded];

    // Every 1-byte and 2-byte input, all four policies, exact and short budgets.
    for index in alphabets.len {
        let alphabet = alphabets[index];
        let padding = paddings[index];
        for b in 0..256 {
            var one: u8[1] = [b as! u8];
            let need = b64::encoded_len(1, padding);
            same_encode(one[..], alphabet, padding, need);
            same_encode(one[..], alphabet, padding, need - 1);
            for c in 0..256 {
                var two: u8[2] = [b as! u8, c as! u8];
                let need2 = b64::encoded_len(2, padding);
                same_encode(two[..], alphabet, padding, need2);
                same_encode(two[..], alphabet, padding, need2 - 1);
            }
        }
    }

    // Lengths across every group boundary, with a deterministic pattern.
    for size in 0..400 {
        var source: u8[>..] = [];
        for i in size { source.push((i * 37 + 11) as! u8); }
        for index in alphabets.len {
            let alphabet = alphabets[index];
            let padding = paddings[index];
            let need = b64::encoded_len(size, padding);
            same_encode(source, alphabet, padding, need);
            same_encode(source, alphabet, padding, need - 1);
            same_encode(source, alphabet, padding, need + 1);
            same_encode(source, alphabet, padding, -1);
            // Decode the text both produce, at the exact budget and one short.
            var text: u8[>..] = [];
            assert(b64::encode(text, source, policy(alphabet, padding, need)) == b64::Error.None);
            same_decode(text, alphabet, padding, size);
            same_decode(text, alphabet, padding, size - 1);
            same_decode(text, alphabet, padding, 0);
            same_decode(text, alphabet, padding, -1);
        }
    }

    // Every 1-, 2- and 3-character text over each alphabet plus the outsiders.
    let outsiders = "=+-_ \t\n\r\x00\xff!.";
    for index in alphabets.len {
        let alphabet = alphabets[index];
        let padding = paddings[index];
        let symbols = if alphabet == b64::Alphabet.Standard { STANDARD } else { URL };
        var pool: u8[>..] = [];
        pool.append(symbols);
        pool.append(outsiders);
        for x in pool.len {
            var one: u8[1] = [pool[x]];
            same_decode(one[..], alphabet, padding, 64);
            for y in pool.len {
                var two: u8[2] = [pool[x], pool[y]];
                same_decode(two[..], alphabet, padding, 64);
                for z in pool.len {
                    var three: u8[3] = [pool[x], pool[y], pool[z]];
                    same_decode(three[..], alphabet, padding, 64);
                }
            }
        }
    }

    // Long texts, their truncations and single-byte corruptions.
    for index in alphabets.len {
        let alphabet = alphabets[index];
        let padding = paddings[index];
        var source: u8[>..] = [];
        for i in 4096 { source.push((i * 131 + 7) as! u8); }
        let need = b64::encoded_len(source.len, padding);
        var text: u8[>..] = [];
        assert(b64::encode(text, source, policy(alphabet, padding, need)) == b64::Error.None);
        same_decode(text, alphabet, padding, source.len);
        for cut in 1..5 {
            same_decode(text[..text.len - cut], alphabet, padding, source.len);
        }
        for at in [0, text.len / 2, text.len - 1] {
            var mutated = str(text);
            mutated[at] = '!';
            same_decode(mutated, alphabet, padding, source.len);
        }
    }

    print("Benchmark competitor implements the same contract byte for byte");
}
