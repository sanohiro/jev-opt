//===- jev.cpp - the jev-opt hint plugin ----------------------------------===//
//
// One LLVM pass plugin, three modes, driven entirely by environment
// variables (decisions 58, SPEC.ja.md 8.2). It never edits a source file:
// the hints a human or Claude wants tried are described by name and by site
// key, and this plugin is what puts them into the IR.
//
//   JEV_MODE=off     register nothing at all
//   JEV_MODE=dump    describe the marked functions and the loops inside them
//   JEV_MODE=apply   apply the hints in JEV_PLAN
//
//   JEV_MARKS        file of Rust paths, one per line: the functions a human
//                    or Claude asked to have optimised (decision 58 item 1)
//   JEV_PLAN         the plan Jev produced (apply only)
//   JEV_PLAN_SHA     sha256 of that file; a mismatch is fatal
//   JEV_REPORT_DIR   where dump output and apply reports go
//
// Extension points, fixed by measurement, not by guesswork
// (artifacts/plugin-day3, results.md "Day 3 (plugin)"):
//
//   function attributes -> PipelineStartEP.  It is the only point that runs
//     before any inlining, and it fires exactly once per CGU, pre-link only
//     -- LLVM's buildLTODefaultPipeline does not invoke it, so there is no
//     second, merged-module invocation to be idempotent against. `noinline`
//     placed any later has already lost.
//
//   loop metadata -> VectorizerStartEP.  Under fat LTO this fires only in
//     the merged module (rustc's pre-link pipeline for a fat-LTO build is
//     the ThinLTO pre-link pipeline, which stops before the vectorizers), so
//     it sees the four toy loops after they have been inlined into
//     toy::main and before any of them is vectorized. Under lto=off it fires
//     in the single per-CGU pipeline. Either way it is the last point at
//     which a loop hint can still reach LoopVectorize.
//
// Stage. Under fat LTO rustc reuses the primary CGU's module identifier and
// process for the merged module, so the stage cannot be read off the module
// name. FullLinkTimeOptimizationEarlyEP is the marker: everything after it
// in that process, for that module, is the merged LTO stage. Reports are
// therefore one file per (module, stage, pid) and the CLI merges them.
//
// Build: scripts/build_plugin.sh. No LLVM library is linked.
//
//===----------------------------------------------------------------------===//

#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Analysis/BlockFrequencyInfo.h"
#include "llvm/Analysis/BranchProbabilityInfo.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/CFG.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/Type.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Metadata.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Analysis/TargetTransformInfo.h"
#include "llvm/Demangle/Demangle.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <unistd.h>
#include <vector>

using namespace llvm;

namespace {

//===----------------------------------------------------------------------===//
// sha256 (self-contained: llvm::SHA256 is not exported by the host libLLVM)
//===----------------------------------------------------------------------===//

struct Sha256 {
  uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  uint64_t len = 0;
  uint8_t buf[64];
  size_t bufLen = 0;

