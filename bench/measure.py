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

## The CPU and the contention gate

The measured CPU is chosen once, before any sample, and every implementation of
every campaign runs on that same CPU. It is never re-chosen per implementation:
a per-implementation choice would let the fastest row be the one that happened
to land on the quietest core.

The gate replaces the earlier absolute one-minute load-average limit of 0.5.
That limit cannot be satisfied on a multicore host that is busy elsewhere, and
it never demonstrated contention on the CPU actually being measured. The gate
here measures the thing that matters, in four parts, and records all of it:

  1. `--cpu` busy fraction over a 2 s window, read from `/proc/stat`, must be at
     most `--max-cpu-busy` (default 0.30). This is an absolute ceiling: it
     catches a genuinely loaded core.
  2. The same busy fraction must be within `--cpu-margin` (default 0.05) of the
     least busy CPU. This is the criterion that actually decides, and it is
     relative on purpose. On this host every core carries the desktop's own
     work, so the floor is around 0.11 and an absolute threshold of 0.10 is
     unsatisfiable even on an otherwise idle machine. What matters is that the
     measured core is as quiet as the quietest one available, not that it is
     quiet in the abstract.
  3. `/proc/pressure/cpu` `some avg60` must be at most `--max-psi` (default 5.0).
  4. A jitter calibration: the harness is run `--calibration-runs` times on the
     chosen CPU, and the coefficient of variation of the per-call time of one
     fixed fixture must be at most `--max-jitter`. This is the
     effective-contention test: a co-tenant on the same core raises it even when
     the busy fraction looks low, and it is the direct measurement that the
     busy fraction only approximates. Each calibration run is long enough
     (`--calibration-iterations`, default 2000, about 1.4 ms of work) that the
     coefficient of variation is an estimate of the noise rather than of one
     scheduling hiccup; a 200-iteration window was too short to be either.

The `--max-jitter` default of 0.10 is a practical resolution threshold, not a
statistical guarantee. It was set so that a campaign on a host with a few
percent of run-to-run noise still runs, and it is justified only in this sense:
at 20 paired samples, a 10% coefficient of variation is small enough that a
difference of roughly 20% or more is usually visible in the paired medians.
That is a rule of thumb. The standard error of a sample median is not
`cv/sqrt(n)` in general, and a 10% jitter does not by itself guarantee that the
bootstrap interval on a ratio will be narrow. The interval is reported for every
paired entry, together with a `resolved` flag that is true only when the
interval excludes 1.0; that interval, not the gate, is what a claim rests on.

A run that fails the gate is refused. `--exploratory` records it anyway and
labels the report `exploratory`, which is a diagnostic and not evidence.

## Identity, before and after

Every identity the report names is captured twice: once before the first sample
and once after the last. That covers the measured sources, the compiler binary,
the runtime headers, the pinned standard library, the external comparators, the
harness sources, the ISA feature set, and the SHA-256 of every target binary --
including a frozen baseline raced under `--alias`. If anything differs between
the two snapshots the raw observations are kept but the report's `status` is
`rejected`: a campaign whose inputs changed underneath it is not evidence.

The gate and the calibration are also taken at both ends. They characterise the
start and the end of the measurement window, not every instant inside it; a
quiet start and a quiet end do not prove the middle was quiet. That is a limit
of the endpoint design and is recorded as one.

The old protocol is kept in `docs/benchmark-protocol.md` so the change is
visible rather than silent.

Usage:
  measure.py --binary .build/bench --iterations 1000 [--samples 21]
             [--cpu N] [--external-binary .build/bench-ext]
