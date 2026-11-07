// SPDX-License-Identifier: Apache-2.0
// What actually happens when `src` aliases `out` in `decode`.
//
// The compiler does not reject this call (see tests/alias_rejected.sh), so the
// documented non-aliasing rule is a caller requirement here rather than a
// static guarantee. This test pins the runtime behaviour that makes the gap a
// contract question and not a memory-safety one:
//
//   * data stacks are fixed reserved regions grown by bump pointer and never
//     reallocated (gs_reserve_region), so a source pointer into the region
//     stays valid while the call appends;
//   * the write pass starts at the buffer's end, which is at or after the end
//     of any slice of that buffer, so the source is never overwritten;
//   * the result is therefore the text followed by its own decoding.
//
// Every size below resizes the buffer to exactly the text length first, so the
// call must commit fresh pages of the region while `src` points into it. Run
// this under ASan and UBSan (`make sanitize`) to check the claim rather than
// read it.
import b64 from "..";
import std;

const ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// Decode `size` characters of text into the same buffer that holds the text.
fn aliased(size: i64) {
    var buffer: u8[>..] = [];
    buffer.resize(size, 0);
    for i in size { buffer[i] = ALPHA[i % 64]; }
    assert(buffer.len == size);

    let error = b64::decode(buffer, buffer[..], b64::Policy { max_out: 300000 });
    assert(error == b64::Error.None);

    // The text is untouched: the write pass began at its end.
    for i in size { assert(buffer[i] == ALPHA[i % 64]); }

    // The appended bytes are exactly the decoding of that text.
    var text: u8[>..] = [];
    text.resize(size, 0);
    for i in size { text[i] = ALPHA[i % 64]; }
    var reference: u8[>..] = [];
    assert(b64::decode(reference, text, b64::Policy { max_out: 300000 }) == b64::Error.None);
    assert(buffer.len == size + reference.len);
    assert(buffer[size..] == reference);
}

fn main() {
    // Whole groups only, so every text is valid: 4 bytes to 8000 bytes.
    for groups in 1..2001 { aliased(groups * 4); }
    // Sizes that commit many pages of the region.
    aliased(65536);
    aliased(262144);
    print("Aliased decode keeps the text and appends its decoding");
}