  static uint32_t ror(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

  void block(const uint8_t *p) {
    static const uint32_t K[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
        0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
        0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
        0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
        0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
    uint32_t w[64];
    for (int i = 0; i < 16; ++i)
      w[i] = (uint32_t(p[i * 4]) << 24) | (uint32_t(p[i * 4 + 1]) << 16) |
             (uint32_t(p[i * 4 + 2]) << 8) | uint32_t(p[i * 4 + 3]);
    for (int i = 16; i < 64; ++i) {
      uint32_t s0 = ror(w[i - 15], 7) ^ ror(w[i - 15], 18) ^ (w[i - 15] >> 3);
      uint32_t s1 = ror(w[i - 2], 17) ^ ror(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3];
    uint32_t e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; ++i) {
      uint32_t S1 = ror(e, 6) ^ ror(e, 11) ^ ror(e, 25);
      uint32_t ch = (e & f) ^ (~e & g);
      uint32_t t1 = hh + S1 + ch + K[i] + w[i];
      uint32_t S0 = ror(a, 2) ^ ror(a, 13) ^ ror(a, 22);
      uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
      uint32_t t2 = S0 + mj;
      hh = g; g = f; f = e; e = d + t1;
      d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }

  void update(const void *data, size_t n) {
    const uint8_t *p = (const uint8_t *)data;
    len += n;
    while (n) {
      size_t take = std::min(n, size_t(64) - bufLen);
      memcpy(buf + bufLen, p, take);
      bufLen += take; p += take; n -= take;
      if (bufLen == 64) { block(buf); bufLen = 0; }
    }
  }

  std::string hex() {
    uint64_t bits = len * 8;
    uint8_t pad = 0x80;
    update(&pad, 1);
    uint8_t zero = 0;
    while (bufLen != 56) update(&zero, 1);
    uint8_t be[8];
    for (int i = 0; i < 8; ++i) be[i] = uint8_t(bits >> (56 - 8 * i));
    // Do not let update() count these eight bytes into a new length; the
    // padding maths is already done, so write the block directly.
    memcpy(buf + 56, be, 8);
    block(buf);
    char out[65];
    for (int i = 0; i < 8; ++i)
      snprintf(out + i * 8, 9, "%08x", h[i]);
    return std::string(out, 64);
  }
};

std::string sha256Hex(StringRef S) {
  Sha256 C;
  C.update(S.data(), S.size());
  return C.hex();
}

//===----------------------------------------------------------------------===//
// minimal JSON (the plan is machine written, so this reads the subset it uses)
//===----------------------------------------------------------------------===//

struct JVal {
  enum Kind { Null, Bool, Num, Str, Arr, Obj } kind = Null;
  bool b = false;
  double num = 0;
  std::string str;
  std::vector<JVal> arr;
  std::vector<std::pair<std::string, JVal>> obj;

  const JVal *get(StringRef k) const {
    if (kind != Obj) return nullptr;
    for (auto &kv : obj)
      if (kv.first == k.str()) return &kv.second;
    return nullptr;
  }
  bool isNull() const { return kind == Null; }
};

struct JParser {
  const char *p, *e;
  std::string err;

  void ws() { while (p < e && isspace((unsigned char)*p)) ++p; }
  bool lit(const char *s) {
    size_t n = strlen(s);
    if (size_t(e - p) >= n && !strncmp(p, s, n)) { p += n; return true; }
    return false;
  }
  bool parse(JVal &v) {
    ws();
    if (p >= e) { err = "unexpected end"; return false; }
    switch (*p) {
    case '{': {
      ++p; v.kind = JVal::Obj; ws();
      if (p < e && *p == '}') { ++p; return true; }
      while (true) {
        ws();
        JVal k;
        if (p >= e || *p != '"' || !parse(k)) { err = "bad key"; return false; }
        ws();
        if (p >= e || *p != ':') { err = "expected :"; return false; }
        ++p;
        JVal val;
        if (!parse(val)) return false;
        v.obj.emplace_back(k.str, std::move(val));
        ws();
        if (p < e && *p == ',') { ++p; continue; }
        if (p < e && *p == '}') { ++p; return true; }
        err = "expected , or }"; return false;
      }
    }
    case '[': {
      ++p; v.kind = JVal::Arr; ws();
      if (p < e && *p == ']') { ++p; return true; }
      while (true) {
        JVal el;
        if (!parse(el)) return false;
        v.arr.push_back(std::move(el));
        ws();
        if (p < e && *p == ',') { ++p; continue; }
        if (p < e && *p == ']') { ++p; return true; }
        err = "expected , or ]"; return false;
      }
    }
    case '"': {
      ++p; v.kind = JVal::Str;
      while (p < e && *p != '"') {
        if (*p == '\\' && p + 1 < e) {
          ++p;
          switch (*p) {
          case 'n': v.str += '\n'; break;
          case 't': v.str += '\t'; break;
          case 'r': v.str += '\r'; break;
          case 'b': v.str += '\b'; break;
          case 'f': v.str += '\f'; break;
          case 'u': {
            // Only the BMP subset the plan can contain; enough for paths.
            if (e - p < 5) { err = "bad \\u"; return false; }
            unsigned cp = strtoul(std::string(p + 1, p + 5).c_str(), nullptr, 16);
            p += 4;
            if (cp < 0x80) v.str += char(cp);
            else if (cp < 0x800) {
              v.str += char(0xC0 | (cp >> 6));
              v.str += char(0x80 | (cp & 0x3F));
            } else {
              v.str += char(0xE0 | (cp >> 12));
              v.str += char(0x80 | ((cp >> 6) & 0x3F));
              v.str += char(0x80 | (cp & 0x3F));
            }
            break;
          }
          default: v.str += *p;
          }
          ++p;
        } else {
          v.str += *p++;
        }
      }
      if (p >= e) { err = "unterminated string"; return false; }
      ++p;
      return true;
    }
    case 't': if (lit("true"))  { v.kind = JVal::Bool; v.b = true;  return true; } break;
    case 'f': if (lit("false")) { v.kind = JVal::Bool; v.b = false; return true; } break;
    case 'n': if (lit("null"))  { v.kind = JVal::Null; return true; } break;
    default: break;
    }
    {
      char *end = nullptr;
      double d = strtod(p, &end);
      if (end != p) { v.kind = JVal::Num; v.num = d; p = end; return true; }
    }
    err = "bad value";
    return false;
  }
};

std::string jsonEscape(StringRef S) {
  std::string O;
  for (char c : S) {
    switch (c) {
    case '"': O += "\\\""; break;
    case '\\': O += "\\\\"; break;
    case '\n': O += "\\n"; break;
    case '\t': O += "\\t"; break;
    case '\r': O += "\\r"; break;
    default:
      if ((unsigned char)c < 0x20) { char b[8]; snprintf(b, 8, "\\u%04x", c); O += b; }
      else O += c;
    }
  }
  return O;
}

std::string jstr(StringRef S) { return "\"" + jsonEscape(S) + "\""; }

//===----------------------------------------------------------------------===//
// configuration from the environment
//===----------------------------------------------------------------------===//

/// ApplyDump is the two-phase shape the design needs: the function
/// attributes of a plan are applied at PipelineStart and the loops are then
/// dumped from the IR those attributes produced. Loop decisions made on a
/// dump taken *before* the attributes were applied can be about loops that
/// no longer exist (results.md "Day 3 (plugin)" 5f).
enum class Mode { Off, Dump, Apply, ApplyDump };

std::string envStr(const char *K) {
  const char *V = getenv(K);
  return V ? std::string(V) : std::string();
}

[[noreturn]] void fatal(const std::string &Msg) {
  errs() << "jev-plugin: fatal: " << Msg << "\n";
  // Not report_fatal_error: rustc installs its own handler and the message
  // reads better as a plain abort with our text already on stderr.
  exit(1);
}

std::string readFile(const std::string &Path, bool &Ok) {
  std::ifstream F(Path, std::ios::binary);
  if (!F) { Ok = false; return {}; }
  std::ostringstream SS;
  SS << F.rdbuf();
  Ok = true;
  return SS.str();
}

//===----------------------------------------------------------------------===//
// marks: Rust paths matched against demangled v0 linkage names
//===----------------------------------------------------------------------===//

/// Remove every balanced <...> group. `_RINvNtC..` v0 names demangle with
/// generic arguments spelled out (`foo::bar::<u8>`, `<A as B>::c`); a mark is
/// written the way a human writes a path, so both sides are normalised by
/// dropping the argument lists. What is left of `<A as B>::c` is `::c`, so
/// the leading `::` is trimmed too.
std::string stripGenerics(StringRef In) {
  std::string Out;
  int Depth = 0;
  for (char C : In) {
    if (C == '<') { ++Depth; continue; }
    if (C == '>') { if (Depth) --Depth; continue; }
    if (!Depth) Out += C;
  }
  // "foo::::bar" can appear once a <...> between two :: is gone.
  std::string Clean;
  for (size_t i = 0; i < Out.size(); ++i) {
    if (Out[i] == ':' && i + 3 < Out.size() && Out.compare(i, 4, "::::") == 0) {
      Clean += "::";
      i += 3;
      continue;
    }
    Clean += Out[i];
  }
  while (Clean.size() >= 2 && Clean.compare(0, 2, "::") == 0)
    Clean = Clean.substr(2);
  return Clean;
}

/// rustc's v0 mangling keeps the crate disambiguator in the demangled form
/// only for `Cs...` hashes, which llvm::demangle already drops. Returns the
/// input unchanged when it is not a mangled name.
std::string demangleName(StringRef Linkage) {
  std::string D = demangle(Linkage.str());
  return D.empty() ? Linkage.str() : D;
}

struct Marks {
  std::vector<std::string> Raw;         // as written in jev-marks.txt
  mutable std::set<std::string> Hit;    // marks that matched at least once

  bool empty() const { return Raw.empty(); }

  /// Prefix/suffix tolerant: a mark matches when, after dropping generic
  /// arguments, the demangled path is the mark, ends with `::` + the mark
  /// (mark written without its crate), or starts with the mark + `::` (an
  /// inner item or closure of the marked function).
  const std::string *match(StringRef Demangled) const {
    std::string D = stripGenerics(Demangled);
    for (const std::string &M : Raw) {
      std::string N = stripGenerics(M);
      if (N.empty())
        continue;
      bool Ok = D == N ||
                (D.size() > N.size() + 2 &&
                 D.compare(D.size() - N.size(), N.size(), N) == 0 &&
                 D.compare(D.size() - N.size() - 2, 2, "::") == 0) ||
                (D.size() > N.size() + 2 && D.compare(0, N.size(), N) == 0 &&
                 D.compare(N.size(), 2, "::") == 0);
      if (Ok) { Hit.insert(M); return &M; }
    }
    return nullptr;
  }
};

Marks loadMarks(const std::string &Path) {
  Marks M;
  if (Path.empty())
    return M;
  bool Ok = false;
  std::string Text = readFile(Path, Ok);
  if (!Ok)
    fatal("cannot read JEV_MARKS=" + Path);
  std::istringstream SS(Text);
  std::string Line;
  while (std::getline(SS, Line)) {
    size_t H = Line.find('#');
    if (H != std::string::npos) Line = Line.substr(0, H);
    while (!Line.empty() && isspace((unsigned char)Line.back())) Line.pop_back();
    size_t B = Line.find_first_not_of(" \t");
    if (B == std::string::npos) continue;
    M.Raw.push_back(Line.substr(B));
  }
  return M;
}

//===----------------------------------------------------------------------===//
// site key (SPEC.ja.md 8.3)
//===----------------------------------------------------------------------===//

std::string subprogramLinkage(const DISubprogram *SP) {
  if (!SP) return {};
  if (!SP->getLinkageName().empty()) return SP->getLinkageName().str();
  return SP->getName().str();
}

/// The DISubprogram chain a location sits in, innermost first: the scope's
/// own subprogram, then one per inlinedAt frame.
void frameChain(const DILocation *DL, SmallVectorImpl<const DISubprogram *> &Out) {
  for (const DILocation *L = DL; L; L = L->getInlinedAt())
    if (const DISubprogram *SP = L->getScope()->getSubprogram())
      Out.push_back(SP);
}

/// The location that names this loop. Loop::getStartLoc() is what the
/// vectorizer's own remarks use, so a key built on it lines up with the
/// remark text; the fallbacks keep the key defined for a loop whose
/// preheader lost its debug location.
DebugLoc loopLoc(const Loop &L) {
  if (DebugLoc D = L.getStartLoc())
    return D;
  for (const Instruction &I : *L.getHeader())
    if (I.getDebugLoc())
      return I.getDebugLoc();
  for (const BasicBlock *BB : L.getBlocks())
    for (const Instruction &I : *BB)
      if (I.getDebugLoc())
        return I.getDebugLoc();
  return DebugLoc();
}

struct SiteKey {
  std::string Key;          // 16 hex + "-" + readable suffix
  std::string OwnerFn;      // linkage name of the function that contains it
  std::vector<std::string> InlineChain; // outer -> inner
  std::string File;
  unsigned Line = 0, Col = 0;
  unsigned Depth = 0;
};

std::string sanitizeSuffix(StringRef S) {
  std::string O;
  for (char C : S)
    O += (isalnum((unsigned char)C) || C == '_' || C == '.') ? C : '_';
  if (O.size() > 40) O = O.substr(0, 40);
  return O;
}

SiteKey computeSiteKey(const Function &F, const Loop &L) {
  SiteKey K;
  K.Depth = L.getLoopDepth();
  K.OwnerFn = F.getSubprogram() ? subprogramLinkage(F.getSubprogram())
                                : F.getName().str();

  DebugLoc DL = loopLoc(L);
  if (DL) {
    SmallVector<const DISubprogram *, 8> Chain;
    frameChain(DL.get(), Chain);
    // SPEC.ja.md 8.3 wants outer -> inner.
    for (auto It = Chain.rbegin(); It != Chain.rend(); ++It)
      K.InlineChain.push_back(subprogramLinkage(*It));
    K.File = DL->getFilename().str();
    K.Line = DL->getLine();
    K.Col = DL->getColumn();
  }

  // (4) loop fingerprint: the sorted set of (innermost linkage name, line)
  // over every instruction in the body. Sorted, so instruction scheduling
  // between dump and apply cannot move the key.
  std::set<std::string> Fp;
  for (const BasicBlock *BB : L.getBlocks())
    for (const Instruction &I : *BB) {
      const DebugLoc &D = I.getDebugLoc();
      if (!D) continue;
      const DISubprogram *SP = D->getScope()->getSubprogram();
      Fp.insert(subprogramLinkage(SP) + ":" + std::to_string(D->getLine()));
    }

  std::string Material;
  Material += K.OwnerFn;
  Material += "\x1f";
  for (const std::string &S : K.InlineChain) { Material += S; Material += "\x1e"; }
  Material += "\x1f";
  Material += K.File + ":" + std::to_string(K.Line) + ":" + std::to_string(K.Col);
  Material += "\x1f";
  for (const std::string &S : Fp) { Material += S; Material += "\x1e"; }
  Material += "\x1f";
  Material += std::to_string(K.Depth);

  std::string Hex = sha256Hex(Material);

  // Readable suffix: the innermost frame's function and source line.
  std::string Leaf = "anon";
  if (!K.InlineChain.empty())
    Leaf = stripGenerics(demangleName(K.InlineChain.back()));
  else if (!K.OwnerFn.empty())
    Leaf = stripGenerics(demangleName(K.OwnerFn));
  size_t Pos = Leaf.rfind("::");
  if (Pos != std::string::npos) Leaf = Leaf.substr(Pos + 2);
  std::string FileBase = K.File;
  Pos = FileBase.rfind('/');
  if (Pos != std::string::npos) FileBase = FileBase.substr(Pos + 1);

  K.Key = Hex.substr(0, 16) + "-" + sanitizeSuffix(Leaf) + "-" +
          sanitizeSuffix(FileBase) + "-" + std::to_string(K.Line);
  return K;
}

//===----------------------------------------------------------------------===//
// loop metadata helpers
//===----------------------------------------------------------------------===//

bool loopIdHas(const MDNode *ID, StringRef Key) {
  if (!ID) return false;
  for (unsigned I = 1, E = ID->getNumOperands(); I < E; ++I)
    if (const MDNode *Op = dyn_cast_or_null<MDNode>(ID->getOperand(I)))
      if (Op->getNumOperands() >= 1)
        if (auto *S = dyn_cast_or_null<MDString>(Op->getOperand(0)))
          if (S->getString() == Key)
            return true;
  return false;
}

/// The string value of a `!{!"name", !"value"}` entry, if present.
std::string loopIdStrValue(const MDNode *ID, StringRef Key) {
  if (!ID) return {};
  for (unsigned I = 1, E = ID->getNumOperands(); I < E; ++I)
    if (const MDNode *Op = dyn_cast_or_null<MDNode>(ID->getOperand(I)))
      if (Op->getNumOperands() == 2)
        if (auto *S = dyn_cast_or_null<MDString>(Op->getOperand(0)))
          if (S->getString() == Key)
            if (auto *V = dyn_cast_or_null<MDString>(Op->getOperand(1)))
              return V->getString().str();
  return {};
}

/// Append operands to a loop's id, creating the self-referential node when
/// the loop has none. Written out rather than using
/// llvm::addStringMetadataToLoop because that helper always emits
/// `!{!"name", i32 V}`, and `llvm.loop.unroll.disable` must be a one-operand
/// node -- with a second operand LoopUnroll reads it as the boolean `false`
/// and the hint silently means its opposite.
void appendLoopMD(Loop &L, ArrayRef<Metadata *> NewEntries) {
  LLVMContext &Ctx = L.getHeader()->getContext();
  SmallVector<Metadata *, 8> Ops;
  Ops.push_back(nullptr); // self reference, filled in below
  if (MDNode *Old = L.getLoopID())
    for (unsigned I = 1, E = Old->getNumOperands(); I < E; ++I)
      Ops.push_back(Old->getOperand(I));
  Ops.append(NewEntries.begin(), NewEntries.end());
  MDNode *New = MDNode::getDistinct(Ctx, Ops);
  New->replaceOperandWith(0, New);
  L.setLoopID(New);
}

MDNode *mdStrInt(LLVMContext &Ctx, StringRef Name, unsigned V) {
  Metadata *Ops[2] = {MDString::get(Ctx, Name),
                      ConstantAsMetadata::get(
                          ConstantInt::get(Type::getInt32Ty(Ctx), V))};
  return MDNode::get(Ctx, Ops);
}

MDNode *mdStr(LLVMContext &Ctx, StringRef Name) {
  Metadata *Ops[1] = {MDString::get(Ctx, Name)};
  return MDNode::get(Ctx, Ops);
}

MDNode *mdStrStr(LLVMContext &Ctx, StringRef Name, StringRef Val) {
  Metadata *Ops[2] = {MDString::get(Ctx, Name), MDString::get(Ctx, Val)};
  return MDNode::get(Ctx, Ops);
}

//===----------------------------------------------------------------------===//
// the plan
//===----------------------------------------------------------------------===//

struct FnAttrEntry {
  std::string Fn;            // linkage name or demangled Rust path
  std::string Inline;        // "hint" | "never" | ""
  bool Cold = false, Hot = false;
  int Align = 0;             // 0 = leave alone
};

struct LoopMDEntry {
  std::string Key;
  std::string Stage;         // "" = any stage
  int UnrollCount = 0;
  bool UnrollDisable = false;
  int VectorizeWidth = 0;
  int InterleaveCount = 0;
};

struct Plan {
  std::string PlanId;
  std::vector<FnAttrEntry> FnAttrs;
  std::vector<LoopMDEntry> LoopMD;
};

int jint(const JVal *V, int Dflt = 0) {
  return (V && V->kind == JVal::Num) ? int(V->num) : Dflt;
}
bool jbool(const JVal *V, bool Dflt = false) {
  return (V && V->kind == JVal::Bool) ? V->b : Dflt;
}
std::string jstrv(const JVal *V) {
  return (V && V->kind == JVal::Str) ? V->str : std::string();
}

std::once_flag PlanOnce;
Plan ThePlan;

void loadPlanOnce() {
  std::call_once(PlanOnce, [] {
    std::string Path = envStr("JEV_PLAN");
    if (Path.empty())
      fatal("JEV_MODE=apply needs JEV_PLAN");
    bool Ok = false;
    std::string Text = readFile(Path, Ok);
    if (!Ok)
      fatal("cannot read JEV_PLAN=" + Path);

    std::string Want = envStr("JEV_PLAN_SHA");
    std::string Got = sha256Hex(Text);
    if (Want.empty())
      fatal("JEV_MODE=apply needs JEV_PLAN_SHA (plan sha256 is " + Got + ")");
    if (Want != Got)
      fatal("JEV_PLAN_SHA mismatch: expected " + Want + ", file is " + Got);

    JParser P{Text.data(), Text.data() + Text.size(), {}};
    JVal Root;
    if (!P.parse(Root) || Root.kind != JVal::Obj)
      fatal("JEV_PLAN is not a JSON object: " + P.err);

    ThePlan.PlanId = jstrv(Root.get("plan_id"));

    if (const JVal *A = Root.get("fn_attrs")) {
      if (A->kind != JVal::Arr) fatal("fn_attrs must be an array");
      for (const JVal &E : A->arr) {
        FnAttrEntry F;
        F.Fn = jstrv(E.get("fn"));
        if (F.Fn.empty()) fatal("fn_attrs entry without \"fn\"");
        const JVal *In = E.get("inline");
        if (In && In->kind == JVal::Str) {
          F.Inline = In->str;
          if (F.Inline != "hint" && F.Inline != "never")
            fatal("fn_attrs.inline must be \"hint\", \"never\" or null, got \"" +
                  F.Inline + "\"");
        }
        F.Cold = jbool(E.get("cold"));
        F.Hot = jbool(E.get("hot"));
        F.Align = jint(E.get("align"));
        if (F.Align && (F.Align <= 0 || (F.Align & (F.Align - 1))))
          fatal("fn_attrs.align must be a power of two, got " +
                std::to_string(F.Align));
        if (F.Cold && F.Hot)
          fatal("fn_attrs entry for " + F.Fn + " sets both cold and hot");
        ThePlan.FnAttrs.push_back(std::move(F));
      }
    }

    if (const JVal *A = Root.get("loop_md")) {
      if (A->kind != JVal::Arr) fatal("loop_md must be an array");
      for (const JVal &E : A->arr) {
        LoopMDEntry L;
        L.Key = jstrv(E.get("key"));
        if (L.Key.empty()) fatal("loop_md entry without \"key\"");
        L.Stage = jstrv(E.get("stage"));
        L.UnrollCount = jint(E.get("unroll_count"));
        L.UnrollDisable = jbool(E.get("unroll_disable"));
        L.VectorizeWidth = jint(E.get("vectorize_width"));
        L.InterleaveCount = jint(E.get("interleave_count"));
        if (L.UnrollCount && L.UnrollDisable)
          fatal("loop_md " + L.Key + " sets both unroll_count and unroll_disable");
        ThePlan.LoopMD.push_back(std::move(L));
      }
    }
  });
}

//===----------------------------------------------------------------------===//
// stage tracking and per-(module, stage) report accumulation
//===----------------------------------------------------------------------===//

std::mutex StateMutex;
std::map<const Module *, std::string> ModuleStage; // default "prelink"

std::string stageOf(const Module &M) {
  std::lock_guard<std::mutex> L(StateMutex);
  auto It = ModuleStage.find(&M);
  return It == ModuleStage.end() ? std::string("prelink") : It->second;
}

void setStage(const Module &M, const std::string &S) {
  std::lock_guard<std::mutex> L(StateMutex);
  ModuleStage[&M] = S;
}

/// Everything a dump or apply run accumulates for one (module, stage). It is
/// flushed at process exit, which is the only point that is reached in every
/// pipeline shape -- OptimizerLast, for instance, never fires for the merged
/// fat-LTO module.
struct Bucket {
  std::string ModuleId, Stage;
  std::vector<std::string> SiteJson;   // dump: one object per loop
  // dump: one object per marked function, keyed by linkage name. A map, not
  // a list, because the function table is written from two points in the
  // pre-link pipeline: PipelineStart (the state the fn_attrs decision acts
  // on) and OptimizerEarly (after PGOInstrumentationUse has attached !prof,
  // so entry_count is no longer null). The later, richer row wins.
  std::map<std::string, std::string> FnJson;
  std::vector<std::string> ResultJson; // apply: one object per plan entry
  std::set<std::string> MatchedMarks;
  bool HasProfileSummary = false;
  // Whether the loop extension point ran for this (module, stage). Under fat
  // LTO it runs only in the merged stage, so the pre-link buckets must not
  // report every mark as unmatched or every plan key as vanished.
  bool LoopEpRan = false;
};

std::map<std::string, Bucket> Buckets; // key: moduleId + "\x1f" + stage
bool AtexitInstalled = false;

std::string sanitizeFile(StringRef S) {
  std::string O;
  for (char C : S)
    O += (isalnum((unsigned char)C) || C == '.' || C == '-' || C == '_') ? C : '_';
  if (O.size() > 100) O = O.substr(O.size() - 100);
  return O;
}

void writeReports();
void finalizeKeyOutcomes();

Bucket &bucketFor(const Module &M, const std::string &Stage) {
  // Caller holds StateMutex.
  if (!AtexitInstalled) { atexit(writeReports); AtexitInstalled = true; }
  std::string K = M.getModuleIdentifier() + "\x1f" + Stage;
  Bucket &B = Buckets[K];
  if (B.ModuleId.empty()) {
    B.ModuleId = M.getModuleIdentifier();
    B.Stage = Stage;
  }
  // PGOInstrumentationUse attaches the summary partway through the pre-link
  // pipeline, so this is latched rather than sampled once (see the EP table
  // in results.md: profsummary is 0 at PipelineStart even with -Cprofile-use).
  if (M.getProfileSummary(false) != nullptr)
    B.HasProfileSummary = true;
  return B;
}

Mode TheMode = Mode::Off;
Marks TheMarks;
std::string ReportDir;

void writeJsonArray(std::ostream &O, StringRef Name,
                    const std::vector<std::string> &Items, bool Last) {
  O << "  " << jstr(Name) << ": [";
  for (size_t I = 0; I < Items.size(); ++I)
    O << (I ? ",\n    " : "\n    ") << Items[I];
  O << (Items.empty() ? "]" : "\n  ]") << (Last ? "\n" : ",\n");
}

void writeReports() {
  std::lock_guard<std::mutex> L(StateMutex);
  if (ReportDir.empty() || Buckets.empty())
    return;
  if (TheMode == Mode::Apply)
    finalizeKeyOutcomes();
  for (auto &KV : Buckets) {
    Bucket &B = KV.second;
    const char *Prefix = TheMode == Mode::Apply ? "apply-report" : "sites";
    // apply-dump writes a sites file: its apply half is only fn_attrs, whose
    // outcomes are carried in the same file's "results".
    std::string Path = ReportDir + "/" + Prefix + "-" + sanitizeFile(B.ModuleId) +
                       "-" + B.Stage + "-" + std::to_string(getpid()) + ".json";
    std::ofstream F(Path);
    if (!F) {
      errs() << "jev-plugin: cannot write " << Path << "\n";
      continue;
    }
    std::vector<std::string> Unmatched;
    if (B.LoopEpRan)
      for (const std::string &M : TheMarks.Raw)
        if (!B.MatchedMarks.count(M))
          Unmatched.push_back(jstr(M));

    F << "{\n";
    F << "  \"schema_version\": 1,\n";
    const char *ModeName = TheMode == Mode::Apply      ? "apply"
                           : TheMode == Mode::ApplyDump ? "apply-dump"
                                                        : "dump";
    F << "  \"mode\": " << jstr(ModeName) << ",\n";
    F << "  \"plan_id\": " << jstr(ThePlan.PlanId) << ",\n";
    F << "  \"module_id\": " << jstr(B.ModuleId) << ",\n";
    F << "  \"stage\": " << jstr(B.Stage) << ",\n";
    F << "  \"pid\": " << getpid() << ",\n";
    F << "  \"profile_summary\": " << (B.HasProfileSummary ? "true" : "false") << ",\n";
    F << "  \"loop_ep_ran\": " << (B.LoopEpRan ? "true" : "false") << ",\n";
    writeJsonArray(F, "unmatched_marks", Unmatched, false);
    if (TheMode == Mode::Apply) {
      writeJsonArray(F, "results", B.ResultJson, true);
    } else if (TheMode == Mode::ApplyDump) {
      writeJsonArray(F, "results", B.ResultJson, false);
      std::vector<std::string> Fns;
      for (auto &KV : B.FnJson) Fns.push_back(KV.second);
      writeJsonArray(F, "functions", Fns, false);
      writeJsonArray(F, "sites", B.SiteJson, true);
    } else {
      std::vector<std::string> Fns;
      for (auto &KV : B.FnJson) Fns.push_back(KV.second);
      writeJsonArray(F, "functions", Fns, false);
      writeJsonArray(F, "sites", B.SiteJson, true);
    }
    F << "}\n";
  }
  Buckets.clear();
}

//===----------------------------------------------------------------------===//
// dump
//===----------------------------------------------------------------------===//

/// Trip count from the profile, by decision 36: exits = header count minus
/// the back-edge count, average trip = header count / exits. Taking
/// `Block counts[0]` as the entry count is unsound because it is zero for
/// some profiles.
bool estimateTripCount(const Loop &L, BlockFrequencyInfo &BFI,
                       BranchProbabilityInfo &BPI, double &AvgTrip,
                       uint64_t &HeaderCount) {
  const BasicBlock *H = L.getHeader();
  std::optional<uint64_t> HC = BFI.getBlockProfileCount(H);
  if (!HC || *HC == 0)
    return false;
  HeaderCount = *HC;
  uint64_t BackEdges = 0;
  for (const BasicBlock *P : predecessors(H)) {
    if (!L.contains(P))
      continue;
    std::optional<uint64_t> PC = BFI.getBlockProfileCount(P);
    if (!PC)
      continue;
    BackEdges += BPI.getEdgeProbability(P, H).scale(*PC);
  }
  if (BackEdges >= HeaderCount)
    return false;
  uint64_t Exits = HeaderCount - BackEdges;
  AvgTrip = double(HeaderCount) / double(Exits);
  return true;
}

bool hasFPReduction(const Loop &L) {
  for (const BasicBlock *BB : L.getBlocks())
    for (const Instruction &I : *BB)
      if ((I.getOpcode() == Instruction::FAdd ||
           I.getOpcode() == Instruction::FMul) &&
          I.getType()->isFloatingPointTy())
        for (const User *U : I.users())
          if (isa<PHINode>(U) && L.contains(cast<Instruction>(U)->getParent()))
            return true;
  return false;
}

std::string currentAttrs(const Function &F) {
  std::vector<std::string> A;
  if (F.hasFnAttribute(Attribute::NoInline)) A.push_back("noinline");
  if (F.hasFnAttribute(Attribute::InlineHint)) A.push_back("inlinehint");
  if (F.hasFnAttribute(Attribute::AlwaysInline)) A.push_back("alwaysinline");
  if (F.hasFnAttribute(Attribute::Cold)) A.push_back("cold");
  if (F.hasFnAttribute(Attribute::Hot)) A.push_back("hot");
  if (F.getAlign()) A.push_back("align=" + std::to_string(F.getAlign()->value()));
  std::string O;
  for (size_t I = 0; I < A.size(); ++I) O += (I ? "," : "") + A[I];
  return O;
}

unsigned instCount(const Function &F) {
  unsigned N = 0;
  for (const BasicBlock &BB : F) N += BB.size();
  return N;
}

/// How a loop relates to a mark.
///
/// The day-3 brief defines the relation as "any instruction's DILocation ->
/// inlinedAt chain reaches the marked function's DISubprogram". On the toy
/// that pulls in one loop per mark that nobody would call part of the marked
/// function: the driver's `for _ in 0..repeats` loop in toy::run_quotes,
/// whose *body* contains the inlined count_quotes but whose own frame chain
/// does not mention it. Both are reported, and this says which is which, so
/// a plan can tell "the loop inside the function I marked" from "the caller's
/// loop around it".
enum class MarkRel {
  None,
  /// The loop's own source location sits inside the marked function (after
  /// inlining, the frame chain of Loop::getStartLoc() reaches it).
  LoopInMark,
  /// Only the body reaches it: the marked function was inlined into this
  /// loop, which belongs to a caller.
  MarkInLoop,
};

const char *markRelName(MarkRel R) {
  switch (R) {
  case MarkRel::LoopInMark: return "loop_in_mark";
  case MarkRel::MarkInLoop: return "mark_in_loop";
  case MarkRel::None: break;
  }
  return "none";
}

MarkRel loopIsMarked(const Function &F, const Loop &L, const Marks &Mk,
                     const std::string **Out) {
  // (1) the containing function itself is marked
  if (F.getSubprogram())
    if (const std::string *M =
            Mk.match(demangleName(subprogramLinkage(F.getSubprogram())))) {
      *Out = M;
      return MarkRel::LoopInMark;
    }
  if (const std::string *M = Mk.match(demangleName(F.getName()))) {
    *Out = M;
    return MarkRel::LoopInMark;
  }
  // (2) the loop's own location is inside an inlined copy of a marked
  //     function
  if (DebugLoc DL = loopLoc(L)) {
    SmallVector<const DISubprogram *, 8> Chain;
    frameChain(DL.get(), Chain);
    for (const DISubprogram *SP : Chain)
      if (const std::string *M =
              Mk.match(demangleName(subprogramLinkage(SP)))) {
        *Out = M;
        return MarkRel::LoopInMark;
      }
  }
  // (3) some instruction in the body is
  for (const BasicBlock *BB : L.getBlocks())
    for (const Instruction &I : *BB) {
      const DebugLoc &D = I.getDebugLoc();
      if (!D) continue;
      SmallVector<const DISubprogram *, 8> Chain;
      frameChain(D.get(), Chain);
      for (const DISubprogram *SP : Chain)
        if (const std::string *M =
                Mk.match(demangleName(subprogramLinkage(SP)))) {
          *Out = M;
          return MarkRel::MarkInLoop;
        }
    }
  return MarkRel::None;
}

struct JevDumpLoops : PassInfoMixin<JevDumpLoops> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &FAM) {
    if (F.isDeclaration())
      return PreservedAnalyses::all();
    Module &M = *F.getParent();
    std::string Stage = stageOf(M);
    {
      // Create the bucket even when nothing matches, so that a module the
      // loop EP visited always produces a report and the unmatched marks in
      // it are meaningful.
      std::lock_guard<std::mutex> Lk(StateMutex);
      bucketFor(M, Stage).LoopEpRan = true;
    }

    LoopInfo &LI = FAM.getResult<LoopAnalysis>(F);
    if (LI.empty() && !TheMarks.match(demangleName(F.getName())))
      return PreservedAnalyses::all();

    BlockFrequencyInfo &BFI = FAM.getResult<BlockFrequencyAnalysis>(F);
    BranchProbabilityInfo &BPI = FAM.getResult<BranchProbabilityAnalysis>(F);

    std::vector<std::string> Sites;
    std::set<std::string> Hit;

    SmallVector<Loop *, 8> Work(LI.begin(), LI.end());
    while (!Work.empty()) {
      Loop *L = Work.pop_back_val();
      Work.append(L->begin(), L->end());

      const std::string *Mk = nullptr;
      MarkRel Rel = loopIsMarked(F, *L, TheMarks, &Mk);
      if (Rel == MarkRel::None)
        continue;
      Hit.insert(*Mk);

      SiteKey K = computeSiteKey(F, *L);
      unsigned Body = 0;
      bool HasCalls = false;
      for (const BasicBlock *BB : L->getBlocks()) {
        Body += BB->size();
        for (const Instruction &I : *BB)
          if (const auto *CB = dyn_cast<CallBase>(&I))
            if (!CB->getCalledFunction() ||
                !CB->getCalledFunction()->isIntrinsic())
              HasCalls = true;
      }

      double AvgTrip = 0;
      uint64_t HeaderCount = 0;
      bool HaveTrip = estimateTripCount(*L, BFI, BPI, AvgTrip, HeaderCount);
      // Without a profile the header's static frequency still orders sites
      // within a function; it is not comparable across functions, and the
      // report says so by carrying header_count = null.
      double Score = double(HeaderCount) * double(Body);

      std::string Chain;
      for (size_t I = 0; I < K.InlineChain.size(); ++I)
        Chain += (I ? "," : "") + jstr(K.InlineChain[I]);

      std::ostringstream S;
      S << "{"
        << "\"key\": " << jstr(K.Key)
        << ", \"mark\": " << jstr(*Mk)
        << ", \"match\": " << jstr(markRelName(Rel))
        << ", \"owner_fn\": " << jstr(K.OwnerFn)
        << ", \"owner_fn_demangled\": " << jstr(stripGenerics(demangleName(K.OwnerFn)))
        << ", \"inline_chain\": [" << Chain << "]"
        << ", \"leaf\": {\"file\": " << jstr(K.File) << ", \"line\": " << K.Line
        << ", \"col\": " << K.Col << "}"
        << ", \"depth\": " << K.Depth
        << ", \"already_vectorized\": "
        << (loopIdHas(L->getLoopID(), "llvm.loop.isvectorized") ? "true" : "false")
        << ", \"jev_applied\": "
        << (loopIdHas(L->getLoopID(), "jev.applied") ? "true" : "false")
        << ", \"trip_count\": ";
      if (HaveTrip) { char B[32]; snprintf(B, 32, "%.3f", AvgTrip); S << B; }
      else S << "null";
      S << ", \"header_count\": ";
      if (HeaderCount) S << HeaderCount; else S << "null";
      S << ", \"body_inst_count\": " << Body
        << ", \"hotness\": " << uint64_t(Score)
        << ", \"has_calls\": " << (HasCalls ? "true" : "false")
        << ", \"has_fp_reduction\": " << (hasFPReduction(*L) ? "true" : "false")
        << "}";
      Sites.push_back(S.str());
    }

    // The function table covers marked functions whether or not they contain
    // a loop, so a mark that names a leaf helper still shows up.
    std::string FnRow;
    if (const std::string *Mk = TheMarks.match(demangleName(F.getName()))) {
      std::ostringstream S;
      S << "{"
        << "\"linkage\": " << jstr(F.getName())
        << ", \"demangled\": " << jstr(stripGenerics(demangleName(F.getName())))
        << ", \"mark\": " << jstr(*Mk)
        << ", \"inst_count\": " << instCount(F)
        << ", \"entry_count\": ";
      if (auto EC = F.getEntryCount()) S << *EC; else S << "null";
      S << ", \"attributes\": " << jstr(currentAttrs(F))
        << ", \"n_loops\": " << std::distance(LI.begin(), LI.end())
        << "}";
      FnRow = S.str();
      Hit.insert(*Mk);
    }

    if (Sites.empty() && FnRow.empty())
      return PreservedAnalyses::all();

    {
      std::lock_guard<std::mutex> Lk(StateMutex);
      Bucket &B = bucketFor(M, Stage);
      for (std::string &S : Sites) B.SiteJson.push_back(std::move(S));
      if (!FnRow.empty()) B.FnJson[F.getName().str()] = std::move(FnRow);
      B.MatchedMarks.insert(Hit.begin(), Hit.end());
    }
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

//===----------------------------------------------------------------------===//
// apply
//===----------------------------------------------------------------------===//

/// Per (module, stage), how many loops each plan key resolved to. Written at
/// process exit so 0 becomes `vanished` and >1 becomes `ambiguous`
/// (SPEC.ja.md 8.3: neither is moved to a different loop, both are counted,
/// because the count is the health metric for the whole design).
std::map<std::string, std::map<std::string, unsigned>> KeyHits; // bucketKey -> key -> n

struct JevApplyLoopMD : PassInfoMixin<JevApplyLoopMD> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &FAM) {
    if (F.isDeclaration() || ThePlan.LoopMD.empty())
      return PreservedAnalyses::all();
    Module &M = *F.getParent();
    std::string Stage = stageOf(M);
    {
      std::lock_guard<std::mutex> Lk(StateMutex);
      bucketFor(M, Stage).LoopEpRan = true;
    }

    LoopInfo &LI = FAM.getResult<LoopAnalysis>(F);
    if (LI.empty())
      return PreservedAnalyses::all();

    std::vector<std::string> Results;
    std::vector<std::pair<std::string, unsigned>> Hits;

    SmallVector<Loop *, 8> Work(LI.begin(), LI.end());
    while (!Work.empty()) {
      Loop *L = Work.pop_back_val();
      Work.append(L->begin(), L->end());

      SiteKey K = computeSiteKey(F, *L);
      const LoopMDEntry *E = nullptr;
      for (const LoopMDEntry &Cand : ThePlan.LoopMD)
        if (Cand.Key == K.Key && (Cand.Stage.empty() || Cand.Stage == Stage)) {
          E = &Cand;
          break;
        }
      if (!E)
        continue;
      Hits.emplace_back(E->Key, 1);

      MDNode *ID = L->getLoopID();
      const char *Outcome = nullptr;
      if (loopIdHas(ID, "llvm.loop.isvectorized"))
        Outcome = "already_vectorized";
      else if (loopIdHas(ID, "jev.applied"))
        Outcome = "skipped_idempotent";
      else if (loopIdStrValue(ID, "jev.site") == E->Key)
        Outcome = "skipped_idempotent";

      std::vector<std::string> Added;
      if (!Outcome) {
        LLVMContext &Ctx = F.getContext();
        SmallVector<Metadata *, 6> New;
        if (E->VectorizeWidth) {
          New.push_back(mdStrInt(Ctx, "llvm.loop.vectorize.width", E->VectorizeWidth));
          New.push_back(mdStrInt(Ctx, "llvm.loop.vectorize.enable", 1));
          Added.push_back("vectorize.width=" + std::to_string(E->VectorizeWidth));
        }
        if (E->InterleaveCount) {
          New.push_back(mdStrInt(Ctx, "llvm.loop.interleave.count", E->InterleaveCount));
          Added.push_back("interleave.count=" + std::to_string(E->InterleaveCount));
        }
        if (E->UnrollCount) {
          New.push_back(mdStrInt(Ctx, "llvm.loop.unroll.count", E->UnrollCount));
          Added.push_back("unroll.count=" + std::to_string(E->UnrollCount));
        }
        if (E->UnrollDisable) {
          New.push_back(mdStr(Ctx, "llvm.loop.unroll.disable"));
          Added.push_back("unroll.disable");
        }
        if (New.empty()) {
          Outcome = "skipped_empty";
        } else {
          New.push_back(mdStrStr(Ctx, "jev.site", E->Key));
          New.push_back(mdStr(Ctx, "jev.applied"));
          appendLoopMD(*L, New);
          Outcome = "attached";
        }
      }

      std::string AddedStr;
      for (size_t I = 0; I < Added.size(); ++I) AddedStr += (I ? "," : "") + Added[I];
      std::ostringstream S;
      S << "{\"key\": " << jstr(E->Key) << ", \"outcome\": " << jstr(Outcome)
        << ", \"owner_fn\": " << jstr(K.OwnerFn)
        << ", \"leaf\": {\"file\": " << jstr(K.File) << ", \"line\": " << K.Line
        << ", \"col\": " << K.Col << "}"
        << ", \"attached\": " << jstr(AddedStr) << "}";
      Results.push_back(S.str());
    }

    if (Results.empty())
      return PreservedAnalyses::all();

    {
      std::lock_guard<std::mutex> Lk(StateMutex);
      Bucket &B = bucketFor(M, Stage);
      std::string BK = B.ModuleId + "\x1f" + B.Stage;
      for (auto &H : Hits) KeyHits[BK][H.first] += H.second;
      for (std::string &S : Results) B.ResultJson.push_back(std::move(S));
    }
    // Loop metadata changes neither the CFG nor any analysis result
    // (SPEC.ja.md 8.2).
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

/// Function attributes, at PipelineStart: before any inlining, once per CGU.
struct JevApplyFnAttrs : PassInfoMixin<JevApplyFnAttrs> {
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    setStage(M, "prelink");
    if (ThePlan.FnAttrs.empty())
      return PreservedAnalyses::all();

    bool Changed = false;
    std::vector<std::string> Results;
    std::map<std::string, unsigned> Matches;
    for (const FnAttrEntry &E : ThePlan.FnAttrs)
      Matches[E.Fn] = 0;

    for (Function &F : M) {
      if (F.isDeclaration())
        continue;
      std::string Dem = stripGenerics(demangleName(F.getName()));
      const FnAttrEntry *E = nullptr;
      for (const FnAttrEntry &C : ThePlan.FnAttrs) {
        std::string N = stripGenerics(C.Fn);
        if (F.getName() == C.Fn || Dem == N ||
            (Dem.size() > N.size() + 2 &&
             Dem.compare(Dem.size() - N.size(), N.size(), N) == 0 &&
             Dem.compare(Dem.size() - N.size() - 2, 2, "::") == 0)) {
          E = &C;
          break;
        }
      }
      if (!E)
        continue;
      Matches[E->Fn]++;

      std::vector<std::string> Applied;
      if (E->Inline == "never") {
        // The verifier rejects a function that is both noinline and
        // inlinehint/alwaysinline, so the opposite attribute goes first.
        F.removeFnAttr(Attribute::InlineHint);
        F.removeFnAttr(Attribute::AlwaysInline);
        if (!F.hasFnAttribute(Attribute::NoInline)) {
          F.addFnAttr(Attribute::NoInline);
          Changed = true;
        }
        Applied.push_back("noinline");
      } else if (E->Inline == "hint") {
        F.removeFnAttr(Attribute::NoInline);
        if (!F.hasFnAttribute(Attribute::InlineHint)) {
          F.addFnAttr(Attribute::InlineHint);
          Changed = true;
        }
        Applied.push_back("inlinehint");
      }
      if (E->Cold) {
        F.removeFnAttr(Attribute::Hot);
        if (!F.hasFnAttribute(Attribute::Cold)) {
          F.addFnAttr(Attribute::Cold);
          Changed = true;
        }
        Applied.push_back("cold");
      }
      if (E->Hot) {
        F.removeFnAttr(Attribute::Cold);
        if (!F.hasFnAttribute(Attribute::Hot)) {
          F.addFnAttr(Attribute::Hot);
          Changed = true;
        }
        Applied.push_back("hot");
      }
      if (E->Align) {
        MaybeAlign Cur = F.getAlign();
        if (!Cur || Cur->value() != uint64_t(E->Align)) {
          F.setAlignment(Align(E->Align));
          Changed = true;
        }
        Applied.push_back("align=" + std::to_string(E->Align));
      }

      std::string AppliedStr;
      for (size_t I = 0; I < Applied.size(); ++I)
        AppliedStr += (I ? "," : "") + Applied[I];
      std::ostringstream S;
      S << "{\"fn\": " << jstr(E->Fn) << ", \"outcome\": "
        << jstr(Applied.empty() ? "skipped_empty" : "consumed")
        << ", \"linkage\": " << jstr(F.getName())
        << ", \"demangled\": " << jstr(Dem)
        << ", \"attached\": " << jstr(AppliedStr) << "}";
      Results.push_back(S.str());
    }

    {
      std::lock_guard<std::mutex> Lk(StateMutex);
      Bucket &B = bucketFor(M, "prelink");
      for (std::string &S : Results) B.ResultJson.push_back(std::move(S));
      // A fn_attrs entry naming a function defined in another crate is
      // legitimately absent from this module; the CLI decides, over all
      // modules, whether it was never found anywhere.
      for (auto &KV : Matches)
        if (KV.second == 0)
          B.ResultJson.push_back("{\"fn\": " + jstr(KV.first) +
                                 ", \"outcome\": \"unmatched\"}");
        else if (KV.second > 1)
          B.ResultJson.push_back("{\"fn\": " + jstr(KV.first) +
                                 ", \"outcome\": \"ambiguous\", \"n\": " +
                                 std::to_string(KV.second) + "}");
    }

    if (!Changed)
      return PreservedAnalyses::all();
    // Inlining cost, alignment and cold/hot all feed TargetTransformInfo;
    // nothing else this pass touches invalidates an analysis.
    PreservedAnalyses PA = PreservedAnalyses::all();
    PA.abandon<TargetIRAnalysis>();
    return PA;
  }
  static bool isRequired() { return true; }
};

/// The function table for marked functions, emitted from a module pass so
/// that it covers functions with no loops at all. Registered twice in the
/// pre-link pipeline (see Bucket::FnJson for why).
struct JevDumpFnTable : PassInfoMixin<JevDumpFnTable> {
  bool AlsoSetPrelink;
  explicit JevDumpFnTable(bool AlsoSetPrelink) : AlsoSetPrelink(AlsoSetPrelink) {}

  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    if (AlsoSetPrelink)
      setStage(M, "prelink");
    std::string Stage = stageOf(M);

    std::map<std::string, std::string> Rows;
    std::set<std::string> Hit;
    for (Function &F : M) {
      if (F.isDeclaration())
        continue;
      const std::string *Mk = TheMarks.match(demangleName(F.getName()));
      if (!Mk)
        continue;
      Hit.insert(*Mk);
      unsigned NLoops = 0;
      for (const BasicBlock &BB : F)
        if (const Instruction *T = BB.getTerminator())
          for (const BasicBlock *Succ : successors(T))
            if (Succ == &BB) { ++NLoops; break; }
      std::ostringstream S;
      S << "{"
        << "\"linkage\": " << jstr(F.getName())
        << ", \"demangled\": " << jstr(stripGenerics(demangleName(F.getName())))
        << ", \"mark\": " << jstr(*Mk)
        << ", \"inst_count\": " << instCount(F)
        << ", \"entry_count\": ";
      if (auto EC = F.getEntryCount()) S << *EC; else S << "null";
      S << ", \"attributes\": " << jstr(currentAttrs(F))
        << ", \"self_loops\": " << NLoops
        << "}";
      Rows[F.getName().str()] = S.str();
    }
    if (Rows.empty())
      return PreservedAnalyses::all();
    {
      std::lock_guard<std::mutex> Lk(StateMutex);
      Bucket &B = bucketFor(M, Stage);
      for (auto &KV : Rows) B.FnJson[KV.first] = KV.second;
      B.MatchedMarks.insert(Hit.begin(), Hit.end());
    }
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

/// Records the merged fat-LTO stage.
struct JevMarkLTOStage : PassInfoMixin<JevMarkLTOStage> {
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    setStage(M, "lto");
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

/// Records the ThinLTO post-link stage. Thin LTO has no
/// FullLinkTimeOptimization extension point; what identifies its second,
/// per-module pipeline is the ThinOrFullLTOPhase argument the module EPs
/// carry (results.md "Day 3 (plugin)" section 2, the lto=thin row).
struct JevMarkStageFromPhase : PassInfoMixin<JevMarkStageFromPhase> {
  const char *Stage;
  explicit JevMarkStageFromPhase(const char *Stage) : Stage(Stage) {}
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    setStage(M, Stage);
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

//===----------------------------------------------------------------------===//
// registration
//===----------------------------------------------------------------------===//

void finalizeKeyOutcomes() {
  // Called from writeReports via atexit ordering: fold the per-key hit counts
  // into vanished / ambiguous rows.
  for (auto &BKV : KeyHits) {
    auto It = Buckets.find(BKV.first);
    if (It == Buckets.end())
      continue;
    for (auto &KKV : BKV.second)
      if (KKV.second > 1)
        It->second.ResultJson.push_back(
            "{\"key\": " + jstr(KKV.first) + ", \"outcome\": \"ambiguous\", \"n\": " +
            std::to_string(KKV.second) + "}");
  }
  // Keys in the plan that no bucket resolved at all.
  for (auto &BKV : Buckets) {
    if (!BKV.second.LoopEpRan)
      continue;
    for (const LoopMDEntry &E : ThePlan.LoopMD) {
      if (!E.Stage.empty() && E.Stage != BKV.second.Stage)
        continue;
      auto It = KeyHits.find(BKV.first);
      if (It == KeyHits.end() || !It->second.count(E.Key))
        BKV.second.ResultJson.push_back("{\"key\": " + jstr(E.Key) +
                                        ", \"outcome\": \"vanished\"}");
    }
  }
}

void registerCallbacks(PassBuilder &PB) {
  // Stage tracking is needed in every non-off mode.
  PB.registerFullLinkTimeOptimizationEarlyEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel) {
        MPM.addPass(JevMarkLTOStage());
      });
  // PipelineEarlySimplification is the first module EP of both the pre-link
  // and the ThinLTO post-link pipelines and is the only one that carries the
  // phase, so it is where a thin post-link module gets labelled.
  PB.registerPipelineEarlySimplificationEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel, ThinOrFullLTOPhase P) {
        if (P == ThinOrFullLTOPhase::ThinLTOPostLink)
          MPM.addPass(JevMarkStageFromPhase("thinlto"));
        else if (P == ThinOrFullLTOPhase::FullLTOPostLink)
          MPM.addPass(JevMarkStageFromPhase("lto"));
      });

  if (TheMode == Mode::ApplyDump) {
    PB.registerPipelineStartEPCallback(
        [](ModulePassManager &MPM, OptimizationLevel) {
          MPM.addPass(JevApplyFnAttrs());
          MPM.addPass(JevDumpFnTable(/*AlsoSetPrelink=*/false));
        });
    PB.registerOptimizerEarlyEPCallback(
        [](ModulePassManager &MPM, OptimizationLevel, ThinOrFullLTOPhase P) {
          if (P == ThinOrFullLTOPhase::ThinLTOPostLink ||
              P == ThinOrFullLTOPhase::FullLTOPostLink)
            return;
          MPM.addPass(JevDumpFnTable(/*AlsoSetPrelink=*/false));
        });
    PB.registerVectorizerStartEPCallback(
        [](FunctionPassManager &FPM, OptimizationLevel) {
          FPM.addPass(JevDumpLoops());
        });
    return;
  }

  if (TheMode == Mode::Dump) {
    // PipelineStart: the pre-inlining snapshot, i.e. exactly the state the
    // fn_attrs half of a plan would act on.
    PB.registerPipelineStartEPCallback(
        [](ModulePassManager &MPM, OptimizationLevel) {
          MPM.addPass(JevDumpFnTable(/*AlsoSetPrelink=*/true));
        });
    // OptimizerEarly, pre-link only: PGOInstrumentationUse has run by now, so
    // the same rows carry entry_count.
    PB.registerOptimizerEarlyEPCallback(
        [](ModulePassManager &MPM, OptimizationLevel, ThinOrFullLTOPhase P) {
          if (P == ThinOrFullLTOPhase::ThinLTOPostLink ||
              P == ThinOrFullLTOPhase::FullLTOPostLink)
            return;
          MPM.addPass(JevDumpFnTable(/*AlsoSetPrelink=*/false));
        });
    PB.registerVectorizerStartEPCallback(
        [](FunctionPassManager &FPM, OptimizationLevel) {
          FPM.addPass(JevDumpLoops());
        });
    return;
  }

  // apply
  PB.registerPipelineStartEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel) {
        MPM.addPass(JevApplyFnAttrs());
      });
  PB.registerVectorizerStartEPCallback(
      [](FunctionPassManager &FPM, OptimizationLevel) {
        FPM.addPass(JevApplyLoopMD());
      });
}

