//===- probe.cpp - map rustc's pass pipelines to PassBuilder EPs ----------===//
//
// jev-opt probe plugin. It changes no IR: at every PassBuilder extension
// point it appends a pass that writes one record to a log and returns
// PreservedAnalyses::all(). The point is to answer, by measurement rather
// than by reading LLVM's source, the questions SPEC.ja.md 8.2 leaves open:
//
//   * which extension points rustc's pipelines actually invoke, and in which
//     ThinOrFullLTOPhase, for lto=off / thin / fat,
//   * whether a plugin is loaded at all in the merged (post-link) LTO stage,
//   * how many loops already carry llvm.loop.isvectorized when each point
//     runs --- i.e. how late is too late to place a loop hint,
//   * whether the module carries a ProfileSummary at that point.
//
// Everything is written to $JEV_REPORT_DIR/<module>-<pid>.log as one
// `key=value` record per line. Several rustc processes run concurrently under
// cargo, and under fat LTO one process optimises the same module identifier
// twice, so the pid is part of the file name and a per-process sequence
// number orders the records within a file.
//
// Build: see scripts/build_plugin.sh. No LLVM library is linked; the symbols
// resolve against the libLLVM.so that rustc itself is linked against
// (results.md "Day 0" section 2).
//
//===----------------------------------------------------------------------===//

#include "llvm/Analysis/LoopInfo.h"
#include "llvm/Analysis/ProfileSummaryInfo.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Metadata.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/IR/ProfileSummary.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Transforms/Scalar/LoopPassManager.h"

#include <atomic>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <set>
#include <string>
#include <unistd.h>

using namespace llvm;

