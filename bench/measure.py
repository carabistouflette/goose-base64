#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record warmed benchmark samples with full provenance.

This recorder asserts structure and content, and reports timings. It pins the
process to one CPU, discards one warmup sample, and reports dispersion over the
remaining measured samples.

Each sample runs the harness once per implementation, and the order in which the
implementations are run alternates between samples. That removes the systematic
bias of always measuring one implementation first, which would otherwise charge
the first one for cold caches and frequency ramp-up.

Ratios are computed only where the harness marks both rows `comparable`, which
is where both implementations do the same work. The standard library rows are
recorded but never produce a ratio: that codec is permissive, so it does
strictly less work and is reported as a lower bound, not as a fair race.

Usage:
  measure.py --binary .build/bench --iterations 1000 [--samples 21]
"""
import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
from pathlib import Path

if not __debug__:
    raise SystemExit("Do not run with -O: assertions are required")

COLUMNS = 9
PHASES = ("encode", "decode", "reject", "pathological", "consumer")
IMPLEMENTATIONS = ("b64", "strict", "stdlib", "b64_fresh", "strict_fresh", "stdlib_fresh")
# Only these pairs do the same work, so only these pairs produce a ratio.
COMPARABLE_PAIRS = (("b64", "strict"), ("b64_fresh", "strict_fresh"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    import subprocess
    return subprocess.check_output(["git", *args], text=True).strip()


def source_identity():
    """Identify the sources actually measured.

    This directory may be nested inside another repository, so the enclosing
    HEAD is not the identity of the code under test. Record the repository root
    that Git resolves here, its HEAD, and the SHA-256 of every measured source
    file; a mismatch between the root and this directory is visible in the
    record instead of being silently attributed to the wrong commit.
    """
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    here = Path.cwd().resolve()
    files = ["b64.goose", "GOOSE_REVISION", "bench/bench.goose", "bench/measure.py",
             "bench/strict.goose", "bench/strict_equivalence.goose",
             "tests/oracle.goose", "tests/oracle.py"]
    return {
        "repo_root": str(root),
        "repo_root_is_library": root == here,
        "source_revision": git("rev-parse", "HEAD"),
        "source_sha256": {name: sha256(name) for name in files},
        "dirty": bool(git("status", "--porcelain")),
    }


def competitor_identity(goose_binary):
    """The pinned standard library this comparison is made against.

    The standard library ships beside the compiler, not in this repository, so
    it is located from the compiler path and hashed in place. Nothing is copied:
    the recorded hashes identify exactly which codec was raced.
    """
    stdlib = Path(goose_binary).resolve().parent.parent / "stdlib"
    files = ["base64.goose", "std.goose"]
    identity = {"stdlib_dir": str(stdlib)}
    for name in files:
        path = stdlib / name
        identity[name] = sha256(path) if path.exists() else None
    return identity


def runtime_identity(goose_binary):
    """The runtime is inlined into the generated C, so hash its headers.

    There is no shared libgoose: the generated C includes these headers
    directly, so their hashes are part of the identity of the measured binary.
    They ship with the compiler, not in this repository.
    """
    root = Path(goose_binary).resolve().parent.parent
    headers = sorted((root / "src" / "runtime").glob("*.h"))
    headers.append(root / "src" / "runtime_inline.h")
    return {path.name: sha256(path) for path in headers if path.exists()}


def cpu_model():
    path = Path("/proc/cpuinfo")
    if not path.exists():
        return platform.processor() or "unknown"
    for line in path.read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def run_harness(binary, iterations, implementation):
    """Run one implementation and return (stdout, peak RSS in KiB).

    `os.wait4` reports the child's own `ru_maxrss`, so the memory figure belongs
    to this implementation instead of being the maximum over every child.
    """
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child
        try:
            os.close(read_fd)
            os.dup2(write_fd, 1)
            os.close(write_fd)
            os.execv(binary, [binary, str(iterations), implementation])
        finally:
            os._exit(127)
    os.close(write_fd)
    chunks = []
    while True:
        block = os.read(read_fd, 1 << 16)
        if not block:
            break
        chunks.append(block)
    os.close(read_fd)
    _, status, usage = os.wait4(pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise SystemExit(f"harness failed for {implementation}: status {status}")
    return b"".join(chunks).decode(), usage.ru_maxrss


def parse(stdout, iterations, implementation):
    """Parse one harness run into {(phase, fixture): record}."""
    rows = [line.split("\t") for line in stdout.splitlines() if line.strip()]
    assert rows, "empty harness output"
    assert rows[-1][0] == "checksum" and len(rows[-1]) == 2, rows[-1]
    work = int(rows[-1][1])
    records = {}
    for row in rows[:-1]:
        assert len(row) == COLUMNS, row
        phase, fixture, impl, elapsed, count, input_len, output_len, comparable, checksum = row
        assert phase in PHASES, row
        assert impl == implementation, row
        assert comparable in ("0", "1"), row
        assert int(count) == iterations, row
        assert int(elapsed) >= 0, row
        assert int(input_len) >= 0 and int(output_len) >= 0, row
        key = (phase, fixture)
        assert key not in records, f"duplicate row {key}"
        records[key] = {
            "elapsed_ns": int(elapsed),
            "input_len": int(input_len),
            "output_len": int(output_len),
            "comparable": int(comparable),
            "checksum": int(checksum),
        }
    return records, work


def dispersion(values):
    ordered = sorted(values)
    median = statistics.median(ordered)
    deviations = sorted(abs(value - median) for value in ordered)
    return {
        "n": len(ordered),
        "median": median,
        "mean": statistics.fmean(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "p10": ordered[max(0, int(round(0.10 * (len(ordered) - 1))))],
        "p90": ordered[max(0, int(round(0.90 * (len(ordered) - 1))))],
        "iqr": ordered[max(0, int(round(0.75 * (len(ordered) - 1))))]
               - ordered[max(0, int(round(0.25 * (len(ordered) - 1))))],
        "mad": statistics.median(deviations),
        "stdev": statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
        "cv": (statistics.stdev(ordered) / statistics.fmean(ordered))
              if len(ordered) > 1 and statistics.fmean(ordered) else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=21)
    parser.add_argument("--output", default=".build/benchmark.json")
    parser.add_argument("--goose", default=os.environ.get("GOOSE", "goose"))
    options = parser.parse_args()
    if not 1 <= options.iterations <= 10_000_000:
        raise SystemExit("iterations must be in 1..10000000")
    if options.samples < 21:
        raise SystemExit("samples must be at least 21: one warmup plus 20 measured runs")
    binary = str(Path(options.binary).resolve())

    cpu = None
    if hasattr(os, "sched_getaffinity"):
        cpu = min(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {cpu})

    # samples[implementation][(phase, fixture)] -> list of elapsed ns
    samples = {impl: {} for impl in IMPLEMENTATIONS}
    memory = {impl: [] for impl in IMPLEMENTATIONS}
    work = {impl: [] for impl in IMPLEMENTATIONS}
    content = {}  # (phase, fixture, implementation) -> (input_len, output_len, checksum)
    order_log = []

    for sample in range(options.samples):
        # Alternate the order so no implementation is always measured first.
        order = IMPLEMENTATIONS if sample % 2 == 0 else tuple(reversed(IMPLEMENTATIONS))
        order_log.append(list(order))
        for implementation in order:
            stdout, peak_rss = run_harness(binary, options.iterations, implementation)
            records, work_done = parse(stdout, options.iterations, implementation)
            work[implementation].append(work_done)
            if sample:
                memory[implementation].append(peak_rss)
            for key, record in records.items():
                identity = (key[0], key[1], implementation)
                value = (record["input_len"], record["output_len"], record["checksum"])
                if identity in content:
                    assert content[identity] == value, (
                        f"content changed between samples for {identity}: "
                        f"{content[identity]} != {value}")
                else:
                    content[identity] = value
                if sample:
                    samples[implementation].setdefault(key, []).append(record["elapsed_ns"])

    # Equal contract: b64 and strict must produce the same bytes for every
    # fixture, and the standard library must agree wherever it does the same
    # work. A mismatch here invalidates the comparison, so it is fatal.
    for phase, fixture in {(key[0], key[1]) for key in content}:
        mine = content.get((phase, fixture, "b64"))
        theirs = content.get((phase, fixture, "strict"))
        assert mine is not None and theirs is not None, (phase, fixture)
        assert mine == theirs, f"b64 and strict disagree on {phase}/{fixture}: {mine} != {theirs}"
    for phase, fixture in {(key[0], key[1]) for key in content}:
        mine = content.get((phase, fixture, "b64"))
        plain = content.get((phase, fixture, "stdlib"))
        if plain is None:
            continue
        if mine[1] != plain[1] or mine[2] != plain[2]:
            # Expected only where the standard library is more permissive.
            assert phase == "reject", (
                f"stdlib disagrees with b64 on a non-reject fixture {phase}/{fixture}: "
                f"{mine} != {plain}")

    per_operation = {}
    for implementation, by_fixture in samples.items():
        for (phase, fixture), values in by_fixture.items():
            per_operation[f"{phase}/{fixture}/{implementation}"] = dispersion(
                [value / options.iterations for value in values])

    ratios = {}
    paired = {}
    for left, right in COMPARABLE_PAIRS:
        for (phase, fixture) in samples[left]:
            if (phase, fixture) not in samples[right]:
                continue
            if not content[(phase, fixture, left)][1] == content[(phase, fixture, right)][1]:
                continue
            left_values = samples[left][(phase, fixture)]
            right_values = samples[right][(phase, fixture)]
            ratios[f"{phase}/{fixture}/{left}_over_{right}"] = (
                statistics.median(left_values) / statistics.median(right_values))
            pairs = [a / b for a, b in zip(left_values, right_values) if b]
            paired[f"{phase}/{fixture}/{left}_over_{right}"] = dispersion(pairs)

    # The standard library is recorded but never ranked: it is permissive, so it
    # does less work. Report the gap and label it, do not call it a ratio.
    lower_bound = {}
    for (phase, fixture) in samples["b64"]:
        if (phase, fixture) not in samples["stdlib"]:
            continue
        lower_bound[f"{phase}/{fixture}"] = (
            statistics.median(samples["b64"][(phase, fixture)])
            / statistics.median(samples["stdlib"][(phase, fixture)]))

    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu_model(),
        "affinity_cpu": cpu,
        "python": sys.version.split()[0],
        "iterations": options.iterations,
        "samples": options.samples,
        "measured_samples": options.samples - 1,
        "warmup_samples": 1,
        "order_policy": "implementations alternate forward/reverse between samples",
        "order_log": order_log,
        "compiler_revision": Path("GOOSE_REVISION").read_text().strip(),
        "compiler_binary": str(Path(options.goose).resolve()),
        "compiler_binary_sha256": sha256(options.goose),
        "cc": os.environ.get("BENCH_CC", "gcc"),
        "cc_version": __import__("subprocess").check_output(
            [os.environ.get("BENCH_CC", "gcc"), "--version"], text=True).splitlines()[0],
        "flags": "goose build -O2",
        "binary_sha256": sha256(binary),
        **source_identity(),
        "competitor_sha256": competitor_identity(options.goose),
        "runtime_sha256": runtime_identity(options.goose),
        "content": {f"{p}/{f}/{i}": list(v) for (p, f, i), v in sorted(content.items())},
        "work_checksum": {impl: sorted(set(values)) for impl, values in work.items()},
        "peak_rss_kib": {impl: dispersion(values) for impl, values in memory.items() if values},
        "raw_ns": {f"{phase}/{fixture}/{implementation}": values
                   for implementation, by_fixture in sorted(samples.items())
                   for (phase, fixture), values in sorted(by_fixture.items())},
        "ns_per_operation": dict(sorted(per_operation.items())),
        "ratio_b64_over_strict": dict(sorted(ratios.items())),
        "ratio_paired": dict(sorted(paired.items())),
        "stdlib_lower_bound_not_classable": dict(sorted(lower_bound.items())),
        "scope": (
            "Warm medians of repeated calls on prebuilt inputs, one process per "
            "implementation per sample, order alternated between samples. "
            "Reused-buffer rows amortise allocation; *_fresh rows allocate per call. "
            "Only b64/strict pairs are ratios: both implement the same contract, "
            "proved byte for byte by bench/strict_equivalence.goose and re-checked "
            "here from the content checksums. The stdlib column is permissive (no "
            "URL alphabet, no unpadded text, no canonicality check, no budget), so "
            "it does less work and is reported as a lower bound only. Not cold "
            "latency, not a universal ranking, and not measured under exclusive "
            "CPU isolation."
        ),
    }
    Path(options.output).write_text(json.dumps(report, indent=2) + "\n")
    for name, value in report["ratio_b64_over_strict"].items():
        print(f"ratio {name}\t{value:.3f}x")
    for name, value in report["stdlib_lower_bound_not_classable"].items():
        print(f"lower bound (not classable) {name}\t{value:.3f}x")
    print(f"wrote {options.output}")


if __name__ == "__main__":
    main()
