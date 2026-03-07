#!/usr/bin/env python3
"""objdiff-cli wrapper with optional full assembly output for both sides.

This script:
- optionally builds the unit via ninja
- runs objdiff-cli in JSON mode
- prints symbol match summary and assembly diffs

Default mode is intentionally diff-focused for iteration.
Use --full / --full-both only when needed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/home/sysop/Melee/melee")
OBJDIFF_CLI = Path("/bin/objdiff")

# Avoid noisy BrokenPipeError when piping output (e.g. `| head`).
# Set SIGPIPE to default so the process terminates quietly on a closed pipe.
try:
    import signal

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except Exception:
    pass


def format_data_diff(data_diffs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for diff in data_diffs:
        if diff.get("kind") == "DIFF_DELETE":
            lines.append(f"    [MISSING] {diff.get('size', '?')} bytes")
        elif diff.get("kind") == "DIFF_INSERT":
            lines.append(f"    [EXTRA] {diff.get('size', '?')} bytes")
    return lines


def format_inst(inst: dict[str, Any]) -> str:
    addr = inst.get("address", "?")
    formatted = inst.get("formatted", "?")
    return f"{addr}: {formatted}"


def iter_instructions(sym: dict[str, Any]) -> list[dict[str, Any]]:
    # objdiff JSON schema: sym["instructions"] is list of entries.
    # Entries can contain: instruction, diff_kind, left, right.
    return sym.get("instructions", []) or []


def has_diff(entry: dict[str, Any]) -> bool:
    return entry.get("diff_kind") is not None or (entry.get("left") and entry.get("right"))


def print_ours_full(sym: dict[str, Any]) -> None:
    instrs = iter_instructions(sym)
    print(f"\n   OUR ASSEMBLY ({len(instrs)} instructions):")
    print(f"   {'-' * 50}")
    for entry in instrs:
        inst = entry.get("instruction")
        if not inst:
            continue
        line = format_inst(inst)
        if entry.get("diff_kind"):
            print(f"   >>> {line}  <-- {entry.get('diff_kind')}")
        else:
            print(f"   {line}")
    print(f"   {'-' * 50}")


def print_ours_diff_only(sym: dict[str, Any]) -> None:
    instrs = iter_instructions(sym)
    diffs = [e for e in instrs if e.get("instruction") and has_diff(e)]
    print(f"\n   OUR MISMATCHES ({len(diffs)} entries):")
    print(f"   {'-' * 50}")
    for entry in diffs:
        inst = entry.get("instruction")
        if not inst:
            continue
        print(f"   >>> {format_inst(inst)}  <-- {entry.get('diff_kind', 'CHANGED')}")
    print(f"   {'-' * 50}")


def print_target_full(sym: dict[str, Any]) -> None:
    instrs = iter_instructions(sym)
    # For target, prefer the "right" side instruction when present, otherwise "instruction".
    # In matches, right may be missing.
    collected: list[dict[str, Any]] = []
    for e in instrs:
        if e.get("right"):
            collected.append(e["right"])
        elif e.get("instruction"):
            collected.append(e["instruction"])

    print(f"\n   TARGET ASSEMBLY ({len(collected)} instructions):")
    print(f"   {'-' * 50}")
    for inst in collected:
        print(f"   {format_inst(inst)}")
    print(f"   {'-' * 50}")


def print_target_diff_only(sym: dict[str, Any]) -> None:
    instrs = iter_instructions(sym)
    diffs = [e for e in instrs if has_diff(e)]
    print(f"\n   TARGET MISMATCHES ({len(diffs)} entries):")
    print(f"   {'-' * 50}")

    printed = 0
    no_target_data = 0
    for e in diffs:
        kind = e.get("diff_kind", "CHANGED")

        # Prefer explicit target-side instruction if present.
        inst = e.get("right")
        if inst:
            print(f"   >>> {format_inst(inst)}  <-- {kind}")
            printed += 1
            continue

        # For DIFF_INSERT (extra in ours), there may be only a `left`.
        left_inst = e.get("left")
        if left_inst:
            print(f"   >>> (no target inst) ours has {format_inst(left_inst)}  <-- {kind}")
            printed += 1
            continue

        # objdiff does not include the target-side instruction for some diff types
        # (e.g. DIFF_ARG_MISMATCH). The `instruction` field here is OUR instruction,
        # NOT the target — showing it in the target section would be misleading.
        # Count these and suggest --full-both instead.
        if e.get("instruction"):
            no_target_data += 1

    if no_target_data:
        print(f"   ({no_target_data} {no_target_data == 1 and 'entry' or 'entries'} omitted: objdiff did not provide target instruction data")
        print(f"    for these diff types. Use --full-both to see the full target assembly.)")

    if printed == 0 and no_target_data == 0:
        print("   (no printable entries)")

    print(f"   {'-' * 50}")


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
            result = subprocess.run(["ninja", "-j1", str(rel_obj_path)], cwd=PROJECT_ROOT, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  Built: {obj_path}")
            else:
                print("=== COMPILATION FAILED ===\n")
                print(result.stderr)
                sys.exit(result.returncode)
    elif not obj_path.exists():
        print(f"Note: Object file not found: {obj_path}")
        print("  Run ninja first to build the project.")


def run_objdiff(symbol: str, unit: str | None) -> dict[str, Any]:
    cmd = [str(OBJDIFF_CLI), "diff", "-p", str(PROJECT_ROOT), "--format", "json", "--output", "-"]
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


def main() -> None:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--full", action="store_true", help="Print full assembly (ours side).")
    ap.add_argument("--full-both", action="store_true", help="Print full assembly for both ours and target.")
    ap.add_argument("symbol", help="Symbol/function name")
    ap.add_argument("unit", nargs="?", default=None, help="Unit name (e.g. main/melee/it/itcoll)")
    args = ap.parse_args()

    # Enforce mutually exclusive modes
    if args.full and args.full_both:
        print("Error: --full and --full-both are mutually exclusive")
        sys.exit(2)

    if args.unit:
        maybe_build_unit(args.unit)

    data = run_objdiff(args.symbol, args.unit)

    left = data.get("left", {})
    symbols = left.get("symbols", [])
    # sections are available but intentionally unused (symbol-level tool)

    matching_symbols = [s for s in symbols if args.symbol in s.get("name", "")]

    print("\n=== SYMBOL MATCH SUMMARY ===\n")

    if not matching_symbols:
        print(f"No symbols found matching '{args.symbol}'")
        if symbols:
            print("\nAvailable symbols:")
            for s in symbols[:20]:
                name = s.get("name", "?")
                match = s.get("match_percent", 0)
                status = "✓" if match == 100.0 else "✗"
                print(f"  {status} {name} ({match}%)")
            if len(symbols) > 20:
                print(f"  ... and {len(symbols) - 20} more")
        sys.exit(1)

    for sym in matching_symbols:
        name = sym.get("name", "?")
        match = sym.get("match_percent", 0)
        addr = sym.get("address", "?")
        size = sym.get("size", "?")
        flags = sym.get("flags", 0)

        sym_type = "FUNC" if flags == 1 else "DATA" if flags == 2 else "UNK"
        status = "✓" if match == 100.0 else "✗"

        print(f"{status} {name} [{sym_type}]")
        if addr != "?":
            print(f"   Address: 0x{addr}  Size: {size} bytes  Match: {match}%")
        else:
            print(f"   Size: {size} bytes  Match: {match}%")

        if "instructions" in sym:
            if args.full_both:
                print_ours_full(sym)
                print_target_full(sym)
            elif args.full:
                print_ours_full(sym)
            else:
                # Default: show mismatches for both sides
                print_ours_diff_only(sym)
                print_target_diff_only(sym)

        if "data_diff" in sym:
            diff_lines = format_data_diff(sym.get("data_diff", []))
            if diff_lines:
                print("\n   Data differences:")
                for line in diff_lines:
                    print(line)

        print()

    # Note: This wrapper is intended for symbol-level iteration, so it does not
    # print section-wide match summaries.


if __name__ == "__main__":
    # If output is piped and the reader exits early, exit quietly.
    try:
        main()
    except BrokenPipeError:
        # Hard-exit without running Python cleanup that can emit
        # "Exception ignored ... BrokenPipeError" when stdout is closed.
        os._exit(0)

