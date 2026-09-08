#!/usr/bin/env python3
"""Explain ProDG/GCC 2.x register allocation for a decomp function.

Re-compiles a unit with the compiler's own -dl/-dg RTL dumps (local-alloc and
global-alloc), then reports, per allocno: reference count, live length, the
exact allocno_compare priority GCC used to order allocation, the preferred
register class and the hard register it finally got.

Why this matters for matching: when a function is structurally correct (DWARF
matches) but the registers are permuted, the cause is almost always one extra
allocno stealing a callee-saved register, which shifts everything below it in
the priority order. This shows you which allocno that is and what it holds.

  regalloc.py -u <unit> -f '<function>' --target
  regalloc.py -u <unit> --list
  regalloc.py -u <unit> -f '<fn>' --reg 145        # what pseudo 145 actually holds
  regalloc.py -u <unit> -f '<fn>' --cflags=-fno-gcse

Run from anywhere inside the decomp checkout, or set NFSMW_REPO to point at it.
"""
import argparse, hashlib, json, os, re, shlex, subprocess, sys
from pathlib import Path

def find_repo():
    """$NFSMW_REPO, else the nearest enclosing directory holding objdiff.json."""
    env = os.environ.get("NFSMW_REPO")
    if env:
        return Path(env).resolve()
    for d in [Path.cwd(), *Path.cwd().parents]:
        if (d / "objdiff.json").exists():
            return d
    sys.exit("not inside a decomp checkout (no objdiff.json found above the "
             "current directory); cd into it or set NFSMW_REPO")


REPO = find_repo()
CACHE = Path(os.environ.get("XDG_CACHE_HOME", "/tmp")) / "nfsmw-regalloc"

# rs6000.h: 0-31 GPR, 32-63 FPR, 64 mq, 65 lr, 66 ctr, 67 ap, 68-75 cr0-7, 76 fpmem
def regname(n):
    if n < 0: return "-"
    if n < 32: return f"r{n}"
    if n < 64: return f"f{n-32}"
    return {64: "mq", 65: "lr", 66: "ctr", 67: "ap", 76: "fpmem"}.get(n, f"cr{n-68}")

# CALL_USED_REGISTERS from config/rs6000/rs6000.h
CALL_USED = ([1]*13 + [1] + [0]*18) + ([1]*14 + [0]*18) + [1,1,1,1, 1,1,0,0,0, 1,1,1,1]

def callee_saved(n):
    return 0 <= n < len(CALL_USED) and not CALL_USED[n]

def floor_log2(x):
    return -1 if x <= 0 else x.bit_length() - 1

def priority(n_refs, live_length, size):
    """GCC 2.x global.c:allocno_compare()."""
    if live_length <= 0: return 0.0
    return (floor_log2(n_refs) * n_refs / live_length) * 10000 * size

def compile_command(unit):
    cfg = json.loads((REPO / "objdiff.json").read_text())
    base = next((u["base_path"] for u in cfg["units"] if u["name"] == unit), None)
    if base is None:
        sys.exit(f"unit not found in objdiff.json: {unit}")
    out = subprocess.run(["ninja", "-t", "commands", base], cwd=REPO,
                         capture_output=True, text=True).stdout.strip().splitlines()
    cmd = next((c for c in reversed(out) if "ngccc.exe" in c), None)
    if cmd is None:
        sys.exit(f"no compile command found for {base}")
    return cmd.split(" && ")[0], base

