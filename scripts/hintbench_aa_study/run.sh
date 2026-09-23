#!/usr/bin/env bash
# A/A-only panel study for the hintbench k5 two-mode finding (decision 95,
# results.md 160). Runs every panel sequentially on the frozen baseline
# binary; nothing is built and nothing is sent over HTTP.
#
# Output: artifacts/hintbench-aa-study/<panel-id>/{samples,stats}.json,
# stats.md, paths.tsv. Log lines: "[aa] <timestamp> <panel-id> start|exit <rc>".
#
# Panels (see results.md 160 for the predictions):
#   p1  full frozen recipe (scripts/bench_panel.sh, k1..k8), 6 copies whose
#       path lengths put argv[0] in glibc chunk classes 80/96/112/128/144/160
#   p2  bench.py k5+k8: 1-char path-length sweep 85..94 across the 88|89
#       boundary, an equal-length twin, and two hard links to ONE inode at 88/89
#   p3  bench.py: two fixed paths (class 96, class 112), k5/k8 with an extra
#       zero-padded repeat argument of lengths 7/25/41/57 (same work, shifted heap)
#   p4  p1 repeated with another seed (drop first if short on time)
#   p5a classes 80/96/112 on CPU 10 (core 5) instead of CPU 8
#   p5b same on CPU 8 with a 4 KiB extra environment variable and cwd /
#   p5c same on CPU 8 with a busy loop on the SMT sibling CPU 9 (drop second)
#
# Usage: run.sh [panel-id ...]   (default: all, in the order above)
set -uo pipefail

REPO=/home/hiro/prj/jev-optimize
STUDY="$REPO/artifacts/hintbench-aa-study"
SRC="$REPO/artifacts/hintbench-sites/baseline/bin"
BENCH="$REPO/scripts/bench.py"
export TARGET=hintbench
export PYTHONUNBUFFERED=1
RUNS=15
WARMUP=3

log() { echo "[aa] $(date '+%Y-%m-%dT%H:%M:%S%z') $*"; }

# One timing job at a time (AGENTS.md). Bracket trick so grep does not match itself.
if ps -eo cmd | grep -E '[b]ench\.py|[j]ev_search|[c]argo (build|rustc)' >/dev/null; then
  echo "another bench.py / jev_search / cargo build is running; refusing" >&2
  ps -eo pid,cmd | grep -E '[b]ench\.py|[j]ev_search|[c]argo (build|rustc)' >&2
  exit 3
fi
[ -f "$SRC" ] || { echo "no baseline binary at $SRC" >&2; exit 2; }
mkdir -p "$STUDY"
SPIN=""
trap '[ -n "$SPIN" ] && kill "$SPIN" 2>/dev/null' EXIT

# name_for DIR TARGET_LEN PREFIX: a file name such that len(DIR/name) == TARGET_LEN,
# asserting that the glibc chunk class of that length is the one encoded in PREFIX
# (class = max(32, (len + 8 + 15) & ~15); PREFIX's digits are the class, or
# for the p2 sweep the target length itself).
name_for() {
  python3 -u - "$1" "$2" "$3" <<'PY'
import sys, re
d, t, p = sys.argv[1], int(sys.argv[2]), sys.argv[3]
n = t - len(d) - 1
assert n >= len(p), f"dir {d} too long for length {t} with prefix {p}"
name = p + "x" * (n - len(p))
assert len(d + "/" + name) == t
print(name)
PY
}
chunk() { python3 -c "import sys; n=int(sys.argv[1]); print(max(32,(n+23)&~15))" "$1"; }

# stripped_copy SRC DST
stripped_copy() { cp "$1" "$2" && strip -s "$2"; }