namespace {

// --- log plumbing ---------------------------------------------------------

std::atomic<unsigned long> Seq{0};
std::mutex LogMutex;

/// Module identifiers are paths ("/home/.../deps/toyloops-1a2b.3c4d-cgu.0"),
/// which cannot go into a file name as they are.
std::string sanitize(StringRef S) {
  std::string Out;
  Out.reserve(S.size());
  for (char C : S)
    Out.push_back((isalnum((unsigned char)C) || C == '.' || C == '-' || C == '_')
                      ? C
                      : '_');
  // Keep the tail: the distinguishing part of a CGU name is at the end.
  if (Out.size() > 120)
    Out = Out.substr(Out.size() - 120);
  return Out;
}

/// Append one record. Opening the file per record is far cheaper than the
/// analyses around it and survives concurrent rustc processes, which write to
/// different files anyway (pid is in the name).
void logLine(const Module &M, const std::string &Rec) {
  const char *Dir = getenv("JEV_REPORT_DIR");
  std::string Path;
  if (Dir && *Dir)
    Path = std::string(Dir) + "/" + sanitize(M.getModuleIdentifier()) + "-" +
           std::to_string(getpid()) + ".log";

  std::string Line = "seq=" + std::to_string(Seq.fetch_add(1)) +
                     " pid=" + std::to_string(getpid()) + " " + Rec + "\n";

  std::lock_guard<std::mutex> Lock(LogMutex);
  if (!Path.empty()) {
    std::ofstream F(Path, std::ios::app);
    if (F) {
      F << Line;
      return;
    }
  }
  // No JEV_REPORT_DIR, or it is not writable: say so on stderr rather than
  // silently producing an empty EP table.
  errs() << "jevprobe: " << Line;
}

// --- IR inspection --------------------------------------------------------

/// True when this loop-id metadata node carries llvm.loop.isvectorized.
bool loopIdHas(const MDNode *LoopID, StringRef Key) {
  if (!LoopID)
    return false;
  for (unsigned I = 1, E = LoopID->getNumOperands(); I < E; ++I) {
    const MDNode *Op = dyn_cast_or_null<MDNode>(LoopID->getOperand(I));
    if (Op && Op->getNumOperands() >= 1)
      if (auto *S = dyn_cast_or_null<MDString>(Op->getOperand(0)))
        if (S->getString() == Key)
          return true;
  }
  return false;
}

struct LoopMDCounts {
  unsigned WithLoopMD = 0;   // terminators carrying !llvm.loop
  unsigned IsVectorized = 0; // ... of which llvm.loop.isvectorized
};

/// Counted straight off the terminators, so it needs no LoopInfo and gives
/// the same answer from a module, function or loop pass.
LoopMDCounts countLoopMD(const Function &F) {
  LoopMDCounts C;
  for (const BasicBlock &BB : F) {
    const Instruction *T = BB.getTerminator();
    if (!T)
      continue;
    const MDNode *ID = T->getMetadata(LLVMContext::MD_loop);
    if (!ID)
      continue;
    ++C.WithLoopMD;
    if (loopIdHas(ID, "llvm.loop.isvectorized"))
      ++C.IsVectorized;
  }
  return C;
}

LoopMDCounts countLoopMD(const Module &M, unsigned &NumDefinedFns) {
  LoopMDCounts C;
  NumDefinedFns = 0;
  for (const Function &F : M) {
    if (F.isDeclaration())
      continue;
    ++NumDefinedFns;
    LoopMDCounts FC = countLoopMD(F);
    C.WithLoopMD += FC.WithLoopMD;
    C.IsVectorized += FC.IsVectorized;
  }
  return C;
}

const char *phaseName(ThinOrFullLTOPhase P) {
  switch (P) {
  case ThinOrFullLTOPhase::None:
    return "None";
  case ThinOrFullLTOPhase::ThinLTOPreLink:
    return "ThinLTOPreLink";
  case ThinOrFullLTOPhase::ThinLTOPostLink:
    return "ThinLTOPostLink";
  case ThinOrFullLTOPhase::FullLTOPreLink:
    return "FullLTOPreLink";
  case ThinOrFullLTOPhase::FullLTOPostLink:
    return "FullLTOPostLink";
  }
  return "?";
}

/// In LLVM 23 OptimizationLevel is a plain `enum class : int` (O0..O3); the
/// getSpeedupLevel()/getSizeLevel() accessors of earlier releases are gone,
/// and so is the Os/Oz distinction at this interface.
std::string levelName(OptimizationLevel L) {
  return "O" + std::to_string(static_cast<int>(L));
}

std::string moduleRecord(const Module &M, StringRef EP, StringRef Scope,
                         StringRef Phase, StringRef Level) {
  unsigned NumFns = 0;
  LoopMDCounts C = countLoopMD(M, NumFns);
  bool HasPS = M.getProfileSummary(/*IsCS=*/false) != nullptr;
  bool HasCSPS = M.getProfileSummary(/*IsCS=*/true) != nullptr;
  return ("ep=" + EP + " scope=" + Scope + " phase=" + Phase +
          " level=" + Level + " module=" + M.getModuleIdentifier() +
          " nfunc=" + std::to_string(NumFns) +
          " nloopmd=" + std::to_string(C.WithLoopMD) +
          " nisvec=" + std::to_string(C.IsVectorized) +
          " profsummary=" + (HasPS ? "1" : "0") +
          " cs_profsummary=" + (HasCSPS ? "1" : "0"))
      .str();
}

// --- the probe passes -----------------------------------------------------

/// Logs the whole module once per invocation. Used at the module EPs.
struct ProbeModulePass : PassInfoMixin<ProbeModulePass> {
  std::string EP, Phase, Level;
  ProbeModulePass(std::string EP, std::string Phase, std::string Level)
      : EP(std::move(EP)), Phase(std::move(Phase)), Level(std::move(Level)) {}

  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    logLine(M, moduleRecord(M, EP, "module", Phase, Level));
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

/// Logs one record per *function that has loop metadata*, plus one
/// module-level record the first time this EP sees this module.
///
/// Function EPs are interleaved with the rest of the function pipeline, so a
/// module-wide count taken here is a snapshot at whichever function arrived
/// first; that is still the number that says whether the vectorizer has
/// already run by this point, which is what the EP table needs. The
/// per-function records are what actually names the four toy loops.
struct ProbeFunctionPass : PassInfoMixin<ProbeFunctionPass> {
  std::string EP, Level;
  ProbeFunctionPass(std::string EP, std::string Level)
      : EP(std::move(EP)), Level(std::move(Level)) {}

