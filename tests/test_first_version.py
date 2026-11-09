import os

from tests.helpers import ALL_QUESTIONS, ActiveCliTestCase, CliTestCase


class FirstVersionTest(CliTestCase):
    def answer_all(self, upto=None, prefix="a "):
        for qid in ALL_QUESTIONS:
            if qid == upto:
                return
            r = self.run_cli("protocol", "answer", qid, "--text", prefix + qid)
            self.assertEqual(r.returncode, 0, r.stderr)

    def start(self):
        self.run_cli("init")
        self.run_cli("protocol", "resume")

    def test_nothing_written_before_last_answer(self):
        self.start()
        self.answer_all(upto="3.constraints")
        for f in ("vision.md", "anti-vision.md", "goals.md"):
            self.assertFalse(os.path.exists(self.data_path(f)))

    def test_completion_writes_verbatim_first_versions(self):
        self.start()
        self.answer_all(upto="3.constraints")
        r = self.run_cli("protocol", "answer", "3.constraints", "--text", "不牺牲睡眠")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            self.read_data("anti-vision.md"),
            "## 2026-01-15\na 3.3\n_Reason: 来自一天协议_\n")
        self.assertEqual(
            self.read_data("vision.md"),
            "## 2026-01-15\na 3.4\n\nIdentity Statement: a 1.13\n"
            "_Reason: 来自一天协议_\n")
        goals = self.run_cli("show", "goals").json()["current"]
        self.assertEqual(goals["reason"], "来自一天协议")
        self.assertEqual(goals["sections"], {
            "Year Goal": "a 3.5", "Month Project": "a 3.6",
            "Daily Levers": "a 3.7", "Constraints": "不牺牲睡眠"})
        vision = self.run_cli("show", "vision").json()["current"]
        self.assertEqual(vision["reason"], "来自一天协议")
        self.assertIn("Identity Statement: a 1.13", vision["content"])

    def test_snapshot_not_empty_after_completion(self):
        self.start()
        self.answer_all()
        snap = self.run_cli("snapshot").json()
        self.assertTrue(snap["vision"])
        self.assertEqual(snap["anti_vision"], "a 3.3")
        self.assertEqual(snap["goals"]["Daily Levers"], "a 3.7")

    def test_plan_change_on_first_version(self):
        self.start()
        self.answer_all()
        r = self.run_cli("plan", "change", "daily-levers", "--text", "new",
                         "--why", "because")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["old"], "a 3.7")
        goals = self.run_cli("show", "goals").json()["versions"]
        self.assertEqual(goals[0]["reason"], "来自一天协议")
        self.assertEqual(goals[1]["reason"], "because")
        self.assertEqual(goals[1]["sections"]["Year Goal"], "a 3.5")

    def test_write_failure_leaves_nothing_and_not_active(self):
        self.start()
        self.answer_all(upto="3.constraints")
        os.makedirs(self.data_path("goals.md"))  # makes the goals write fail
        r = self.run_cli("protocol", "answer", "3.constraints", "--text", "x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing was written", r.stderr)
        self.assertFalse(os.path.exists(self.data_path("anti-vision.md")))
        self.assertFalse(os.path.exists(self.data_path("vision.md")))
        self.assertEqual(self.read_state()["phase"], "protocol_in_progress")
        self.assertNotIn("## 3.constraints",
                         "".join(self.read_data("protocol", n)
                                 for n in os.listdir(self.data_path("protocol"))))
        os.rmdir(self.data_path("goals.md"))  # retry succeeds
        r = self.run_cli("protocol", "answer", "3.constraints", "--text", "x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_state()["phase"], "active")

    def test_write_failure_preserves_existing_bytes(self):
        self.start()
        self.write_data("## 2025-12-01\nold\n", "anti-vision.md")
        self.answer_all(upto="3.constraints")
        os.makedirs(self.data_path("goals.md"))
        self.run_cli("protocol", "answer", "3.constraints", "--text", "x")
        self.assertEqual(self.read_data("anti-vision.md"), "## 2025-12-01\nold\n")


class RedoFirstVersionTest(ActiveCliTestCase):
    def test_redo_appends_new_versions_old_bytes_untouched(self):
        before = {f: self.read_data(f) for f in
                  ("vision.md", "anti-vision.md", "goals.md")}
        self.set_now("2026-02-01T09:00:00")
        self.run_cli("protocol", "redo")
        for qid in ALL_QUESTIONS:
            r = self.run_cli("protocol", "answer", qid, "--text", "b " + qid)
            self.assertEqual(r.returncode, 0, r.stderr)
        for f, old in before.items():
            new = self.read_data(f)
            self.assertTrue(new.startswith(old))
            self.assertIn("_Reason: 来自重做的一天协议_", new[len(old):])
        self.assertEqual(self.read_data("anti-vision.md")[len(before["anti-vision.md"]):],
                         "\n## 2026-02-01\nb 3.3\n_Reason: 来自重做的一天协议_\n")
        self.assertEqual(self.read_state()["phase"], "active")
