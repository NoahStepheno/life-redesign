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


class ApplyBlockTest(ActiveCliTestCase):
    def setUp(self):
        super().setUp()  # protocol completed on 2026-01-15
        self.set_now("2026-01-16T09:00:00")  # day after completion: no silence

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
        before = self.read_data("vision.md")
        self.set_now("2026-04-02T09:00:00")
        r = self.apply(block("vision.md", "append", "new\n_Reason: why_"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("vision.md"),
                         before + "\n## 2026-04-02\nnew\n_Reason: why_\n")

    def test_append_goals_merges_sections(self):
        r = self.apply(block("goals.md", "append", "### Month Project\nMP\n_Reason: r_"))
        self.assertEqual(r.returncode, 0, r.stderr)
        cur = self.run_cli("show", "goals").json()["current"]["sections"]
        self.assertEqual(cur["Month Project"], "MP")
        self.assertEqual(cur["Constraints"], "a 3.constraints")

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
            (block("goals.md", "append", "no heading\n_Reason: r_"), "section"),
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
                + "chatter between\n" + block("vision.md", "append", "v\n_Reason: r_"))
        r = self.apply(text)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-16.md"), "a\n")
        self.assertTrue(self.read_data("vision.md").endswith("## 2026-01-16\nv\n_Reason: r_\n"))

    def test_reads_from_file(self):
        p = os.path.join(self._tmp, "blk.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(block("log/2026-01-16.md", "create", "hi"))
        r = self.run_cli("apply-block", "--file", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-16.md"), "hi\n")


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

    def verdict_block(self, day, verdict, mode="create", reason="x", away=None):
        head = "# 2026-01-%02d\n" % day if mode == "create" else ""
        tail = "\n- 这几天发生了什么: %s" % away if away else ""
        return block("log/2026-01-%02d.md" % day, mode,
                     head + "- 判定: %s\n- 判定理由: %s%s" % (verdict, reason, tail))

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
        text = "".join(self.verdict_block(d, "走偏", away="忙" if d == 15 else None)
                       for d in (15, 16, 17))
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
        r = self.apply("".join(self.verdict_block(d, "走偏", away="忙" if d == 15 else None)
                               for d in (15, 16, 17)))
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
        r = self.apply(self.verdict_block(18, "在轨", mode="append", away="出差"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["streak"]["unrecorded"], 0)
        self.assertFalse(r.json()["streak"]["escalation"])
        self.assertEqual(self.run_cli("streak", "status").json()["unrecorded"], 0)

    def test_verdict_on_older_placeholder_day_leaves_later_ones(self):
        self.cli_checkin(15, "在轨")
        self.set_now("2026-01-19T09:00:00")  # 16, 17, 18 missed
        self.run_cli("streak", "status")
        r = self.apply(self.verdict_block(16, "在轨", mode="append", away="出差"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["streak"]["unrecorded"], 2)


class BlockGateTest(CliTestCase):
    """Update blocks need a completed protocol (issue #25 part 1)."""

    def apply(self, text):
        return CliResult(subprocess.run(
            [sys.executable, CLI, "apply-block"], input=text,
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True))

    def snapshot_dir(self):
        out = {}
        for root, _d, files in os.walk(self.data_dir):
            for f in files:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    out[p] = fh.read()
        return out

    def test_new_phase_refuses_every_target(self):
        self.run_cli("init")
        before = self.snapshot_dir()
        for f, body in (("vision.md", "V\n_Reason: r_"), ("anti-vision.md", "A\n_Reason: r_"),
                        ("goals.md", "### Year Goal\nG\n_Reason: r_"),
                        ("log/2026-01-15.md", "note"), ("protocol/x.md", "note")):
            r = self.apply(block(f, "create", body))
            self.assertNotEqual(r.returncode, 0, f)
            self.assertIn("protocol is not complete", r.stderr)
            self.assertIn("protocol resume", r.stderr)
        self.assertEqual(self.snapshot_dir(), before)

    def test_in_progress_and_shelved_refused(self):
        self.run_cli("init")
        self.run_cli("protocol", "resume")
        r = self.apply(block("vision.md", "create", "V\n_Reason: r_"))
        self.assertIn("protocol_in_progress", r.stderr)
        self.set_now("2026-01-30T09:00:00")  # past the 7-day shelving
        r = self.apply(block("vision.md", "create", "V\n_Reason: r_"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("protocol_shelved", r.stderr)
        self.assertFalse(os.path.exists(self.data_path("vision.md"))
                         and bool(self.read_data("vision.md").strip()))


class RedoBlockTest(ActiveCliTestCase):
    def test_redo_keeps_blocks_working(self):
        r = self.run_cli("protocol", "redo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_state()["phase"], "active")
        r = CliResult(subprocess.run(
            [sys.executable, CLI, "apply-block"],
            input=block("vision.md", "append", "V2\n_Reason: r_"),
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True))
        self.assertEqual(r.returncode, 0, r.stderr)


class BlockLogDateTest(ActiveCliTestCase):
    """Log block file names must be real dates in [completion day, today]
    (issue #25 part 2)."""

    def setUp(self):
        super().setUp()  # completed 2026-01-15
        self.set_now("2026-01-16T09:00:00")

    def apply(self, text):
        return CliResult(subprocess.run(
            [sys.executable, CLI, "apply-block"], input=text,
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True))

    def test_future_date_rejected_whole_batch(self):
        r = self.apply(block("log/2026-01-16.md", "create", "ok")
                       + block("log/2099-01-01.md", "create",
                               "- 判定: 走偏\n- 判定理由: x"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("in the future", r.stderr)
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-16.md")))
        self.assertFalse(os.path.exists(self.data_path("log", "2099-01-01.md")))
        self.assertEqual(self.read_state()["streak"]["drift"], 0)

    def test_before_completion_rejected_completion_day_allowed(self):
        r = self.apply(block("log/2026-01-14.md", "create", "note"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("before the protocol was completed", r.stderr)
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-14.md")))
        r = self.apply(block("log/2026-01-15.md", "create", "note"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("log", "2026-01-15.md"), "note\n")

    def test_non_date_names_rejected(self):
        for name in ("x", "2026-13-01", "2026-02-30", "2026-1-16", "notes"):
            r = self.apply(block("log/%s.md" % name, "create", "note"))
            self.assertNotEqual(r.returncode, 0, name)
            self.assertIn("not a valid date", r.stderr)
            self.assertFalse(os.path.exists(self.data_path("log", name + ".md")))


class BlockSilenceNoteTest(ActiveCliTestCase):
    """After silence a new verdict needs the 这几天发生了什么 line, saved as
    `checkin record --while-away` saves it (issue #25 part 3)."""

    def setUp(self):
        super().setUp()  # completed 2026-01-15
        self.set_now("2026-01-18T09:00:00")  # 16 and 17 silent

    def apply(self, text):
        return CliResult(subprocess.run(
            [sys.executable, CLI, "apply-block"], input=text,
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True))

    VERDICT = "- 判定: 在轨\n- 判定理由: x"

    def test_missing_or_empty_note_rejected_unchanged(self):
        for body in (self.VERDICT, self.VERDICT + "\n- 这几天发生了什么:   "):
            r = self.apply(block("log/2026-01-18.md", "create", "# 2026-01-18\n" + body))
            self.assertNotEqual(r.returncode, 0, body)
            self.assertIn("you were silent", r.stderr)
            self.assertFalse(os.path.exists(self.data_path("log", "2026-01-18.md")))
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-16.md")))
        self.assertEqual(self.read_state()["streak"]["unrecorded"], 0)

    def test_note_in_any_block_of_batch_accepts(self):
        text = (block("log/2026-01-18.md", "create", "# 2026-01-18\n" + self.VERDICT)
                + block("log/2026-01-17.md", "create", "- 这几天发生了什么: 病了"))
        r = self.apply(text)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_same_log_as_command_line(self):
        r = self.apply(block("log/2026-01-18.md", "create",
                             "# 2026-01-18\n" + self.VERDICT
                             + "\n- 这几天发生了什么: 病了"))
        self.assertEqual(r.returncode, 0, r.stderr)
        via_block = self.read_data("log", "2026-01-18.md")
        self.setUp()
        r = self.run_cli(
            "checkin", "record", "--lever", "写作", "--levers-done", "写了",
            "--action-drift", "no", "--action-reason", "无",
            "--identity-protection", "yes", "--identity-reason", "无",
            "--toward", "vision", "--toward-reason", "写了",
            "--verdict", "在轨", "--verdict-reason", "x",
            "--tomorrow-lever", "写作", "--while-away", "病了")
        self.assertEqual(r.returncode, 0, r.stderr)
        via_cli = self.read_data("log", "2026-01-18.md")
        away_line = "- 这几天发生了什么: 病了"
        self.assertIn(away_line, via_block.split("\n"))
        self.assertIn(away_line, via_cli.split("\n"))

    def test_note_not_needed_without_silence(self):
        self.set_now("2026-01-16T09:00:00")
        r = self.apply(block("log/2026-01-16.md", "create", "# 2026-01-16\n" + self.VERDICT))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_note_not_needed_when_gap_is_dnd(self):
        self.run_cli("dnd", "add", "2026-01-16")
        self.run_cli("dnd", "add", "2026-01-17")
        r = self.apply(block("log/2026-01-18.md", "create", "# 2026-01-18\n" + self.VERDICT))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_non_verdict_block_needs_no_note_after_silence(self):
        r = self.apply(block("log/2026-01-18.md", "create", "just a note"))
        self.assertEqual(r.returncode, 0, r.stderr)


class PlanBlockReasonTest(ActiveCliTestCase):
    """Update blocks that change vision/anti-vision/goals carry a reason,
    stored exactly as `plan change` stores it (issue #22)."""

    def setUp(self):
        super().setUp()
        self.set_now("2026-01-20T09:00:00")

    def apply(self, text):
        return CliResult(subprocess.run(
            [sys.executable, CLI, "apply-block"], input=text,
            env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True))

    def test_missing_or_blank_reason_rejected_file_unchanged(self):
        for f in ("vision.md", "anti-vision.md", "goals.md"):
            before = self.read_data(f)
            body = "### Year Goal\nNEW-EASIER-GOAL" if f == "goals.md" else "easier"
            for tail in ("", "\n_Reason: _", "\n_Reason:   _", "\n_Reason: x_\nmore"):
                r = self.apply(block(f, "append", body + tail))
                self.assertNotEqual(r.returncode, 0, (f, tail))
                self.assertIn("reason", r.stderr)
                self.assertEqual(self.read_data(f), before)

    def test_valid_reason_stored_as_reason_and_reviewed(self):
        r = self.apply(block("goals.md", "append",
                             "### Year Goal\nNEW\n_Reason: scope grew_"))
        self.assertEqual(r.returncode, 0, r.stderr)
        cur = self.run_cli("show", "goals").json()["current"]
        self.assertEqual(cur["reason"], "scope grew")
        self.assertEqual(cur["sections"]["Year Goal"], "NEW")
        rev = self.run_cli("review", "month").json()
        self.assertEqual([(c["object"], c["reason"]) for c in rev["plan_changes"]],
                         [("goals", "scope grew")])

    def test_block_and_plan_change_make_identical_versions(self):
        r = self.apply(block("vision.md", "append", "V2\n_Reason: why_"))
        self.assertEqual(r.returncode, 0, r.stderr)
        via_block = self.read_data("vision.md")
        self.setUp()
        r = self.run_cli("plan", "change", "vision", "--text", "V2", "--why", "why")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("vision.md"), via_block)

    def test_create_into_empty_plan_file_needs_reason(self):
        self.write_data("", "vision.md")
        r = self.apply(block("vision.md", "create", "V"))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.read_data("vision.md"), "")
        r = self.apply(block("vision.md", "create", "V\n_Reason: first_"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.run_cli("show", "vision").json()["current"]["reason"], "first")

    def test_missing_reason_rejects_whole_batch(self):
        before = self.read_data("vision.md")
        r = self.apply(block("vision.md", "append", "V\n_Reason: ok_")
                       + block("anti-vision.md", "append", "AV"))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.read_data("vision.md"), before)

    def test_log_blocks_need_no_reason(self):
        r = self.apply(block("log/2026-01-20.md", "create", "note"))
        self.assertEqual(r.returncode, 0, r.stderr)
