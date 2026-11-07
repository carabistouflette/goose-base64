#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record warmed benchmark samples with full provenance.

This recorder asserts structure and checksums, never timings. It pins the
process to one CPU, discards one warmup process, and reports medians of the
remaining process averages. Ratios are computed only for rows the harness marks
`comparable`, where both implementations do the same work.

Usage: measure.py --binary .build/bench --iterations 1000 [--samples 8]
"""
import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from pathlib import Path

if not __debug__:
    raise SystemExit("Do not run with -O: assertions are required")

COLUMNS = 8


def git(*args):
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
             "tests/oracle.goose", "tests/oracle.py"]
    return {
        "repo_root": str(root),
        "repo_root_is_library": root == here,
        "source_revision": git("rev-parse", "HEAD"),
        "source_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                          for name in files},
        "dirty": bool(git("status", "--porcelain")),
    }


def cpu_model():
    path = Path("/proc/cpuinfo")
    if not path.exists():
        return platform.processor() or "unknown"
    for line in path.read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=21)
    parser.add_argument("--output", default=".build/benchmark.json")
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

    samples = {}
    checksums = set()
    for sample in range(options.samples):
        result = subprocess.run([binary, str(options.iterations)], capture_output=True,
                                text=True, check=True, timeout=1800)
        rows = [line.split("\t") for line in result.stdout.splitlines()]
        assert rows, result.stdout
        assert rows[-1][0] == "checksum" and len(rows[-1]) == 3, rows[-1]
        checksums.add((int(rows[-1][1]), int(rows[-1][2])))
        for row in rows[:-1]:
            assert len(row) == COLUMNS, row
            phase, fixture, implementation, elapsed, count, input_len, output_len, comparable = row
            assert phase in ("encode", "decode", "reject"), row
            assert implementation in ("b64", "stdlib", "b64_fresh", "stdlib_fresh"), row
            assert comparable in ("0", "1"), row
            assert int(count) == options.iterations, row
            assert int(elapsed) >= 0 and int(input_len) >= 0 and int(output_len) >= 0, row
            key = (phase, fixture, implementation)
            if sample:
                samples.setdefault(key, []).append(int(elapsed))
    # The checksum must be identical across processes: the work is deterministic.
    assert len(checksums) == 1, checksums

    medians = {key: statistics.median(values) / options.iterations
               for key, values in samples.items()}
    comparable = {}
    for row in rows[:-1]:
        phase, fixture, implementation, _, _, _, _, flag = row
        if flag == "1":
            comparable[(phase, fixture, implementation)] = True
    ratios = {}
    for (phase, fixture, implementation), value in medians.items():
        if not comparable.get((phase, fixture, implementation)):
            continue
        if implementation != "b64":
            continue
        other = medians.get((phase, fixture, "stdlib"))
        if other:
            ratios[f"{phase}/{fixture}"] = value / other

    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu_model(),
        "affinity_cpu": cpu,
        "iterations": options.iterations,
        "samples": options.samples,
        "measured_samples": options.samples - 1,
        "warmup_processes": 1,
        "compiler_revision": Path("GOOSE_REVISION").read_text().strip(),
        "cc": os.environ.get("BENCH_CC", "gcc"),
        "cc_version": subprocess.check_output(
            [os.environ.get("BENCH_CC", "gcc"), "--version"], text=True).splitlines()[0],
        "flags": "goose build -O2",
        "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        **source_identity(),
        "checksum": checksums.pop(),
        "raw_ns": {f"{p}/{f}/{i}": v for (p, f, i), v in sorted(samples.items())},
        "median_ns_per_operation": {f"{p}/{f}/{i}": v for (p, f, i), v in sorted(medians.items())},
        "b64_over_stdlib": dict(sorted(ratios.items())),
        "scope": (
            "Warm process medians of repeated calls on prebuilt inputs. Reused-buffer rows "
            "amortise allocation; *_fresh rows allocate per call. Reject rows are not equal "
            "work and carry no ratio. Not cold latency, not a universal ranking, and not "
            "measured under exclusive CPU isolation."
        ),
    }
    Path(options.output).write_text(json.dumps(report, indent=2) + "\n")
    for name, value in report["median_ns_per_operation"].items():
        print(f"{name}\t{value:.2f} ns/op")
    for name, value in report["b64_over_stdlib"].items():
        print(f"ratio {name}\t{value:.3f}x")
    print(f"wrote {options.output}")


if __name__ == "__main__":
    main()
