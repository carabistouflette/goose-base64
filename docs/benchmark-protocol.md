# Benchmark protocol

This file records the measurement protocol, including the rule it replaced, so
that a change in protocol is auditable rather than silent. The current gate is
implemented in `bench/measure.py` and described in
[bench/README.md](../bench/README.md).

## Superseded: absolute load average ≤ 0.5

The earlier protocol refused to measure unless the machine's one-minute load
average was at or below 0.5. It was applied as an operational precondition when
starting a campaign; it was never a committed check, which is why this file
exists — the rule was real, it was followed, and it is now replaced.

It is superseded because it does not test what it claims to test. The load
average counts runnable and uninterruptible tasks across the whole machine. On
this host — an Intel Core Ultra 7 258V with eight cores and no SMT — a load
average of 3.5 can leave the measured core idle, and a load average of 0.4 can
leave it busy with one spinning task. The quantity that matters is the occupancy
of the core the campaign is pinned to, and the load average is not that quantity.
Keeping the rule would have meant either refusing to measure on a machine that
was in fact quiet enough, or measuring on a machine that was not.

The rule is preserved here rather than deleted, because a reader comparing an old
campaign with a new one needs to know that the acceptance criterion changed and
why.

## Current gate

The gate decides from the measured core, and it is evaluated once before the
samples and once after.

1. **CPU choice, once.** Unless `--cpu` names one, the measured CPU is the least
   busy over a 2 s `/proc/stat` window. The choice, every core's busy fraction and
   the CPU topology (`thread_siblings_list`, `core_id`, `physical_package_id`) are
   recorded. The same CPU is then used by every implementation in the campaign
   and by every campaign in the series. It is never re-chosen per implementation:
   that would let each one be timed on a differently loaded core and would make
   the ratios meaningless.
2. **Chosen-CPU busy fraction ≤ 0.30**, from the same `/proc/stat` window. This is
   an absolute ceiling: it catches a genuinely loaded core.
3. **Chosen-CPU busy fraction within 0.05 of the least busy CPU.** This is the
   criterion that actually decides, and it is relative on purpose. On this host
   every core carries the desktop's own work, so the floor is around 0.11 and an
   absolute threshold of 0.10 is unsatisfiable even on an otherwise idle machine.
   What matters is that the measured core is as quiet as the quietest one
   available, not that it is quiet in the abstract. The first clang campaign was
   rejected by the absolute rule at 0.246 busy on a core that was not the least
   busy one; that rejection is kept in `.build/c1/campaign-clang.log` rather than
   deleted, because it is evidence about the machine.
4. **PSI `cpu some avg60` ≤ 5.0.** Pressure stall information reports the share
   of time tasks were stalled on CPU; it catches whole-machine stalls that a
   single core's busy fraction would miss.
5. **Jitter calibration CV ≤ 0.10.** A calibration workload runs
   `--calibration-runs` times (default 9) at `--calibration-iterations` (default
   200) before the samples, and its coefficient of variation must be at or below
   the threshold. This is the direct test the load average was standing in for:
   it measures the timing noise this campaign will actually experience, on this
   core, with this binary. The busy fraction is a proxy for that noise; the
   calibration measures it.

### What the thresholds are, and are not

The busy-fraction criteria and the 0.10 CV are **practical resolution
thresholds, not statistical guarantees**. They assert that the campaign can
resolve the differences it reports. They do not assert that the reported ratios
are exact, and a stricter threshold would not make them exact — it would only
make the campaign harder to run. The bootstrap interval on each paired ratio is
what expresses the remaining uncertainty, and a ratio whose interval contains 1.0
is reported as `resolved: false` rather than as a difference.

An earlier revision of this protocol justified the CV threshold with a
`cv/sqrt(n)` standard-error argument for a median. That argument is wrong: the
standard error of a median is not `cv/sqrt(n)` in general, and the threshold is
not derived from a distributional assumption. It is a practical threshold, and it
is described as one.

An earlier revision also used a single absolute busy-fraction threshold of 0.10.
It was replaced by the ceiling-plus-margin pair above, not because it produced an
unwanted answer but because it was unsatisfiable on this host: the desktop's own
work puts every core at roughly 0.11 before any campaign starts. Raising a
threshold to obtain a result would be the wrong fix; making the criterion
relative to the host's own floor is the right one, and the absolute ceiling is
kept so that a genuinely loaded machine still fails.

### Both endpoints

The gate and the calibration are taken at the **start** and at the **end** of the
campaign, and both are recorded. A machine that was quiet at the start and busy at
the end produces a campaign that looks fine and is not. The limitation is named
rather than hidden: two calibration points bound the noise at the two ends of the
run, not continuously, so a burst of contention in the middle of the samples is
not detected by the gate. The per-sample raw data and the dispersion of the
paired ratios are what would reveal it, which is why both are kept.

## Identity snapshots

Every campaign snapshots the identity of everything it measures before the first
sample and again after the last: the effective source identity (repository root,
whether that root is this directory, HEAD, SHA-256 of every measured source file,
dirty flag), the compiler revision and compiler binary SHA-256, the SHA-256 of
every measured binary including the `--alias` frozen baseline, the runtime header
SHA-256s, the competitor's `base64.goose` and `std.goose` SHA-256, the external
comparators' identity, the ISA feature set and the CPU topology.

If the two snapshots differ, the raw samples are kept and the campaign is written
with `status: "rejected"`. A binary that changed under the measurement is not a
measurement. This is why the frozen baseline is extracted from the immutable
archive and hash-checked against its manifest before it is built, and why the
frozen binary in `.build/baseline/` is never overwritten.

## Status values

| `status` | Meaning |
| --- | --- |
| `accepted` | The gate passed at both ends and the identity snapshots agree. |
| `exploratory` | `--exploratory` was passed. The gate failed; the run is a labelled diagnostic, not evidence. |
| `rejected` | The gate failed, or an identity changed between the snapshots. Raw samples are kept. |

A campaign that is not `accepted` is not cited as a result. It is kept because a
failed campaign is evidence about the machine, and because discarding it would
hide the failure.

## Sampling

21 samples: one warmup, discarded, and 20 measured. Fewer than 21 is refused. One
process per implementation per sample, with the order alternated forward and
reverse between samples, so no implementation is always measured first and
charged for cold caches and frequency ramp-up. Every row carries a FNV-1a content
checksum computed outside the timed loop, so a wrong-but-same-length result
cannot pass, and the content is required to be identical across all 21 samples.

Ratios are reported as a ratio of medians and as a median of paired per-sample
ratios, the latter being more robust to drift, with a bootstrap 95% interval on
the paired median. Dispersion is reported per row: median, mean, min, max, p10,
p90, IQR, MAD, standard deviation and coefficient of variation. Every raw sample
is kept in the JSON.

## What is not measured

No hardware performance counter is read, so no branch-miss, cache-miss or IPC
figure is claimed anywhere. The disassembly evidence in
`.build/c1/disassembly/` is instruction-form evidence, and the causal link from
instruction form to wall-clock time is offered as a plausible mechanism, not as a
measured one.

The measurements are warm-process medians of repeated calls on prebuilt inputs,
on one machine, without exclusive CPU isolation. They are not cold latency,
allocation counts, or a universal ranking.
