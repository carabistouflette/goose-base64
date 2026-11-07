// SPDX-License-Identifier: Apache-2.0
// Benchmark harness. One process times exactly one implementation, so the
// runner (bench/measure.py) controls the order in which implementations are
// measured and can alternate it between samples. That removes the systematic
// bias of always timing one implementation first, and gives a per-process peak
// RSS for each implementation.
//
// Implementations:
//
//   b64     this library.
//   strict  the equal-contract competitor: the pinned standard library's
//           `base64` plus the policy layer a caller has to write today to get
//           this contract (bench/strict.goose). Same contract, same codec
//           underneath, different structure. bench/strict_equivalence.goose
//           proves the two agree byte for byte before any number is recorded.
//   stdlib  the pinned standard library alone. It is the maintained, fast codec
//           but it is permissive: no URL alphabet, no unpadded text, no
//           canonicality check and no budget. It does strictly less work, so
//           its rows carry `comparable` 0 and no ratio is computed from them.
//           It is reported as a lower bound, never as a fair race.
//
// Fairness rules enforced here and recorded in every row:
//   * identical call shapes: a caller-owned `u8[>..]` output and a `const u8[:]`
//     input, for all three;
//   * `comparable` is 1 only where the implementation does the same work as
//     `b64`, so only `strict` rows produce a ratio;
//   * `*_fresh` rows allocate a new output buffer per call, so allocation and
//     ownership cost is visible instead of amortised;
//   * inputs are built outside the timed loop; inside it a three-byte content
//     sample keeps each call live without adding O(n) work that would dilute
//     the ratio; the full output is checksummed outside the loop, so a
//     wrong-but-same-length result cannot pass;
//   * the checksum is FNV-1a over the whole output, not a length;
//   * the implementation is selected once, before the loop, into an integer, so
//     the per-call dispatch is an integer compare rather than a string compare.
//
// Usage: bench <iterations> <implementation>
import b64 from "..";
import strict;
import std;
import os;
import base64;

const MAX_OUT: i64 = 1048576;

// A cheap content sample for the timed loop: three real output bytes, so the
// call cannot be elided, without adding O(n) work that would dilute the ratio.
fn sample(bytes: u8[:]) -> i64 {
    if bytes.len == 0 { return 0; }
    return bytes[0] + bytes[bytes.len / 2] + bytes[bytes.len - 1];
}

// FNV-1a over the whole output, accumulated outside the timed loop. A length
// alone would not detect a wrong-but-same-length output. The multiply stays
// below 2^56, so it cannot overflow i64.
fn fnv(bytes: u8[:]) -> i64 {
    var h: i64 = 2166136261;
    for i in bytes.len {
        h = ((h ^ bytes[i]) * 16777619) & 4294967295;
    }
    return h;
}

fn row(phase: u8[:], fixture: u8[:], implementation: u8[:], elapsed: i64,
       iterations: i64, input_len: i64, output_len: i64, comparable: i64,
       checksum: i64) {
    print(phase, "\t", fixture, "\t", implementation, "\t", elapsed, "\t",
          iterations, "\t", input_len, "\t", output_len, "\t", comparable, "\t",
          checksum);
}

// 0 = b64, 1 = strict, 2 = stdlib. Resolved once, outside every timed loop.
fn kind_of(implementation: u8[:]) -> i64 {
    if implementation.starts_with("b64") { return 0; }
    if implementation.starts_with("strict") { return 1; }
    assert(implementation.starts_with("stdlib"));
    return 2;
}

fn encode_once(kind: i64, out: u8[>..]&, source: u8[:], policy: b64::Policy) -> bool {
    if kind == 0 { return b64::encode(out, source, policy) == b64::Error.None; }
    if kind == 1 { return strict::encode(out, source, policy) == b64::Error.None; }
    base64::encode(out, source);
    return true;
}

fn decode_once(kind: i64, out: u8[>..]&, text: u8[:], policy: b64::Policy) -> bool {
    if kind == 0 { return b64::decode(out, text, policy) == b64::Error.None; }
    if kind == 1 { return strict::decode(out, text, policy) == b64::Error.None; }
    return base64::decode(out, text);
}

// The consumer end of the path: an HTTP Basic header value (RFC 7617 §2).
fn basic_auth_once(kind: i64, out: u8[>..]&, user: u8[:], password: u8[:]) -> bool {
    var credential: u8[>..] = [];
    credential.append(user);
    credential.push(':');
    credential.append(password);
    out.append("Basic ");
    let policy = b64::Policy { max_out: 4096 };
    if kind == 0 { return b64::encode(out, credential, policy) == b64::Error.None; }
    return strict::encode(out, credential, policy) == b64::Error.None;
}

