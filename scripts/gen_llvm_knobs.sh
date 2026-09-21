#!/usr/bin/env bash
#
# Generate llvm-knobs.json: every cl::opt that exists in the pinned toolchain's
# LLVM (SPEC.ja.md 4). Knob names and enum values must come from this file, not
# from an LLVM 22.x knob table and not from memory -- SPEC.ja.md 4 already has
# one example (`-pass-remarks-output`) that 22.x had and 23.1.1 does not.
#
# Defaults: LLVM's own `--print-all-options` / `--print-options` cl::opts exist
# on 23.1.1 but produce no output through rustc's -Cllvm-args path, so the only
# machine-readable default is whatever the help text states in its description
# ("default = 225", "Zero is autoselect", ...). The field is `default_doc` for
# that reason: it is the documented default, not a probed one. A config that
# does not pass the flag is by definition at the default.
#
# Usage: scripts/gen_llvm_knobs.sh [output-path]      (default: llvm-knobs.json)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$REPO/llvm-knobs.json}"
RAW="$(mktemp)"
trap 'rm -f "$RAW"' EXIT

# Run inside the repository so rust-toolchain.toml applies.
cd "$REPO"
echo 'fn main(){}' | rustc -Cllvm-args=--help-list-hidden - -o /dev/null >"$RAW" 2>&1 || true

python3 - "$RAW" "$OUT" <<'PY'
import json, re, subprocess, sys

raw_path, out_path = sys.argv[1], sys.argv[2]

vv = subprocess.run(["rustc", "-vV"], capture_output=True, text=True).stdout
rustc_release = re.search(r"^release: (.*)$", vv, re.M).group(1)
llvm_version = re.search(r"^LLVM version: (.*)$", vv, re.M).group(1)

# "  --name=<uint>   - help"  /  "  --name   - help"
opt_re = re.compile(r"^  (--[A-Za-z0-9][^ =]*)(=<([^>]*)>)?\s+- (.*)$")
# "    =value    -   description"   (enum choice of the preceding option)
val_re = re.compile(r"^    =(\S+)\s+-\s*(.*)$")
# "      continuation of the help text"
cont_re = re.compile(r"^ {6,}(\S.*)$")

options, current = {}, None
for line in open(raw_path, errors="replace"):
    line = line.rstrip("\n")
    m = opt_re.match(line)
    if m:
        name, _, argtype, help_text = m.groups()
        current = {"name": name.lstrip("-"), "arg_type": argtype, "help": help_text,
                   "values": []}
        options[current["name"]] = current
        continue
    if current is not None:
        m = val_re.match(line)
        if m:
            current["values"].append({"value": m.group(1), "help": m.group(2)})
            continue
        m = cont_re.match(line)
        if m and not line.startswith("    ="):
            current["help"] += " " + m.group(1)
            continue
    current = None

# The documented default, when the description states one.
default_re = re.compile(r"default\s*=\s*([^,)\.]+)", re.I)
for o in options.values():
    m = default_re.search(o["help"])
    o["default_doc"] = m.group(1).strip() if m else None

doc = {
    "schema_version": 1,
    "generated_by": "echo 'fn main(){}' | rustc -Cllvm-args=--help-list-hidden - -o /dev/null",
    "rustc_release": rustc_release,
    "llvm_version": llvm_version,
    "note": ("default_doc is scraped from the help description; LLVM's "
             "--print-all-options prints nothing through rustc -Cllvm-args on "
             "this toolchain. Absence of the flag == the compiler default."),
    "count": len(options),
    "options": options,
}
with open(out_path, "w") as f:
    json.dump(doc, f, indent=1, sort_keys=True)
    f.write("\n")
print(f"{out_path}: {len(options)} options, rustc {rustc_release}, LLVM {llvm_version}")
PY
