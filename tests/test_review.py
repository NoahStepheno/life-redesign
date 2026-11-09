from tests.helpers import ActiveCliTestCase, CliTestCase


class ReviewTestCase(ActiveCliTestCase):
    def setUp(self):
        super().setUp()
        self.set_now("2026-01-15T09:00:00")  # protocol completed on the 15th

    def checkin(self, day, verdict, month="2026-01"):
        self.set_now("%s-%02dT21:00:00" % (month, day))
        r = self.run_cli(
            "checkin", "record", "--lever", "写作", "--levers-done", "写了",
            "--action-drift", "no", "--action-reason", "无",
            "--identity-protection", "yes", "--identity-reason", "无",
            "--toward", "vision", "--toward-reason", "写了",
            "--verdict", verdict, "--verdict-reason", "理由",
            "--tomorrow-lever", "写作",
            "--while-away", "不在")
        self.assertEqual(r.returncode, 0, r.stderr)

    def month(self, now, *extra):
        self.set_now(now)
        r = self.run_cli("review", "month", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.json()

    def change(self, day, obj, text, why, month="2026-01"):
        self.set_now("%s-%02dT10:00:00" % (month, day))
        r = self.run_cli("plan", "change", obj, "--text", text, "--why", why)
        self.assertEqual(r.returncode, 0, r.stderr)


class InactiveTest(CliTestCase):
    def test_all_review_commands_refused(self):
        self.run_cli("init")
        for args in (("month",), ("year",),
                     ("save", "--kind", "month", "--text", "x")):
            r = self.run_cli("review", *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("not complete", r.stderr)


class MonthCountsTest(ReviewTestCase):
    def test_counts_sum_to_days_in_scope(self):
        self.checkin(16, "在轨")
        self.checkin(17, "轻微偏离")
        self.checkin(18, "走偏")
        # 19 skipped (unrecorded), 20 is DND, today is the 21st
        self.run_cli("dnd", "add", "2026-01-20")
        r = self.month("2026-01-21T09:00:00")
        self.assertEqual(r["counts"], {"on_track": 1, "minor_drift": 1,
                                       "drifted": 1, "unrecorded": 1})
        self.assertEqual(r["days_in_period"], 31)
        self.assertEqual(r["days_in_scope"], 4)
        self.assertEqual(sum(r["counts"].values()), r["days_in_scope"])
        self.assertEqual(r["dnd_days"], ["2026-01-20"])
        self.assertEqual(r["excluded"], {
            "before_activation": 15, "future_or_today_pending": 11, "dnd": 1})
        self.assertEqual(sum(r["excluded"].values()) + r["days_in_scope"], 31)

    def test_past_full_month_sums_to_days_in_month(self):
        self.checkin(16, "在轨")
        r = self.month("2026-03-01T09:00:00", "--month", "2026-02")
        self.assertEqual(r["days_in_period"], 28)
        self.assertEqual(r["counts"]["unrecorded"], 28)
        self.assertEqual(sum(r["counts"].values()), 28)

    def test_dnd_day_not_unrecorded(self):
        self.run_cli("dnd", "add", "2026-01-17")
        r = self.month("2026-01-19T09:00:00")
        self.assertEqual(r["counts"]["unrecorded"], 2)  # 16, 18
        self.assertEqual(r["dnd_days"], ["2026-01-17"])


class MonthPlanTest(ReviewTestCase):
    def test_unchanged_flag(self):
        r = self.month("2026-01-20T09:00:00")
        self.assertEqual(r["plan_changes"], [])
        self.assertTrue(r["plan_unchanged"])
        self.assertEqual(r["plan_message"], "本月计划未改动")

    def test_changes_listed_with_reason(self):
        self.change(18, "vision", "新愿景", "想清楚了")
        self.change(19, "year-goal", "新年目标", "目标太虚")
        r = self.month("2026-01-20T09:00:00")
        self.assertFalse(r["plan_unchanged"])
        self.assertIsNone(r["plan_message"])
        got = [(c["object"], c["date"], c["reason"]) for c in r["plan_changes"]]
        self.assertEqual(got, [("vision", "2026-01-18", "想清楚了"),
                               ("goals", "2026-01-19", "目标太虚")])
        self.assertEqual(r["plan_changes"][1]["sections"], ["Year Goal"])

    def test_other_month_changes_not_listed(self):
        self.change(18, "vision", "新愿景", "x")
        r = self.month("2026-03-20T09:00:00", "--month", "2026-02")
        self.assertTrue(r["plan_unchanged"])


class YearTest(ReviewTestCase):
    def test_distribution_and_year_goal_history(self):
        self.checkin(16, "在轨")
        self.checkin(17, "走偏")
        self.change(17, "year-goal", "第一版年目标", "初")
        self.change(18, "year-goal", "第二版年目标", "改")
        self.change(19, "vision", "愿景2", "不涉及年目标")
        self.set_now("2026-01-20T09:00:00")
        r = self.run_cli("review", "year")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = r.json()
        self.assertEqual(r["year"], 2026)
        self.assertEqual(r["counts"]["on_track"], 1)
        self.assertEqual(r["counts"]["drifted"], 1)
        self.assertEqual(sum(r["counts"].values()), r["days_in_scope"])
        hist = r["year_goal_history"]
        self.assertEqual(len(hist), 2)
        self.assertIn("第二版年目标", hist[-1]["text"])
        self.assertEqual(hist[-1]["reason"], "改")
        self.assertTrue(r["offer_redo_protocol"])

    def test_year_arg(self):
        self.set_now("2026-01-20T09:00:00")
        r = self.run_cli("review", "year", "--year", "2025").json()
        self.assertEqual(r["days_in_period"], 365)
        self.assertEqual(r["days_in_scope"], 0)


class SaveTest(ReviewTestCase):
    def test_saves_append_only(self):
        self.set_now("2026-01-31T22:00:00")
        r = self.run_cli("review", "save", "--kind", "month", "--text", "第一份结论")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.set_now("2026-02-28T22:00:00")
        r = self.run_cli("review", "save", "--kind", "month", "--text", "第二份结论")
        self.assertEqual(r.json()["reviews"], 2)
        text = self.read_data("reviews.md")
        self.assertLess(text.index("第一份结论"), text.index("第二份结论"))
        self.assertIn("## 2026-01-31 月复盘 2026-01", text)
        self.assertIn("## 2026-02-28 月复盘 2026-02", text)

    def test_year_kind_and_text_required(self):
        r = self.run_cli("review", "save", "--kind", "year", "--text", "年结论")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("年复盘 2026", self.read_data("reviews.md"))
        r = self.run_cli("review", "save", "--kind", "year")
        self.assertNotEqual(r.returncode, 0)

