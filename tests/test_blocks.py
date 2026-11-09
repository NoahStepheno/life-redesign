import json
import os
import subprocess
import sys

from tests.helpers import ActiveCliTestCase, CLI, CliResult, CliTestCase


def block(file, mode, body):
    return "=== LIFE-REDESIGN UPDATE ===\nfile: %s\nmode: %s\n---\n%s\n=== END ===\n" % (
        file, mode, body)


class SnapshotTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init")

    def test_empty_snapshot_degrades(self):
        out = self.run_cli("snapshot").json()
        self.assertIsNone(out["vision"])
        self.assertIsNone(out["anti_vision"])
        self.assertEqual(out["goals"], {})
        self.assertEqual(out["verdicts"], [])
        self.assertEqual(out["streak"], {"drift": 0, "unrecorded": 0, "escalation": False})

    def test_snapshot_uses_current_versions_and_last_7_days(self):
        self.run_cli("append", "vision", "--text", "old v")
        self.set_now("2026-02-01T09:00:00")
        self.run_cli("append", "vision", "--text", "new v")
        self.run_cli("append", "anti-vision", "--text", "av")
        self.run_cli("append", "goals", "--year-goal", "YG", "--month-project", "MP")
        self.write_data("# 2026-01-25\n- 判定: 走偏\n- 判定理由: x\n", "log", "2026-01-25.md")
        self.write_data("# 2026-01-26\n- 判定: 在轨\n- 判定理由: x\n", "log", "2026-01-26.md")
        self.write_data("# 2026-02-01\n- 判定: 轻微偏离\n- 判定理由: x\n", "log", "2026-02-01.md")
        st = self.read_state()
        st["streak"] = {"drift": 2, "unrecorded": 1}
        self.write_data(json.dumps(st), "state.json")
        out = self.run_cli("snapshot").json()
        self.assertEqual(out["vision"], "new v")
        self.assertEqual(out["anti_vision"], "av")
        self.assertEqual(out["goals"]["Year Goal"], "YG")
        self.assertEqual(out["goals"]["Month Project"], "MP")
        self.assertEqual(out["verdicts"], [
            {"date": "2026-01-26", "verdict": "在轨"},
            {"date": "2026-02-01", "verdict": "轻微偏离"}])
        self.assertEqual(out["streak"], {"drift": 2, "unrecorded": 1, "escalation": False})


class ApplyBlockTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init")

    def apply(self, text):
        return CliResult(subprocess.run(
            [sys.executable, CLI, "apply-block"], input=text,
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True))

    def test_create_writes_file(self):
        r = self.apply(block("log/2026-01-16.md", "create", "# 2026-01-16\n- 判定: 在轨\n- 判定理由: x"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-16.md"),
                         "# 2026-01-16\n- 判定: 在轨\n- 判定理由: x\n")

    def test_create_existing_fails_unchanged(self):
        self.write_data("orig\n", "log", "2026-01-16.md")
        r = self.apply(block("log/2026-01-16.md", "create", "new"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("exists", r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-16.md"), "orig\n")

    def test_append_log_keeps_old_bytes(self):
        self.write_data("orig\n", "log", "2026-01-16.md")
        r = self.apply(block("log/2026-01-16.md", "append", "more"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-16.md"), "orig\nmore\n")

    def test_append_vision_adds_dated_version(self):
        self.run_cli("append", "vision", "--text", "old")
        self.set_now("2026-04-02T09:00:00")
        r = self.apply(block("vision.md", "append", "new"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("vision.md"),
                         "## 2026-01-15\nold\n\n## 2026-04-02\nnew\n")

    def test_append_goals_merges_sections(self):
        self.run_cli("append", "goals", "--year-goal", "YG", "--constraints", "C")
        r = self.apply(block("goals.md", "append", "### Month Project\nMP"))
        self.assertEqual(r.returncode, 0, r.stderr)
        cur = self.run_cli("show", "goals").json()["current"]["sections"]
        self.assertEqual(cur, {"Year Goal": "YG", "Month Project": "MP", "Constraints": "C"})

    def test_replace_and_delete_rejected(self):
        self.write_data("orig\n", "log", "2026-01-16.md")
        for mode in ("replace", "delete", "overwrite"):
            r = self.apply(block("log/2026-01-16.md", mode, "x"))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("mode", r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-16.md"), "orig\n")

    def test_malformed_blocks_rejected_with_reason(self):
        cases = [
            ("", "no update block"),
            ("=== LIFE-REDESIGN UPDATE ===\nmode: create\n---\nx\n=== END ===\n", "file"),
            ("=== LIFE-REDESIGN UPDATE ===\nfile: log/a.md\n---\nx\n=== END ===\n", "mode"),
            ("=== LIFE-REDESIGN UPDATE ===\nfile: log/a.md\nmode: create\nx\n=== END ===\n", "---"),
            ("=== LIFE-REDESIGN UPDATE ===\nfile: log/a.md\nmode: create\n---\nx\n", "END"),
            (block("log/a.md", "create", "  "), "empty"),
            (block("state.json", "append", "x"), "not an allowed"),
            (block("goals.md", "append", "no heading"), "section"),
        ]
        for text, reason in cases:
            r = self.apply(text)
            self.assertNotEqual(r.returncode, 0, text)
            self.assertIn(reason, r.stderr, text)
        self.assertFalse(os.path.exists(self.data_path("log", "a.md")))

    def test_paths_outside_data_dir_rejected(self):
        outside = os.path.join(self._tmp, "outside")
        os.makedirs(outside)
        os.symlink(outside, self.data_path("log", "link"))
        for f in ("../evil.md", "log/../../evil.md", "/tmp/evil.md",
                  "log/link/evil.md"):
            r = self.apply(block(f, "create", "x"))
            self.assertNotEqual(r.returncode, 0, f)
        self.assertEqual(os.listdir(outside), [])
        self.assertFalse(os.path.exists(os.path.join(self._tmp, "evil.md")))

    def test_multi_block_all_or_nothing(self):
        text = (block("log/2026-01-16.md", "create", "good")
                + block("log/2026-01-17.md", "replace", "bad"))
        self.assertNotEqual(self.apply(text).returncode, 0)
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-16.md")))

    def test_multi_block_success(self):
        text = (block("log/2026-01-16.md", "create", "a")
                + "chatter between\n" + block("vision.md", "append", "v"))
        r = self.apply(text)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-16.md"), "a\n")
        self.assertEqual(self.read_data("vision.md"), "## 2026-01-15\nv\n")

    def test_reads_from_file(self):
        p = os.path.join(self._tmp, "blk.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(block("log/x.md", "create", "hi"))
        r = self.run_cli("apply-block", "--file", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("log", "x.md"), "hi\n")


class SnapshotRealDataTest(ActiveCliTestCase):
    def checkin(self, day, verdict):
        self.set_now("2026-01-%02dT21:00:00" % day)
        r = self.run_cli(
            "checkin", "record", "--lever", "写作", "--levers-done", "写了",
            "--action-drift", "no", "--action-reason", "无",
            "--identity-protection", "yes", "--identity-reason", "无",
            "--toward", "vision", "--toward-reason", "写了",
            "--verdict", verdict, "--verdict-reason", "理由",
            "--tomorrow-lever", "写作")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_snapshot_reflects_checkins_and_unrecorded_days(self):
        self.set_now("2026-01-15T09:00:00")
        self.checkin(15, "走偏")
        self.checkin(16, "走偏")
        self.set_now("2026-01-19T09:00:00")  # 17 and 18 missed
        out = self.run_cli("snapshot").json()
        self.assertEqual(out["verdicts"], [
            {"date": "2026-01-15", "verdict": "走偏"},
            {"date": "2026-01-16", "verdict": "走偏"}])
        self.assertEqual(out["streak"]["drift"], 2)
        self.assertEqual(out["streak"]["unrecorded"], 2)


class VerdictBlockTest(ActiveCliTestCase):
    """Verdicts written through update blocks follow the check-in rules and
    feed the same streak recomputation (issue #18)."""

    def setUp(self):
        super().setUp()
        self.set_now("2026-01-15T09:00:00")  # protocol completed on the 15th

    def apply(self, text):
        return CliResult(subprocess.run(
            [sys.executable, CLI, "apply-block"], input=text,
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True))

    def verdict_block(self, day, verdict, mode="create", reason="x"):
        head = "# 2026-01-%02d\n" % day if mode == "create" else ""
        return block("log/2026-01-%02d.md" % day, mode,
                     head + "- 判定: %s\n- 判定理由: %s" % (verdict, reason))

    def cli_checkin(self, day, verdict):
        self.set_now("2026-01-%02dT21:00:00" % day)
        r = self.run_cli(
            "checkin", "record", "--lever", "写作", "--levers-done", "写了",
            "--action-drift", "no", "--action-reason", "无",
            "--identity-protection", "yes", "--identity-reason", "无",
            "--toward", "vision", "--toward-reason", "写了",
            "--verdict", verdict, "--verdict-reason", "x",
            "--tomorrow-lever", "写作")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_drift_via_block_counts_and_returns_streak(self):
        self.set_now("2026-01-18T09:00:00")
        text = "".join(self.verdict_block(d, "走偏") for d in (15, 16, 17))
        r = self.apply(text)
        self.assertEqual(r.returncode, 0, r.stderr)
        streak = r.json()["streak"]
        self.assertEqual((streak["drift"], streak["escalation"]), (3, True))
        self.assertEqual(self.read_state()["streak"]["drift"], 3)
        self.assertTrue(self.read_state()["escalation"])

    def test_block_and_checkin_paths_agree(self):
        for d in (15, 16, 17):
            self.cli_checkin(d, "走偏")
        via_cli = self.run_cli("streak", "status").json()
        self.assertTrue(via_cli["escalation"])
        # the same facts through update blocks in a fresh data dir
        self.setUp()
        self.set_now("2026-01-17T21:00:00")
        r = self.apply("".join(self.verdict_block(d, "走偏") for d in (15, 16, 17)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["streak"], via_cli)
        self.assertEqual(self.run_cli("streak", "status").json(), via_cli)

    def test_non_drift_block_resets_drift(self):
        self.cli_checkin(15, "走偏")
        self.cli_checkin(16, "走偏")
        self.set_now("2026-01-17T21:00:00")
        r = self.apply(self.verdict_block(17, "轻微偏离"))
        self.assertEqual(r.json()["streak"]["drift"], 0)
        self.assertEqual(self.read_state()["streak"]["drift"], 0)

    def test_missing_reason_or_bad_value_rejected_unchanged(self):
        self.set_now("2026-01-16T09:00:00")
        for body in ("# 2026-01-16\n- 判定: 走偏",
                     "# 2026-01-16\n- 判定: 走偏\n- 判定理由:   ",
                     "# 2026-01-16\n- 判定: 很糟\n- 判定理由: x",
                     "# 2026-01-16\n- 判定:走偏\n- 判定理由: x"):
            r = self.apply(block("log/2026-01-16.md", "create", body))
            self.assertNotEqual(r.returncode, 0, body)
            self.assertFalse(os.path.exists(self.data_path("log", "2026-01-16.md")))
        self.assertEqual(self.read_state()["streak"]["drift"], 0)

    def test_rejected_batch_writes_nothing(self):
        self.set_now("2026-01-16T09:00:00")
        good = self.verdict_block(15, "走偏")
        bad = block("log/2026-01-16.md", "create", "- 判定: 走偏")
        r = self.apply(good + bad)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-15.md")))

    def test_appending_different_verdict_rejected(self):
        self.cli_checkin(15, "在轨")
        before = self.read_data("log", "2026-01-15.md")
        r = self.apply(self.verdict_block(15, "走偏", mode="append"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("new fact", r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-15.md"), before)
        # also within one batch
        r = self.apply(self.verdict_block(20, "在轨")
                       + self.verdict_block(20, "走偏", mode="append"))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-20.md")))

    def test_same_verdict_again_is_allowed_but_needs_reason(self):
        self.cli_checkin(15, "在轨")
        r = self.apply(self.verdict_block(15, "在轨", mode="append"))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.apply(block("log/2026-01-15.md", "append", "- 判定: 在轨"))
        self.assertNotEqual(r.returncode, 0)

    def test_revision_line_accepted_and_recomputes(self):
        for d in (15, 16, 17):
            self.cli_checkin(d, "走偏")
        self.assertTrue(self.run_cli("streak", "status").json()["escalation"])
        line = "- 改判: 走偏 → 在轨 — 因 跑了步 事实改判 (21:30:00)"
        r = self.apply(block("log/2026-01-17.md", "append", line))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["streak"]["drift"], 0)
        self.assertFalse(r.json()["streak"]["escalation"])
        self.assertIn(line, self.read_data("log", "2026-01-17.md"))

    def test_bad_revisions_rejected(self):
        self.cli_checkin(15, "走偏")
        before = self.read_data("log", "2026-01-15.md")
        for line in ("- 改判: 走偏 → 在轨 — 因  事实改判",       # empty fact
                     "- 改判: 在轨 → 走偏 — 因 吵架 事实改判",  # wrong previous
                     "- 改判: 走偏 → 很好 — 因 跑步 事实改判",  # illegal value
                     "- 改判: 走偏 到 在轨"):                    # malformed
            r = self.apply(block("log/2026-01-15.md", "append", line))
            self.assertNotEqual(r.returncode, 0, line)
        self.assertEqual(self.read_data("log", "2026-01-15.md"), before)
        r = self.apply(block("log/2026-01-19.md", "create",
                             "- 改判: 走偏 → 在轨 — 因 跑步 事实改判"))
        self.assertNotEqual(r.returncode, 0)  # nothing to revise

    def test_verdict_on_unrecorded_placeholder_day(self):
        self.cli_checkin(15, "在轨")
        self.set_now("2026-01-19T09:00:00")  # 16, 17, 18 missed
        s = self.run_cli("streak", "status").json()
        self.assertEqual(s["unrecorded"], 3)
        self.assertTrue(s["escalation"])
        r = self.apply(self.verdict_block(18, "在轨", mode="append"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["streak"]["unrecorded"], 0)
        self.assertFalse(r.json()["streak"]["escalation"])
        self.assertEqual(self.run_cli("streak", "status").json()["unrecorded"], 0)

    def test_verdict_on_older_placeholder_day_leaves_later_ones(self):
        self.cli_checkin(15, "在轨")
        self.set_now("2026-01-19T09:00:00")  # 16, 17, 18 missed
        self.run_cli("streak", "status")
        r = self.apply(self.verdict_block(16, "在轨", mode="append"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["streak"]["unrecorded"], 2)
