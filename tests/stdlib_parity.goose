// SPDX-License-Identifier: Apache-2.0
// Differential test against the pinned standard library's `base64` module.
//
// Two claims are checked here. First, on the compatible path (standard
// alphabet, padded, canonical text) this module and the standard library agree
// byte for byte, so the standard library really is the reused encoder. Second,
// the two differ exactly where this module adds policy: non-canonical trailing
// bits, the URL alphabet and unpadded text.
import b64 from "..";
import std;
import base64;

const STANDARD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn main() {
    // Encode parity: identical bytes for every length across group boundaries.
    for size in 0..300 {
        var source: u8[>..] = [];
        for i in size { source.push((i * 91 + 7) as! u8); }
        var mine:   u8[>..] = [];
        var theirs: u8[>..] = [];
        assert(b64::encode(mine, source, b64::Policy { max_out: 4096 }) == b64::Error.None);
        base64::encode(theirs, source);
        assert(mine == theirs);
    }

    // Decode parity on canonical standard padded text.
    for size in 0..300 {
        var source: u8[>..] = [];
        for i in size { source.push((i * 53 + 3) as! u8); }
        var text: u8[>..] = [];
        base64::encode(text, source);
        var mine:   u8[>..] = [];
        var theirs: u8[>..] = [];
        assert(b64::decode(mine, text, b64::Policy { max_out: 4096 }) == b64::Error.None);
        assert(base64::decode(theirs, text));
        assert(mine == theirs);
        assert(mine == source);
    }

    // Divergence 1: non-canonical trailing bits. The standard library accepts
    // every final character; this module accepts only the canonical ones.
    var stdlib_accepted = 0;
    var strict_accepted = 0;
    for v in 64 {
        var text = str("Z");
        text.push(STANDARD[v]);
        text.append("==");
        var theirs: u8[>..] = [];
        if base64::decode(theirs, text) { stdlib_accepted++; }
        var mine: u8[>..] = [];
        if b64::decode(mine, text, b64::Policy { max_out: 8 }) == b64::Error.None {
            strict_accepted++;
            assert(mine == theirs);
        }
    }
    assert(stdlib_accepted == 64);
    assert(strict_accepted == 4);
    stdlib_accepted = 0;
    strict_accepted = 0;
    for v in 64 {
        var text = str("Zm");
        text.push(STANDARD[v]);
        text.push('=');
        var theirs: u8[>..] = [];
        if base64::decode(theirs, text) { stdlib_accepted++; }
        var mine: u8[>..] = [];
        if b64::decode(mine, text, b64::Policy { max_out: 8 }) == b64::Error.None {
            strict_accepted++;
            assert(mine == theirs);
        }
    }
    assert(stdlib_accepted == 64);
    assert(strict_accepted == 16);

    // Divergence 2: the URL alphabet and unpadded text are outside the
    // standard library's contract, so it rejects them and this module does not.
    var theirs: u8[>..] = [];
    assert(!base64::decode(theirs, "-_8="));
    var mine: u8[>..] = [];
    assert(b64::decode(mine, "-_8=", b64::Policy { alphabet: b64::Alphabet.Url, max_out: 8 }) == b64::Error.None);
    assert(mine == "\xfb\xff");
    theirs.clear();
    assert(!base64::decode(theirs, "Zg"));
    mine.clear();
    assert(b64::decode(mine, "Zg", b64::Policy { padding: b64::Padding.Unpadded, max_out: 8 }) == b64::Error.None);
    assert(mine == "f");
    // And the standard library always pads, so it cannot produce "Zg".
    theirs.clear();
    base64::encode(theirs, "f");
    assert(theirs == "Zg==");
    mine.clear();
    assert(b64::encode(mine, "f", b64::Policy { padding: b64::Padding.Unpadded, max_out: 8 }) == b64::Error.None);
    assert(mine == "Zg");

    print("Standard library parity and divergence tests passed");
}
