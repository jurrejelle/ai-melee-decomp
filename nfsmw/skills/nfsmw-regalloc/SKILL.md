---
name: nfsmw-regalloc
description: Explain why an NFS:MW (ProDG/GCC) decomp function has permuted registers, a different frame size, or one register too many — by dumping the compiler's own allocator state and diffing it against the retail object. Use when a function is structurally correct (DWARF matches) but the code diff is register substitutions, or when you are about to guess at source rewrites to shift an allocation.
---

# Why the registers are wrong

Use this **before** guessing at source rewrites. A function whose DWARF matches
but whose diff is register substitutions is not a logic problem, and reshuffling
statements to see what sticks wastes hours. The compiler will just tell you.

`regalloc.py` sits in this skill's directory and needs only the standard
library. Run it from anywhere inside the decomp checkout — it finds the repo by
walking up to `objdiff.json`, or set `NFSMW_REPO`.

    python3 regalloc.py -u <unit> -f '<function>' --target

## The one thing to know

`ngccc.exe` is GCC 2.x. Global register allocation is a **single descending
pass over one priority number** (`global.c:allocno_compare`):

    pri = (floor_log2(n_refs) * n_refs / live_length) * 10000 * size

Registers are handed out in that order, each allocno taking the first free
register of its class. So **one extra allocno shifts everything below it**. That
is the entire mechanism behind "the registers are permuted for no reason".

Two consequences worth holding on to:

- **`floor_log2` cliffs at powers of two.** An allocno with 8 refs outranks one
  with 13 refs over a longer range, because `floor_log2(8)=3` and the quotient
  wins. A value at 7 refs ranks far below the same value at 8. When two
  long-lived values hold each other's registers, check the cliff before
  rewriting anything.
- **Priority uses RTL refs, not the refs you can see in the asm.** Read them off
  the dump; do not count `lwz`s.

## Reading the report

    ;; allocation order is by descending priority
      #  pseudo    ->  refs  live  sz     priority  class          flags      prefers
     36      82   r31     8   180   1       1333.3  BASE_REGS      var+ptr+SAVED r3
     37     125   r30    13   316   1       1234.2  GENERAL_REGS   SAVED
     41     128   r28     3   314   1         95.5  BASE_REGS      ptr+SAVED

    ;; callee-saved:   r28 r29 r30 r31   -> 4 to save/restore
    ;; target callee-saved: r29 r30 r31   frame 40
    ;; regs we use that retail does not: r28
    ;; 1 MORE callee-saved than retail -> an extra allocno is stealing one
    ;; lowest-priority saved allocno: pseudo 128 -> r28 (3 refs / 314 insns)

`--target` disassembles the retail object and diffs the register sets. The two
shapes it distinguishes:

- **"N MORE callee-saved than retail"** — we materialise a value retail doesn't.
  Kill that allocno and the order below it snaps back. Start at the named
  lowest-priority one.
- **"regs retail uses that we do not"** with a matching saved count — retail
  keeps something live in a *volatile* register that we rematerialise. Usually a
  hoisted constant address kept across several uses.

## Then: what is it, and who made it

    python3 regalloc.py -u <unit> -f '<fn>' --reg 128

prints the RTL insns that mention that pseudo. `(set (reg:SI 128) (high:SI
(symbol_ref "*$LC930")))` is a hoisted constant *address*; a `(mem/u:DF ...)`
with a `REG_EQUIV` `const_double` of `0x4330000080000000` is the int→double
conversion magic.

Then bisect the pass that created it — extra flags are appended last, so they
override the build's:

    python3 regalloc.py -u <unit> -f '<fn>' --cflags=-fno-gcse
    ... --cflags=-fno-move-all-movables    ... --cflags=-fno-rerun-loop-opt

Watch the `;; callee-saved:` line. When one flag reproduces retail's set, that
pass is the culprit — **do not adopt the flag** (unit-wide flags are already
tuned; `-fno-gcse` alone costs zEAXSound2 ~100 matched functions). Use it as a
fast binary oracle while you screen source shapes: `saved == retail's set` beats
watching a fuzzy percentage crawl.

## Worked outcomes

- `GinsuSynthData::SampleToCycle` — 4 saved vs retail's 3. Extra is pseudo 128,
  `high(*$LC930)`, priority 95.5 (dead last, 3 refs over 314 insns). GCSE hoists
  it out of the loop; `-fno-gcse` gives retail's exact 3. Every other register
  difference in the function is downstream of that one hoist.
- `SFXCTL_Physics::UpdateMixerOutputs` — saved count *matches*; `regs retail
  uses that we do not: r7`. Retail keeps the `0.0f` literal address in r7 across
  four inlined `bSqrt` fallbacks; we re-`lis` it each time. Different shape, so
  hunting a callee-saved culprit there would have been wasted effort.

## Gotchas

- `--cflags` needs `=`: `--cflags=-fno-gcse`, not `--cflags -fno-gcse` (argparse
  eats the leading dash).
- Dumps are cached under `/tmp/nfsmw-regalloc` keyed on the compile command,
  invalidated by the unit's `.d` dependency mtimes. `--refresh` forces a rebuild;
  do that after editing a header the `.d` file misses.
- Function names come from `decl_printable_name`, so they look like
  `float GinsuSynthData::SampleToCycle(int) const`. Substring match is fine;
  `--list` shows them all.
- The report describes **our** build. Retail's allocator state is gone — you only
  get its register set back via `--target`. Reason from the delta, not from an
  imagined retail dump.
- Dumping a whole SourceList is ~2.4s and ~40MB of RTL. That is fine; do not try
  to carve out a minimal TU first.
