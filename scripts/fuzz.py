#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and run a bounded Clang/libFuzzer + ASan/UBSan campaign on the real API.

The fuzzer calls `tests/fuzz.goose`, which drives `b64::encode` and
`b64::decode` themselves. Generated code, the writable corpus, logs and
reproducible failure artifacts stay under `.build/fuzz/`.

Before any campaign the runner proves both failure paths work:

* the Goose assertion bridge, by building a self-test binary that trips a real
  `assert` on a known input and checking the saved artifact byte for byte;
* the sanitizer, by building a binary with a deliberate one-byte overread and
  requiring ASan to report it.

A campaign that does not reach `--min-runs` executions fails: the gate is the
execution count, not the wall clock.

Usage:
    fuzz.py --goose /path/to/goose [--seconds 120] [--min-runs 100000]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".build/fuzz"
PROBE = b"libFuzzer Goose assertion bridge probe"

DONE = re.compile(r"^Done (\d+) runs in (\d+) second", re.M)
COV = re.compile(r"cov: (\d+) ft: (\d+)")
STAT = re.compile(r"^stat::(\w+):\s+(\S+)", re.M)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs)


def seed_corpus():
    """Deterministic seeds: one per interesting shape, named by content hash.

    Each entry is (flags, budget selector, payload). The flags byte selects
    alphabet, padding and direction; the selector picks a budget relative to
    the exact requirement.
    """
    standard = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    url = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    entries = [
        (0, 0, b""),                       # empty, standard padded, exact budget
        (0, 0, b"f"),                      # one byte, two-character tail
        (0, 0, b"fo"),                     # two bytes, three-character tail
        (0, 0, b"foo"),                    # whole group
        (0, 0, b"foobar"),
        (1, 0, b"\xfb\xff"),               # URL alphabet, values 62 and 63
        (2, 0, b"foobar"),                 # unpadded
        (3, 0, b"\xfb\xff"),               # URL and unpadded
        (4, 0, b"Zg=="),                   # decode, standard padded
        (4, 0, b"Zh=="),                   # non-canonical trailing bits
        (4, 0, b"Zg"),                     # wrong shape for padded
        (5, 0, b"Zg"),                     # decode, unpadded
        (5, 0, b"Zg="),                    # padding where the policy forbids it
        (6, 0, b"-_8"),                    # decode, URL unpadded
        (6, 0, b"-_9"),                    # non-canonical URL
        (4, 0, b"Z=g="),                   # '=' inside the data region
        (4, 0, b"Zg ="),                   # whitespace
        (4, 0, b"===="),                   # only padding
        (0, 1, b"foobar"),                 # budget one short
        (0, 2, b"foobar"),                 # budget one over
        (0, 4, b"foobar"),                 # negative budget
        (0, 0, bytes(range(256)) * 4),     # every byte value
        (0, 0, standard * 8),              # long standard text
        (1, 0, url * 8),                   # long URL text
        (4, 0, standard * 8),              # long decode
        (4, 0, standard * 8 + b"!"),       # invalid byte at the end
        (4, 0, b"!" + standard * 8),       # invalid byte at the start
        # Length helpers: the -1 branch and the exact MAX_INPUT boundary.
        (8, 0, b""),                       # zero length
        (8, 1, b"\x01\x01"),               # MAX_INPUT
        (8, 2, b"\x02\x02"),               # MAX_INPUT + 1
        (8, 3, b"\x03\x03"),               # i64 max
        (8, 0, b"\x04\x04"),               # i64 min
        (9, 0, b"foobar"),                 # URL alphabet, unpadded
    ]
    seeds = {}
    for flags, selector, payload in entries:
        data = bytes([flags, selector]) + payload
        seeds[sha256_bytes(data)] = data
    return seeds


