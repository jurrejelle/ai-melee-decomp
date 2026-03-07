---
name: melee-objdiff
description: Runs objdiff-cli on a function/symbol, builds the unit first, and shows match percentage and assembly diffs. Can optionally print full assembly for both sides.
---

# Melee objdiff Skill

This skill runs `objdiff-cli` to compare your decompiled C code against the original binary.

It automatically builds the relevant unit first (when you pass a unit name) and then shows match percentage and assembly diffs.

## Setup

No setup required. The skill uses:
- `objdiff-cli` binary
- Project's `objdiff.json` configuration
- `ninja` build system (auto-invoked to compile before diffing)

**Auto-build:** The skill always tries to compile the unit first. If compilation fails, it shows the compiler errors before displaying the diff results.

## Usage

Provide a symbol name and optionally a unit name to diff:

### Recommended: with Unit Name (precise)
```bash
python /home/sysop/.claude/skills/melee-objdiff/objdiff_wrapper.py it_80271B60 main/melee/it/itcoll
python /home/sysop/.claude/skills/melee-objdiff/objdiff_wrapper.py Command_Execute main/melee/lb/lbcommand
```

### Basic: symbol only (may pick wrong unit)
```bash
python /home/sysop/.claude/skills/melee-objdiff/objdiff_wrapper.py it_80271B60
```

### Output modes

While iterating, you should almost always use the default mode (diff-focused). Full assembly output is noisy and best used occasionally when you get stuck.

- **Default / iterate mode:** show only mismatching instructions
  ```bash
  python /home/sysop/.claude/skills/melee-objdiff/objdiff_wrapper.py it_80271B60 main/melee/it/itcoll
  ```

- **Full assembly (ours side):**
  ```bash
  python /home/sysop/.claude/skills/melee-objdiff/objdiff_wrapper.py --full it_80271B60 main/melee/it/itcoll
  ```


- **Full assembly (both sides):** prints full assembly for both *ours* and *target*
  ```bash
  python .pi/skills/melee-objdiff/objdiff_wrapper.py --full-both it_80271B60 main/melee/it/itcoll
  ```

- **Diff-only for both sides:**
  ```bash
  python .pi/skills/melee-objdiff/objdiff_wrapper.py --both-diff-only it_80271B60 main/melee/it/itcoll
  ```

## How to Find the Unit Name

Unit names are in `objdiff.json` under the `units` array, formatted as:
- `main/melee/lb/lbcommand` (for `src/melee/lb/lbcommand.c`)
- `main/melee/it/itcoll` (for `src/melee/it/itcoll.c`)

Or run with symbol only and it will search all units.

## Output Format

The tool prints outputs in this order:

### 1) Compilation errors (if any)
If the build fails, you’ll see the compiler errors so you can fix them first.

### 2) Symbol match summary
Each symbol with:
- ✓ or ✗ status
- name and type (FUNC/DATA)
- address and size
- match percentage

### 3) Assembly listing
Depends on output mode:
- default: mismatches only
- `--full`: full assembly for ours with diff markers
- `--full-both`: full assembly for ours and target
- `--both-diff-only`: only mismatches, printed for ours and target

### 4) Section summary
Overall match per section (.text, .data, etc.)

### 5) Final verdict
Perfect match or partial match indicator.

## Diff Markers

- `>>>` prefix = instruction has a mismatch
- `DIFF_ARG_MISMATCH` = argument/register mismatch
- `DIFF_DELETE` = instruction missing in ours
- `DIFF_INSERT` = extra instruction in ours
- `DIFF_REPLACE` = different instruction

## Tips

- Fix compiler errors first.
- Use the default output mode while iterating.
- If you’re stuck on stack layout or scheduling, temporarily use `--full-both` to compare the full instruction streams.

## Notes on making matches
- We aim for "true matches" instead of "fake matches". A true match is code like how the developer has written it, e.g. `var->x3[i*2] = 3`, whereas a fake match is code that technically matches but is "slop", e.g. `*(s16*) var+x3+i*2 = 3`
- Avoid pointer arithmathics for that reason. Most likely, the devs didn't intend to use raw pointer math.
- Any loop like `i=0; do{ blabla; i++} while (i<10)` should be transformed into `for (i=0; i<10; i++){` instead.
- Avoid labels like `after_if:` and `goto after_if`, use control flow, if statements, for/while loops etc instead.
- For structs, label them based on the local offset of the struct. E.g. `struct { /* 0x00 */ u16 x00, /* 0x02 */ u16 x02}` etc. You are allowed to also put the global offset behind the local offset in the comment if it's relevant (e.g. gets referenced from a struct it's embedded in a lot).