def run_dumps(unit, refresh=False, extra=""):
    cmd, base = compile_command(unit)
    key = hashlib.sha1((unit + cmd + extra).encode()).hexdigest()[:12]
    d = CACHE / key
    src = next((t for t in shlex.split(cmd) if t.endswith((".cpp", ".c"))), None)
    stamp = d / "stamp"
    newest = 0
    dep = REPO / (base.rsplit(".", 1)[0] + ".d")
    if dep.exists():
        for tok in dep.read_text().replace("\\\n", " ").split():
            if tok.endswith((":", "\\")): continue
            p = Path(tok if os.path.isabs(tok) else REPO / tok)
            try: newest = max(newest, p.stat().st_mtime)
            except OSError: pass
    if not refresh and stamp.exists() and float(stamp.read_text() or 0) >= newest:
        g = sorted(d.glob("*.greg")); l = sorted(d.glob("*.lreg"))
        if g and l: return g[0], l[0]
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*"): f.unlink()
    toks = shlex.split(cmd)
    # the command runs from REPO; we run it from the dump dir, so absolutise paths
    for i, t in enumerate(toks):
        if t.startswith(("build/", "src/")) and not os.path.isabs(t):
            toks[i] = str(REPO / t)
        elif t.startswith("SN_NGC_PATH=") and not os.path.isabs(t.split("=", 1)[1]):
            toks[i] = "SN_NGC_PATH=" + str(REPO / t.split("=", 1)[1])
    for i, t in enumerate(toks):
        if t in ("-I", "-i") and i + 1 < len(toks) and not os.path.isabs(toks[i+1]):
            toks[i+1] = str(REPO / toks[i+1])
        if t == "-o":
            toks[i+1] = str(d / "out.o")
    exe = next(i for i, t in enumerate(toks) if "ngccc" in t)
    toks = toks[:exe+1] + ["-dg", "-dl"] + toks[exe+1:] + shlex.split(extra)  # extra last: overrides
    env = dict(os.environ, SN_NGC_PATH=str(REPO / "build/compilers/ProDG/3.9.3"))
    r = subprocess.run(toks, cwd=d, capture_output=True, text=True, env=env)
    g = sorted(d.glob("*.greg")); l = sorted(d.glob("*.lreg"))
    if not g or not l:
        sys.exit("compiler produced no dumps:\n" + r.stderr[-2000:])
    stamp.write_text(str(newest))
    return g[0], l[0]

def split_functions(path):
    text = path.read_text(errors="replace")
    parts = re.split(r"^;; Function (.*)$", text, flags=re.M)
    return {parts[i].strip(): parts[i+1] for i in range(1, len(parts) - 1, 2)}

LREG_RE = re.compile(
    r"^Register (\d+) used (\d+) times? across (\d+) insns?"
    r"(?: in block (\d+))?; set (\d+) times?;(.*?)\.$", re.M)

def parse_lreg(body):
    regs = {}
    for m in LREG_RE.finditer(body):
        n, refs, length, block, sets, rest = m.groups()
        pref = re.search(r"pref ([A-Z_0-9]+)(?:, else ([A-Z_0-9]+))?", rest)
        regs[int(n)] = dict(
            refs=int(refs), length=int(length), sets=int(sets),
            block=int(block) if block else None,
            uservar="user var" in rest, pointer="pointer" in rest,
            pref=pref.group(1) if pref else "", pref2=pref.group(2) if pref and pref.group(2) else "")
    return regs

def parse_greg(body):
    order, disp, hard, conflicts, prefs, sizes = [], {}, [], {}, {}, {}
    m = re.search(r";; \d+ regs to allocate:(.*)", body)
    if m:
        for tok in re.finditer(r"(\d+(?:\+\d+)*)(?:\s+\((\d+)\))?", m.group(1)):
            ids = [int(x) for x in tok.group(1).split("+")]
            order.append(ids[0]); sizes[ids[0]] = int(tok.group(2) or 1)
    for m in re.finditer(r";; (\d+) conflicts:(.*)", body):
        conflicts[int(m.group(1))] = m.group(2).split()
    for m in re.finditer(r";; (\d+) preferences:(.*)", body):
        prefs[int(m.group(1))] = [int(x) for x in m.group(2).split()]
    m = re.search(r";; Register dispositions:\n(.*?)\n\n", body, re.S)
    if m:
        for a, b in re.findall(r"(\d+) in (-?\d+)", m.group(1)):
            disp[int(a)] = int(b)
    m = re.search(r";; Hard regs used:(.*)", body)
    if m:
        hard = [int(x) for x in m.group(1).split()]
    return order, disp, hard, conflicts, prefs, sizes

