from tests.helpers import CliTestCase

QUESTIONS = (["1.%d" % i for i in range(1, 15)]
             + ["3.%d" % i for i in range(1, 8)] + ["3.constraints"])

OBJECTS = {
    "vision": "Vision",
    "anti-vision": "Anti-vision",
    "year-goal": "Year Goal",
    "month-project": "Month Project",
    "daily-levers": "Daily Levers",
    "constraints": "Constraints",
}
SECTIONED = ("year-goal", "month-project", "daily-levers", "constraints")
SECTION = {"year-goal": "Year Goal", "month-project": "Month Project",
           "daily-levers": "Daily Levers", "constraints": "Constraints"}


class PlanTestCase(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init")

    def complete_protocol(self):
        self.run_cli("protocol", "resume")
        for q in QUESTIONS:
            r = self.run_cli("protocol", "answer", q, "--text", "a")
            self.assertEqual(r.returncode, 0, r.stderr)

    def plan(self, obj, text="new", why="because"):
        args = ["plan", "change", obj]
        if text is not None:
            args += ["--text", text]
        if why is not None:
            args += ["--why", why]
        return self.run_cli(*args)


class PlanGateTest(PlanTestCase):
    def test_refused_before_protocol_complete(self):
        r = self.plan("vision")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("protocol", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_refused_while_protocol_in_progress(self):
        self.run_cli("protocol", "resume")
        r = self.plan("vision")
        self.assertNotEqual(r.returncode, 0)
        with self.assertRaises(FileNotFoundError):
            self.read_data("vision.md")


class PlanChangeTest(PlanTestCase):
    def setUp(self):
        super().setUp()
        self.complete_protocol()

    def test_missing_or_blank_why_refused_and_nothing_written(self):
        self.run_cli("append", "vision", "--text", "old")
        before = self.read_data("vision.md")
        for why in (None, "", "   "):
            r = self.plan("vision", why=why)
            self.assertNotEqual(r.returncode, 0, why)
            self.assertIn("why", r.stderr)
            self.assertEqual(self.read_data("vision.md"), before)

    def test_vision_change_appends_dated_version_with_reason(self):
        self.run_cli("append", "vision", "--text", "old")
        before = self.read_data("vision.md")
        self.set_now("2026-03-01T09:00:00")
        r = self.plan("vision", text="new", why="priorities shifted")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = self.read_data("vision.md")
        self.assertTrue(after.startswith(before))
        self.assertEqual(
            after[len(before):],
            "\n## 2026-03-01\nnew\n_Reason: priorities shifted_\n")
        out = r.json()
        self.assertEqual(out["old"], "old")
        self.assertEqual(out["new"], "new")
        self.assertEqual(out["why"], "priorities shifted")
        self.assertEqual(out["date"], "2026-03-01")

    def test_show_reports_reason_separately_from_content(self):
        self.plan("anti-vision", text="n", why="w")
        cur = self.run_cli("show", "anti-vision").json()["current"]
        self.assertEqual(cur["content"], "n")
        self.assertEqual(cur["reason"], "w")

    def test_first_change_has_null_old(self):
        out = self.plan("vision").json()
        self.assertIsNone(out["old"])

    def test_all_six_objects_changeable(self):
        for obj in OBJECTS:
            r = self.plan(obj, text="v-" + obj, why="r-" + obj)
            self.assertEqual(r.returncode, 0, (obj, r.stderr))
            out = r.json()
            self.assertEqual(out["new"], "v-" + obj)
            self.assertIn("old", out)
            if obj in SECTIONED:
                cur = self.run_cli("show", "goals").json()["current"]
                self.assertEqual(cur["sections"][SECTION[obj]], "v-" + obj)
                self.assertEqual(cur["reason"], "r-" + obj)
            else:
                cur = self.run_cli("show", obj).json()["current"]
                self.assertEqual(cur["content"], "v-" + obj)

    def test_goal_change_carries_other_sections_and_reports_old(self):
        self.run_cli("append", "goals", "--year-goal", "Y",
                     "--month-project", "M", "--constraints", "C")
        before = self.read_data("goals.md")
        self.set_now("2026-02-01T09:00:00")
        self.plan("daily-levers", text="walk", why="start")
        self.set_now("2026-02-02T09:00:00")
        out = self.plan("month-project", text="M2", why="done early").json()
        self.assertEqual(out["old"], "M")
        self.assertTrue(self.read_data("goals.md").startswith(before))
        cur = self.run_cli("show", "goals").json()["current"]
        self.assertEqual(cur["sections"], {
            "Year Goal": "Y", "Month Project": "M2",
            "Constraints": "C", "Daily Levers": "walk"})
        self.assertEqual(cur["reason"], "done early")

    def test_append_after_plan_keeps_daily_levers(self):
        self.plan("daily-levers", text="walk", why="start")
        self.run_cli("append", "goals", "--year-goal", "Y")
        cur = self.run_cli("show", "goals").json()["current"]
        self.assertEqual(cur["sections"],
                         {"Year Goal": "Y", "Daily Levers": "walk"})
        self.assertNotIn("reason", cur)

    def test_forged_headings_rejected(self):
        r = self.plan("vision", text="x\n## 1999-01-01\ny")
        self.assertNotEqual(r.returncode, 0)
        r = self.plan("year-goal", text="x\n### Constraints\ny")
        self.assertNotEqual(r.returncode, 0)

    def test_multiline_why_collapsed_to_one_line(self):
        out = self.plan("vision", why="a\nb").json()
        self.assertEqual(out["why"], "a b")

    def test_unknown_object_rejected(self):
        self.assertNotEqual(self.plan("mood").returncode, 0)