"""
import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

if not __debug__:
    raise SystemExit("Do not run with -O: assertions are required")

COLUMNS = 9
PHASES = ("encode", "decode", "reject", "pathological", "consumer")
# Implementations the Goose harness knows.
GOOSE_IMPLEMENTATIONS = ("b64", "strict", "stdlib", "b64_accel", "b64_fresh",
                         "strict_fresh", "stdlib_fresh", "b64_accel_fresh")
# Implementations the external harness knows (bench/ext/bench_ext.cpp).
EXTERNAL_IMPLEMENTATIONS = ("simdutf", "simdutf_fast", "aklomp")
# Only these pairs do the same work, so only these pairs produce a ratio.
COMPARABLE_PAIRS = (("b64", "strict"), ("b64_fresh", "strict_fresh"),
                    ("b64", "simdutf"), ("b64", "simdutf_fast"),
                    ("b64", "aklomp"), ("b64", "b64_old"),
                    ("b64", "b64_accel"), ("b64_fresh", "b64_accel_fresh"),
                    ("b64_accel", "simdutf_fast"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
             "bench/strict.goose", "bench/strict_equivalence.goose",
             "bench/ext/bench_ext.cpp",
             "b64_accel.goose", "b64_accel.build", "b64_accel.cpp",
             "vendor/simdutf/simdutf.cpp", "vendor/simdutf/simdutf.h",
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


def cpu_topology(cpu):
    """SMT siblings and core id of the measured CPU, so the record says whether
    a co-tenant could share its execution units."""
    base = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
    identity = {"cpu": cpu}
    for name in ("thread_siblings_list", "core_id", "physical_package_id"):
        path = base / name
        identity[name] = path.read_text().strip() if path.exists() else None
    return identity


def isa_identity():
    """The instruction-set features the measured binaries could use.

    The Goose C backend passes no -march, so the baseline is the generic x86-64
    ISA; the standard library's `simd fn` versions are built only under clang on
    x86-64, where the runtime sets GS_SIMD to 2. Recording the CPU's own feature
    words keeps the two apart: what the machine has, and what the build used.
    """
    wanted = ("avx2", "avx512f", "avx512bw", "avx512vl", "bmi2", "sse4_2")
    flags = set()
    path = Path("/proc/cpuinfo")
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("flags"):
                flags = set(line.split(":", 1)[1].split())
                break
    return {"cpu_features_present": {name: name in flags for name in wanted},
            "goose_c_backend_march": "none (generic x86-64 baseline)",
            "simd_fn_versions": "built only under clang on x86-64 (GS_SIMD=2)"}


def snapshot(options, targets, external_identity):
    """Everything that must be identical before and after the samples.

    Taken twice and compared. A difference means the campaign measured something
    other than what it reports, so the raw observations are kept and the report
    is marked rejected.
    """
    return {
        "source": source_identity(),
        "compiler": {
            "path": str(Path(options.goose).resolve()),
            "sha256": sha256(options.goose),
            "version": subprocess.check_output(
                [str(Path(options.goose).resolve()), "--version"],
                text=True).splitlines()[0],
        },
        "targets": {label: {"binary": path, "sha256": sha256(path)}
                    for label, (path, _argv) in sorted(targets.items())},
        "external": external_identity,
        "runtime": runtime_identity(options.goose),
        "competitor": competitor_identity(options.goose),
        "isa": isa_identity(),
        "harness": {name: sha256(name) for name in
                    ("bench/bench.goose", "bench/strict.goose",
                     "bench/measure.py", "bench/ext/bench_ext.cpp")},
    }


def cpu_busy_fractions(window_seconds):
    """Per-CPU busy fraction from /proc/stat over a window.

    `idle` is idle plus iowait, which is what the kernel counts as not running.
    """
    def read():
        counters = {}
        for line in Path("/proc/stat").read_text().splitlines():
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            fields = line.split()
            values = [int(value) for value in fields[1:]]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            counters[fields[0]] = (idle, sum(values))
        return counters

    first = read()
    time.sleep(window_seconds)
    second = read()
    fractions = {}
    for name, (idle, total) in first.items():
        delta_idle = second[name][0] - idle
        delta_total = second[name][1] - total
        fractions[name] = 1.0 - (delta_idle / delta_total) if delta_total else 0.0
    return fractions


def psi_cpu():
    path = Path("/proc/pressure/cpu")
    if not path.exists():
        return None
    values = {}
    for line in path.read_text().splitlines():
        kind, rest = line.split(None, 1)
        for field in rest.split():
            key, value = field.split("=")
            values[f"{kind}_{key}"] = float(value)
    return values


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


def bootstrap_interval(values, resamples=2000, seed=20261107):
    """A percentile interval for the median of `values`.

    Deterministic: the generator is seeded, so the interval is reproducible from
    the retained raw observations.
    """
    import random
    generator = random.Random(seed)
    n = len(values)
    medians = []
    for _ in range(resamples):
        medians.append(statistics.median(
            [values[generator.randrange(n)] for _ in range(n)]))
    medians.sort()
    return {"low": medians[int(0.025 * resamples)],
            "high": medians[int(0.975 * resamples) - 1]}


def calibration(binary, iterations, runs):
    """Jitter of one fixed fixture on the chosen CPU.

    The fixture is `decode/size_1024` of `b64`, which is a fixed amount of work
    with no allocation and no I/O. The coefficient of variation of its per-call
    time is the effective-contention signal: a co-tenant on the same core, a
    frequency change or a migration all raise it.
    """
    per_call = []
    # The first run of a fresh process pays page faults and a frequency ramp, so
    # it is a warmup and is discarded, exactly as the first sample is.
    for run in range(runs + 1):
        stdout, _ = run_harness(binary, iterations, "b64")
        records, _ = parse(stdout, iterations, "b64")
        if run:
            per_call.append(records[("decode", "size_1024")]["elapsed_ns"] / iterations)
    return {"runs": runs, "warmup_runs": 1, "iterations": iterations,
            "ns_per_call": per_call, "dispersion": dispersion(per_call)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--external-binary",
                        help="harness for the external comparators (bench/ext)")
    parser.add_argument("--external-identity",
                        help="JSON file with the pinned external source identity")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=21)
    parser.add_argument("--output", default=".build/benchmark.json")
    parser.add_argument("--goose", default=os.environ.get("GOOSE", "goose"))
    parser.add_argument("--cpu", type=int,
                        help="measured CPU; chosen once and reused by every "
                             "implementation and every campaign")
    parser.add_argument("--max-cpu-busy", type=float, default=0.30,
                        help="absolute ceiling on the measured CPU's busy "
                             "fraction; a genuinely loaded core fails here")
    parser.add_argument("--cpu-margin", type=float, default=0.05,
                        help="the measured CPU must be within this of the "
                             "least busy CPU, so the choice is relative to the "
                             "host's own floor rather than to an absolute "
                             "number that a desktop can never meet")
    parser.add_argument("--max-psi", type=float, default=5.0)
    parser.add_argument("--max-jitter", type=float, default=0.10)
    parser.add_argument("--calibration-runs", type=int, default=11)
    parser.add_argument("--calibration-iterations", type=int, default=2000)
    parser.add_argument("--settle-seconds", type=float, default=3.0,
                        help="wait this long before the gate, so the campaign's "
                             "own build processes have drained")
    parser.add_argument("--alias", action="append", default=[],
                        metavar="LABEL=BINARY:ARGVNAME",
                        help="measure BINARY, invoked as ARGVNAME, under LABEL. "
                             "Used to race the frozen baseline binary against "
                             "the current one in the same campaign.")
    parser.add_argument("--exploratory", action="store_true",
                        help="record a run that fails the gate, labelled")
    options = parser.parse_args()
    if not 1 <= options.iterations <= 10_000_000:
        raise SystemExit("iterations must be in 1..10000000")
    if options.samples < 21:
        raise SystemExit("samples must be at least 21: one warmup plus 20 measured runs")
    binary = str(Path(options.binary).resolve())
    external = str(Path(options.external_binary).resolve()) if options.external_binary else None

    # label -> (binary, argv name). The argv name is what the harness prints in
    # its `implementation` column, which is not the label when a frozen binary
    # is raced under a different name.
    targets = {impl: (binary, impl) for impl in GOOSE_IMPLEMENTATIONS}
    if external:
        for impl in EXTERNAL_IMPLEMENTATIONS:
            targets[impl] = (external, impl)
    for spec in options.alias:
        label, rest = spec.split("=", 1)
        path, argv_name = rest.rsplit(":", 1)
        targets[label] = (str(Path(path).resolve()), argv_name)
    implementations = list(targets)

    def binary_for(implementation):
        return targets[implementation][0]

    def argv_name_for(implementation):
        return targets[implementation][1]

    external_identity = None
    if options.external_identity:
        external_identity = json.loads(Path(options.external_identity).read_text())

    # --- The gate, before any sample is taken. -----------------------------
    # Settle first. The campaign's own builds have just finished, and their
    # compiler processes are still draining; measuring the gate in that tail
    # would charge the campaign for its own build. This is not a relaxation of
    # the gate, it is measuring the machine rather than the build.
    time.sleep(options.settle_seconds)
    busy = cpu_busy_fractions(2.0)
    if options.cpu is None:
        # Chosen once, from the whole machine, and then fixed for everything.
        chosen = min(busy, key=lambda name: (busy[name], int(name[3:])))
        cpu = int(chosen[3:])
        cpu_choice = "least busy CPU over a 2 s /proc/stat window"
    else:
        cpu = options.cpu
        cpu_choice = "given by --cpu"
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {cpu})
    least_busy_cpu = min(busy, key=busy.get) if busy else None
    least_busy_fraction = busy[least_busy_cpu] if least_busy_cpu else None
    gate = {
        "cpu": cpu,
        "cpu_choice": cpu_choice,
        "cpu_busy_fraction": busy.get(f"cpu{cpu}"),
        "cpu_busy_fraction_all": busy,
        "least_busy_cpu": least_busy_cpu,
        "least_busy_fraction": least_busy_fraction,
        "cpu_margin": options.cpu_margin,
        "max_cpu_busy": options.max_cpu_busy,
        "psi_cpu": psi_cpu(),
        "max_psi": options.max_psi,
        "topology": cpu_topology(cpu),
        "load_average": Path("/proc/loadavg").read_text().strip(),
        "load_average_note": (
            "recorded, not gated: an absolute one-minute load average does not "
            "show contention on the measured CPU on a multicore host"),
    }
    jitter = calibration(binary, options.calibration_iterations,
                         options.calibration_runs)
    gate["jitter"] = jitter
    gate["max_jitter"] = options.max_jitter
    failures = []
    # Two busy-fraction criteria, because one absolute number cannot serve both
    # purposes. The ceiling catches a genuinely loaded core. The margin catches
    # the case this host actually produces: every core carries the desktop's own
    # work, so the floor is around 0.11 and an absolute 0.10 is unsatisfiable
    # even on an otherwise idle machine. What matters is that the measured core
    # is as quiet as the quietest one available, not that it is quiet in the
    # abstract.
    if gate["cpu_busy_fraction"] is None or gate["cpu_busy_fraction"] > options.max_cpu_busy:
        failures.append(f"cpu{cpu} busy {gate['cpu_busy_fraction']} > "
                        f"ceiling {options.max_cpu_busy}")
    if (least_busy_fraction is not None
            and gate["cpu_busy_fraction"] is not None
            and gate["cpu_busy_fraction"] > least_busy_fraction + options.cpu_margin):
        failures.append(f"cpu{cpu} busy {gate['cpu_busy_fraction']:.4f} > "
                        f"least busy {least_busy_cpu} "
                        f"{least_busy_fraction:.4f} + margin {options.cpu_margin}")
    if gate["psi_cpu"] and gate["psi_cpu"].get("some_avg60", 0.0) > options.max_psi:
        failures.append(f"psi some avg60 {gate['psi_cpu']['some_avg60']} > {options.max_psi}")
    if jitter["dispersion"]["cv"] > options.max_jitter:
        failures.append(f"calibration cv {jitter['dispersion']['cv']:.4f} > {options.max_jitter}")
    gate["failures"] = failures
    gate["passed"] = not failures
    if failures and not options.exploratory:
        print(json.dumps(gate, indent=2))
        raise SystemExit("contention gate failed; rerun with --exploratory to "
                         "record a labelled diagnostic")

    # Everything the report will name, captured before the first sample.
    identity_before = snapshot(options, targets, external_identity)

    # samples[implementation][(phase, fixture)] -> list of elapsed ns
    samples = {impl: {} for impl in implementations}
    memory = {impl: [] for impl in implementations}
    work = {impl: [] for impl in implementations}
    comparable = {}  # (phase, fixture, implementation) -> 0/1
    content = {}  # (phase, fixture, implementation) -> (input_len, output_len, checksum)
    order_log = []

    for sample in range(options.samples):
        # Alternate the order so no implementation is always measured first.
        order = implementations if sample % 2 == 0 else list(reversed(implementations))
        order_log.append(list(order))
        for implementation in order:
            stdout, peak_rss = run_harness(binary_for(implementation),
                                           options.iterations,
                                           argv_name_for(implementation))
            records, work_done = parse(stdout, options.iterations,
                                       argv_name_for(implementation))
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
                comparable[identity] = record["comparable"]
                if sample:
                    samples[implementation].setdefault(key, []).append(record["elapsed_ns"])

    # The same identities, and the same calibration, at the other end of the
    # window. A quiet start and a quiet end do not prove the middle was quiet;
    # that limit is recorded rather than papered over.
    identity_after = snapshot(options, targets, external_identity)
    jitter_after = calibration(binary, options.calibration_iterations,
                               options.calibration_runs)
    identity_stable = identity_before == identity_after
    if not identity_stable:
        changed = sorted(key for key in identity_before
                         if identity_before[key] != identity_after.get(key))
        gate["identity_changes"] = changed

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
    # The optional native backend implements the same contract, so it must
    # agree byte for byte with the Goose implementation on every fixture,
    # including the rejected ones: a difference would mean the accelerated path
    # is a different library, not a faster one.
    for implementation in ("b64_accel", "b64_accel_fresh"):
        if implementation not in samples:
            continue
        for phase, fixture in {(key[0], key[1]) for key in content}:
            mine = content.get((phase, fixture, "b64"))
            theirs = content.get((phase, fixture, implementation))
            if theirs is None or mine is None:
                continue
            assert mine == theirs, (
                f"{implementation} disagrees with b64 on {phase}/{fixture}: "
                f"{mine} != {theirs}")
    # The frozen baseline implements the same contract, so it must agree byte
    # for byte with the current one; a difference would mean the comparison is
    # between two different jobs.
    if "b64_old" in samples:
        for phase, fixture in {(key[0], key[1]) for key in content}:
            mine = content.get((phase, fixture, "b64"))
            old = content.get((phase, fixture, "b64_old"))
            if old is None or mine is None:
                continue
            assert mine == old, (
                f"b64 and the frozen baseline disagree on {phase}/{fixture}: "
                f"{mine} != {old}")

    # An external comparator is content-checked only on the rows it declares
    # comparable: where its contract differs, the difference is the finding.
    for implementation in EXTERNAL_IMPLEMENTATIONS:
        if implementation not in samples:
            continue
        for phase, fixture in {(key[0], key[1]) for key in content}:
            mine = content.get((phase, fixture, "b64"))
            theirs = content.get((phase, fixture, implementation))
            if theirs is None or mine is None:
                continue
            if comparable.get((phase, fixture, implementation)) != 1:
                continue
            assert mine == theirs, (
                f"{implementation} claims {phase}/{fixture} comparable but "
                f"disagrees with b64: {mine} != {theirs}")

    per_operation = {}
    for implementation, by_fixture in samples.items():
        for (phase, fixture), values in by_fixture.items():
            per_operation[f"{phase}/{fixture}/{implementation}"] = dispersion(
                [value / options.iterations for value in values])

    ratios = {}
    paired = {}
    for left, right in COMPARABLE_PAIRS:
        if left not in samples or right not in samples:
            continue
        for (phase, fixture) in samples[left]:
            if (phase, fixture) not in samples[right]:
                continue
            if comparable.get((phase, fixture, left)) != 1:
                continue
            if comparable.get((phase, fixture, right)) != 1:
                continue
            if not content[(phase, fixture, left)][1] == content[(phase, fixture, right)][1]:
                continue
            left_values = samples[left][(phase, fixture)]
            right_values = samples[right][(phase, fixture)]
            ratios[f"{phase}/{fixture}/{left}_over_{right}"] = (
                statistics.median(left_values) / statistics.median(right_values))
            pairs = [a / b for a, b in zip(left_values, right_values) if b]
            entry = dispersion(pairs)
            interval = bootstrap_interval(pairs)
            entry["median_ci95"] = interval
            # A ratio whose interval contains 1.0 is not a demonstrated
            # difference, whatever its median says.
            entry["resolved"] = interval["low"] > 1.0 or interval["high"] < 1.0
            paired[f"{phase}/{fixture}/{left}_over_{right}"] = entry

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
        "gate": gate,
        "gate_after": {"jitter": jitter_after,
                       "psi_cpu": psi_cpu(),
                       "cpu_busy_fraction": cpu_busy_fractions(2.0).get(f"cpu{cpu}"),
                       "endpoint_limit": (
                           "the gate and the calibration are taken at the start "
                           "and the end of the window only; neither proves the "
                           "window between them was quiet")},
        "identity_before": identity_before,
        "identity_after": identity_after,
        "identity_stable": identity_stable,
        "status": ("accepted" if gate["passed"] and identity_stable
                   else "rejected" if not identity_stable
                   else "exploratory"),
        "python": sys.version.split()[0],
        "iterations": options.iterations,
        "samples": options.samples,
        "measured_samples": options.samples - 1,
        "warmup_samples": 1,
        "order_policy": "implementations alternate forward/reverse between samples",
        "order_log": order_log,
        "implementations": implementations,
        "compiler_revision": Path("GOOSE_REVISION").read_text().strip(),
        "compiler_binary": str(Path(options.goose).resolve()),
        "compiler_binary_sha256": sha256(options.goose),
        "cc": os.environ.get("BENCH_CC", "gcc"),
        "cc_version": subprocess.check_output(
            [os.environ.get("BENCH_CC", "gcc"), "--version"], text=True).splitlines()[0],
        "flags": "goose build -O2",
        "binary_sha256": sha256(binary),
        "external_binary_sha256": sha256(external) if external else None,
        "external_identity": external_identity,
        **source_identity(),
        "competitor_sha256": competitor_identity(options.goose),
        "runtime_sha256": runtime_identity(options.goose),
        "content": {f"{p}/{f}/{i}": list(v) for (p, f, i), v in sorted(content.items())},
        "comparable": {f"{p}/{f}/{i}": v for (p, f, i), v in sorted(comparable.items())},
        "work_checksum": {impl: sorted(set(values)) for impl, values in work.items()},
        "peak_rss_kib": {impl: dispersion(values) for impl, values in memory.items() if values},
        "raw_ns": {f"{phase}/{fixture}/{implementation}": values
                   for implementation, by_fixture in sorted(samples.items())
                   for (phase, fixture), values in sorted(by_fixture.items())},
        "ns_per_operation": dict(sorted(per_operation.items())),
        "ratio_b64_over_strict": {k: v for k, v in sorted(ratios.items())
                                  if k.endswith("_over_strict") or k.endswith("_over_strict_fresh")},
        "ratio_b64_over_external": {k: v for k, v in sorted(ratios.items())
                                    if k.endswith("_over_simdutf") or k.endswith("_over_aklomp")},
        "ratio_b64_over_baseline": {k: v for k, v in sorted(ratios.items())
                                    if k.endswith("_over_b64_old")},
        "ratio_paired": dict(sorted(paired.items())),
        "stdlib_lower_bound_not_classable": dict(sorted(lower_bound.items())),
        "scope": (
            "Warm medians of repeated calls on prebuilt inputs, one process per "
            "implementation per sample, order alternated between samples, all "
            "implementations and both campaigns on one fixed CPU. "
            "Reused-buffer rows amortise allocation; *_fresh rows allocate per call. "
            "Only pairs the harness marks comparable produce a ratio: both sides "
            "implement the same contract there, proved byte for byte by "
            "bench/strict_equivalence.goose and re-checked here from the content "
            "checksums. The stdlib column is permissive (no URL alphabet, no "
            "unpadded text, no canonicality check, no budget), so it does less "
            "work and is reported as a lower bound only. simdutf ignores ASCII "
            "whitespace inside base64 text, so its whitespace row is not a race. "
            "Not cold latency, not a universal ranking."
        ),
    }
    Path(options.output).write_text(json.dumps(report, indent=2) + "\n")
    for name, value in report["ratio_b64_over_strict"].items():
        print(f"ratio {name}\t{value:.3f}x")
    for name, value in report["ratio_b64_over_external"].items():
        print(f"ratio {name}\t{value:.3f}x")
    for name, value in report["ratio_b64_over_baseline"].items():
        print(f"ratio {name}\t{value:.3f}x")
    for name, value in report["stdlib_lower_bound_not_classable"].items():
        print(f"lower bound (not classable) {name}\t{value:.3f}x")
    print(f"status {report['status']} on cpu{cpu}, "
          f"jitter cv {jitter['dispersion']['cv']:.4f} before, "
          f"{jitter_after['dispersion']['cv']:.4f} after, "
          f"identity {'stable' if identity_stable else 'CHANGED'}")
    print(f"wrote {options.output}")


if __name__ == "__main__":
    main()
