---
name: nfsmw-match
description: Inspect an NFS:MW (GameCube GOWE69) decomp function before matching it — list what's left in a TU, read the objdiff instruction diff, and pull the original DWARF (inline tree, local names, register homes). Use when the user names a function or unit to work on in the nfsmw decomp.
---

# NFS:MW decomp — inspect before you edit

    REPO=/home/shared/nfsmw/nfsmw
    PY=/home/shared/nfsmw/nfsmw_venv/bin/python   # NOT system python
    cd $REPO && ninja                              # rebuild; regenerates build/GOWE69/report.json

Two independent axes. Never conflate them:
- **code %** — do the emitted bytes equal retail? (`build/GOWE69/report.json`, objdiff)
- **DWARF %** — is the source *shaped* like the original? (`symbols/Dwarf/`, dwarf-compare)

A function can be 98% code / 100% DWARF (structure right, regalloc wrong) or the reverse.

## 0. Optional — what's left

Unit names come from `objdiff.json`. Ranked worklist inside one unit:

    $PY tools/decomp-diff.py -u <unit> -s nonmatching --sort unmatched --limit 20

Columns: `STATUS MATCH UNMATCH SIZE SECTION NAME`. Sort by **UNMATCH**, not match% — a 99.8%
1000B function has more bytes left than a 31% 40B one.

Units ranked by remaining bytes, and whether a unit is untouched (`fuzzy 0.00%`, needs source
written from scratch) vs partial (needs per-function work):

    $PY -c "
    import json;d=json.load(open('build/GOWE69/report.json'))
    r=[(int(u['measures'].get('total_code',0))-int(u['measures'].get('matched_code',0)),
        int(u['measures'].get('total_code',0)),u['measures'].get('fuzzy_match_percent',0),u['name'])
       for u in d['units'] if int(u['measures'].get('total_code',0))]
    r.sort(reverse=True)
    [print(f'{a:>9,} left of {b:>9,}  fuzzy {c:6.2f}%  {n}') for a,b,c,n in r[:15]]"

## Find the unit for a symbol the user names

Accepts mangled or demangled, substring, case-insensitive:

    $PY ~/.claude/skills/nfsmw-match/findfn.py UpdateMixerOutputs__14SFXCTL_Physics

## 1. Code diff

    $PY tools/decomp-diff.py -u <unit> -d '<demangled symbol>' -C 0    # mismatches only
    $PY tools/decomp-diff.py -u <unit> -d '<demangled symbol>' -C 6    # with context
    ... --range 19e00-1a200        # zoom
    ... --reloc-diffs all          # surface relocation-only diffs (default: none)

Columns are `OFFSET | LEFT | LINE | RIGHT`. **LEFT = target (retail), RIGHT = ours.**
Confirm by the label style: LEFT has synthesized `$LC2151511324`, RIGHT has real mwcc `$LC796`.

Markers: `<` target-only (we're missing it) · `>` ours-only (we emit extra) · `~` changed.

Start with `-C 0` — it collapses 300 instructions to the handful that matter. Then classify:
- **register substitution / extra `lis` reloads** → regalloc or CSE, logic is fine. Source-shape
  problem: hoist a repeated subexpression to a local, reorder calls, change an inline's shape.
- **branch-target (`b`/`bso`) diffs adjacent to an add/drop** → usually *downstream* of the
  instruction-count shift, not independent. Fix the cause first, re-diff.
- **different opcodes / operands / call targets** → real logic or type error; go to DWARF.

`tools/flag_permuter.py` automates source-form search when hand-guessing stalls.

## 2. DWARF

One bundled view — objdiff status + original DWARF + debug-line mapping to the original file:line:

    $PY tools/decomp-context.py -u <unit> -f '<fn>' --no-source --no-ghidra --brief
    ... --lookup-mode signature    # trim; default `full` prints the whole inline tree

Structural score of our rebuilt DWARF vs the original's:

    $PY tools/dwarf-compare.py -u <unit> -f '<fn>' --summary      # % + change groups
    ... --full-diff                # line-level diff
    ... --require-exact

The original DWARF gives what disassembly cannot: **the inline tree with per-inline address
ranges**, original local/parameter names, and **which register each local lived in**
(`// this: r30`, `unsigned int key; // r23`, `struct TypeCounter t; // r1+0x8`). When the code
diff is a regalloc problem, this is the evidence that tells you what the source looked like.

Aggregate report (all units): `$PY tools/generate-dwarf-report.py` → `build/GC_Dwarf/report.json`.

## Optional — Ghidra decompile

Headless CLI, program already checked out from the decomp.dev shared project:

    ghidra decompile '<fn>'      # ~/.local/bin/ghidra, default_program NFSMWRELEASE.ELF
    ghidra stop                  # bridge stays resident between calls

Useful for control flow, but it invents `local_60`/`iVar5` names and open-codes STL. Prefer the
DWARF inline tree when deciding what to write.

## Gotchas

- `decomp-context.py` prints "Suggested Next Commands" referencing **`tools/decomp-workflow.py`,
  which does not exist**. Stale. Use `decomp-diff.py` / `dwarf-compare.py` directly.
- `dwarf-compare.py` needs `pyelftools` (installed in the venv; not in `requirements.txt`).
- DWARF tools need `symbols/Dwarf/` — regenerate via setup.md step 6 if absent.
- `$LC<number>` labels are **not** virtual addresses. Don't decode them; read the constant from
  the objdiff operand instead.
- `fuzzy_match_percent` ≠ progress toward the DOL. Only `matched_code` counts for `build.sha1`.
- Rebuild before trusting any diff — every tool here reads the last-built `.o`.

## Worked example

`SFXCTL_Physics::UpdateMixerOutputs` (`zEAXSound`, 0x800BFFC8, 1212B): 98.22% code, 13 mismatched
instructions — but **100% DWARF (280/280)**. `-C 0` showed all 13 tracing to one cause: retail
hoists `lis r7, $LC…@ha` once and keeps it live across four inlined `sqrtf` fallbacks; we
rematerialize `lis r9` before each `lfs`. The four `bso` diffs were downstream displacement
shifts. Structure already correct → source-shape/regalloc fix, not a logic fix.
