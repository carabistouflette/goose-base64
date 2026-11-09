#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mutation-test the guarantees this library claims.

Each mutant is a single edit to `b64.goose` that breaks one documented
guarantee while still compiling. The suite must pass on the pristine tree and
fail on every mutant; a mutant that survives is a gap in the tests, not
evidence of stability, and this script exits non-zero for it.

Every mutant runs in its own copy of the tracked tree under
`.build/mutation/`, so the working tree is never modified. The record keeps the
diff, the SHA-256 of the mutated source, the exact command and the diagnostic.

Usage:
    mutation-test.py --goose /path/to/goose [--only NAME]
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".build/mutation"

# Each entry breaks one guarantee. `old` must occur exactly once in b64.goose.
MUTANTS = [
    {
        "name": "url_rewrite_ignores_alphabet",
        "guarantee": "the alphabet and the padding policy are independent",
        "why": ("Rewrites '+' and '/' to '-' and '_' whatever the alphabet, which "
                "is the historical bug: standard/unpadded would emit URL text."),
        "old": "    if policy.alphabet == Alphabet.Url {\n"
               "        for i in start..start + full / 3 * 4 {",
        "new": "    if true {\n"
               "        for i in start..start + full / 3 * 4 {",
    },
    {
        "name": "canonicality_check_removed",
        "guarantee": "non-canonical trailing bits are rejected (RFC 4648 §3.5)",
        "why": "Drops the two-character-tail check, so 'Zh==' decodes like 'Zg=='.",
        "old": "        if (value_of(src[body - 1], policy.alphabet) & 15) != 0 { return Error.NonCanonical; }",
        "new": "        if false { return Error.NonCanonical; }",
    },
    {
        "name": "trailing_bit_mask_too_narrow",
        "guarantee": "exactly 4 of 64 final characters are canonical for a 2-char tail",
        "why": "Masks 3 bits instead of 4, so 8 final characters are accepted.",
        "old": "        if (value_of(src[body - 1], policy.alphabet) & 15) != 0 { return Error.NonCanonical; }",
        "new": "        if (value_of(src[body - 1], policy.alphabet) & 7) != 0 { return Error.NonCanonical; }",
    },
    {
        "name": "decode_budget_off_by_one",
        "guarantee": "the exact requirement is accepted and one byte less is not",
        "why": "Uses >= instead of >, so a budget equal to the requirement is refused.",
        "old": "    if need < 0 { return Error.InvalidLength; }\n"
               "    if need > policy.max_out { return Error.OutputBudget; }",
        "new": "    if need < 0 { return Error.InvalidLength; }\n"
               "    if need >= policy.max_out { return Error.OutputBudget; }",
    },
    {
        "name": "padding_precedence_lost",
        "guarantee": "a '=' inside the data region is InvalidPadding, not InvalidCharacter",
        "why": "Removes the '=' test from the validation loop, so '=' falls through to the alphabet test.",
        "old": "        if c == '=' { return Error.InvalidPadding; }",
        "new": "        if false { return Error.InvalidPadding; }",
    },
    {
        "name": "unpadded_policy_always_pads",
        "guarantee": "Padding.Unpadded writes no '=' and appends the exact count",
        "why": "Pads regardless of the policy, so unpadded output is four characters per group.",
        "old": "        if policy.padding == Padding.Padded {\n"
               "            out.push('=');\n"
               "            if rest == 1 { out.push('='); }\n"
               "        }",
        "new": "        if true {\n"
               "            out.push('=');\n"
               "            if rest == 1 { out.push('='); }\n"
               "        }",
    },
    {
        "name": "unpadded_single_character_accepted",
        "guarantee": "one leftover character is InvalidLength under Unpadded",
        "why": "Returns a length instead of -1 for a 4k+1 text, so 'A' looks decodable.",
        "old": "    if rest == 1 { return -1; }",
        "new": "    if rest == 1 { return n / 4 * 3; }",
    },
    {
        "name": "padding_run_capped_at_one",
        "guarantee": "a two-character '=' run is recognised and sized correctly",
        "why": "Caps padding_of at one, so 'Zg==' becomes InvalidLength.",
        "old": "    if n >= 2 && src[n - 2] == '=' { return 2; }",
        "new": "    if n >= 2 && src[n - 2] == '=' { return 1; }",
    },
    {
        "name": "alphabets_not_separated",
        "guarantee": "each alphabet rejects the other's two extra characters",
        "why": ("Resolves every byte through the standard table, so the URL "
                "alphabet accepts '+' and '/' and rejects '-' and '_'."),
        "old": "    if alphabet == Alphabet.Standard { return STANDARD_VALUES[c]; }\n"
               "    return URL_VALUES[c];",
        "new": "    return STANDARD_VALUES[c];",
    },
    {
        "name": "table_entry_outside_alphabet_accepted",
        "guarantee": "a byte outside the selected alphabet is InvalidCharacter",
        "why": ("Maps '@' to 0 in the standard table, so a byte that is in "
                "neither alphabet decodes as a zero sextet. '@' is outside every "
                "pool the differential corpus draws from, so only the exhaustive "
                "per-byte test can see this."),
        "old": "    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 62, 255, 255, 255, 63,\n"
               "    52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 255, 255, 255, 255, 255, 255,\n"
               "    255, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,",
        "new": "    255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 62, 255, 255, 255, 63,\n"
               "    52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 255, 255, 255, 255, 255, 255,\n"
               "    0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,",
    },
]


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_tree(target):
    """Copy the tracked tree, so a mutant never touches the working tree."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    for name in listing.split(b"\0"):
        if not name:
            continue
        relative = name.decode()
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)


def run_suite(directory, goose):
    """Run the primary gate and return (passed, output)."""
    result = subprocess.run(["make", "test", "GOOSE=" + str(goose)],
                            cwd=directory, capture_output=True, text=True,
                            timeout=1800)
    return result.returncode == 0, result.stdout + result.stderr


def diagnostic(output):
    """The most specific failure line the run produced."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for marker in ("assert failed", "error:", "FAIL:", "Traceback"):
        for line in reversed(lines):
            if marker in line:
                return line[:400]
    return lines[-1][:400] if lines else ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goose", type=Path, required=True)
    parser.add_argument("--only", help="run one mutant by name")
    parser.add_argument("--output", type=Path, default=WORK / "mutation.json")
    options = parser.parse_args()
    goose = options.goose.resolve()
    source = (ROOT / "b64.goose").read_text()

    selected = [m for m in MUTANTS if not options.only or m["name"] == options.only]
    if not selected:
        raise SystemExit(f"no mutant named {options.only}")
    for mutant in selected:
        if source.count(mutant["old"]) != 1:
            raise SystemExit(f"{mutant['name']}: the edit site occurs "
                             f"{source.count(mutant['old'])} times, not once")

    WORK.mkdir(parents=True, exist_ok=True)

    # The suite must pass on the pristine tree, or a mutant's failure proves
    # nothing.
    pristine = WORK / "pristine"
    copy_tree(pristine)
    passed, output = run_suite(pristine, goose)
    if not passed:
        print(output[-4000:])
        raise SystemExit("the suite does not pass on the pristine tree")
    print("pristine: the suite passes")

    records = []
    survivors = []
    for mutant in selected:
        directory = WORK / mutant["name"]
        copy_tree(directory)
        mutated = source.replace(mutant["old"], mutant["new"])
        (directory / "b64.goose").write_text(mutated)
        passed, output = run_suite(directory, goose)
        record = {
            "name": mutant["name"],
            "guarantee": mutant["guarantee"],
            "why": mutant["why"],
            "diff": f"--- b64.goose\n+++ b64.goose (mutant)\n-{mutant['old']}\n+{mutant['new']}",
            "mutated_b64_sha256": sha256_file(directory / "b64.goose"),
            "command": f"make test GOOSE={goose}  (cwd {directory})",
            "detected": not passed,
            "diagnostic": diagnostic(output),
        }
        records.append(record)
        if passed:
            survivors.append(mutant["name"])
            print(f"  SURVIVED {mutant['name']}: the suite still passes")
        else:
            print(f"  killed   {mutant['name']}: {record['diagnostic'][:120]}")

    report = {
        "goose": {"path": str(goose), "sha256": sha256_file(goose),
                  "version": subprocess.run([str(goose), "--version"],
                                            capture_output=True, text=True).stdout.strip()},
        "pristine_b64_sha256": sha256_file(ROOT / "b64.goose"),
        "pristine_passes": True,
        "mutants": records,
        "survivors": survivors,
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {options.output}")
    if survivors:
        raise SystemExit(f"{len(survivors)} mutant(s) survived: {', '.join(survivors)}")
    print(f"all {len(records)} mutants detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