# write paths.tsv for a list of absolute paths
paths_tsv() {
  local out="$1"; shift
  printf 'path\tlen\tchunk\tinode\tsha256\n' > "$out"
  for p in "$@"; do
    printf '%s\t%d\t%d\t%s\t%s\n' "$p" "${#p}" "$(chunk "${#p}")" \
      "$(stat -c %i "$p")" "$(sha256sum "$p" | cut -c1-16)" >> "$out"
  done
}

# direct_panel ID CPU SEED -- label=path... -- workload...
direct_panel() {
  local id="$1" cpu="$2" seed="$3"; shift 3
  [ "$1" = "--" ] && shift
  local labels=() wls=() base="" paths=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
    labels+=(--label "$1"); paths+=("${1#*=}")
    [ -z "$base" ] && base="${1%%=*}"; shift
  done
  [ "${1:-}" = "--" ] && shift
  while [ "$#" -gt 0 ]; do wls+=(--workload "$1"); shift; done
  local out="$STUDY/$id"
  paths_tsv "$out/paths.tsv" "${paths[@]}"
  python3 -u "$BENCH" run --cpu "$cpu" --warmup "$WARMUP" --runs "$RUNS" \
    --stdout pipe --gap-ms 0 --shuffle "$seed" \
    "${labels[@]}" "${wls[@]}" --out "$out/samples.json" || return $?
  python3 -u "$BENCH" stats "$out/samples.json" --base "$base" --seed "$seed" \
    --resamples 10000 --json "$out/stats.json" > "$out/stats.md" || return $?
}

# ---- p1 / p4: frozen recipe via bench_panel.sh (it copies + strips per label)
ref_panel() {
  local id="$1" seed="$2"
  local out="$STUDY/$id" tdir="$STUDY/$id/timing"
  mkdir -p "$out"
  # base first: class 112 (the class of the driver's confirm batches)
  local specs=() cls len
  for pair in 112:96 80:70 96:80 128:112 144:128 160:144; do
    cls="${pair%%:*}"; len="${pair#*:}"
    [ "$(chunk "$len")" = "$cls" ] || { echo "class assert failed $pair" >&2; return 9; }
    specs+=("$(name_for "$tdir" "$len" "c$cls")=$SRC")
  done
  scripts_panel "$out" "$seed" "${specs[@]}" || return $?
  local ps=(); for s in "${specs[@]}"; do ps+=("$tdir/${s%%=*}"); done
  paths_tsv "$out/paths.tsv" "${ps[@]}"
}
scripts_panel() {
  local out="$1" seed="$2"; shift 2
  (cd "$REPO" && "$REPO/scripts/bench_panel.sh" "$out" "$RUNS" "$WARMUP" "$seed" "$@")
}

# ---- p2: boundary sweep + equal-length twin + one inode at two lengths
p2() {
  local id=p2 bdir="$STUDY/p2/bin"; mkdir -p "$bdir"
  local specs=() n
  # base first: length 91 (class 112)
  for len in 91 85 86 87 88 89 90 92 93 94; do
    n="$(name_for "$bdir" "$len" "L0$len")"
    stripped_copy "$SRC" "$bdir/$n" || return $?
    specs+=("$n=$bdir/$n")
  done
  n="$(name_for "$bdir" 89 "Q089")"; stripped_copy "$SRC" "$bdir/$n" || return $?
  specs+=("$n=$bdir/$n")
  stripped_copy "$SRC" "$STUDY/p2/linksrc" || return $?
  for len in 88 89; do
    n="$(name_for "$bdir" "$len" "H0$len")"
    ln -f "$STUDY/p2/linksrc" "$bdir/$n" || return $?
    specs+=("$n=$bdir/$n")
  done
  direct_panel "$id" 8 20260922 -- "${specs[@]}" -- k5 k8
}

# ---- p3: fixed paths, heap shifted by an extra (zero-padded) repeat argument
p3() {
  local id=p3 bdir="$STUDY/p3/bin"; mkdir -p "$bdir"
  local a b
  a="$(name_for "$bdir" 96 "S112")"; b="$(name_for "$bdir" 80 "S096")"
  stripped_copy "$SRC" "$bdir/$a" && stripped_copy "$SRC" "$bdir/$b" || return $?
  pad() { python3 -c "import sys; v,l=sys.argv[1],int(sys.argv[2]); print('0'*(l-len(v))+v)" "$1" "$2"; }
  local wl=("k5a0=k5")
  for l in 7 25 41 57; do wl+=("k5a$l=k5 $(pad 3800000 "$l")"); done
  wl+=("k8a0=k8" "k8a6=k8 920000" "k8a25=k8 $(pad 920000 25)")
  direct_panel "$id" 8 20360924 -- "$a=$bdir/$a" "$b=$bdir/$b" -- "${wl[@]}"
}

# ---- p5*: three classes, placement / environment variations
three_class_labels() {   # DIR -> prints label=path for classes 112 (base), 80, 96
  local bdir="$1" n
  for pair in 112:96 80:70 96:80; do
    n="$(name_for "$bdir" "${pair#*:}" "c${pair%%:*}")"
    stripped_copy "$SRC" "$bdir/$n" || return $?
    echo "$n=$bdir/$n"
  done
}
p5a() {
  local bdir="$STUDY/p5a/bin"; mkdir -p "$bdir"
  local specs; mapfile -t specs < <(three_class_labels "$bdir")
  [ "${#specs[@]}" -eq 3 ] || return 8
  direct_panel p5a 10 20260921 -- "${specs[@]}" -- k5 k8
}
p5b() {
  local bdir="$STUDY/p5b/bin"; mkdir -p "$bdir"
  local specs; mapfile -t specs < <(three_class_labels "$bdir")
  local padv; padv="$(python3 -c "print('x'*4096)")"
  [ "${#specs[@]}" -eq 3 ] || return 8
  (cd / && export AA_ENV_PAD="$padv" && direct_panel p5b 8 20260921 -- "${specs[@]}" -- k5 k8)
}
p5c() {
  local bdir="$STUDY/p5c/bin"; mkdir -p "$bdir"
  local specs; mapfile -t specs < <(three_class_labels "$bdir")
  [ "${#specs[@]}" -eq 3 ] || return 8
  taskset -c 9 bash -c 'while :; do :; done' &
  SPIN=$!
  direct_panel p5c 8 20260921 -- "${specs[@]}" -- k5 k8
  local rc=$?
  kill "$SPIN" 2>/dev/null; wait "$SPIN" 2>/dev/null; SPIN=""
  return $rc
}
p1() { ref_panel p1 20260927; }
p4() { ref_panel p4 20360922; }

PANELS=("$@")
[ "${#PANELS[@]}" -eq 0 ] && PANELS=(p1 p2 p3 p4 p5a p5b p5c)
for id in "${PANELS[@]}"; do
  if [ -e "$STUDY/$id/samples.json" ]; then
    log "$id skip (samples.json exists)"; continue
  fi
  mkdir -p "$STUDY/$id"
  log "$id start load=$(cut -d' ' -f1-3 /proc/loadavg)"
  "$id" > "$STUDY/$id/run.log" 2>&1
  rc=$?
  log "$id exit $rc"
done
python3 -u "$(dirname "$(readlink -f "$0")")/readout.py" "$STUDY" | tee "$STUDY/readout.txt"
