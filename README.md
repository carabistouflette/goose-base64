# goose-base64

Strict, bounded RFC 4648 Base64 and Base64url for the
[Goose programming language](https://github.com/aardappel/goose). Choose the
standard or URL-safe alphabet, choose padded or unpadded output, cap the bytes
one call may append, and reject text whose unused trailing bits are not zero.

Apache-2.0. Experimental, with no stable release yet. The import below pins the
reviewed implementation; only Linux x86-64 with the recorded compiler revision
has been validated.

## Quickstart

Requires Git, Make, CMake 3.27+, a C compiler and a C++20 compiler. Setup builds
the Goose compiler pinned in [GOOSE_REVISION](GOOSE_REVISION).

```sh
git clone https://github.com/carabistouflette/goose-base64.git
cd goose-base64
make setup
.toolchain/goose/build/goose run examples/basic_auth.goose
```

The example prints the `Authorization` header value for an HTTP Basic
credential and checks it against RFC 7617's own example:

```
Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==
Basic dXNlcjpwYXNz
Basic w6k6cA==
goose-http Basic authorization example passed
```

To use the library in your own application, save this as `app.goose` and run
`goose run app.goose` with that compiler on your `PATH`:

```goose
import b64 from "carabistouflette/goose-base64@334e708d4d02448ae9caeb8767d773516a1f99ed";
import std;

fn main() {
    var text: u8[>..] = [];
    let error = b64::encode(text, "\xfb\xff", b64::Policy {
        alphabet: b64::Alphabet.Url,
        padding: b64::Padding.Unpadded,
        max_out: 64,
    });
    if error != b64::Error.None { print("encode failed: ", error); return; }
    print(text);                       // -_8

    var bytes: u8[>..] = [];
    if b64::decode(bytes, text, b64::Policy {
        alphabet: b64::Alphabet.Url,
        padding: b64::Padding.Unpadded,
        max_out: 64,
    }) != b64::Error.None { print("decode failed"); return; }
    print(bytes.len);                  // 2
}
```

Declare the package import in the application's root source. For a sibling local
checkout, use `import b64 from "../goose-base64";` instead.

The namespace is `b64`, not `base64`: the pinned standard library already owns
`base64`, and this module imports it.

## API and limits

| Function | Result |
| --- | --- |
| `encode(out, src, policy)` | Append the text of `src`; `Error.None` on success |
| `decode(out, src, policy)` | Append the bytes `src` encodes; `Error.None` on success |
| `encoded_len(src_len, padding)` | Exact appended bytes for a byte count, or `-1` |
| `decoded_len(src, padding)` | Exact appended bytes for a text, or `-1` |

`policy` is `b64::Policy { alphabet, padding, max_out }`. `alphabet` defaults to
`Alphabet.Standard` and `padding` to `Padding.Padded`; `max_out` is required and
is the maximum number of bytes one call may append. `out` is a caller-owned
growable byte buffer (`u8[>..]&`); `src` is a `const u8[:]`.

Errors are `None`, `InvalidLength`, `InvalidCharacter`, `InvalidPadding`,
`NonCanonical` and `OutputBudget`. A failure never changes the caller's buffer.
The precedence is fixed: a negative budget, then the length and padding shape,
then the budget, then the first offending byte in text order, then the trailing
bits.

The four policy combinations are independent. `0xfb 0xff` encodes to `+/8=`,
`+/8`, `-_8=` and `-_8` for standard/padded, standard/unpadded, URL/padded and
URL/unpadded.

Whitespace is rejected in every policy, as are the other alphabet's two extra
characters. `NonCanonical` means the unused low bits of the final data character
are not zero (RFC 4648 §3.5), so a different text would decode to the same
bytes. Of the 64 possible final characters, 4 are canonical for a two-character
tail and 16 for a three-character tail.

Encoding and decoding take O(n) time and O(1) extra space beyond the output.
The logical output grows by exactly the appended count; the runtime controls
the buffer's allocation capacity. `max_out` limits appended bytes, not allocator
overhead or retained capacity. There is no library input-size cap: callers must
bound the read, the write and total work.

`src` must not alias `out`. The compiler rejects that statically for `encode`,
with "cannot resize out while src is still used" (§5.1). For `decode` it is a
caller requirement rather than a compile-time guarantee: the write pass grows
the buffer with `push`, which the §5.1 check does not flag. Such a call is not a
memory-safety hazard — data stacks are fixed reserved regions grown by bump
pointer and never reallocated, so the source bytes stay valid — but it appends
the decoding after the text, which is outside the contract.
`tests/alias_rejected.sh` pins the compile-time behaviour and
`tests/alias_decode_lifetime.goose` pins the runtime behaviour, so both are
checked rather than assumed.

The library does not provide streaming, MIME line folding, `base32`/`base16`,
alphabet detection, whitespace tolerance or I/O. Decoding is not constant-time
and must not be used to compare secrets.

## Why not the standard library

The pinned compiler ships `base64`, and this module reuses its encoder for whole
3-byte groups. It is not sufficient for four reasons, each quoted from the
pinned `docs/stdlib.md`:

- It rejects "other alphabets (the `-` and `_` of the URL-safe alphabet are
  invalid)", which RFC 4648 §5 and RFC 7515 §2 require.
- It always pads and rejects "unpadded text", which RFC 7515 §2 forbids.
- "It does not require the bits left over before the padding to be zero, so
  `Zh==` decodes the same as `Zg==`". This module rejects that as
  `NonCanonical`.
- It has no output budget: it grows the caller's buffer to whatever the input
  implies.

`tests/stdlib_parity.goose` proves the two agree byte for byte on the compatible
path and differ exactly where the policy is added. See
[the design contract](docs/design.md) for the full argument.

## Consumers

**goose-http, HTTP Basic.** goose-http sends an explicit caller-supplied
`Authorization` header's bytes unchanged and performs no authentication
negotiation. RFC 7617 §2 defines the value as `Basic ` plus the padded
standard-alphabet Base64 of `user-id ":" password`. `examples/basic_auth.goose`
builds that value, rejects a user-id containing the separator, and checks the
RFC's own example. The standard library alone is sufficient for this case; the
example uses this module because it is already present.

**JSON and protocol fields.** JSON has no byte string, so protocols that embed
binary in JSON encode it as Base64. JOSE (RFC 7515 §2) and its descendants use
the URL-safe alphabet with the padding omitted and require canonical encoding.
`examples/json_binary.goose` decodes such a field with a byte budget and shows
why canonicality matters: `-_8` and `-_9` are different strings that a
permissive decoder turns into the same two bytes, so a key identifier or a
detached signature compared as text and as bytes can disagree.

Neither consumer is modified by this repository, and neither has adopted this
library. The examples state the contract each would need; adoption is a separate
decision for those projects.

## Support and development

Validated on Linux x86-64 with the pinned Goose compiler, GCC and Clang; CI runs
on Ubuntu 24.04. The library is pure Goose and makes no OS calls. Other
platforms and compiler revisions have not been verified. Tests need Python 3.11+.

Run `make check test` after setup, and `make fuzz mutation` before claiming a
behaviour change is proven. See [development commands](docs/development.md),
[validation history](docs/validation.md) and
[benchmark scope](bench/README.md). CI checks that the benchmark harness builds
and runs, without timing thresholds. See [contributing](CONTRIBUTING.md),
[security reporting](SECURITY.md), [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md).
