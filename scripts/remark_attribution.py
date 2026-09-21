#!/usr/bin/env python3
"""Attribute LLVM text remarks back to the target crate's functions.

SPEC.ja.md 7 spells the problem out: the only remark mechanism that survives
fat LTO on the pinned toolchain is LLVM's plain-text stderr remarks, and those
carry a DebugLoc (`file:line:col`) but **no function name**. After inlining the
DebugLoc of an iterator loop points into `library/core/...`, where std's own
loops live too, so the remark text alone cannot say which loop is which.

The spec's remedy, implemented here:

  1. take each remark's `file:line`;
  2. find the addresses in the strip-free, debuginfo=1 binary whose innermost
     DWARF frame is that `file:line`;
  3. expand each address's inline chain with `addr2line -i -f -p -C` and
     attribute it to a function.

Two attributions are produced for every address, because they answer different
questions:

  `owner`  the OUTERMOST frame, i.e. the real function in the binary. This is
           the `owner_fn` of the Stage 2 site key (SPEC.ja.md 8.2).
  `site`   the INNERMOST frame whose file is under --src-prefix, i.e. the
           target's own function whose source text contains the loop. This is
           what "which zopfli function has a vectorized loop" means.

A `file:line` that resolves to more than one function is `ambiguous` and is
reported as such with its candidate set (SPEC.ja.md 7 step 3); no attempt is
made to pair individual remark lines with individual inline instances, because
the text carries no handle for it.

Only symbols matching --sym-filter are walked, which bounds the disassembly to
the target's own code plus whatever was inlined into it.

Usage:
  scripts/remark_attribution.py --bin <unstripped binary> --log <build log> \
      --src-prefix zopfli/src --sym-filter zopfli --out artifacts/zopfli-attr
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# remark parsing
# ---------------------------------------------------------------------------

REMARK_RE = re.compile(r"^remark: (?P<file>[^ ]+?):(?P<line>\d+):(?P<col>\d+): (?P<text>.*)$")

VECTORIZED_RE = re.compile(
    r"^vectorized loop \(vectorization width: (?P<vf>\d+), interleaved count: (?P<ic>\d+)\)")
NOTVEC_RE = re.compile(r"^loop not vectorized:?\s*(?P<reason>.*)$")
INTERLEAVED_RE = re.compile(r"^interleaved loop \(interleaved count: (?P<ic>\d+)\)")

# SPEC.ja.md 4's remark-reason-map.json, LLVM 23.1.1. The first nine are the
# seeds hand-classified in results.md Day 0 section 6; anything not listed
# stays `unknown` by construction, which is the rule the spec fixes.
REASON_CLASS = {
    # --- legality: no loop metadata can lift these ---
    "Incorrect number of successors from early exiting block": "legality",
    "Loop contains an unsupported switch": "legality",
    "cannot prove it is safe to reorder floating-point operations": "legality",
    "Cannot vectorize early exit loop": "legality",
    "cannot identify array bounds": "legality",
    "unsafe dependent memory operations in loop. Use "
    "#pragma clang loop distribute(enable) to allow loop distribution to "
    "attempt to isolate the offending operations into a separate loop": "legality",
    "cannot prove it is safe to reorder memory operations": "legality",
    "loop contains a switch statement": "legality",
    # --- unsupported: the vectorizer has no lowering for the shape ---
    "could not determine number of loop iterations": "unsupported",
    "call instruction cannot be vectorized": "unsupported",
    "value that could not be identified as reduction is used outside the loop":
        "unsupported",
    "Control flow cannot be substituted for a select": "unsupported",
    "loop induction variable could not be identified": "unsupported",
    "loop control flow is not understood by vectorizer": "unsupported",
    "control flow cannot be substituted for a select": "unsupported",
    "loop not vectorized": "unsupported",
    "Unsupported outer loop": "unsupported",
    "instruction return type cannot be vectorized": "unsupported",
    "loop contains a non-vectorizable instruction": "unsupported",
    # --- cost: the decision the hints are aimed at ---
    "the cost-model indicates that vectorization is not beneficial": "cost",
    "the cost-model indicates that interleaving is not beneficial": "cost",
    "the cost-model indicates that vectorization is not beneficial and "
    "user-specified vectorization is not enabled": "cost",
    "the cost-model indicates that interleaving is not beneficial and "
    "is explicitly disabled or interleave count is set to 1": "cost",
    "vectorization is not beneficial and is not explicitly forced": "cost",
    "will not try to vectorize a loop with a runtime check": "cost",
}


def classify(reason):
    r = reason.strip().rstrip(".")
    if r in REASON_CLASS:
        return REASON_CLASS[r]
    low = r.lower()
    # Substring fallbacks, applied only after the exact table misses. Anything
    # they do not catch stays `unknown`, as SPEC.ja.md 8.3 requires.
    if "cost-model" in low or "not beneficial" in low:
        return "cost"
    return "unknown"


SLP_RE = re.compile(r"^(List vectorization|Vectorized horizontal reduction|"
                    r"Vectorizing (ordered|horizontal) reduction|Cannot SLP vectorize|"
                    r"Stores SLP vectorized|SLP vectorized)")


def parse_remarks(path):
    """-> rows, each with a `kind`:

    vectorized   "vectorized loop (vectorization width: N, interleaved count: M)"
                 --- one per loop the loop vectorizer transformed.
    declined     the bare "loop not vectorized" line --- LLVM emits this as the
                 *missed* remark and puts the why in separate analysis lines,
                 so this line, not the reason count, is the number of loops
                 that were offered and refused.
    reason       "loop not vectorized: <reason>", and the standalone analysis
                 remarks that carry a reason without repeating the prefix
                 ("the cost-model indicates that vectorization is not
                 beneficial"). Several reasons can attach to one declined loop.
    slp          SLP-vectorizer remarks; counted, but they are not loop
                 decisions and no loop-metadata hint reaches them.
    """
    rows = []
    with open(path, errors="replace") as f:
        for line in f:
            m = REMARK_RE.match(line.rstrip("\n"))
            if not m:
                continue
            text = m.group("text")
            row = {"file": m.group("file"), "line": int(m.group("line")),
                   "col": int(m.group("col")), "vf": None, "ic": None,
                   "reason": None, "reason_class": None, "text": text}
            mm = VECTORIZED_RE.match(text)
            if mm:
                row.update(kind="vectorized", vf=int(mm.group("vf")),
                           ic=int(mm.group("ic")))
            elif text.strip() == "loop not vectorized":
                row.update(kind="declined")
            elif text.startswith("loop not vectorized:"):
                reason = text[len("loop not vectorized:"):].strip()
                row.update(kind="reason", reason=reason,
                           reason_class=classify(reason))
            elif SLP_RE.match(text):
                row.update(kind="slp")
            elif is_analysis_reason(text):
                row.update(kind="reason", reason=text,
                           reason_class=classify(text))
            else:
                continue
            rows.append(row)
    return rows


def is_analysis_reason(text):
    """A standalone loop-vectorizer analysis remark that states a reason but
    does not repeat the "loop not vectorized:" prefix. LLVM 23.1.1 emits the
    cost-model verdicts this way, which is exactly the class SPEC.ja.md 7
    wants to feed to Jev, so missing them would have hidden the whole `cost`
    bucket."""
    t = text.strip().rstrip(".")
    if t in REASON_CLASS:
        return True
    return "cost-model indicates" in t


# ---------------------------------------------------------------------------
# binary walking
# ---------------------------------------------------------------------------

def symbols(binary, sym_filter):
    out = subprocess.run(["nm", "-S", "--defined-only", binary],
                         capture_output=True, text=True, check=True).stdout
    syms = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        addr, size, typ, name = parts[0], parts[1], parts[2], " ".join(parts[3:])
        if typ.lower() != "t":
            continue
        try:
            a, s = int(addr, 16), int(size, 16)
        except ValueError:
            continue
        if s == 0:
            continue
        if sym_filter and sym_filter not in name and name != "main":
            continue
        syms.append((a, s, name))
    return sorted(syms)


VEC_RE = re.compile(r"\b[xyz]mm\d+\b")
F64_MNEMONICS = re.compile(r"^v?(add|sub|mul|div|fmadd|fmsub|max|min|sqrt)[ps]d")
F32_MNEMONICS = re.compile(r"^v?(add|sub|mul|div|fmadd|fmsub|max|min|sqrt)[ps]s")
INT_MNEMONICS = re.compile(r"^vp[a-z]+")


def disassemble(binary, syms):
    """-> list of (addr:int, text:str, sym_name:str)"""
    insns = []
    for a, s, name in syms:
        out = subprocess.run(
            ["objdump", "-d", "--no-show-raw-insn",
             f"--start-address={a}", f"--stop-address={a + s}", binary],
            capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            m = re.match(r"^\s+([0-9a-f]+):\t(.*)$", line)
            if m:
                insns.append((int(m.group(1), 16), m.group(2).strip(), name))
    return insns


FRAME_RE = re.compile(r"^(?P<fn>.*?) at (?P<file>.*?):(?P<line>\d+|\?)")


def addr2line_chains(binary, addrs, workdir):
    """-> list of chains; each chain is [(fn, file, line), ...] outer-last.

    `addr2line -i -p` prints the innermost frame first and each further
    inlined-into frame on a following " (inlined by) " line, so the LAST
    element of a chain is the real function in the binary.
    """
    listfile = os.path.join(workdir, "addrs.txt")
    with open(listfile, "w") as f:
        for a in addrs:
            f.write("0x%x\n" % a)
    out = subprocess.run(["addr2line", "-i", "-f", "-p", "-C", "-e", binary,
                          "@" + listfile],
                         capture_output=True, text=True, check=True).stdout
    chains, cur = [], None
    for line in out.splitlines():
        if line.startswith(" (inlined by)"):
            frame = line[len(" (inlined by)"):].strip()
            cur.append(parse_frame(frame))
        else:
            cur = [parse_frame(line.strip())]
            chains.append(cur)
    return chains


def parse_frame(text):
    m = FRAME_RE.match(text)
    if not m:
        return (text, "?", 0)
    line = m.group("line")
    return (m.group("fn"), m.group("file"), int(line) if line.isdigit() else 0)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bin", required=True, help="unstripped, debuginfo=1 binary")
    p.add_argument("--log", required=True, help="build log holding the remarks")
    p.add_argument("--src-prefix", default="",
                   help="path fragment identifying the target's own sources")
    p.add_argument("--sym-filter", default="",
                   help="only walk symbols whose name contains this")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--top", type=int, default=30)
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)

    remarks = parse_remarks(args.log)
    kinds = collections.Counter(r["kind"] for r in remarks)
    print("remarks parsed: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))

    syms = symbols(args.bin, args.sym_filter)
    text_bytes = sum(s for _, s, _ in syms)
    print(f"symbols walked: {len(syms)} ({text_bytes} bytes of .text), "
          f"filter={args.sym_filter!r}")

    insns = disassemble(args.bin, syms)
    print(f"instructions:   {len(insns)}")

    chains = addr2line_chains(args.bin, [a for a, _, _ in insns], args.out)
    if len(chains) != len(insns):
        sys.exit(f"frame/instruction mismatch: {len(chains)} vs {len(insns)}")

    # leaf (full file path, line) -> {"owner": set, "site": set}
    loc_index = collections.defaultdict(lambda: {"owner": set(), "site": set()})
    # per-site-function machine-code shape
    shape = collections.defaultdict(lambda: collections.Counter())
    nvec = collections.Counter()
    ninsn = collections.Counter()

    for (addr, text, sym), chain in zip(insns, chains):
        leaf_fn, leaf_file, leaf_line = chain[0]
        owner = chain[-1][0]
        site = None
        for fn, file, _ in chain:
            if args.src_prefix and args.src_prefix in file:
                site = fn
                break
        if site is None:
            site = owner
        key = (leaf_file, leaf_line)
        loc_index[key]["owner"].add(owner)
        loc_index[key]["site"].add(site)
        mnem = text.split()[0] if text else "?"
        shape[site][mnem] += 1
        ninsn[site] += 1
        if VEC_RE.search(text):
            nvec[site] += 1

    # ----- attribute every remark -----
    #
    # A remark spells its file the way rustc saw it (`src/deflate.rs`,
    # `library/core/src/ptr/mod.rs`); addr2line spells it resolved against the
    # compilation directory. So a remark path matches a DWARF path when the
    # DWARF path ENDS WITH it. Matching on a basename instead would merge
    # every crate's `src/lib.rs`, and this binary has several: zopfli's own
    # sources, and the `gimli` / `addr2line` / `object` crates that std
    # bundles for backtraces, all of which spell their files `src/...`.
    dwarf_files = {f for f, _ in loc_index}
    suffix_map = {}
    for rf in {r["file"] for r in remarks}:
        if rf == "<unknown>":
            continue
        suffix_map[rf] = [f for f in dwarf_files
                          if f == rf or f.endswith("/" + rf)]

    attributed = []
    per_site = collections.defaultdict(lambda: collections.Counter())
    unattributed = 0
    ambiguous_file = 0
    for r in remarks:
        cands = suffix_map.get(r["file"], [])
        if len(cands) > 1:
            ambiguous_file += 1
        hit = None
        for f in cands:
            h = loc_index.get((f, r["line"]))
            if h:
                if hit is None:
                    hit = {"owner": set(h["owner"]), "site": set(h["site"])}
                else:
                    hit["owner"] |= h["owner"]
                    hit["site"] |= h["site"]
        if not hit:
            unattributed += 1
            r2 = dict(r, sites=[], owners=[], ambiguous=None)
            attributed.append(r2)
            continue
        sites = sorted(hit["site"])
        owners = sorted(hit["owner"])
        r2 = dict(r, sites=sites, owners=owners, ambiguous=len(sites) > 1)
        attributed.append(r2)
        unique = len(sites) == 1
        for s in sites:
            if r["kind"] == "vectorized":
                per_site[s][f"vectorized VF{r['vf']} IC{r['ic']}"] += 1
                per_site[s]["#vectorized"] += 1
                if unique:
                    per_site[s]["#vectorized_unambiguous"] += 1
            elif r["kind"] == "declined":
                per_site[s]["#declined"] += 1
                if unique:
                    per_site[s]["#declined_unambiguous"] += 1
            elif r["kind"] == "reason":
                per_site[s][f"reason/{r['reason_class']}"] += 1
            else:
                per_site[s]["#slp"] += 1

    with open(os.path.join(args.out, "remark-attribution.json"), "w") as f:
        json.dump({"binary": args.bin, "log": args.log,
                   "src_prefix": args.src_prefix,
                   "symbols_walked": len(syms), "instructions": len(insns),
                   "remarks": attributed,
                   "unattributed": unattributed}, f, indent=1)

    # ----- reports -----
    print()
    print(f"unattributed remark locations: {unattributed} of {len(remarks)}")
    amb = sum(1 for r in attributed if r.get("ambiguous"))
    print(f"ambiguous (DebugLoc resolving to >1 function): {amb}")
    print(f"remarks whose file path matched >1 DWARF file: {ambiguous_file}")

    print()
    print(f"## loops: {kinds['vectorized']} vectorized, {kinds['declined']} "
          f"declined (the bare `loop not vectorized` line)")
    print()
    print("## reason strings, by count and class")
    reasons = collections.Counter()
    for r in remarks:
        if r["kind"] == "reason":
            reasons[(r["reason_class"], r["reason"])] += 1
    for (cls, reason), n in reasons.most_common():
        print(f"{n:6d}  {cls:<12s} {reason}")

    print()
    print("## VF/IC distribution of vectorized loops")
    vfic = collections.Counter((r["vf"], r["ic"]) for r in remarks
                               if r["kind"] == "vectorized")
    for (vf, ic), n in sorted(vfic.items()):
        print(f"  VF {vf:>3} IC {ic:>2}: {n}")

    print()
    print(f"## functions with vectorizer decisions (top {args.top} by decisions)")
    rank = sorted(per_site.items(),
                  key=lambda kv: -(kv[1]["#vectorized_unambiguous"] * 1000
                                   + kv[1]["#vectorized"]))
    for site, c in rank[:args.top]:
        vecfrac = f"{nvec[site]}/{ninsn[site]}"
        detail = ", ".join(f"{k}={v}" for k, v in sorted(c.items())
                           if not k.startswith("#"))
        print(f"- {site}")
        print(f"    insns {ninsn[site]}, vector-reg insns {vecfrac}, "
              f"fp={fp_kind(shape[site])}")
        print(f"    vectorized={c['#vectorized']} "
              f"(unambiguous {c['#vectorized_unambiguous']}), "
              f"declined={c['#declined']} "
              f"(unambiguous {c['#declined_unambiguous']})")
        print(f"    {detail}")

    with open(os.path.join(args.out, "per-function.json"), "w") as f:
        json.dump({s: {"decisions": dict(c), "insns": ninsn[s],
                       "vector_reg_insns": nvec[s],
                       "fp_kind": fp_kind(shape[s]),
                       "mnemonics": dict(shape[s].most_common(20))}
                   for s, c in per_site.items()}, f, indent=1)


def fp_kind(mnemonics):
    """Integer loops or floating-point loops? (SPEC.ja.md 6.2: an f64
    reduction is out of reach of every loop-metadata hint.)"""
    f64 = sum(v for k, v in mnemonics.items() if F64_MNEMONICS.match(k))
    f32 = sum(v for k, v in mnemonics.items() if F32_MNEMONICS.match(k))
    integer = sum(v for k, v in mnemonics.items() if INT_MNEMONICS.match(k))
    bits = []
    if integer:
        bits.append(f"int:{integer}")
    if f64:
        bits.append(f"f64:{f64}")
    if f32:
        bits.append(f"f32:{f32}")
    return "+".join(bits) if bits else "scalar"


if __name__ == "__main__":
    main()
