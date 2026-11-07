// SPDX-License-Identifier: Apache-2.0
// Test-only line adapter for the Python differential oracle. Applications own
// their own input size limits; this reads one request per line from stdin.
//
// Request:  E|D \t alphabet(0|1) \t padding(0|1) \t max_out \t hex
// Response: E|D \t error-name \t hex
import b64 from "..";
import std;
import os;

fn nibble(c: u8) -> u8 {
    if c >= '0' && c <= '9' { return c - '0'; }
    assert(c >= 'a' && c <= 'f');
    return c - 'a' + 10;
}

fn unhex(input: u8[:], out: u8[>..]&) {
    assert(input.len % 2 == 0);
    out.clear();
    var i = 0;
    while i < input.len {
        out.push(nibble(input[i]) * 16 + nibble(input[i + 1]));
        i += 2;
    }
}

fn tohex(input: u8[:], out: u8[>..]&) {
    let digits = "0123456789abcdef";
    out.clear();
    for i in input.len {
        out.push(digits[input[i] / 16]);
        out.push(digits[input[i] % 16]);
    }
}

fn name_of(e: b64::Error) -> u8[:] {
    if e == b64::Error.None { return "None"; }
    if e == b64::Error.InvalidLength { return "InvalidLength"; }
    if e == b64::Error.InvalidCharacter { return "InvalidCharacter"; }
    if e == b64::Error.InvalidPadding { return "InvalidPadding"; }
    if e == b64::Error.NonCanonical { return "NonCanonical"; }
    return "OutputBudget";
}

// The field starting at `at`, advancing `at` past its tab.
fn next_field(line: u8[:], at: i64&) -> u8[:] {
    var i = at;
    while i < line.len && line[i] != '\t' { i++; }
    let field = line[at..i];
    at = if i < line.len { i + 1 } else { i };
    return field;
}

fn number(field: u8[:]) -> i64 {
    let value, ok = parse_int(field, 10);
    assert(ok);
    return value;
}

fn main() {
    var line:   u8[>..] = [];
    var input:  u8[>..] = [];
    var output: u8[>..] = [];
    var hex:    u8[>..] = [];
    loop {
        line.clear();
        if !read_line(line) { break; }
        if line.len == 0 { continue; }
        var at = 0;
        let kind = next_field(line, at);
        let alphabet = if number(next_field(line, at)) == 0 { b64::Alphabet.Standard } else { b64::Alphabet.Url };
        let padding = if number(next_field(line, at)) == 0 { b64::Padding.Padded } else { b64::Padding.Unpadded };
        let policy = b64::Policy { alphabet: alphabet, padding: padding, max_out: number(next_field(line, at)) };
        unhex(next_field(line, at), input);
        output.clear();
        var error = b64::Error.None;
        if kind == "E" { error = b64::encode(output, input, policy); }
        else {
            assert(kind == "D");
            error = b64::decode(output, input, policy);
        }
        tohex(output, hex);
        print(kind, "\t", name_of(error), "\t", hex);
    }
}
