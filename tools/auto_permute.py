#!/usr/bin/env python3
"""Run decomp-permuter on functions above a match threshold.

Combines the function-filtering logic from easy_funcs.py with the permuter
invocation from permute.sh. For each selected function, runs the permuter
for a configurable duration, then saves any improved/matching outputs to a
results directory.
"""

import argparse
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

ROOT = Path(__file__).parents[1]
MODULE = "main"
REPORT_PATH = ROOT / "build" / "GALE01" / "report.json"
PERMUTER = ROOT.parent / "decomp-permuter"
NONMATCHINGS = ROOT / "nonmatchings"
SRC_MELEE = ROOT / "src" / "melee"

SKIP_SYMBOLS = {"GetR2_80322F20"}


@dataclass(frozen=True)
class Function:
    name: str
    unit: str
    matched: float
    size: int


def build_report() -> dict:
    log("Building report.json with ninja...")
    t0 = time.time()
    proc = subprocess.run(
        ["ninja", str(REPORT_PATH.relative_to(ROOT))],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout.decode() + proc.stderr.decode())
        raise SystemExit(f"ninja failed: {proc.returncode}")
    log(f"Report built in {time.time() - t0:.1f}s")
    with REPORT_PATH.open() as fp:
        return cast(dict, json.load(fp))


def collect_candidates(min_match: float, max_match: float) -> list[Function]:
    report = build_report()
    out: list[Function] = []
    prefix = f"{MODULE}/"
    for unit in report.get("units", []):
        unit_name = unit["name"]
        if not unit_name.startswith(prefix):
            continue
        unit_short = unit_name[len(prefix):]
        for fn in unit.get("functions", []):
            name = fn["name"]
            if name in SKIP_SYMBOLS:
                continue
            pct = float(fn.get("fuzzy_match_percent", 0))
            if pct < min_match or pct > max_match:
                continue
            out.append(Function(name, unit_short, pct, int(fn.get("size", 0))))
    return out


def find_source(func: Function) -> Path | None:
    candidate = (ROOT / "src" / func.unit).with_suffix(".c")
    if candidate.exists():
        return candidate
    pattern = re.compile(rf"^[a-zA-Z_].*\b{re.escape(func.name)}\b\s*\(")
    for path in SRC_MELEE.rglob("*.c"):
        try:
            with path.open() as fp:
                for line in fp:
                    if pattern.match(line):
                        return path
        except OSError:
            continue
    return None


