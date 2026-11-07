#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independent Python oracle for the strict Base64/Base64url contract.

The expected result is computed from Python's own `base64` module plus a
separate canonicality check: a text is accepted only when re-encoding the
decoded bytes under the same policy reproduces it byte for byte. That check is
what rejects non-canonical trailing bits, which Python's decoder accepts.

Usage: oracle.py /path/to/oracle-binary
"""
import base64
import random
import subprocess
import sys
from pathlib import Path

if not __debug__:
    raise SystemExit("Do not run with -O: assertions are required")

MAX_INPUT = 2305843009213693951
I64_MIN = -(2**63)
I64_MAX = 2**63 - 1
STANDARD = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
URL = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
ALPHABETS = (STANDARD, URL)


def value_of(c, alphabet):
    if 0x41 <= c <= 0x5A:
        return c - 0x41
    if 0x61 <= c <= 0x7A:
        return c - 0x61 + 26
    if 0x30 <= c <= 0x39:
        return c - 0x30 + 52
    if alphabet == 0:
        return 62 if c == 0x2B else (63 if c == 0x2F else 255)
    return 62 if c == 0x2D else (63 if c == 0x5F else 255)


def encoded_len(n, padding):
    if n < 0 or n > MAX_INPUT:
        return -1
    groups, rest = divmod(n, 3)
    if padding == 0:
        return groups * 4 + (0 if rest == 0 else 4)
    return groups * 4 + (0 if rest == 0 else rest + 1)


def padding_of(text):
    n = len(text)
    if n == 0 or text[-1:] != b"=":
        return 0
    if n >= 2 and text[-2:-1] == b"=":
        return 2
    return 1


def decoded_len(text, padding):
    n = len(text)
    if padding == 0:
        if n % 4:
            return -1
        padlen = padding_of(text)
        if padlen and n < 4:
            return -1
        return n // 4 * 3 - padlen
    rest = n % 4
    if rest == 1:
        return -1
    return n // 4 * 3 + (0 if rest == 0 else rest - 1)


def expect_encode(data, alphabet, padding, max_out):
    need = encoded_len(len(data), padding)
    if need < 0 or max_out < 0 or need > max_out:
        return "OutputBudget", b""
    text = base64.b64encode(data) if alphabet == 0 else base64.urlsafe_b64encode(data)
    if padding == 1:
        text = text.rstrip(b"=")
    return "None", text


def expect_decode(text, alphabet, padding, max_out):
    if max_out < 0:
        return "OutputBudget", b""
    need = decoded_len(text, padding)
    if need < 0:
        return "InvalidLength", b""
    if need > max_out:
        return "OutputBudget", b""
    padlen = padding_of(text) if padding == 0 else 0
    body = text[: len(text) - padlen] if padlen else text
    allowed = ALPHABETS[alphabet]
    for c in body:
        if c == 0x3D:
            return "InvalidPadding", b""
        if c not in allowed:
            return "InvalidCharacter", b""
    rest = len(body) % 4
    if rest == 2 and value_of(body[-1], alphabet) & 15:
        return "NonCanonical", b""
    if rest == 3 and value_of(body[-1], alphabet) & 3:
        return "NonCanonical", b""
    # Independent bit work: Python's decoder, after normalising the alphabet.
    normalised = text.translate(bytes.maketrans(b"-_", b"+/")) if alphabet == 1 else text
    normalised += b"=" * (-len(normalised) % 4)
    decoded = base64.b64decode(normalised, validate=True)
    # Additional canonical validation: the text must be the unique encoding.
    if expect_encode(decoded, alphabet, padding, MAX_INPUT)[1] != text:
        return "NonCanonical", b""
    return "None", decoded


def build_cases():
    rng = random.Random(20261107)
    cases = []
    groups = {}
    group = ["unset"]

    def enc(data, alphabet, padding, max_out):
        cases.append(("E", alphabet, padding, max_out, data))
        groups[group[0]] = groups.get(group[0], 0) + 1

    def dec(text, alphabet, padding, max_out):
        cases.append(("D", alphabet, padding, max_out, text))
        groups[group[0]] = groups.get(group[0], 0) + 1

    policies = [(a, p) for a in (0, 1) for p in (0, 1)]

    # Every 1-byte and 2-byte input under all four policies.
    group[0] = "exhaustive_1_2_byte_encode"
    for a, p in policies:
        for b in range(256):
            enc(bytes([b]), a, p, 64)
        for b in range(256):
            for c in range(256):
                enc(bytes([b, c]), a, p, 64)

    # Sizes 0/1/2/3 and the group boundaries around them.
    group[0] = "group_boundary_encode"
    for size in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13):
        data = bytes(rng.randrange(256) for _ in range(size))
        for a, p in policies:
            enc(data, a, p, 64)

    # Random lengths, including long inputs.
    group[0] = "random_length_encode"
    for _ in range(4000):
        size = rng.choice([rng.randrange(0, 40), rng.randrange(0, 300), rng.randrange(0, 5000)])
        data = rng.randbytes(size)
        a, p = rng.choice(policies)
        enc(data, a, p, 8192)

    # Budget boundaries around the exact requirement.
    group[0] = "encode_budget_boundaries"
    for size in (0, 1, 2, 3, 4, 5, 6, 7, 100, 1000):
        data = rng.randbytes(size)
        for a, p in policies:
            need = encoded_len(size, p)
            for budget in (need - 1, need, need + 1, 0, -1, I64_MIN, I64_MAX):
                enc(data, a, p, budget)

    # Valid round-trips, then mutations of the same texts.
    group[0] = "roundtrip_and_mutations"
    for _ in range(6000):
        size = rng.choice([rng.randrange(0, 8), rng.randrange(0, 64), rng.randrange(0, 600)])
        data = rng.randbytes(size)
        a, p = rng.choice(policies)
        text = expect_encode(data, a, p, MAX_INPUT)[1]
        dec(text, a, p, 8192)
        need = decoded_len(text, p)
        for budget in (need - 1, need, need + 1, 0, -1, I64_MIN, I64_MAX):
            dec(text, a, p, budget)
        if not text:
            continue
        # Single-byte mutations: foreign bytes, the other alphabet, whitespace.
        for _ in range(4):
            at = rng.randrange(len(text))
            for replacement in (b"=", b"+", b"/", b"-", b"_", b" ", b"\t", b"\n", b"\r",
                                b"\x00", b"\xff", b"!", b"0", b"A", b"z"):
                dec(text[:at] + replacement + text[at + 1:], a, p, 8192)
        # Length mutations.
        for cut in (1, 2, 3, 4):
            if len(text) > cut:
                dec(text[:-cut], a, p, 8192)
        dec(text + b"=", a, p, 8192)
        dec(text + b"==", a, p, 8192)
        dec(text + b"A", a, p, 8192)
        dec(text + b"AA", a, p, 8192)
        dec(b"=" + text, a, p, 8192)
        dec(b" " + text, a, p, 8192)
        dec(text + b"\n", a, p, 8192)
        # Non-canonical trailing bits: every value of the unused low bits.
        padlen = padding_of(text) if p == 0 else 0
        body = text[: len(text) - padlen] if padlen else text
        rest = len(body) % 4
        if rest in (2, 3):
            mask = 15 if rest == 2 else 3
            base = value_of(body[-1], a)
            for delta in range(1, mask + 1):
                v = (base & ~mask) | ((base + delta) & mask)
                symbol = (b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"[v]
                          if a == 0 else
                          b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"[v])
                dec(body[:-1] + bytes([symbol]) + text[len(body):], a, p, 8192)

    # Exhaustive short texts over the alphabet plus the interesting outsiders.
    group[0] = "exhaustive_short_decode"
    outsiders = b"=+-_ \t\n\r\x00\xff!."
    for a, p in policies:
        pool = bytes(sorted(ALPHABETS[a])) + outsiders
        for x in pool:
            dec(bytes([x]), a, p, 64)
        for x in pool:
            for y in pool:
                dec(bytes([x, y]), a, p, 64)
        for x in pool:
            for y in pool:
                for z in (b"A", b"B", b"=", b"-", b"_", b" ", b"\x00"):
                    dec(bytes([x, y]) + z, a, p, 64)

    # Whitespace and control bytes at every position of a valid text.
    group[0] = "whitespace_positions"
    for a, p in policies:
        text = expect_encode(b"foobar", a, p, MAX_INPUT)[1]
        for at in range(len(text) + 1):
            for junk in (b" ", b"\t", b"\n", b"\r\n", b"\x0b", b"\x0c", b"\x00"):
                dec(text[:at] + junk + text[at:], a, p, 64)

    # Long valid texts and their truncations.
    group[0] = "long_texts"
    for a, p in policies:
        data = bytes(range(256)) * 64
        text = expect_encode(data, a, p, MAX_INPUT)[1]
        dec(text, a, p, 65536)
        dec(text, a, p, len(data) - 1)
        dec(text[:-1], a, p, 65536)
        dec(text + b"=", a, p, 65536)

    return cases, groups


def main():
    binary = str(Path(sys.argv[1]).resolve())
    cases, groups = build_cases()
    payload = "".join(
        f"{kind}\t{alphabet}\t{padding}\t{max_out}\t{data.hex()}\n"
        for kind, alphabet, padding, max_out, data in cases
    )
    result = subprocess.run([binary], input=payload, text=True, capture_output=True,
                            check=False, timeout=600)
    if result.returncode:
        sys.stderr.write(result.stderr[:4096])
        result.check_returncode()
    lines = result.stdout.splitlines()
    assert len(lines) == len(cases), (len(lines), len(cases), result.stderr[:1000])
    for index, (line, case) in enumerate(zip(lines, cases)):
        kind, alphabet, padding, max_out, data = case
        want_error, want_bytes = (expect_encode(data, alphabet, padding, max_out)
                                  if kind == "E" else
                                  expect_decode(data, alphabet, padding, max_out))
        fields = line.split("\t")
        assert len(fields) == 3, (index, line)
        got_kind, got_error, got_hex = fields
        assert got_kind == kind, (index, line)
        assert got_error == want_error, (index, kind, alphabet, padding, max_out,
                                         data[:64].hex(), got_error, want_error)
        assert got_hex == want_bytes.hex(), (index, kind, alphabet, padding, max_out,
                                             data[:64].hex(), got_hex, want_bytes.hex())
    print(f"Python Base64 oracle: {len(cases)} cases passed")
    for name, count in groups.items():
        print(f"  {name}\t{count}")


if __name__ == "__main__":
    main()
