// SPDX-License-Identifier: Apache-2.0
// Consumer: a JSON or protocol field that carries binary data as text.
//
// JSON has no byte string, so protocols that embed binary in JSON encode it as
// Base64. JOSE (RFC 7515 §2) and its descendants use the URL-safe alphabet
// with the padding omitted, and require the encoding to be canonical. That
// matters for more than tidiness: a permissive decoder maps several distinct
// strings onto the same bytes, so a value compared as text and the same value
// compared as bytes can disagree. A key identifier or a detached signature
// checked that way is malleable.
//
// This example decodes such a field with an explicit byte budget and rejects
// the non-canonical spelling.
import b64 from "..";
import std;

// The largest binary field this consumer accepts.
const MAX_FIELD: i64 = 4096;

// Decode one base64url field from a JSON document into `out`.
fn decode_field(out: u8[>..]&, field: u8[:]) -> b64::Error {
    return b64::decode(out, field, b64::Policy {
        alphabet: b64::Alphabet.Url,
        padding:  b64::Padding.Unpadded,
        max_out:  MAX_FIELD,
    });
}

// Encode one binary field for a JSON document. The text budget is the exact
// encoded size of the largest field this consumer accepts, so the two limits
// cannot drift apart.
fn encode_field(out: u8[>..]&, bytes: u8[:]) -> b64::Error {
    return b64::encode(out, bytes, b64::Policy {
        alphabet: b64::Alphabet.Url,
        padding:  b64::Padding.Unpadded,
        max_out:  b64::encoded_len(MAX_FIELD, b64::Padding.Unpadded),
    });
}

fn main() {
    // A 32-byte key identifier, as it appears in a JSON document.
    var key_id: u8[>..] = [];
    for i in 32 { key_id.push(i as! u8); }
    var field: u8[>..] = [];
    assert(encode_field(field, key_id) == b64::Error.None);
    assert(field == "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8");
    print(field);

    // The field round-trips, and the decoded bytes are the original ones.
    var decoded: u8[>..] = [];
    assert(decode_field(decoded, field) == b64::Error.None);
    assert(decoded == key_id);

    // The URL alphabet is required: the standard alphabet's two extra
    // characters are rejected rather than silently accepted.
    decoded.clear();
    assert(decode_field(decoded, "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8+") == b64::Error.InvalidCharacter);
    assert(decoded.len == 0);

    // Padding is not part of the field's contract.
    decoded.clear();
    assert(decode_field(decoded, "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=") == b64::Error.InvalidPadding);
    assert(decoded.len == 0);

    // Canonicality: "-_8" and "-_9" are different strings that a permissive
    // decoder turns into the same two bytes. Only the canonical one is
    // accepted, so a text comparison and a byte comparison cannot disagree.
    decoded.clear();
    assert(decode_field(decoded, "-_8") == b64::Error.None);
    assert(decoded == "\xfb\xff");
    decoded.clear();
    assert(decode_field(decoded, "-_9") == b64::Error.NonCanonical);
    assert(decoded.len == 0);
    decoded.clear();
    assert(decode_field(decoded, "-_B") == b64::Error.NonCanonical);
    assert(decoded.len == 0);

    // The budget is a byte budget, not a character budget: a field whose
    // decoded size exceeds it is refused before any byte is written.
    decoded.clear();
    var oversized: u8[>..] = [];
    for i in MAX_FIELD + 1 { oversized.push(0x41); }
    var big_field: u8[>..] = [];
    assert(encode_field(big_field, oversized) == b64::Error.OutputBudget);
    assert(big_field.len == 0);
    var at_limit: u8[>..] = [];
    for i in MAX_FIELD { at_limit.push(0x41); }
    assert(encode_field(big_field, at_limit) == b64::Error.None);
    decoded.clear();
    assert(decode_field(decoded, big_field) == b64::Error.None);
    assert(decoded == at_limit);

    print("JSON binary field example passed");
}
