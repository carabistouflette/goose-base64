// SPDX-License-Identifier: Apache-2.0
// Consumer: goose-http. An HTTP Basic credential is a header value the caller
// builds; goose-http sends an explicit `Authorization` header's bytes
// unchanged (docs/API.md: "An explicit caller-supplied Authorization header is
// supported") and performs no authentication negotiation of its own.
//
// Contract (RFC 7617 §2): the header value is "Basic " followed by the
// standard-alphabet, padded Base64 of `user-id ":" password` as UTF-8 bytes.
// The colon is the separator, so a user-id containing ':' is ambiguous and is
// rejected here rather than silently producing a different credential.
import b64 from "..";
import std;

// The largest credential this example accepts, in bytes before encoding.
const MAX_CREDENTIAL: i64 = 1024;

// Append "Basic <base64(user:password)>" to `out`, or nothing on failure.
fn basic_authorization(out: u8[>..]&, user: u8[:], password: u8[:]) -> b64::Error {
    for i in user.len {
        if user[i] == ':' { return b64::Error.InvalidCharacter; }
    }
    let credential_len = user.len + 1 + password.len;
    if credential_len > MAX_CREDENTIAL { return b64::Error.OutputBudget; }
    // "Basic " is six bytes; the encoded credential is padded standard Base64.
    let need = 6 + b64::encoded_len(credential_len, b64::Padding.Padded);
    if need > MAX_CREDENTIAL * 2 { return b64::Error.OutputBudget; }
    var credential: u8[>..] = [];
    credential.append(user);
    credential.push(':');
    credential.append(password);
    let start = out.len;
    out.append("Basic ");
    let error = b64::encode(out, credential, b64::Policy { max_out: need - 6 });
    if error != b64::Error.None {
        out.resize(start, 0);
        return error;
    }
    return b64::Error.None;
}

fn main() {
    // RFC 7617 §2 and RFC 2617 §2 use this exact credential.
    var header: u8[>..] = [];
    assert(basic_authorization(header, "Aladdin", "open sesame") == b64::Error.None);
    assert(header == "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==");
    print(header);

    // The value is what goose-http's Header struct carries verbatim.
    header.clear();
    assert(basic_authorization(header, "user", "pass") == b64::Error.None);
    assert(header == "Basic dXNlcjpwYXNz");
    print(header);

    // Empty password is legal; an empty user-id is not rejected by the RFC, so
    // it is accepted here and the caller decides.
    header.clear();
    assert(basic_authorization(header, "user", "") == b64::Error.None);
    assert(header == "Basic dXNlcjo=");

    // A user-id containing the separator is ambiguous and is refused.
    header.clear();
    assert(basic_authorization(header, "us:er", "pass") == b64::Error.InvalidCharacter);
    assert(header.len == 0);

    // The budget is enforced before anything is appended.
    header.clear();
    var long_user: u8[>..] = [];
    for i in MAX_CREDENTIAL { long_user.push('a'); }
    assert(basic_authorization(header, long_user, "pass") == b64::Error.OutputBudget);
    assert(header.len == 0);

    // Non-ASCII credentials are encoded as their UTF-8 bytes, which is what
    // RFC 7617 §2.1 recommends and what a server expecting UTF-8 will decode.
    header.clear();
    assert(basic_authorization(header, "é", "p") == b64::Error.None);
    assert(header == "Basic w6k6cA==");
    print(header);

    print("goose-http Basic authorization example passed");
}
