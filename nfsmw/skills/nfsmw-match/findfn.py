#!/usr/bin/env python3
"""Find which TU holds a function. Mangled or demangled, substring, case-insensitive.

    findfn.py UpdateMixerOutputs__14SFXCTL_Physics
    findfn.py 'SFXCTL_Physics::Update'
"""
import json
import os
import sys

REPORT = os.environ.get(
    "NFSMW_REPORT", "/home/shared/nfsmw/nfsmw/build/GOWE69/report.json"
)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    query = sys.argv[1].lower()
    with open(REPORT, encoding="utf-8") as f:
        report = json.load(f)

    hits = []
    for unit in report["units"]:
        for func in unit.get("functions") or []:
            name = func.get("name", "") or ""
            demangled = (func.get("metadata") or {}).get("demangled_name", "") or ""
            if query in name.lower() or query in demangled.lower():
                hits.append((func, unit["name"], demangled or name))

    if not hits:
        print(f"no match for {sys.argv[1]!r} in {REPORT}", file=sys.stderr)
        return 1

    hits.sort(key=lambda h: -int(h[0].get("size", 0) or 0))
    for func, unit, label in hits:
        pct = func.get("fuzzy_match_percent", 0.0)
        size = int(func.get("size", 0) or 0)
        print(f"{pct:6.2f}%  {size:>6}B  {label}")
        print(f"          unit: {unit}")
        print(f"          diff: -u {unit} -d '{label}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
