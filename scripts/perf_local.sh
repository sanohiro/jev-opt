#!/usr/bin/env bash
#
# Make `perf` usable on this machine without root.
#
# results.md "Day 0 (toy)" section 3 recorded that `perf` is not installed,
# and scripts/ipsample.c exists because of that. Decision 58 makes `perf` the
# profiler of record, so this script gets one without touching the system:
# Debian's linux-perf package and its three non-installed shared libraries are
# *downloaded* (no root needed) and unpacked into a private prefix, and a
# wrapper sets LD_LIBRARY_PATH / PERF_EXEC_PATH.
#
# Why this works on WSL2 at all (it did not on the earlier kernels the toy
# section tested): /proc/config.gz on 6.18.33.2-microsoft-standard-WSL2 has
# CONFIG_PERF_EVENTS=y, and perf_event_open succeeds for both software events
# and the AMD PMU's hardware `cycles` at perf_event_paranoid=2 (user space
# only -- kernel time is invisible, which is why the shares below are shares
# of *user* CPU time). The tool version (7.1.8 from trixie-backports) is
# newer than the kernel; record/report of `cycles:u` work regardless.
#
# Usage:
#   scripts/perf_local.sh setup [PREFIX]   # download + unpack, prints the wrapper path
#   scripts/perf_local.sh path  [PREFIX]   # print the wrapper path
#   $(scripts/perf_local.sh path) record ...
#
# PREFIX defaults to $PERF_LOCAL_PREFIX or /tmp/perf-local.
set -euo pipefail

cmd="${1:-setup}"
prefix="${2:-${PERF_LOCAL_PREFIX:-/tmp/perf-local}}"
wrapper="$prefix/bin/perf"

case "$cmd" in
  path) printf '%s\n' "$wrapper"; exit 0 ;;
  setup) ;;
  *) echo "usage: $0 {setup|path} [prefix]" >&2; exit 2 ;;
esac

if [ -x "$wrapper" ] && "$wrapper" --version >/dev/null 2>&1; then
  printf '%s\n' "$wrapper"; exit 0
fi

mkdir -p "$prefix/deb" "$prefix/root" "$prefix/bin"
cd "$prefix/deb"
# linux-perf brings /usr/bin/perf and /usr/lib/perf-core; the other three are
# the only shared libraries it needs that Pengwin 13 does not already have.
apt-get download linux-perf libopencsd1 libbabeltrace1 libtraceevent1 >&2
for d in *.deb; do dpkg-deb -x "$d" "$prefix/root"; done

cat > "$wrapper" <<EOF
#!/usr/bin/env bash
export LD_LIBRARY_PATH="$prefix/root/usr/lib/x86_64-linux-gnu:\${LD_LIBRARY_PATH:-}"
export PERF_EXEC_PATH="$prefix/root/usr/lib/perf-core"
exec "$prefix/root/usr/bin/perf" "\$@"
EOF
chmod +x "$wrapper"
"$wrapper" --version >&2
printf '%s\n' "$wrapper"