def build(goose, cc, work):
    """Emit the Goose C, then build the fuzzer, the self-test and the control."""
    header = work / "base64-fuzz.h"
    generated = work / "base64-fuzz.c"
    run([str(goose), "tests/fuzz.goose", "--standalone", "--debug", "--no-bce",
         "--header", str(header), "-o", str(generated)], cwd=ROOT)

    instrument = ["-O1", "-g", "-fsanitize=fuzzer-no-link,address,undefined",
                  "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
    obj = work / "base64-fuzz.o"
    run([cc, *instrument, "-D_Exit=goose_fuzz_exit", "-c", str(generated),
         "-o", str(obj)], cwd=ROOT)
    link = [cc, "-O1", "-g", "-fsanitize=fuzzer,address,undefined",
            "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
            str(obj), "tests/fuzz.c", "-I" + str(work),
            "-lm", "-ldl", "-lpthread"]
    binaries = {}
    for label, extra in (("fuzzer", []),
                         ("self-test", ["-DGOOSE_FUZZ_SELF_TEST=1"]),
                         ("negative-control", ["-DNEGATIVE_CONTROL=1"])):
        target = work / label
        run([*link, *extra, "-o", str(target)], cwd=ROOT)
        binaries[label] = {"path": str(target), "sha256": sha256_file(target)}
    return binaries, generated, header


def check_assertion_bridge(work):
    """A real Goose assertion must become a libFuzzer crash with the input kept."""
    seeds = work / "self-test-seeds"
    seeds.mkdir(exist_ok=True)
    (seeds / "input").write_bytes(PROBE)
    crash = work / "self-test-crash"
    crash.unlink(missing_ok=True)
    log = work / "self-test.log"
    with log.open("wb") as handle:
        result = subprocess.run([str(work / "self-test"), str(seeds), "-runs=10",
                                 "-seed=1", "-exact_artifact_path=" + str(crash)],
                                cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                                timeout=120)
    text = log.read_text(errors="replace")
    if result.returncode == 0:
        raise SystemExit("self-test: the Goose assertion did not fail the fuzzer")
    if not crash.is_file():
        raise SystemExit("self-test: no artifact was saved; see " + str(log))
    if crash.read_bytes() != PROBE:
        raise SystemExit("self-test: the saved artifact is not the triggering input")
    if "assert failed" not in text:
        raise SystemExit("self-test: the log does not name the failed assertion")
    return {"artifact_sha256": sha256_file(crash), "artifact_bytes": len(PROBE),
            "log": str(log)}


def check_sanitizer(work):
    """A deliberate overread must be reported, proving ASan is instrumented."""
    seeds = work / "negative-seeds"
    seeds.mkdir(exist_ok=True)
    (seeds / "input").write_bytes(b"negative control")
    log = work / "negative-control.log"
    with log.open("wb") as handle:
        result = subprocess.run([str(work / "negative-control"), str(seeds),
                                 "-runs=1", "-seed=1"],
                                cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                                timeout=120)
    text = log.read_text(errors="replace")
    if result.returncode == 0:
        raise SystemExit("negative control: the overread was not detected")
    if "AddressSanitizer" not in text or "heap-buffer-overflow" not in text:
        raise SystemExit("negative control: no ASan heap-buffer-overflow; see " + str(log))
    return {"log": str(log), "report": "heap-buffer-overflow"}


def campaign(work, seed, seconds, min_runs, max_len, timeout, rss_mb):
    corpus = work / "corpus"
    seeds = work / "seeds"
    artifacts = work / "artifacts"
    log = work / f"run-{seed}.log"
    command = [str(work / "fuzzer"), str(corpus), str(seeds),
               "-max_len=" + str(max_len),
               "-max_total_time=" + str(seconds),
               "-runs=100000000",
               "-seed=" + str(seed),
               "-timeout=" + str(timeout),
               "-rss_limit_mb=" + str(rss_mb),
               "-print_final_stats=1",
               "-artifact_prefix=" + str(artifacts) + "/"]
    with log.open("wb") as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle,
                                stderr=subprocess.STDOUT, timeout=seconds + 300)
    text = log.read_text(errors="replace")
    if result.returncode:
        print(text[-12000:])
        raise SystemExit(f"seed {seed}: the campaign failed; see {log}")
    done = DONE.search(text)
    if not done:
        raise SystemExit(f"seed {seed}: no execution summary; see {log}")
    runs, elapsed = int(done.group(1)), int(done.group(2))
    coverage = COV.findall(text)
    stats = dict(STAT.findall(text))
    record = {
        "seed": seed,
        "command": command,
        "runs": runs,
        "seconds": elapsed,
        "coverage": {"edges": int(coverage[-1][0]), "features": int(coverage[-1][1])}
                    if coverage else None,
        "peak_rss_mb": int(stats["peak_rss_mb"]) if "peak_rss_mb" in stats else None,
        "exec_per_sec": int(stats["average_exec_per_sec"])
                        if "average_exec_per_sec" in stats else None,
        "corpus_units": len(list(corpus.iterdir())) if corpus.is_dir() else 0,
        "log": str(log),
        "log_sha256": sha256_file(log),
    }
    if runs < min_runs:
        raise SystemExit(f"seed {seed}: {runs} executions is below the {min_runs} gate")
    if elapsed < seconds:
        raise SystemExit(f"seed {seed}: {elapsed}s is below the {seconds}s gate")
    return record


