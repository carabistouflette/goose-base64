# Design contract

Strict, bounded RFC 4648 Base64 and Base64url for Goose. Pure Goose, no native
code, no I/O, no global state. Namespace `b64`.

## Why this exists next to the standard library

The pinned compiler (`eadca409f68210893f366e60d0c2f0dc29a339be`) ships
`stdlib/base64.goose`, documented in `docs/stdlib.md` §base64. It is a good
codec and this module reuses it. It is not sufficient for four concrete
reasons, each quoted from that documentation:

1. **No URL-safe alphabet.** "It rejects line breaks, white space, unpadded
   text and other alphabets (the `-` and `_` of the URL-safe alphabet are
   invalid)." RFC 4648 §5 and every JOSE-family protocol (RFC 7515 §2) use
   exactly that alphabet.
2. **No unpadded output.** `encode` "appends 4 characters per 3 bytes, padded",
   and `decode` rejects "unpadded text". RFC 7515 §2 requires the padding to be
   omitted.
3. **Non-canonical text is accepted.** "It does not require the bits left over
   before the padding to be zero, so `Zh==` decodes the same as `Zg==`; most
   decoders allow this." RFC 4648 §3.5 says conforming encoders must zero those
   bits and decoders may reject them. Accepting them makes the encoding
   non-injective: two distinct texts decode to the same bytes, so a value
   compared as text and the same value compared as bytes can disagree.
4. **No output budget.** `encode` and `decode` grow the caller's buffer to
   whatever the input implies. There is no way to say "append at most N bytes"
   and no way to learn the required size before the call.

A Basic `Authorization` header alone does **not** justify a second codec: the
standard library's padded standard-alphabet encoder is exactly right for
RFC 7617, and `examples/basic_auth.goose` shows that path using this module only
because it is already present. The justification is items 1-4.

## Interface

```goose
enum Alphabet { Standard, Url }
enum Padding { Padded, Unpadded }
enum Error { None, InvalidLength, InvalidCharacter, InvalidPadding, NonCanonical, OutputBudget }

struct Policy {
    alphabet: Alphabet = Alphabet.Standard,
    padding:  Padding  = Padding.Padded,
    max_out:  i64,                      // required, no default
}

fn encoded_len(src_len: i64, padding: Padding) -> i64
fn decoded_len(src: const u8[:], padding: Padding) -> i64
fn encode(out: u8[>..]&, src: const u8[:], policy: Policy) -> Error
fn decode(out: u8[>..]&, src: const u8[:], policy: Policy) -> Error
```

`max_out` has no default on purpose: every call states its budget.

`encoded_len` is exact for a byte count. `decoded_len` is exact for a text and
reads only its trailing `=`; it does not validate characters. Both return `-1`
when the length cannot be valid under the policy, so a caller can size a buffer
or reject a field before doing any work.

## Semantics

`encode` appends exactly `encoded_len(src.len, policy.padding)` bytes.
`decode` appends exactly `decoded_len(src, policy.padding)` bytes. Neither
clears or rewrites the caller's existing bytes, and neither retains a reference
to its input.

The four policy combinations are independent. The alphabet selects the two
extra characters (values 62 and 63: `+`/`/` or `-`/`_`); the padding policy
selects whether `=` is written and required. `0xfb 0xff` is `+/8=`, `+/8`,
`-_8=` and `-_8` in the four combinations, in that order.

Whitespace is never accepted, in any policy. A caller that must tolerate folded
or wrapped text strips it explicitly and owns that decision.

### Error precedence

Fixed, documented and tested, in this order:

1. `max_out < 0` → `OutputBudget`, before any input is examined.
2. The length and padding shape → `InvalidLength`.
3. `decoded_len > max_out` → `OutputBudget`, before any character is examined.
4. The first offending byte in text order: `=` inside the data region →
   `InvalidPadding`; any byte outside the selected alphabet →
   `InvalidCharacter`.
5. The unused low bits of the final data character → `NonCanonical`.

A rejected call leaves the caller's buffer byte-identical. `decode` therefore
scans the input twice: once to validate, once to write. That is the price of
rejection before mutation, and it is the same contract the sibling libraries
use.

### Canonicality

For a text whose data region is not a multiple of four, the final character
carries 4 unused bits (two characters left over) or 2 unused bits (three
characters left over). Those bits must be zero. Of the 64 possible final
characters, 4 are canonical for a two-character tail and 16 for a
three-character tail; `tests/api.goose` checks both exhaustively and
`tests/stdlib_parity.goose` shows the standard library accepting all 64.

## Limits

| Limit | Value | Enforced by |
| --- | --- | --- |
| Appended bytes per call | `policy.max_out` | `encode`, `decode` |
| Input length for `encoded_len` | 2^61 − 1 bytes | `encoded_len` returns `-1` above it |
| Text length | bounded by the caller's slice | no library cap |
| Total work | O(n) time, O(1) extra space | no allocation inside the codec |

There is no library input-size cap. A caller that reads text from a network or
a file must bound the read itself; `max_out` bounds the write, not the read.

## Allocation and ownership

`out` is a caller-owned growable byte buffer (`u8[>..]&`). The only allocation
is the buffer's own growth, and it is exactly the appended count: `encode`
writes the final 1-2 byte group itself rather than letting the standard library
write padding that would then be removed, so no temporary padding is ever
allocated. `decode` allocates nothing beyond the output growth.

`src` must not alias `out`. The compiler enforces this statically: a call whose
source slice points into the buffer being grown is rejected with "cannot resize
out while src is still used: it may hold a reference or slice into it (§5.1)".
`tests/alias_rejected.sh` asserts that diagnostic, so the guarantee is checked
rather than assumed.

## What is reused, and what is not

`encode` delegates whole 3-byte groups to `base64::encode` from the standard
library. Those groups are identical in both alphabets and never padded, so the
delegation is exact; only the final 1-2 byte group is written here, because the
standard library always pads and always uses the standard alphabet. On the
compatible path (standard alphabet, padded) the output is byte-identical to the
standard library, which `tests/stdlib_parity.goose` checks for every length from
0 to 299.

`decode` is implemented here rather than delegated. The standard library's
decoder cannot express the URL alphabet, unpadded text, a canonicality check or
a budget, and using it on one policy path only would make the error taxonomy
depend on the policy. The differential test against the standard library on the
compatible subset is the substitute for delegation: it proves the two agree
where they overlap.

## Non-goals

No streaming or incremental codec, no MIME line folding or unfolding, no
`base32`/`base16`, no automatic alphabet detection, no whitespace tolerance, no
I/O, no logging, no constant-time claims. Decoding is not constant-time and must
not be used to compare secrets; compare the decoded bytes with a dedicated
constant-time routine.

## Validation

See [validation.md](validation.md) for the exact commands, results and the
coverage that was not executed.