def target_prologue(unit, func):
    """What the retail object actually saves: frame size + callee-saved set."""
    cfg = json.loads((REPO / "objdiff.json").read_text())
    tgt = next((u.get("target_path") for u in cfg["units"] if u["name"] == unit), None)
    if not tgt or not (REPO / tgt).exists(): return None
    rep = json.loads((REPO / "build/GOWE69/report.json").read_text())
    sym = size = None
    for u in rep["units"]:
        if u["name"] != unit: continue
        for f in (u.get("functions") or []):
            dem = f.get("metadata", {}).get("demangled_name", "")
            if func.lower() in dem.lower() or func.lower() in f["name"].lower():
                sym, size = f["name"], int(f["size"]); break
    if not sym: return None
    od = REPO / "build/ppc_binutils/powerpc-eabi-objdump"
    if not od.exists(): return None
    syms = subprocess.run([str(od), "-t", str(REPO / tgt)], capture_output=True, text=True).stdout
    m = re.search(rf"^([0-9a-f]+).*\s{re.escape(sym)}$", syms, re.M)
    if not m: return None
    start = int(m.group(1), 16)
    dis = subprocess.run([str(od), "-d", "--no-show-raw-insn",
                          f"--start-address={start}",
                          f"--stop-address={start+size}", str(REPO / tgt)],
                         capture_output=True, text=True).stdout
    # Only scan operands: --no-show-raw-insn is used, but the address column
    # would still match, and objdump misdecodes paired-single psq_st/psq_l as
    # VSX, so the prologue is not a reliable place to read the saved set from.
    # Any callee-saved register appearing at all must have been saved.
    frame, used = None, set()
    for line in dis.splitlines():
        m = re.match(r"\s*[0-9a-f]+:\s+(\S+)\s*(.*)", line)
        if not m: continue
        mnem, ops = m.groups()
        if mnem == "stwu" and frame is None:
            f = re.search(r"r1,(-?\d+)\(r1\)", ops)
            if f: frame = -int(f.group(1))
        for mm in re.finditer(r"\b([rf])(\d{1,2})\b", ops):
            used.add(int(mm.group(2)) + (0 if mm.group(1) == "r" else 32))
    return dict(sym=sym, frame=frame, used=sorted(used),
                saved=sorted(r for r in used if callee_saved(r)))