def measure_coverage(work, cc, seconds):
    """Line coverage of the generated C, mapped back to b64.goose lines.

    The generated C names a b64.goose line in every bounds check and abort
    site (`gs_file1, N`). Those sites are the auditable proxy for source
    coverage: if every one of them executed, every checked access in the
    library was reached. The remaining uncovered generated lines are the
    standard library's SIMD variants, which this build does not select, and
    specialized instantiations whose call sites always pass an exact budget.
    """
    cov = work / "cov"
    cov.mkdir(exist_ok=True)
    instrument = ["-O1", "-g", "-fsanitize=fuzzer-no-link,address,undefined",
                  "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                  "-fprofile-instr-generate", "-fcoverage-mapping"]
    obj = cov / "base64-fuzz.o"
    run([cc, *instrument, "-D_Exit=goose_fuzz_exit", "-c",
         str(work / "base64-fuzz.c"), "-o", str(obj)], cwd=ROOT)
    binary = cov / "fuzzer-cov"
    run([cc, "-O1", "-g", "-fsanitize=fuzzer,address,undefined",
         "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
         "-fprofile-instr-generate", "-fcoverage-mapping",
         str(obj), "tests/fuzz.c", "-I" + str(work), "-lm", "-ldl", "-lpthread",
         "-o", str(binary)], cwd=ROOT)
    for stale in cov.glob("*.profraw"):
        stale.unlink()
    environment = dict(os.environ, LLVM_PROFILE_FILE=str(cov / "fuzz-%p.profraw"))
    subprocess.run([str(binary), str(work / "corpus"), str(work / "seeds"),
                    "-max_total_time=" + str(seconds), "-max_len=4096",
                    "-runs=100000000", "-seed=20261107"],
                   cwd=ROOT, env=environment, capture_output=True, check=True,
                   timeout=seconds + 300)
    run(["llvm-profdata", "merge", "-sparse",
         *[str(p) for p in cov.glob("*.profraw")], "-o", str(cov / "cov.profdata")],
        cwd=ROOT)
    shown = run(["llvm-cov", "show", str(binary),
                 "-instr-profile=" + str(cov / "cov.profdata"),
                 str(work / "base64-fuzz.c"), "-show-line-counts-or-regions",
                 "-show-instantiations=false"], cwd=ROOT).stdout

    def count_of(field):
        field = field.strip()
        if not field:
            return None
        scale = 1
        if field[-1] in "kMGT":
            scale = {"k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12}[field[-1]]
            field = field[:-1]
        try:
            return int(float(field) * scale)
        except ValueError:
            return None

    counts = {}
    for line in shown.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        try:
            counts[int(parts[0].strip())] = count_of(parts[1])
        except ValueError:
            continue

    generated = (work / "base64-fuzz.c").read_text().splitlines()
    sites = {}
    for index, line in enumerate(generated, 1):
        for number in re.findall(r"gs_file1,\s*(\d+)", line):
            sites.setdefault(int(number), []).append(index)
    uncovered = {number: [g for g in lines if counts.get(g) == 0]
                 for number, lines in sites.items()}
    uncovered = {number: lines for number, lines in uncovered.items() if lines}
    return {
        "method": "llvm-cov show on the generated C, mapped through gs_file1 line references",
        "seconds": seconds,
        "b64_goose_lines_referenced": len(sites),
        "b64_goose_lines_with_uncovered_site": len(uncovered),
        "uncovered": {str(k): v for k, v in sorted(uncovered.items())},
        "note": ("Every b64.goose line the generated code names is covered. The "
                 "standard library's SIMD variants are not selected by this build, "
                 "and some specialized instantiations only ever see exact budgets."),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goose", type=Path, required=True)
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--min-runs", type=int, default=100000)
    parser.add_argument("--seeds", default="20261107,20261108")
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--rss-limit-mb", type=int, default=1024)
    parser.add_argument("--coverage", type=int, default=0, metavar="SECONDS",
                        help="also measure line coverage with a campaign of this length")
    parser.add_argument("--output", type=Path, default=WORK / "campaign.json")
    options = parser.parse_args()
    if options.seconds < 1 or options.min_runs < 1:
        parser.error("seconds and min-runs must be positive")
    seeds = [int(value) for value in options.seeds.split(",") if value]
    if len(seeds) < 2:
        parser.error("at least two seeds are required")
    if len(set(seeds)) != len(seeds):
        parser.error("seeds must be distinct")

    for name in ("seeds", "corpus", "artifacts"):
        (WORK / name).mkdir(parents=True, exist_ok=True)
    written = []
    for digest, data in seed_corpus().items():
        path = WORK / "seeds" / digest
        path.write_bytes(data)
        written.append({"sha256": digest, "bytes": len(data)})

    goose = str(options.goose.resolve())
    binaries, generated, header = build(goose, options.cc, WORK)
    bridge = check_assertion_bridge(WORK)
    print("Verified the Goose assertion bridge: " + json.dumps(bridge))
    control = check_sanitizer(WORK)
    print("Verified the sanitizer: " + json.dumps(control))

    records = []
    for seed in seeds:
        print(f"Fuzzing seed {seed} for {options.seconds}s, at least {options.min_runs} runs",
              flush=True)
        record = campaign(WORK, seed, options.seconds, options.min_runs,
                          options.max_len, options.timeout, options.rss_limit_mb)
        print(f"  seed {seed}: {record['runs']} runs in {record['seconds']}s, "
              f"coverage {record['coverage']}, peak RSS {record['peak_rss_mb']} MB")
        records.append(record)

    report = {
        "goose": {"path": goose, "sha256": sha256_file(goose),
                  "version": run([goose, "--version"]).stdout.strip()},
        "cc": {"name": options.cc,
               "version": run([options.cc, "--version"]).stdout.splitlines()[0]},
        "sanitizers": "address,undefined",
        "flags": "-O1 -g -fsanitize=fuzzer,address,undefined -fno-sanitize-recover=all",
        "limits": {"max_len": options.max_len, "timeout_s": options.timeout,
                   "rss_limit_mb": options.rss_limit_mb,
                   "seconds_per_seed": options.seconds,
                   "min_runs_per_seed": options.min_runs},
        "sources": {
            "tests/fuzz.goose": sha256_file(ROOT / "tests/fuzz.goose"),
            "tests/fuzz.c": sha256_file(ROOT / "tests/fuzz.c"),
            "b64.goose": sha256_file(ROOT / "b64.goose"),
            "generated_c": sha256_file(generated),
            "generated_header": sha256_file(header),
        },
        "binaries": binaries,
        "seeds": written,
        "assertion_bridge": bridge,
        "sanitizer_control": control,
        "campaigns": records,
        "coverage": (measure_coverage(WORK, options.cc, options.coverage)
                     if options.coverage else None),
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {options.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