struct Init {
  Init() {
    std::string M = envStr("JEV_MODE");
    if (M.empty() || M == "off") TheMode = Mode::Off;
    else if (M == "dump") TheMode = Mode::Dump;
    else if (M == "apply") TheMode = Mode::Apply;
    else if (M == "apply-dump") TheMode = Mode::ApplyDump;
    else fatal("JEV_MODE must be off, dump, apply or apply-dump, got \"" + M +
               "\"");

    if (TheMode == Mode::Off)
      return;

    // Known-answer test. JEV_PLAN_SHA is the only thing standing between a
    // stale plan and a silently mis-hinted build, and the sha256 above is
    // hand written because the host libLLVM does not export llvm::SHA256, so
    // it is checked rather than trusted. Two vectors, empty and "abc".
    if (sha256Hex("") !=
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" ||
        sha256Hex("abc") !=
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
      fatal("internal sha256 self-test failed");

    ReportDir = envStr("JEV_REPORT_DIR");
    if (ReportDir.empty())
      fatal("JEV_MODE=" + M + " needs JEV_REPORT_DIR");
    TheMarks = loadMarks(envStr("JEV_MARKS"));
    if ((TheMode == Mode::Dump || TheMode == Mode::ApplyDump) && TheMarks.empty())
      fatal("JEV_MODE=" + M + " needs JEV_MARKS with at least one function");
    if (TheMode == Mode::Apply || TheMode == Mode::ApplyDump)
      loadPlanOnce();
  }
};

} // namespace

extern "C" __attribute__((visibility("default"))) LLVM_ATTRIBUTE_WEAK
::llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  static Init I;
  if (TheMode == Mode::Off) {
    // Off is a genuine no-op: no callback is registered at all, so the
    // pipeline rustc builds is byte for byte the one it builds with no
    // plugin loaded (SPEC.ja.md 8.2 off-equivalence gate).
    return {LLVM_PLUGIN_API_VERSION, "jev", "0.1", nullptr};
  }
  return {LLVM_PLUGIN_API_VERSION, "jev", "0.1", registerCallbacks};
}
