from tests.helpers import CliTestCase


class AppendTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init")

    def test_append_creates_dated_section(self):
        self.set_now("2026-01-15T09:00:00")
        r = self.run_cli("append", "vision", "--text", "first")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_data("vision.md"), "## 2026-01-15\nfirst\n")

    def test_second_append_keeps_old_version_and_current_is_last(self):
        self.set_now("2026-01-15T09:00:00")
        self.run_cli("append", "anti-vision", "--text", "old")
        self.set_now("2026-04-02T09:00:00")
        self.run_cli("append", "anti-vision", "--text", "new")
        self.assertEqual(
            self.read_data("anti-vision.md"),
            "## 2026-01-15\nold\n\n## 2026-04-02\nnew\n")
        r = self.run_cli("show", "anti-vision")
        out = r.json()
        self.assertEqual(out["current"]["date"], "2026-04-02")
        self.assertEqual(out["current"]["content"], "new")
        self.assertEqual([v["date"] for v in out["versions"]],
                         ["2026-01-15", "2026-04-02"])

    def test_same_day_appends_make_two_versions(self):
        self.run_cli("append", "vision", "--text", "a")
        self.run_cli("append", "vision", "--text", "b")
        out = self.run_cli("show", "vision").json()
        self.assertEqual(len(out["versions"]), 2)
        self.assertEqual(out["current"]["content"], "b")

    def test_show_before_any_version(self):
        out = self.run_cli("show", "vision").json()
        self.assertIsNone(out["current"])
        self.assertEqual(out["versions"], [])

    def test_text_from_stdin_is_not_supported_but_empty_text_rejected(self):
        r = self.run_cli("append", "vision", "--text", "   ")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("empty", r.stderr)

    def test_content_cannot_forge_version_heading(self):
        r = self.run_cli("append", "vision", "--text", "x\n## 1999-01-01\ny")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("heading", r.stderr)

    def test_requires_init(self):
        import shutil
        shutil.rmtree(self.data_dir)
        r = self.run_cli("append", "vision", "--text", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("init", r.stderr)


class GoalsTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init")

    def test_goals_version_has_sections(self):
        r = self.run_cli("append", "goals", "--year-goal", "Y",
                         "--month-project", "M", "--constraints", "C")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            self.read_data("goals.md"),
            "## 2026-01-15\n### Year Goal\nY\n\n### Month Project\nM\n\n"
            "### Constraints\nC\n")

    def test_omitted_sections_carry_forward_from_current(self):
        self.run_cli("append", "goals", "--year-goal", "Y",
                     "--month-project", "M", "--constraints", "C")
        self.set_now("2026-02-01T09:00:00")
        self.run_cli("append", "goals", "--month-project", "M2")
        out = self.run_cli("show", "goals").json()
        self.assertEqual(out["current"]["date"], "2026-02-01")
        self.assertEqual(out["current"]["sections"],
                         {"Year Goal": "Y", "Month Project": "M2",
                          "Constraints": "C"})
        self.assertEqual(len(out["versions"]), 2)
        self.assertEqual(out["versions"][0]["sections"]["Month Project"], "M")

    def test_first_goals_version_needs_something_and_no_target_text(self):
        r = self.run_cli("append", "goals")
        self.assertNotEqual(r.returncode, 0)
        r = self.run_cli("append", "goals", "--text", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_section_flags_rejected_for_other_targets(self):
        r = self.run_cli("append", "vision", "--year-goal", "x")
        self.assertNotEqual(r.returncode, 0)


class AppendOnlyTest(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init")
        self.run_cli("append", "vision", "--text", "keep me")
        self.before = self.read_data("vision.md")

    def assertRejected(self, *args):
        r = self.run_cli(*args)
        self.assertNotEqual(r.returncode, 0, args)
        self.assertIn("append-only", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.read_data("vision.md"), self.before)

    def test_overwrite_style_commands_rejected(self):
        for cmd in ("overwrite", "replace", "edit", "update", "set",
                    "delete", "remove", "rm", "reset", "archive"):
            self.assertRejected(cmd, "vision", "--text", "evil")

    def test_forbidden_words_as_content_are_fine(self):
        r = self.run_cli("append", "vision", "--text", "delete")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_overwrite_style_flags_rejected(self):
        for flag in ("--overwrite", "--replace", "--force", "--delete",
                     "--edit", "--amend"):
            self.assertRejected("append", "vision", "--text", "evil", flag)
