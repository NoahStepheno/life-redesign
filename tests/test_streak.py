import os

from tests.helpers import ActiveCliTestCase


class StreakTestCase(ActiveCliTestCase):
    def setUp(self):
        super().setUp()
        self.set_now("2026-01-15T09:00:00")  # protocol completed on the 15th

    def checkin(self, day, verdict="在轨", *extra):
        self.set_now("2026-01-%02dT21:00:00" % day)
        return self.run_cli(
            "checkin", "record", "--lever", "写作", "--levers-done", "写了",
            "--action-drift", "no", "--action-reason", "无",
            "--identity-protection", "yes", "--identity-reason", "无",
            "--toward", "vision", "--toward-reason", "写了",
            "--verdict", verdict, "--verdict-reason", "理由",
            "--tomorrow-lever", "写作", *extra)

    def status(self, day):
        self.set_now("2026-01-%02dT22:00:00" % day)
        r = self.run_cli("streak", "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.json()


class DriftTest(StreakTestCase):
    def test_three_drift_days_escalate(self):
        for d in (15, 16):
            self.assertEqual(self.checkin(d, "走偏").returncode, 0)
        s = self.status(16)
        self.assertEqual((s["drift"], s["escalation"]), (2, False))
        self.checkin(17, "走偏")
        s = self.status(17)
        self.assertEqual((s["drift"], s["escalation"]), (3, True))
        self.assertEqual(self.read_state()["streak"]["drift"], 3)

    def test_non_drift_resets(self):
        self.checkin(15, "走偏")
        self.checkin(16, "走偏")
        self.checkin(17, "轻微偏离")
        self.assertEqual(self.status(17)["drift"], 0)

    def test_second_checkin_same_day_not_double_counted(self):
        self.checkin(15, "走偏")
        self.checkin(15, "走偏")
        self.assertEqual(self.status(15)["drift"], 1)

    def test_revise_recomputes_drift(self):
        for d in (15, 16, 17):
            self.checkin(d, "走偏")
        self.assertTrue(self.status(17)["escalation"])
        r = self.run_cli("checkin", "revise-verdict", "--new-fact", "跑了步",
                         "--verdict", "在轨")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.status(17)
        self.assertEqual((s["drift"], s["escalation"]), (0, False))
        r = self.run_cli("checkin", "revise-verdict", "--new-fact", "其实没跑",
                         "--verdict", "走偏")
        self.assertEqual(self.status(17)["drift"], 3)


class UnrecordedTest(StreakTestCase):
    def test_missed_day_backfilled_as_unrecorded_not_drift(self):
        self.checkin(15, "走偏")
        s = self.status(17)  # 16th missed
        self.assertEqual((s["unrecorded"], s["drift"]), (1, 1))
        self.assertEqual(self.read_data("log", "2026-01-16.md"),
                         "# 2026-01-16\n- 未记录\n")
        s = self.status(17)  # idempotent
        self.assertEqual(s["unrecorded"], 1)

    def test_backfill_never_rewrites_existing_logs(self):
        self.checkin(15)
        before = self.read_data("log", "2026-01-15.md")
        self.status(19)
        self.assertEqual(self.read_data("log", "2026-01-15.md"), before)

    def test_three_unrecorded_escalate(self):
        self.checkin(15)
        s = self.status(18)  # 16, 17 missed
        self.assertEqual((s["unrecorded"], s["escalation"]), (2, False))
        s = self.status(19)
        self.assertEqual((s["unrecorded"], s["escalation"]), (3, True))

    def test_dnd_neither_counts_nor_breaks_run(self):
        self.checkin(15)
        self.assertEqual(self.run_cli("dnd", "add", "2026-01-17").returncode, 0)
        s = self.status(18)  # 16 missed, 17 DND
        self.assertEqual(s["unrecorded"], 1)
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-17.md")))
        s = self.status(20)  # 16, 18, 19 missed -> run of 3 across the DND
        self.assertEqual((s["unrecorded"], s["escalation"]), (3, True))

    def test_dnd_does_not_break_drift_run(self):
        self.checkin(15, "走偏")
        self.run_cli("dnd", "add", "2026-01-16")
        self.checkin(17, "走偏")
        self.assertEqual(self.status(17)["drift"], 2)

    def test_return_after_silence_requires_while_away(self):
        self.checkin(15)
        r = self.checkin(18)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("while-away", r.stderr)
        self.assertFalse(os.path.exists(self.data_path("log", "2026-01-18.md")))
        r = self.checkin(18, "在轨", "--while-away", "   ")
        self.assertNotEqual(r.returncode, 0)
        r = self.checkin(18, "在轨", "--while-away", "出差,没带电脑")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("出差,没带电脑", self.read_data("log", "2026-01-18.md"))
        self.assertEqual(self.status(18)["unrecorded"], 0)

    def test_checkin_after_only_dnd_gap_needs_no_explanation(self):
        self.checkin(15)
        self.run_cli("dnd", "add", "2026-01-16")
        self.assertEqual(self.checkin(17).returncode, 0)


class DndTest(StreakTestCase):
    def test_add_list_remove(self):
        self.run_cli("dnd", "add", "2026-01-20")
        self.run_cli("dnd", "add", "2026-01-18")
        self.run_cli("dnd", "add", "2026-01-18")
        self.assertEqual(self.run_cli("dnd", "list").json()["dnd_dates"],
                         ["2026-01-18", "2026-01-20"])
        self.assertEqual(self.run_cli("dnd", "remove", "2026-01-18").returncode, 0)
        self.assertEqual(self.run_cli("dnd", "list").json()["dnd_dates"],
                         ["2026-01-20"])
        self.assertEqual(self.read_state()["dnd_dates"], ["2026-01-20"])

    def test_bad_date_rejected(self):
        self.assertNotEqual(self.run_cli("dnd", "add", "tomorrow").returncode, 0)
