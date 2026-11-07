#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Freeze an auditable baseline of the library before any runtime change.

Records, into one directory:

* the Git revision and a `git archive` tarball of the tracked tree;
* the SHA-256 of every tracked file, from the Git blob and from the worktree,
  with an explicit check that the two agree;
* the pinned compiler binary, its version banner and its `GOOSE_REVISION`;
* the compiler's runtime headers, which are inlined into every generated
  binary, and the generated C for the benchmark with the absolute source path
  normalised so the hash is portable;
* the competitor sources the benchmark compares against (the pinned standard
  library's `base64` module and its documentation section);
* baseline binaries built from the frozen sources, with their SHA-256, their
  `ldd` resolution and their `DT_NEEDED` list;
* the toolchain and platform identity.

Nothing here measures time. The point is that a later result can be attributed
to exact bytes, and that a regression cannot be hidden by overwriting the
baseline with a newer build.

The baseline is only ever built from the checked-out revision. A historical
revision is refused rather than silently built from a different worktree: to
freeze one, check it out (or extract `git archive`) and run this there.

`--supplement` adds a dependency record for an existing freeze without touching
it, so an incomplete record can be completed without rewriting its identity.

Usage:
    baseline-freeze.py --goose /path/to/goose [--out .build/baseline]
    baseline-freeze.py --goose /path/to/goose --supplement .build/baseline
"""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Built from the frozen sources so the baseline has runnable artifacts, not
# only text. Each entry is (label, source, extra goose build flags).
BINARIES = [
    ("api_o2", "tests/api.goose", ["-O2"]),
    ("api_debug", "tests/api.goose", ["--debug", "--no-bce"]),
    ("oracle_o2", "tests/oracle.goose", ["-O2"]),
    ("oracle_debug", "tests/oracle.goose", ["--debug", "--no-bce"]),
    ("parity_debug", "tests/stdlib_parity.goose", ["--debug", "--no-bce"]),
    ("bench_o2", "bench/bench.goose", ["-O2"]),
    ("basic_auth_o2", "examples/basic_auth.goose", ["-O2"]),
    ("json_binary_o2", "examples/json_binary.goose", ["-O2"]),
]

# The runtime is not a shared library: the compiler inlines these headers into
# the generated C, so their hashes are the runtime identity of every binary.
RUNTIME_HEADERS = [
    "src/runtime/goose.h",
    "src/runtime/runtime.h",
    "src/runtime/runtime_impl.h",
    "src/runtime/runtime_os.h",
    "src/runtime/runtime_ext.h",
    "src/runtime/runtime_threads.h",
]

ADDRESS = re.compile(r"\s*\(0x[0-9a-fA-F]+\)\s*$")


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


def git(*args):
    return run(["git", *args], cwd=ROOT).stdout.strip()


def git_bytes(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def tracked_files(revision):
    """Every tracked path with its Git blob hash, its blob content hash and its
    worktree hash, plus an explicit agreement flag.

    `git status` alone would be an assertion about the index; hashing the blob
    content and the worktree file proves the bytes that will be built are the
    bytes the revision names.
    """
    listing = run(["git", "ls-tree", "-r", revision], cwd=ROOT).stdout.splitlines()
    entries = {}
    for line in listing:
        meta, path = line.split("\t", 1)
        mode, kind, blob = meta.split()
        assert kind == "blob", line
        worktree = ROOT / path
        blob_sha = sha256_bytes(git_bytes("cat-file", "blob", blob))
        worktree_sha = sha256_file(worktree) if worktree.is_file() else None
        entries[path] = {
            "mode": mode,
            "git_blob": blob,
            "blob_sha256": blob_sha,
            "worktree_sha256": worktree_sha,
            "worktree_matches_blob": worktree_sha == blob_sha,
        }
    return entries


def compiler_identity(goose):
    goose = Path(goose).resolve()
    root = goose.parents[1]
    return {
        "path": str(goose),
        "sha256": sha256_file(goose),
        "size": goose.stat().st_size,
        "version": run([str(goose), "--version"]).stdout.strip(),
        "goose_revision_file": (ROOT / "GOOSE_REVISION").read_text().strip(),
        "runtime_headers": {
            name: (sha256_file(root / name) if (root / name).is_file() else None)
            for name in RUNTIME_HEADERS
        },
    }


def competitor_identity(goose):
    """The maintained competitor: the pinned standard library's base64 module.

    The compiler checkout is the only place these bytes exist, so hash them
    here rather than trusting a transcription in the docs.
    """
    root = Path(goose).resolve().parents[1]
    sources = {}
    for name in ("stdlib/base64.goose", "docs/stdlib.md", "stdlib/std.goose"):
        path = root / name
        sources[name] = sha256_file(path) if path.is_file() else None
    return {"compiler_root": str(root), "sha256": sources}


def dependencies(binary):
    """What the binary actually loads, and what it declares it needs.

    `ldd` resolves the loader's view at run time; `DT_NEEDED` is the static
    declaration. Both are recorded because a missing shared object would show
    up in one and not the other.
    """
    resolved = []
    for line in run(["ldd", str(binary)]).stdout.splitlines():
        line = ADDRESS.sub("", line.strip())
        if not line:
            continue
        if " => " in line:
            name, path = line.split(" => ", 1)
            name, path = name.strip(), path.strip()
        else:
            name, path = line, None
        entry = {"name": name, "path": path}
        if path and Path(path).is_file():
            entry["sha256"] = sha256_file(path)
        resolved.append(entry)
    needed = []
    for line in run(["objdump", "-p", str(binary)]).stdout.splitlines():
        if "NEEDED" in line:
            needed.append(line.split()[-1])
    return {"ldd": resolved, "dt_needed": sorted(needed)}


def generated_c(goose, source, work):
    """The C the compiler emits, with the absolute source path normalised.

    The generated C embeds the source path for diagnostics, so hashing it raw
    would make the record depend on the checkout location. Replacing the
    repository prefix keeps the hash portable while still pinning the code.
    """
    target = work / (Path(source).stem + ".c")
    run([str(goose), source, "-o", str(target)], cwd=ROOT)
    text = target.read_text(errors="surrogateescape")
    normalised = text.replace(str(ROOT), "<repo>")
    return {"source": source, "sha256": sha256_bytes(normalised.encode("utf-8", "surrogateescape")),
            "bytes": len(normalised)}


def build_binaries(goose, out_dir, work):
    built = {}
    for label, source, flags in BINARIES:
        target = out_dir / label
        run([str(goose), "build", source, "--cc", os.environ.get("CC", "gcc"),
             *flags, "-o", str(target)], cwd=ROOT)
        built[label] = {
            "source": source,
            "flags": ["goose", "build", source, "--cc", os.environ.get("CC", "gcc"), *flags],
            "sha256": sha256_file(target),
            "size": target.stat().st_size,
            "dependencies": dependencies(target),
            "generated_c": generated_c(goose, source, work),
        }
    return built


def tool_identity():
    def first_line(command):
        try:
            return run(command).stdout.splitlines()[0]
        except (OSError, subprocess.CalledProcessError):
            return None

    cpu = "unknown"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu,
        "python": platform.python_version(),
        "gcc": first_line(["gcc", "--version"]),
        "clang": first_line(["clang", "--version"]),
        "uname": " ".join(platform.uname()),
    }


def write_checksums(directory):
    lines = []
    for path in sorted(directory.iterdir()):
        if path.name == "MANIFEST.sha256" or not path.is_file():
            continue
        lines.append(f"{sha256_file(path)}  {path.name}")
    (directory / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")


def supplement(goose, baseline):
    """Complete an existing freeze with a dependency record, without touching it.

    The original manifest and its checksums are left byte-identical; the new
    record anchors itself to the manifest hash it was derived from.
    """
    baseline = baseline.resolve()
    manifest_path = baseline / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"no manifest.json in {baseline}")
    manifest = json.loads(manifest_path.read_text())
    out_dir = baseline.parent / (baseline.name + "-deps")
    if out_dir.exists():
        raise SystemExit(f"refusing to overwrite an existing record: {out_dir}")
    out_dir.mkdir(parents=True)

    record = {
        "anchored_manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "revision": manifest["revision"],
        },
        "compiler": compiler_identity(goose),
        "binaries": {},
    }
    for label, entry in sorted(manifest["binaries"].items()):
        binary = baseline / label
        actual = sha256_file(binary)
        if actual != entry["sha256"]:
            raise SystemExit(f"{label}: binary hash {actual} does not match the manifest")
        record["binaries"][label] = {
            "sha256": actual,
            "dependencies": dependencies(binary),
        }
    (out_dir / "dependencies.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n")
    write_checksums(out_dir)
    print(f"supplemented {baseline} with {out_dir}")
    for label, entry in record["binaries"].items():
        names = ", ".join(d["name"] for d in entry["dependencies"]["ldd"])
        print(f"  {label}: {names}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goose", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / ".build/baseline")
    parser.add_argument("--revision", default="HEAD",
                        help="must resolve to HEAD; a historical revision is refused")
    parser.add_argument("--skip-build", action="store_true",
                        help="record sources only; do not build baseline binaries")
    parser.add_argument("--supplement", type=Path, metavar="BASELINE",
                        help="add a dependency record to an existing freeze")
    options = parser.parse_args()
    goose = options.goose.resolve()

    if options.supplement:
        return supplement(goose, options.supplement)

    out_dir = options.out.resolve()
    if out_dir.exists():
        raise SystemExit(f"refusing to overwrite an existing baseline: {out_dir}")

    # The baseline is built from the worktree, so the worktree must be the
    # revision. A different revision would silently freeze the wrong bytes.
    head = git("rev-parse", "HEAD")
    revision = git("rev-parse", options.revision)
    if revision != head:
        raise SystemExit(
            f"refusing to freeze {revision}: the worktree is at {head} and the "
            "baseline is built from the worktree. Check out the revision, or "
            "extract `git archive` and run this there.")
    status = git("status", "--porcelain", "--untracked-files=no")
    if status:
        raise SystemExit("tracked files are modified; a baseline must be a committed tree:\n" + status)

    out_dir.mkdir(parents=True)
    work = out_dir / "generated"
    work.mkdir()

    archive = out_dir / "baseline-src.tar.gz"
    with archive.open("wb") as handle:
        subprocess.run(["git", "archive", "--format=tar.gz", revision],
                       cwd=ROOT, stdout=handle, check=True)

    files = tracked_files(revision)
    mismatched = [name for name, entry in files.items() if not entry["worktree_matches_blob"]]
    if mismatched:
        raise SystemExit("worktree bytes differ from the revision blobs: " + ", ".join(mismatched))

    manifest = {
        "revision": revision,
        "revision_subject": git("log", "-1", "--format=%s", revision),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "archive": {"name": archive.name, "sha256": sha256_file(archive),
                    "size": archive.stat().st_size},
        "tracked_files": files,
        "compiler": compiler_identity(goose),
        "competitor": competitor_identity(goose),
        "tools": tool_identity(),
        "binaries": {} if options.skip_build else build_binaries(goose, out_dir, work),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_checksums(out_dir)

    print(f"frozen {revision} into {out_dir}")
    print(f"  tracked files: {len(files)} (all worktree bytes match their blobs)")
    print(f"  binaries:      {len(manifest['binaries'])}")
    print(f"  compiler:      {manifest['compiler']['sha256']}")
    print(f"  archive:       {manifest['archive']['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