def pick(funcs, want):
    if want in funcs: return want
    hits = [k for k in funcs if want.lower() in k.lower()]
    if len(hits) == 1: return hits[0]
    if not hits: sys.exit(f"no function matching {want!r}; try --list")
    sys.exit("ambiguous, matches:\n  " + "\n  ".join(hits[:20]))

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-u", "--unit", required=True)
    ap.add_argument("-f", "--function")
    ap.add_argument("--list", action="store_true", help="list functions in the unit")
    ap.add_argument("--reg", type=int, help="show RTL insns mentioning this pseudo")
    ap.add_argument("--limit", type=int, default=0, help="only show the first N allocnos")
    ap.add_argument("--refresh", action="store_true", help="force recompile of the dumps")
    ap.add_argument("--target", action="store_true",
                    help="also report what the retail object saves, and the delta")
    ap.add_argument("--cflags", default="", help="extra compiler flags, for isolating which pass creates an allocno")
    a = ap.parse_args()

    greg_path, lreg_path = run_dumps(a.unit, a.refresh, a.cflags)
    greg, lreg = split_functions(greg_path), split_functions(lreg_path)

    if a.list or not a.function:
        for k in sorted(greg): print(k)
        return

    name = pick(greg, a.function)
    order, disp, hard, conflicts, prefs, sizes = parse_greg(greg[name])
    stats = parse_lreg(lreg.get(name, ""))

    if a.reg is not None:
        body = lreg.get(name, "")
        pat = re.compile(rf"\breg(?:/[a-z]+)*:[A-Z]+ {a.reg}\b")
        for blk in re.split(r"\n\n", body):
            if pat.search(blk): print(blk.strip() + "\n")
        return

    print(f";; {name}")
    print(f";; unit {a.unit}")
    print(f";; allocation order is by descending priority "
          f"(floor_log2(refs)*refs/live_length)*10000*size\n")
    hdr = f"{'#':>3} {'pseudo':>6} {'->':>5} {'refs':>5} {'live':>5} {'sz':>3} {'priority':>12}  {'class':<16} {'flags':<10} prefers"
    print(hdr); print("-" * len(hdr))
    rows = order if not a.limit else order[:a.limit]
    for i, pid in enumerate(rows):
        s = stats.get(pid, {})
        refs, length = s.get("refs", 0), s.get("length", 0)
        sz = sizes.get(pid, 1)
        hr = disp.get(pid, -1)
        flags = []
        if s.get("uservar"): flags.append("var")
        if s.get("pointer"): flags.append("ptr")
        if callee_saved(hr): flags.append("SAVED")
        pr = ",".join(regname(x) for x in prefs.get(pid, [])[:4])
        print(f"{i:>3} {pid:>6} {regname(hr):>5} {refs:>5} {length:>5} {sz:>3} "
              f"{priority(refs, length, sz):>12.1f}  {s.get('pref',''):<16} "
              f"{'+'.join(flags):<10} {pr}")

    used_saved = sorted({r for r in hard if callee_saved(r)})
    print(f"\n;; hard regs used: {' '.join(regname(r) for r in hard)}")
    print(f";; callee-saved:   {' '.join(regname(r) for r in used_saved) or '(none)'}"
          f"   -> {len(used_saved)} to save/restore")
    for r in used_saved:
        who = [p for p, h in disp.items() if h == r]
        for p in who:
            s = stats.get(p, {})
            print(f";;   {regname(r):<4} = pseudo {p} "
                  f"({s.get('refs',0)} refs / {s.get('length',0)} insns"
                  f"{', user var' if s.get('uservar') else ''})"
                  f"   [--reg {p} to see it]")

    if a.target:
        t = target_prologue(a.unit, a.function)
        if not t:
            print(";; (no target object / symbol found for --target)")
            return
        tset = [regname(r) for r in t["saved"]]
        print(f"\n;; target {t['sym']}")
        print(f";; target callee-saved: {' '.join(tset) or '(none)'}"
              f"   frame {t['frame'] if t['frame'] is not None else '?'}")
        ours = {r for r in hard if r < 64}
        theirs = {r for r in t["used"] if r != 1}       # r1 = sp, always present
        only_t = sorted(theirs - ours); only_o = sorted(ours - theirs)
        if only_t or only_o:
            print(f";; regs retail uses that we do not: "
                  f"{' '.join(regname(r) for r in only_t) or '(none)'}")
            print(f";; regs we use that retail does not: "
                  f"{' '.join(regname(r) for r in only_o) or '(none)'}")
        d = len(used_saved) - len(t["saved"])
        if d == 0:
            print(";; MATCH on saved-register count.")
        else:
            print(f";; {abs(d)} {'MORE' if d > 0 else 'FEWER'} callee-saved than retail -> "
                  f"{'an extra allocno is stealing one; kill it and the order below it shifts back'
                     if d > 0 else 'we are missing a long-lived value retail keeps'}")
            if d > 0:
                extra = [p for p in reversed(order)
                         if callee_saved(disp.get(p, -1))][:d]
                for p in extra:
                    st = stats.get(p, {})
                    print(f";; lowest-priority saved allocno: pseudo {p} -> {regname(disp[p])} "
                          f"({st.get('refs',0)} refs / {st.get('length',0)} insns, "
                          f"priority {priority(st.get('refs',0), st.get('length',0), sizes.get(p,1)):.1f})")

if __name__ == "__main__":
    main()