def run_permuter(func: Function, source: Path, duration: int, jobs: int) -> bool:
    work_dir = NONMATCHINGS / func.name
    if work_dir.exists():
        log(f"Cleaning previous {work_dir.relative_to(ROOT)}")
        shutil.rmtree(work_dir)

    log(f"Importing {func.name} from {source.relative_to(ROOT)}")
    imp = subprocess.run(
        ["python", str(PERMUTER / "import.py"), str(source), f"--func={func.name}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if imp.returncode != 0 or not work_dir.exists():
        sys.stderr.write(imp.stdout.decode(errors="replace"))
        log(f"[skip] import failed for {func.name}")
        return False

    log(f"Running permuter on {func.name}  (j={jobs}, up to {duration}s)")
    proc = subprocess.Popen(
        ["python", "-u", str(PERMUTER / "permuter.py"), str(work_dir), "-j", str(jobs)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
        bufsize=1,
    )

    start = time.time()
    best_seen: list[int | None] = [None]
    iter_count: list[int] = [0]
    zero_hits: list[int] = [0]
    enough_zeros = threading.Event()
    iter_re = re.compile(r"^iteration\s+(\d+),\s+\d+\s+errors,\s+score\s*=\s*(\S+)")
    new_best_re = re.compile(r"\bfound new best score!\s*\((-?\d+)\s+vs")
    better_re = re.compile(r"\bfound a better score!\s*\((-?\d+)\s+vs")
    tied_re = re.compile(r"\btied best score!\s*\((-?\d+)\s+vs")

    ZERO_LIMIT = 5

    def note_zero():
        zero_hits[0] += 1
        if zero_hits[0] >= ZERO_LIMIT:
            enough_zeros.set()

    def pump():
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue

            m = iter_re.match(line)
            if m:
                iter_count[0] = int(m.group(1))
                continue

            m = new_best_re.search(line)
            if m:
                s = int(m.group(1))
                if best_seen[0] is None or s < best_seen[0]:
                    best_seen[0] = s
                log(f"  ** new best score {s} at iteration {iter_count[0]}")
                if s == 0:
                    note_zero()
                continue

            m = tied_re.search(line)
            if m:
                s = int(m.group(1))
                if s == 0:
                    log(f"  ** tied match (score 0) at iteration {iter_count[0]} "
                        f"[{zero_hits[0] + 1}/{ZERO_LIMIT}]")
                    note_zero()
                continue

            if (
                better_re.search(line)
                or "found different asm with same score" in line
                or line.startswith("wrote to ")
            ):
                continue

            print(f"  | {line}", flush=True)

    t = threading.Thread(target=pump, daemon=True)
    t.start()

    last_tick = start
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                log(f"Permuter exited (rc={rc}) after {time.time()-start:.0f}s")
                break
            elapsed = time.time() - start
            if enough_zeros.is_set():
                log(f"Got {ZERO_LIMIT} score-0 results for {func.name}; moving on")
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                break
            if elapsed >= duration:
                log(f"Reached duration limit ({duration}s); stopping permuter")
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    log("Permuter didn't exit on SIGTERM; sending SIGKILL")
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                break
            if time.time() - last_tick >= 30:
                last_tick = time.time()
                remaining = max(0, duration - int(elapsed))
                best_str = "n/a" if best_seen[0] is None else str(best_seen[0])
                log(f"  ...{int(elapsed)}s elapsed, {remaining}s left, "
                    f"iter={iter_count[0]}, best score so far: {best_str}")
            time.sleep(1)
    except KeyboardInterrupt:
        log("Interrupted; killing permuter")
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise

    t.join(timeout=2)
    return True


def harvest(func: Function, results_dir: Path) -> tuple[int, int | None]:
    """Copy improvement outputs out of nonmatchings/<func>/ into results_dir.

    Returns (count_copied, best_score_or_None).
    """
    work_dir = NONMATCHINGS / func.name
    if not work_dir.exists():
        return 0, None
    outputs = sorted(p for p in work_dir.iterdir() if p.is_dir() and p.name.startswith("output-"))
    if not outputs:
        return 0, None

    best: int | None = None
    pat = re.compile(r"output-(-?\d+)-\d+")
    for out in outputs:
        m = pat.match(out.name)
        if not m:
            continue
        score = int(m.group(1))
        if best is None or score < best:
            best = score

    best_tag = "best-unknown" if best is None else f"best-{best}"
    dest = results_dir / f"{func.name}__{best_tag}"
    for stale in results_dir.glob(f"{func.name}__best-*"):
        shutil.rmtree(stale)
    legacy = results_dir / func.name
    if legacy.exists():
        shutil.rmtree(legacy)
    dest.mkdir(parents=True)
    for out in outputs:
        shutil.copytree(out, dest / out.name)
    for extra in ("base.c", "target.s"):
        src = work_dir / extra
        if src.exists():
            shutil.copy2(src, dest / extra)
    return len(outputs), best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-match", type=float, default=95.0,
                    help="minimum fuzzy match %% (default 95)")
    ap.add_argument("--max-match", type=float, default=99.999,
                    help="maximum fuzzy match %% (default 99.999, excludes matched)")
    ap.add_argument("--duration", type=int, default=240,
                    help="seconds to run permuter per function (default 240)")
    ap.add_argument("--order", choices=("random", "ordered"), default="random",
                    help="iteration order over candidates")
    ap.add_argument("--max-funcs", type=int, default=0,
                    help="stop after this many functions (0 = no limit)")
    ap.add_argument("-j", "--jobs", type=int, default=64,
                    help="permuter -j (default 64)")
    ap.add_argument("--results-dir", type=Path,
                    default=ROOT / "permuter_results",
                    help="directory to save successful diffs")
    ap.add_argument("--seed", type=int, default=None,
                    help="random seed (for --order random)")
    args = ap.parse_args()

    if not PERMUTER.exists():
        raise SystemExit(f"decomp-permuter not found at {PERMUTER}")

    rng = random.Random(args.seed)
    results_dir: Path = args.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    log(f"Results directory: {results_dir}")
    log(f"Collecting candidates with match in [{args.min_match}%, {args.max_match}%]")
    candidates = collect_candidates(args.min_match, args.max_match)
    log(f"Found {len(candidates)} candidate function(s)")
    if args.order == "random":
        rng.shuffle(candidates)
        log(f"Shuffled candidates (seed={args.seed})")
    else:
        candidates.sort(key=lambda f: -f.matched)
        log("Ordered candidates by descending match%")

    if args.max_funcs > 0 and len(candidates) > args.max_funcs:
        candidates = candidates[:args.max_funcs]
        log(f"Trimmed to first {args.max_funcs} candidate(s)")

    total_budget_min = len(candidates) * args.duration / 60
    log(f"Worst-case wall time: ~{total_budget_min:.1f} min "
        f"({len(candidates)} funcs * {args.duration}s)")

    saved = 0
    matched = 0
    started = time.time()
    for i, fn in enumerate(candidates, 1):
        print()
        log(f"=== [{i}/{len(candidates)}] {fn.name}  unit={fn.unit}  "
            f"match={fn.matched:.2f}%  size={fn.size}B ===")
        source = find_source(fn)
        if source is None:
            log(f"[skip] could not locate source for {fn.name}")
            continue
        if not run_permuter(fn, source, args.duration, args.jobs):
            continue
        n, best = harvest(fn, results_dir)
        if n > 0 and best is not None:
            tag = "MATCH!" if best == 0 else f"score={best}"
            log(f"[save] {fn.name}: {n} improvement(s), best {tag} -> "
                f"{results_dir / f'{fn.name}__best-{best}'}")
            saved += 1
            if best == 0:
                matched += 1
        else:
            log(f"[none] {fn.name}: no improvements found")
        log(f"Progress: {i}/{len(candidates)} done, {saved} saved, {matched} matched, "
            f"{(time.time()-started)/60:.1f} min elapsed")

    elapsed = time.time() - started
    print()
    log(f"Done. {saved}/{len(candidates)} had improvements ({matched} full matches) "
        f"in {elapsed/60:.1f} min. Results at {results_dir}")


if __name__ == "__main__":
    main()
