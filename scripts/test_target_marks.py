#!/usr/bin/env python3
"""Unit tests for scripts/target_marks.py (decision 109), with stubs.

No perf, no build, no HTTP: the profile commands, the busy check, perf's
presence and the generator are replaced by stubs. Run:

    python3 scripts/test_target_marks.py -v
"""

import argparse
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import target_marks as TM      # noqa: E402


class Matching(unittest.TestCase):
    def test_plugin_rule(self):
        m = TM.plugin_match
        self.assertTrue(m("jaq_json::read::parse",
                          "jaq_json::read::parse::<hifijson::SliceLexer>"))
        self.assertTrue(m("jaq_json::read::parse",
                          "jaq_json::read::parse::{closure#1}"))
        self.assertFalse(m("jaq_json::read::parse",
                           "jaq_json::read::parse_string"))
        self.assertTrue(m("k2_mix", "hbkernels::k2_mix"))

    def test_line_of_keeps_names_the_stripped_line_would_miss(self):
        self.assertEqual(TM.line_of(
            "<jaq_json::Val as core::hash::Hash>::hash::<foldhash::F>"),
            "<jaq_json::Val as core::hash::Hash>::hash")
        full = "jaq_json::read::parse::<hifijson::SliceLexer>::{closure#1}"
        self.assertEqual(TM.line_of(full), full)

    def test_final_lines_folds_covered_lines(self):
        lines, folded = TM.final_lines([
            "jaq_json::read::parse",
            "jaq_json::read::parse::<hifijson::SliceLexer>::{closure#1}",
            "jaq_json::read::parse_string"])
        self.assertEqual(lines, ["jaq_json::read::parse",
                                 "jaq_json::read::parse_string"])
        self.assertEqual(list(folded.values()), ["jaq_json::read::parse"])


