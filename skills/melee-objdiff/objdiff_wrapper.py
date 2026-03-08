#!/usr/bin/env python3
"""objdiff-cli wrapper with optional full assembly output for both sides.

This script:
- optionally builds the unit via ninja
- runs objdiff-cli in JSON mode
- prints symbol match summary and assembly diffs

Default mode is intentionally diff-focused for iteration.
Use --full / --full-both only when needed.

objdiff JSON layout:
  left  = "target" (original binary, target_path / -1)
  right = "ours"   (compiled from source, base_path / -2)
  Instructions are paired 1:1 by index across left/right.
  diff_kind values:
    DIFF_INSERT      — slot exists here but not on the other side
                       (instruction is null on this side; the real
                        instruction lives on the *other* side)
    DIFF_DELETE      — this side has an instruction the other doesn't
    DIFF_ARG_MISMATCH— same opcode, different operand/reloc
    DIFF_REPLACE     — completely different opcode
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/home/ubuntu/Desktop/Melee/melee")
OBJDIFF_CLI = Path("/bin/objdiff")

# Avoid noisy BrokenPipeError when piping output (e.g. `| head`).
try:
    import signal

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except Exception:
    pass


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def hex_addr(addr: int | str) -> str:
    """Convert a decimal address (int or str) to hex."""
    try:
        return f"0x{int(addr):X}"
    except (ValueError, TypeError):
        return str(addr)


def format_inst(inst: dict[str, Any]) -> str:
    addr = hex_addr(inst.get("address", "?"))
    formatted = inst.get("formatted", "?")
    return f"{addr}: {formatted}"


def format_data_diff(data_diffs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for diff in data_diffs:
        if diff.get("kind") == "DIFF_DELETE":
            lines.append(f"    [MISSING] {diff.get('size', '?')} bytes")
        elif diff.get("kind") == "DIFF_INSERT":
            lines.append(f"    [EXTRA] {diff.get('size', '?')} bytes")
    return lines


# ---------------------------------------------------------------------------
# Instruction iterators
# ---------------------------------------------------------------------------

def iter_instructions(sym: dict[str, Any]) -> list[dict[str, Any]]:
    return sym.get("instructions", []) or []


# ---------------------------------------------------------------------------
# Printing: full assembly
# ---------------------------------------------------------------------------

def print_full(label: str, sym: dict[str, Any]) -> None:
    """Print full assembly for one side with diff markers."""
    instrs = iter_instructions(sym)
    real_count = sum(1 for e in instrs if e.get("instruction"))
    diff_count = sum(1 for e in instrs if e.get("diff_kind"))
    print(f"\n   {label} ({real_count} instructions):")
    print(f"   {'-' * 60}")
    for entry in instrs:
        inst = entry.get("instruction")
        dk = entry.get("diff_kind")
        if not inst:
            if dk:
                # Placeholder gap — other side has an instruction here we don't
                print(f"   >>> {'---':50s} <-- {dk} (gap)")
            continue
        line = format_inst(inst)
        if dk:
            print(f"   >>> {line:50s} <-- {dk}")
        else:
            print(f"       {line}")
    print(f"   {'-' * 60}")
    total = len(instrs)
    matched = total - diff_count
    print(f"   {matched}/{total} instructions match, {diff_count} differ")


# ---------------------------------------------------------------------------
# Printing: diff-only (mismatches)
# ---------------------------------------------------------------------------

def print_diff_only(label: str, sym: dict[str, Any]) -> None:
    """Print only mismatching instructions for one side."""
    instrs = iter_instructions(sym)
    diffs = [e for e in instrs if e.get("diff_kind")]
    print(f"\n   {label} ({len(diffs)} diff entries):")
    print(f"   {'-' * 60}")
    for entry in diffs:
        inst = entry.get("instruction")
        dk = entry.get("diff_kind", "CHANGED")
        if not inst:
            print(f"   >>> {'---':50s} <-- {dk} (gap)")
        else:
            print(f"   >>> {format_inst(inst):50s} <-- {dk}")
    if not diffs:
        print("   (no differences)")
    print(f"   {'-' * 60}")


# ---------------------------------------------------------------------------
# Printing: paired side-by-side diff
# ---------------------------------------------------------------------------

def print_paired_diff(ours_sym: dict[str, Any],
                      target_sym: dict[str, Any] | None,
                      full: bool) -> None:
    """Print paired side-by-side comparison.

    If full=True, prints every instruction.  Otherwise only rows with diffs.
    """
    ours_instrs = iter_instructions(ours_sym)
    target_instrs = iter_instructions(target_sym) if target_sym else []
    max_len = max(len(ours_instrs), len(target_instrs))

    if full:
        print(f"\n   PAIRED ASSEMBLY ({max_len} rows):")
    else:
        print(f"\n   PAIRED DIFF:")
    print(f"   {'OURS':<44s}  {'TARGET':>44s}")
    print(f"   {'-' * 93}")

    diff_count = 0
    for i in range(max_len):
        ours_e = ours_instrs[i] if i < len(ours_instrs) else {}
        tgt_e = target_instrs[i] if i < len(target_instrs) else {}

        ours_dk = ours_e.get("diff_kind")
        tgt_dk = tgt_e.get("diff_kind")
        has_diff = bool(ours_dk or tgt_dk)

        if not full and not has_diff:
            continue

        diff_count += has_diff

        ours_inst = ours_e.get("instruction")
        tgt_inst = tgt_e.get("instruction")

        ours_str = format_inst(ours_inst) if ours_inst else "---"
        tgt_str = format_inst(tgt_inst) if tgt_inst else "---"

        if has_diff:
            dk_label = ours_dk or tgt_dk or "CHANGED"
            print(f"   >>> {ours_str:<42s}  |  {tgt_str:>42s}  [{dk_label}]")
        else:
            print(f"       {ours_str:<42s}  |  {tgt_str:>42s}")

    print(f"   {'-' * 93}")
    if not full:
        total = max_len
        matched = total - diff_count
        print(f"   {matched}/{total} instructions match, {diff_count} differ")


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------

def get_object_path(unit: str) -> Path:
    parts = unit.split('/')
    obj_path = PROJECT_ROOT / "build" / "GALE01" / "src" / "/".join(parts[1:])
    obj_path = obj_path.with_suffix(".o")
    if not obj_path.exists():
        obj_path = PROJECT_ROOT / "build" / "GALE01" / "obj" / "/".join(parts[1:])
        obj_path = obj_path.with_suffix(".o")
    return obj_path


def get_source_path(unit: str) -> Path | None:
    parts = unit.split('/')
    for ext in ['.c', '.cpp', '.cp']:
        src_path = PROJECT_ROOT / "src" / "/".join(parts[1:])
        src_path = src_path.with_suffix(ext)
        if src_path.exists():
            return src_path
    return None


def maybe_build_unit(unit: str) -> None:
    obj_path = get_object_path(unit)
    src_path = get_source_path(unit)

    if src_path and obj_path.exists():
        if src_path.stat().st_mtime > obj_path.stat().st_mtime:
            print("Source file is newer than object, running ninja...")
            rel_obj_path = obj_path.relative_to(PROJECT_ROOT)
            result = subprocess.run(
                ["ninja", "-j1", str(rel_obj_path)],
                cwd=PROJECT_ROOT, capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"  Built: {obj_path}")
            else:
                print("=== COMPILATION FAILED ===\n")
                print(result.stderr)
                sys.exit(result.returncode)
    elif not obj_path.exists():
        print(f"Note: Object file not found: {obj_path}")
        print("  Run ninja first to build the project.")


# ---------------------------------------------------------------------------
# objdiff runner
# ---------------------------------------------------------------------------

def run_objdiff(symbol: str, unit: str | None) -> dict[str, Any]:
    cmd = [
        str(OBJDIFF_CLI), "diff",
        "-p", str(PROJECT_ROOT),
        "--format", "json",
        "--output", "-",
    ]
    if unit:
        cmd.extend(["-u", unit])
    cmd.append(symbol)

    print(f"Running objdiff-cli for symbol: {symbol}")
    if unit:
        print(f"Unit: {unit}")
    print("-" * 60)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(result.returncode)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON: {e}")
        print(result.stdout[:500])
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(add_help=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--full", action="store_true",
        help="Print full assembly (ours side only, with diff markers).",
    )
    mode.add_argument(
        "--full-both", action="store_true",
        help="Print full paired side-by-side assembly for both ours and target.",
    )
    mode.add_argument(
        "--both-diff-only", action="store_true",
        help="Print paired diff (only mismatching rows, both sides).",
    )
    mode.add_argument(
        "--sections", action="store_true",
        help="Print section-level match summary only (no assembly).",
    )
    ap.add_argument("symbol", help="Symbol/function name")
    ap.add_argument("unit", nargs="?", default=None,
                    help="Unit name (e.g. main/melee/it/itcoll)")
    args = ap.parse_args()

    if args.unit:
        maybe_build_unit(args.unit)

    data = run_objdiff(args.symbol, args.unit)

    left = data.get("left", {})   # target (original binary)
    right = data.get("right", {})  # ours (compiled from source)

    # "ours" symbols come from right; "target" symbols from left
    ours_symbols = right.get("symbols", [])
    target_symbols = left.get("symbols", [])

    # Build lookup from symbol name → target-side symbol data
    target_sym_map: dict[str, dict[str, Any]] = {}
    for ts in target_symbols:
        tname = ts.get("name", "")
        if tname:
            target_sym_map[tname] = ts

    # Section-only mode: just print section match percentages and exit
    if args.sections:
        ours_sections = right.get("sections", [])
        print("\n=== SECTION SUMMARY ===")
        for s in ours_sections:
            mp = s.get("match_percent")
            if mp is not None:
                status = "✓" if mp == 100.0 else "✗"
                print(f"  {status} {s['name']}: {mp:.1f}%")
        print()
        return

    matching_symbols = [s for s in ours_symbols if args.symbol in s.get("name", "")]

    print("\n=== SYMBOL MATCH SUMMARY ===\n")

    if not matching_symbols:
        print(f"No symbols found matching '{args.symbol}'")
        if ours_symbols:
            print("\nAvailable symbols:")
            for s in ours_symbols[:20]:
                name = s.get("name", "?")
                match = s.get("match_percent", 0)
                status = "✓" if match == 100.0 else "✗"
                print(f"  {status} {name} ({match}%)")
            if len(ours_symbols) > 20:
                print(f"  ... and {len(ours_symbols) - 20} more")
        sys.exit(1)

    for sym in matching_symbols:
        name = sym.get("name", "?")
        match = sym.get("match_percent", 0)
        raw_addr = sym.get("address")
        size = sym.get("size", "?")

        # Use target symbol flags for type (ground truth from original binary)
        target_sym = target_sym_map.get(name)
        flags = target_sym.get("flags", 0) if target_sym else sym.get("flags", 0)

        sym_type = "FUNC" if flags == 1 else "DATA" if flags == 2 else "UNK"
        status = "✓" if match == 100.0 else "✗"

        print(f"{status} {name} [{sym_type}]")
        if raw_addr is not None:
            print(f"   Address: {hex_addr(raw_addr)}  Size: {size} bytes  Match: {match}%")
        else:
            print(f"   Size: {size} bytes  Match: {match}%")

        if "instructions" in sym:
            if args.full_both:
                # Full paired side-by-side
                print_paired_diff(sym, target_sym, full=True)
            elif args.both_diff_only:
                # Paired but diff-only
                print_paired_diff(sym, target_sym, full=False)
            elif args.full:
                # Full assembly, ours only
                print_full("OUR ASSEMBLY", sym)
            else:
                # Default: paired diff-only (most useful for iteration)
                print_paired_diff(sym, target_sym, full=False)

        if "data_diff" in sym:
            diff_lines = format_data_diff(sym.get("data_diff", []))
            if diff_lines:
                print("\n   Data differences:")
                for line in diff_lines:
                    print(line)

        print()


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        os._exit(0)
