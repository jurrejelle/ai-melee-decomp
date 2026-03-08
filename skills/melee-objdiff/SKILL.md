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
python .pi/skills/melee-objdiff/objdiff_wrapper.py it_80271B60 main/melee/it/itcoll
python .pi/skills/melee-objdiff/objdiff_wrapper.py Command_Execute main/melee/lb/lbcommand
```

### Basic: symbol only (may pick wrong unit)
```bash
python .pi/skills/melee-objdiff/objdiff_wrapper.py it_80271B60
```

### Output modes

While iterating, you should almost always use the default mode (paired diff). Full assembly output is noisy and best used occasionally when you get stuck.

- **Default / iterate mode:** show only mismatching instructions, paired side-by-side (ours vs target)
  ```bash
  python .pi/skills/melee-objdiff/objdiff_wrapper.py it_80271B60 main/melee/it/itcoll
  ```

- **Full assembly (ours side only):**
  ```bash
  python .pi/skills/melee-objdiff/objdiff_wrapper.py --full it_80271B60 main/melee/it/itcoll
  ```

- **Full assembly (both sides, paired):** prints full paired side-by-side assembly
  ```bash
  python .pi/skills/melee-objdiff/objdiff_wrapper.py --full-both it_80271B60 main/melee/it/itcoll
  ```

- **Paired diff-only (same as default):**
  ```bash
  python .pi/skills/melee-objdiff/objdiff_wrapper.py --both-diff-only it_80271B60 main/melee/it/itcoll
  ```

- **Section-level summary only (no assembly):**
  ```bash
  python .pi/skills/melee-objdiff/objdiff_wrapper.py --sections it_80271B60 main/melee/it/itcoll
  ```

## How to Find the Unit Name

Unit names are in `objdiff.json` under the `units` array, formatted as:
- `main/melee/lb/lbcommand` (for `src/melee/lb/lbcommand.c`)
- `main/melee/it/itcoll` (for `src/melee/it/itcoll.c`)

Or run with symbol only and it will search all units.

## Output Format

The tool prints outputs in this order:

### 1) Compilation errors (if any)
If the build fails, you'll see the compiler errors so you can fix them first.

### 2) Symbol match summary
Each symbol with:
- ✓ or ✗ status
- name and type (FUNC/DATA)
- address and size
- match percentage

### 3) Assembly listing
Depends on output mode:
- **default / `--both-diff-only`**: paired diff — only mismatching rows, showing both ours and target side-by-side
- **`--full`**: full assembly for ours side with diff markers
- **`--full-both`**: full paired side-by-side assembly for both ours and target

### 4) Section summary (only with `--sections`)
Overall match per section (.text, .data, etc.) — not shown by default.

## Diff Markers

- `>>>` prefix = instruction row has a mismatch
- `---` = gap (this side has no instruction; the other side does)
- `DIFF_ARG_MISMATCH` = same opcode, different operand/register/relocation
- `DIFF_DELETE` = instruction present on this side but not the other
- `DIFF_INSERT` = instruction present on the other side but not this one (shown as `---` gap)
- `DIFF_REPLACE` = completely different instruction

## Tips

- Fix compiler errors first.
- Use the default output mode while iterating.
- If you're stuck on stack layout or scheduling, temporarily use `--full-both` to compare the full instruction streams.

## Notes on making matches
- We aim for "true matches" instead of "fake matches". A true match is code like how the developer has written it, e.g. `var->x3[i*2] = 3`, whereas a fake match is code that technically matches but is "slop", e.g. `*(s16*) var+x3+i*2 = 3`
- Avoid pointer arithmathics for that reason. Most likely, the devs didn't intend to use raw pointer math.
- Any loop like `i=0; do{ blabla; i++} while (i<10)` should be transformed into `for (i=0; i<10; i++){` instead.
- Avoid labels like `after_if:` and `goto after_if`, use control flow, if statements, for/while loops etc instead.
- For structs, label them based on the local offset of the struct. E.g. `struct { /* 0x00 */ u16 x00, /* 0x02 */ u16 x02}` etc. You are allowed to also put the global offset behind the local offset in the comment if it's relevant (e.g. gets referenced from a struct it's embedded in a lot).
- When matching, ignore register swaps. If all instances of a register in the target are actually another register in our code, that can be counted as matched. We will solve that later using a different skill.
- When the stack is off (e.g. there's n bytes on the target stack but not on ours), use `PAD_STACK(n);` to create n bytes on the stack. This can only be done at the end of a stack;
- For statements like `x=n; if(x>0): x=-x`, use `x=ABS(n)` instead.
- For statements like `x=n; if(x>m): x=m` use `x=MIN(n,m)` instead. Same goes for `MAX(n,m)`
