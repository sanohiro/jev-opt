#!/usr/bin/env bash
#
# Build the jev-opt LLVM pass plugins.
#
# Nothing from LLVM is linked. The plugins are dlopen'd by rustc, which is
# already linked against libLLVM.so.23.1-rust-1.100.0-nightly, so every llvm::
# symbol resolves at load time out of that library (results.md "Day 0"
# section 2). Linking any LLVM library in here would register its cl::opt
# objects a second time and abort inside dlopen.
#
# The headers must match that libLLVM exactly, including the two macros that
# change struct layouts:
#   NDEBUG                        assertions off, like the host
#   LLVM_ENABLE_ABI_BREAKING_CHECKS = 0  (via the generated abi-breaking.h,
#                                         configured with FORCE_OFF, which is
#                                         the DisableABIBreakingChecks side)
# scripts/fetch_llvm_headers.sh produces both include trees.
#
# Usage:
#   scripts/build_plugin.sh            # build both plugins
#   scripts/build_plugin.sh probe      # just libjevprobe.so
#   scripts/build_plugin.sh jev        # just libjevplugin.so
#
# Output: plugin/build/libjevprobe.so, plugin/build/libjevplugin.so
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TP="$REPO/third_party"
VER=23.1.1
SRC="$TP/llvm-project-$VER.src"
BUILD="$TP/llvm-build"
OUT="$REPO/plugin/build"

if [ ! -d "$SRC/llvm/include/llvm" ] || [ ! -d "$BUILD/include/llvm" ]; then
  echo "missing LLVM headers; run scripts/fetch_llvm_headers.sh first" >&2
  exit 1
fi

CXX="${CXX:-g++}"
mkdir -p "$OUT"

# -fno-rtti  : libLLVM is built without RTTI, so any class of ours that
#              derives from an LLVM class must agree.
# -fno-exceptions, -DNDEBUG, -std=c++17 : SPEC.ja.md 8.2.
# -fvisibility=hidden with an explicit default on llvmGetPassPluginInfo keeps
#              everything else out of the dynamic symbol table, so the plugin
#              cannot accidentally interpose a libLLVM symbol.
# libc/ is on the include path because llvm/ADT headers reach into
#              libc/shared/* in 23.x (see fetch_llvm_headers.sh step 2).
FLAGS=(-fPIC -shared -fno-rtti -fno-exceptions -DNDEBUG -std=c++17 -O2
       -fvisibility=hidden -fvisibility-inlines-hidden
       -Wall -Wno-unused-parameter
       -I"$SRC/llvm/include" -I"$BUILD/include" -I"$SRC/libc")

build_one() {
  local name="$1" src="$2" so="$OUT/$3"
  echo "== $name -> $so"
  "$CXX" "${FLAGS[@]}" "$src" -o "$so"

  # Gate: every undefined llvm:: / LLVM symbol must be exported by the
  # libLLVM rustc will load. An undefined symbol that is not there shows up
  # at dlopen time, inside rustc, as an unreadable error; catching it here
  # instead is the whole reason this check exists.
  local L
  L="$(rustc --print sysroot)/lib/libLLVM.so.23.1-rust-1.100.0-nightly"
  if [ -f "$L" ]; then
    local missing
    missing="$(comm -23 \
      <(nm -u --format=posix "$so" | awk '{print $1}' | sed 's/@.*//' \
          | grep -E '^(_ZN4llvm|_ZNK4llvm|LLVM)' | sort -u) \
      <(nm -D --defined-only --format=posix "$L" | awk '{print $1}' \
          | sed 's/@.*//' | sort -u))"
    if [ -n "$missing" ]; then
      echo "FAIL: undefined LLVM symbols not provided by $L:" >&2
      echo "$missing" | c++filt >&2
      exit 1
    fi
    echo "   undefined-LLVM-symbol check: ok"
  fi
}

what="${1:-all}"
case "$what" in
  probe) build_one probe "$REPO/plugin/probe/probe.cpp" libjevprobe.so ;;
  jev)   build_one jev   "$REPO/plugin/jev/jev.cpp"     libjevplugin.so ;;
  all)
    build_one probe "$REPO/plugin/probe/probe.cpp" libjevprobe.so
    build_one jev   "$REPO/plugin/jev/jev.cpp"     libjevplugin.so
    ;;
  *) echo "usage: build_plugin.sh [probe|jev|all]" >&2; exit 2 ;;
esac