fn main() {
    let argv = args();
    assert(argv.len == 3);
    let iterations, ok = parse_int(argv[1], 10);
    assert(ok && iterations > 0 && iterations <= 10000000);
    let implementation = argv[2];
    let fresh = implementation.ends_with("_fresh");
    let kind = kind_of(implementation);
    let comparable: i64 = if kind == 2 { 0 } else { 1 };
    let policy = b64::Policy { max_out: MAX_OUT };
    var checksum = 0;

    let sizes = [0, 1, 2, 3, 4, 16, 64, 256, 1024, 4096, 65536];
    let names = ["size_0", "size_1", "size_2", "size_3", "size_4", "size_16",
                 "size_64", "size_256", "size_1024", "size_4096", "size_65536"];

    for index in sizes.len {
        var source: u8[>..] = [];
        for i in sizes[index] { source.push((i * 37 + 11) as! u8); }
        var text: u8[>..] = [];
        base64::encode(text, source);

        // Encode.
        var elapsed = 0;
        var produced = 0;
        if fresh {
            let start = clock_ns();
            for i in iterations {
                var buffer: u8[>..] = [];
                assert(encode_once(kind, buffer, source, policy));
                checksum += sample(buffer);
                produced = buffer.len;
            }
            elapsed = clock_ns() - start;
        } else {
            var buffer: u8[>..] = [];
            let start = clock_ns();
            for i in iterations {
                buffer.clear();
                assert(encode_once(kind, buffer, source, policy));
                checksum += sample(buffer);
            }
            elapsed = clock_ns() - start;
            produced = buffer.len;
        }
        var final: u8[>..] = [];
        assert(encode_once(kind, final, source, policy));
        assert(final.len == produced);
        row("encode", names[index], implementation, elapsed, iterations, source.len,
            produced, comparable, fnv(final));

        // Decode.
        if fresh {
            let start = clock_ns();
            for i in iterations {
                var buffer: u8[>..] = [];
                assert(decode_once(kind, buffer, text, policy));
                checksum += sample(buffer);
                produced = buffer.len;
            }
            elapsed = clock_ns() - start;
        } else {
            var buffer: u8[>..] = [];
            let start = clock_ns();
            for i in iterations {
                buffer.clear();
                assert(decode_once(kind, buffer, text, policy));
                checksum += sample(buffer);
            }
            elapsed = clock_ns() - start;
            produced = buffer.len;
        }
        final.clear();
        assert(decode_once(kind, final, text, policy));
        assert(final.len == produced);
        row("decode", names[index], implementation, elapsed, iterations, text.len,
            produced, comparable, fnv(final));
    }

    // Rejection paths. `b64` and `strict` do the same work here, so they are
    // comparable; the standard library does less and is not.
    var long_text: u8[>..] = [];
    for i in 65536 { long_text.push('A'); }
    var long_bad = str(long_text);
    long_bad[long_bad.len - 1] = '!';
    let rejects = ["noncanonical", "invalid_char", "whitespace", "bad_padding",
                   "url_unpadded", "invalid_at_end_64k"];
    let rejected = ["Zh==", "Zg!=", "Zg =", "Zg=", "-_8", long_bad];
    for index in rejects.len {
        let text = rejected[index];
        var buffer: u8[>..] = [];
        let start = clock_ns();
        for i in iterations {
            buffer.clear();
            if !decode_once(kind, buffer, text, policy) { checksum += 1; }
        }
        let elapsed = clock_ns() - start;
        row("reject", rejects[index], implementation, elapsed, iterations, text.len,
            buffer.len, comparable, fnv(buffer));
    }

    // Valid but worst case for the validating decoder: 64 KiB of 'A', every
    // group canonical, so the whole text is walked and accepted.
    {
        let text = long_text;
        var buffer: u8[>..] = [];
        let start = clock_ns();
        for i in iterations {
            buffer.clear();
            assert(decode_once(kind, buffer, text, policy));
            checksum += sample(buffer);
        }
        let elapsed = clock_ns() - start;
        assert(buffer.len == 49152);
        row("pathological", "all_A_64k", implementation, elapsed, iterations,
            text.len, buffer.len, comparable, fnv(buffer));
    }

    // The consumer end of the path: build an HTTP Basic header value. Only the
    // two implementations that offer this contract are measured.
    if kind != 2 {
        let users = ["Aladdin", "user", "a"];
        let passwords = ["open sesame", "pass", ""];
        let consumers = ["basic_auth_rfc7617", "basic_auth_short",
                         "basic_auth_empty_password"];
        for index in users.len {
            var buffer: u8[>..] = [];
            let start = clock_ns();
            for i in iterations {
                buffer.clear();
                assert(basic_auth_once(kind, buffer, users[index], passwords[index]));
                checksum += sample(buffer);
            }
            let elapsed = clock_ns() - start;
            row("consumer", consumers[index], implementation, elapsed, iterations,
                users[index].len + passwords[index].len, buffer.len, comparable,
                fnv(buffer));
        }
    }

    print("checksum\t", checksum);
}
