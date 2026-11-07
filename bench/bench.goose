// SPDX-License-Identifier: Apache-2.0
// Benchmark harness. It measures this module against the pinned standard
// library's `base64` module, which is the maintained competitor and the code
// this module reuses on the compatible path.
//
// Fairness rules, enforced by the harness and recorded in every row:
//   * Both implementations append to a caller-owned `u8[>..]` buffer and take
//     a `const u8[:]` input, so the call shapes are identical.
//   * The `comparable` column is 1 only where both do the same work. Decode
//     rows that exercise canonicality, the URL alphabet or unpadded text are 0,
//     because this module does strictly more work there.
//   * `*_fresh` rows allocate a new output buffer per call, so the allocation
//     and ownership cost is visible instead of amortised away.
//   * Inputs are built outside the timed loop. Inside it, a three-byte content
//     sample keeps each call live without adding O(n) work that would dilute
//     the ratio; the full output content is summed outside the loop, so a
//     wrong-but-same-length result cannot pass. Both are identical work for
//     both implementations.
//
// Usage: bench <iterations>
import b64 from "..";
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

// The full content checksum, accumulated outside the timed loop. A length alone
// would not detect a wrong-but-same-length output.
fn content(bytes: u8[:]) -> i64 {
    var sum: i64 = 0;
    for i in bytes.len { sum += bytes[i]; }
    return sum;
}

fn main() {
    let argv = args();
    var iterations = 1000;
    if argv.len > 1 {
        let count, ok = parse_int(argv[1], 10);
        assert(ok && count > 0 && count <= 10000000);
        iterations = count;
    }
    let sizes = [0, 1, 2, 3, 4, 16, 64, 256, 1024, 4096, 65536];
    let names = ["size_0", "size_1", "size_2", "size_3", "size_4", "size_16",
                 "size_64", "size_256", "size_1024", "size_4096", "size_65536"];
    var checksum = 0;
    var content_sum = 0;

    for index in sizes.len {
        var source: u8[>..] = [];
        for i in sizes[index] { source.push((i * 37 + 11) as! u8); }
        var mine:   u8[>..] = [];
        var theirs: u8[>..] = [];

        // Encode, reused buffer: the codec, with allocation amortised.
        var start = clock_ns();
        for i in iterations {
            mine.clear();
            assert(b64::encode(mine, source, b64::Policy { max_out: MAX_OUT }) == b64::Error.None);
            checksum += sample(mine);
        }
        let mine_ns = clock_ns() - start;
        start = clock_ns();
        for i in iterations {
            theirs.clear();
            base64::encode(theirs, source);
            checksum += sample(theirs);
        }
        let theirs_ns = clock_ns() - start;
        assert(mine == theirs);
        content_sum += content(mine) + content(theirs);
        print("encode\t", names[index], "\tb64\t", mine_ns, "\t", iterations, "\t",
              source.len, "\t", mine.len, "\t1\n");
        print("encode\t", names[index], "\tstdlib\t", theirs_ns, "\t", iterations, "\t",
              source.len, "\t", theirs.len, "\t1\n");

        // Encode, fresh buffer: allocation and ownership cost per call.
        start = clock_ns();
        for i in iterations {
            var fresh: u8[>..] = [];
            assert(b64::encode(fresh, source, b64::Policy { max_out: MAX_OUT }) == b64::Error.None);
            checksum += sample(fresh);
        }
        let mine_fresh_ns = clock_ns() - start;
        start = clock_ns();
        for i in iterations {
            var fresh: u8[>..] = [];
            base64::encode(fresh, source);
            checksum += sample(fresh);
        }
        let theirs_fresh_ns = clock_ns() - start;
        print("encode\t", names[index], "\tb64_fresh\t", mine_fresh_ns, "\t", iterations, "\t",
              source.len, "\t", mine.len, "\t1\n");
        print("encode\t", names[index], "\tstdlib_fresh\t", theirs_fresh_ns, "\t", iterations, "\t",
              source.len, "\t", theirs.len, "\t1\n");

        // Decode, reused buffer, on canonical standard padded text.
        var text: u8[>..] = [];
        base64::encode(text, source);
        mine.clear();
        theirs.clear();
        start = clock_ns();
        for i in iterations {
            mine.clear();
            assert(b64::decode(mine, text, b64::Policy { max_out: MAX_OUT }) == b64::Error.None);
            checksum += sample(mine);
        }
        let mine_decode_ns = clock_ns() - start;
        start = clock_ns();
        for i in iterations {
            theirs.clear();
            assert(base64::decode(theirs, text));
            checksum += sample(theirs);
        }
        let theirs_decode_ns = clock_ns() - start;
        assert(mine == theirs && mine == source);
        content_sum += content(mine) + content(theirs);
        print("decode\t", names[index], "\tb64\t", mine_decode_ns, "\t", iterations, "\t",
              text.len, "\t", mine.len, "\t1\n");
        print("decode\t", names[index], "\tstdlib\t", theirs_decode_ns, "\t", iterations, "\t",
              text.len, "\t", theirs.len, "\t1\n");

        // Decode, fresh buffer.
        start = clock_ns();
        for i in iterations {
            var fresh: u8[>..] = [];
            assert(b64::decode(fresh, text, b64::Policy { max_out: MAX_OUT }) == b64::Error.None);
            checksum += sample(fresh);
        }
        let mine_decode_fresh_ns = clock_ns() - start;
        start = clock_ns();
        for i in iterations {
            var fresh: u8[>..] = [];
            assert(base64::decode(fresh, text));
            checksum += sample(fresh);
        }
        let theirs_decode_fresh_ns = clock_ns() - start;
        print("decode\t", names[index], "\tb64_fresh\t", mine_decode_fresh_ns, "\t", iterations, "\t",
              text.len, "\t", mine.len, "\t1\n");
        print("decode\t", names[index], "\tstdlib_fresh\t", theirs_decode_fresh_ns, "\t", iterations, "\t",
              text.len, "\t", theirs.len, "\t1\n");
    }

    // Rejection paths. These are not equal work: this module adds the
    // canonicality check and the budget, so `comparable` is 0.
    let rejects = ["noncanonical", "invalid_char", "whitespace", "bad_padding", "url_unpadded"];
    let rejected = ["Zh==", "Zg!=", "Zg =", "Zg=", "-_8"];
    for index in rejects.len {
        let text = rejected[index];
        var mine: u8[>..] = [];
        var start = clock_ns();
        for i in iterations {
            mine.clear();
            if b64::decode(mine, text, b64::Policy { max_out: MAX_OUT }) != b64::Error.None {
                checksum += 1;
            }
        }
        let mine_ns = clock_ns() - start;
        var theirs: u8[>..] = [];
        start = clock_ns();
        for i in iterations {
            theirs.clear();
            if !base64::decode(theirs, text) { checksum += 1; }
        }
        let theirs_ns = clock_ns() - start;
        print("reject\t", rejects[index], "\tb64\t", mine_ns, "\t", iterations, "\t",
              text.len, "\t", mine.len, "\t0\n");
        print("reject\t", rejects[index], "\tstdlib\t", theirs_ns, "\t", iterations, "\t",
              text.len, "\t", theirs.len, "\t0\n");
    }

    print("checksum\t", checksum, "\t", content_sum);
}