class Resolve(unittest.TestCase):
    """--marks resolution: explicit -> existing generated -> generate once;
    --marks-regenerate -> the next versioned file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = mock.patch.object(TM, "REPO", self.tmp)
        self.repo.start()
        self.t = "zz"
        os.makedirs(os.path.join(self.tmp, "targets", self.t))
        self.calls = []

    def tearDown(self):
        self.repo.stop()
        shutil.rmtree(self.tmp)

    def gen(self, argv):
        self.calls.append(argv)
        out = os.path.join(self.tmp, argv[argv.index("--out") + 1])
        rid = argv[argv.index("--run-id") + 1]
        with open(out, "w") as f:
            f.write("# Produced by: scripts/target_marks.py %s\n"
                    "# Jev log: artifacts/jev-marks/zz/%s.jsonl\n\nzz::f\n"
                    % (" ".join(argv), rid))
        return 0

    def test_explicit(self):
        p = os.path.join(self.tmp, "m.txt")
        open(p, "w").write("zz::f\n")
        path, prov = TM.resolve_marks(self.t, explicit=p, generate=self.gen)
        self.assertEqual(path, p)
        self.assertEqual(prov["how"], "explicit")
        self.assertEqual(self.calls, [])

    def test_generate_once_then_reuse(self):
        path, prov = TM.resolve_marks(self.t, generate=self.gen)
        self.assertEqual(prov["how"], "generated now")
        self.assertTrue(path.endswith("targets/zz/jev-marks.jev.txt"))
        self.assertEqual(prov["jev_log"], "artifacts/jev-marks/zz/tm-zz.jsonl")
        self.assertIn("--jev", self.calls[0])
        sha = prov["sha256"]
        path2, prov2 = TM.resolve_marks(self.t, generate=self.gen)
        self.assertEqual((path2, prov2["how"], prov2["sha256"]),
                         (path, "existing generated", sha))
        self.assertEqual(len(self.calls), 1)       # never regenerated silently

    def test_regenerate_is_versioned(self):
        TM.resolve_marks(self.t, generate=self.gen)
        first = open(TM.generated_path(self.t)).read()
        path, prov = TM.resolve_marks(self.t, regenerate=True,
                                      generate=self.gen)
        self.assertTrue(path.endswith("jev-marks.jev.v2.txt"))
        self.assertEqual(prov["version"], 2)
        self.assertIn("tm-zz-v2", self.calls[-1])
        self.assertEqual(open(TM.generated_path(self.t)).read(), first)
        path3, prov3 = TM.resolve_marks(self.t, generate=self.gen)
        self.assertEqual((path3, prov3["how"]), (path, "existing generated"))
        path4, _ = TM.resolve_marks(self.t, regenerate=True, marks_n=5,
                                    generate=self.gen)
        self.assertTrue(path4.endswith("jev-marks.jev.v3.txt"))
        self.assertIn("5", self.calls[-1])

    def test_no_generation_in_dry_modes(self):
        with self.assertRaises(SystemExit):
            TM.resolve_marks(self.t, allow_generate=False, generate=self.gen)
        self.assertEqual(self.calls, [])

    def test_explicit_and_regenerate_conflict(self):
        p = os.path.join(self.tmp, "m.txt")
        open(p, "w").write("zz::f\n")
        with self.assertRaises(SystemExit):
            TM.resolve_marks(self.t, explicit=p, regenerate=True)


class Profile(unittest.TestCase):
    """The automatic profile when the perf tables are missing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        md = os.path.join(self.tmp, "artifacts", "zz-marks")
        self.a = argparse.Namespace(
            target="zz",
            perf_tsv_self=os.path.join(md, "perf-self-{split}.tsv"),
            perf_tsv_inline=os.path.join(md, "perf-inline-{split}.tsv"),
            structure_tsv=os.path.join(md, "inline-structure.tsv"),
            binary=os.path.join(self.tmp, "bin", "zz"))
        os.makedirs(os.path.dirname(self.a.binary))
        open(self.a.binary, "w").write("")
        self.ran = []

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fake_run(self, cmd, env=None):
        self.ran.append((os.path.basename(cmd[1] if cmd[0] == sys.executable
                                          else cmd[0]), env or {}))
        name = self.ran[-1][0]
        if name == "perf_marks_profile.sh":
            os.makedirs(cmd[1], exist_ok=True)
            open(os.path.join(cmd[1], "train-a.data"), "w").write("")
        elif name == "perf_hotness.py":
            for flag in ("--tsv", "--inline-tsv"):
                open(cmd[cmd.index(flag) + 1], "w").write("x\n")
        elif name == "inline_structure.py":
            open(cmd[cmd.index("--tsv") + 1], "w").write("x\n")

    def patches(self, perf="/p/perf", busy=()):
        return [mock.patch.object(TM, "perf_binary", lambda: perf),
                mock.patch.object(TM, "busy_pids", lambda: list(busy)),
                mock.patch.object(TM, "_run", self.fake_run)]

    def run_with(self, *pp, run=True):
        for p in pp:
            p.start()
        try:
            return TM.ensure_profile(self.a, run=run)
        finally:
            for p in pp:
                p.stop()

    def test_perf_missing_is_the_error(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_with(*self.patches(perf=None))
        self.assertIn("run `scripts/perf_local.sh setup` first",
                      str(cm.exception))
        self.assertEqual(self.ran, [])

    def test_refuses_while_busy(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_with(*self.patches(busy=["4242 python3 bench.py"]))
        self.assertIn("refusing to profile", str(cm.exception))
        self.assertEqual(self.ran, [])

    def test_profiles_training_on_the_base_binary(self):
        self.assertTrue(self.run_with(*self.patches()))
        self.assertEqual([r[0] for r in self.ran],
                         ["perf_marks_profile.sh", "perf_hotness.py",
                          "inline_structure.py"])
        env = self.ran[0][1]
        self.assertEqual((env["SETS"], env["BIN"], env["TARGET"]),
                         ("training", self.a.binary, "zz"))
        self.ran.clear()
        self.assertFalse(self.run_with(*self.patches()))   # tables exist now
        self.assertEqual(self.ran, [])

    def test_builds_the_base_when_missing(self):
        os.unlink(self.a.binary)
        self.run_with(*self.patches())
        self.assertEqual(self.ran[0][0], "target_sites.sh")

    def test_dry_modes_never_profile(self):
        with self.assertRaises(SystemExit):
            self.run_with(*self.patches(), run=False)
        self.assertEqual(self.ran, [])


class Busy(unittest.TestCase):
    def test_own_process_tree_is_not_busy(self):
        me = os.getpid()
        out = "%d python3 jev_search.py --target zz\n4242 cargo build\n" % me
        fake = mock.Mock(stdout=out, returncode=0)
        with mock.patch.object(TM.subprocess, "run", return_value=fake):
            self.assertEqual(TM.busy_pids(), ["4242 cargo build"])


class Refusal(unittest.TestCase):
    def test_never_writes_the_frozen_file(self):
        with self.assertRaises(SystemExit):
            TM.main(["--target", "hintbench", "--seed-only",
                     "--out", "targets/hintbench/jev-marks.txt"])


if __name__ == "__main__":
    unittest.main()