  PreservedAnalyses run(Function &F, FunctionAnalysisManager &) {
    Module &M = *F.getParent();
    // One module summary per (EP, module, process).
    static std::mutex SeenMutex;
    static std::set<std::string> Seen;
    {
      std::lock_guard<std::mutex> L(SeenMutex);
      std::string K = EP + "\x1f" + M.getModuleIdentifier();
      if (Seen.insert(K).second)
        logLine(M, moduleRecord(M, EP, "module-first", "-", Level));
    }

    LoopMDCounts C = countLoopMD(F);
    if (C.WithLoopMD == 0)
      return PreservedAnalyses::all();
    logLine(M, ("ep=" + EP + " scope=function phase=- level=" + Level +
                " module=" + M.getModuleIdentifier() + " func=" + F.getName() +
                " nloopmd=" + std::to_string(C.WithLoopMD) +
                " nisvec=" + std::to_string(C.IsVectorized) +
                " entrycount=" +
                (F.getEntryCount() ? std::to_string(*F.getEntryCount())
                                   : std::string("-")))
                   .str());
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

/// Logs one record per loop. Used at the loop EPs.
struct ProbeLoopPass : PassInfoMixin<ProbeLoopPass> {
  std::string EP, Level;
  ProbeLoopPass(std::string EP, std::string Level)
      : EP(std::move(EP)), Level(std::move(Level)) {}

  PreservedAnalyses run(Loop &L, LoopAnalysisManager &,
                        LoopStandardAnalysisResults &, LPMUpdater &) {
    Function &F = *L.getHeader()->getParent();
    Module &M = *F.getParent();
    const MDNode *ID = L.getLoopID();
    std::string Loc = "-";
    if (const DebugLoc &DL = L.getStartLoc())
      Loc = (DL->getFilename() + ":" + Twine(DL->getLine())).str();
    logLine(M, ("ep=" + EP + " scope=loop phase=- level=" + Level +
                " module=" + M.getModuleIdentifier() + " func=" + F.getName() +
                " depth=" + std::to_string(L.getLoopDepth()) + " loc=" + Loc +
                " isvec=" + (loopIdHas(ID, "llvm.loop.isvectorized") ? "1" : "0"))
                   .str());
    return PreservedAnalyses::all();
  }
  static bool isRequired() { return true; }
};

void registerCallbacks(PassBuilder &PB) {
  // Module EPs without a phase argument.
  PB.registerPipelineStartEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel L) {
        MPM.addPass(ProbeModulePass("PipelineStart", "-", levelName(L)));
      });
  PB.registerFullLinkTimeOptimizationEarlyEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel L) {
        MPM.addPass(
            ProbeModulePass("FullLinkTimeOptimizationEarly", "-", levelName(L)));
      });
  PB.registerFullLinkTimeOptimizationLastEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel L) {
        MPM.addPass(
            ProbeModulePass("FullLinkTimeOptimizationLast", "-", levelName(L)));
      });

  // Module EPs that are handed the LTO phase. This is the authoritative
  // pre-link / post-link signal; everything else has to infer it.
  PB.registerPipelineEarlySimplificationEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel L, ThinOrFullLTOPhase P) {
        MPM.addPass(ProbeModulePass("PipelineEarlySimplification", phaseName(P),
                                    levelName(L)));
      });
  PB.registerOptimizerEarlyEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel L, ThinOrFullLTOPhase P) {
        MPM.addPass(ProbeModulePass("OptimizerEarly", phaseName(P), levelName(L)));
      });
  PB.registerOptimizerLastEPCallback(
      [](ModulePassManager &MPM, OptimizationLevel L, ThinOrFullLTOPhase P) {
        MPM.addPass(ProbeModulePass("OptimizerLast", phaseName(P), levelName(L)));
      });

  // Function EPs.
  PB.registerPeepholeEPCallback(
      [](FunctionPassManager &FPM, OptimizationLevel L) {
        FPM.addPass(ProbeFunctionPass("Peephole", levelName(L)));
      });
  PB.registerScalarOptimizerLateEPCallback(
      [](FunctionPassManager &FPM, OptimizationLevel L) {
        FPM.addPass(ProbeFunctionPass("ScalarOptimizerLate", levelName(L)));
      });
  PB.registerVectorizerStartEPCallback(
      [](FunctionPassManager &FPM, OptimizationLevel L) {
        FPM.addPass(ProbeFunctionPass("VectorizerStart", levelName(L)));
      });
  PB.registerVectorizerEndEPCallback(
      [](FunctionPassManager &FPM, OptimizationLevel L) {
        FPM.addPass(ProbeFunctionPass("VectorizerEnd", levelName(L)));
      });

  // Loop EPs. LateLoopOptimizations is not in SPEC.ja.md 8.2's candidate
  // list, but it is the other place a loop pass can be inserted, so the table
  // covers it too.
  PB.registerLateLoopOptimizationsEPCallback(
      [](LoopPassManager &LPM, OptimizationLevel L) {
        LPM.addPass(ProbeLoopPass("LateLoopOptimizations", levelName(L)));
      });
  PB.registerLoopOptimizerEndEPCallback(
      [](LoopPassManager &LPM, OptimizationLevel L) {
        LPM.addPass(ProbeLoopPass("LoopOptimizerEnd", levelName(L)));
      });
}

} // namespace

// -fvisibility=hidden hides everything by default (so the plugin can never
// interpose a libLLVM symbol), which would hide the one symbol rustc looks
// up by name as well; hence the explicit default visibility here.
extern "C" __attribute__((visibility("default"))) LLVM_ATTRIBUTE_WEAK
::llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "jevprobe", "0.1", registerCallbacks};
}
