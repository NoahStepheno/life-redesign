import os

from tests.helpers import ActiveCliTestCase, CliTestCase

LOG = ("log", "2026-01-15.md")


class CheckinTestCase(ActiveCliTestCase):
    def checkin(self, **over):
        a = {"lever": ["写完第一章", "跑步30分钟"],
             "levers-done": "第一章写了2页;没跑步",
             "action-drift": "yes", "action-reason": "下雨没出门",
             "identity-protection": "no", "identity-reason": "无",
             "toward": "vision", "toward-reason": "晚上写作了",
             "verdict": "轻微偏离", "verdict-reason": "1项偏离有具体原因",
             "tomorrow-lever": ["写完第一章", "跑步30分钟"]}
        a.update(over)
        argv = ["checkin", "record"]
        for k, v in a.items():
            if v is None:
                continue
            for item in (v if isinstance(v, list) else [v]):
                argv += ["--" + k, item]
        return self.run_cli(*argv)


class RecordTest(CheckinTestCase):
    def test_one_checkin_writes_all_fields(self):
        r = self.checkin()
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read_data(*LOG)
        self.assertTrue(text.startswith("# 2026-01-15\n"))
        for frag in ["- Daily Levers: 写完第一章; 跑步30分钟",
                     "- 完成情况: 第一章写了2页;没跑步",
                     "- 行动偏离: 是 — 下雨没出门",
                     "- 身份保护: 否 — 无",
                     "- 靠近反愿景: 靠近愿景 — 晚上写作了",
                     "- 判定: 轻微偏离",
                     "- 判定理由: 1项偏离有具体原因"]:
            self.assertIn(frag, text)

    def test_invalid_verdict_rejected(self):
        r = self.checkin(verdict="还行")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.data_path(*LOG)))

    def test_missing_or_blank_verdict_reason_rejected(self):
        for v in (None, "   "):
            r = self.checkin(**{"verdict-reason": v})
            self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.data_path(*LOG)))

    def test_second_checkin_same_day_appends(self):
        self.checkin()
        first = self.read_data(*LOG)
        self.set_now("2026-01-15T22:30:00")
        r = self.checkin(verdict="走偏", **{"verdict-reason": "晚上又刷手机"})
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read_data(*LOG)
        self.assertTrue(text.startswith(first))
        self.assertIn("22:30:00", text[len(first):])
        self.assertIn("- 判定: 走偏", text[len(first):])

    def test_refused_before_protocol_complete(self):
        class Fresh(CliTestCase):
            def runTest(self):
                pass
        t = Fresh()
        t.setUp()
        try:
            t.run_cli("init")
            r = t.run_cli(
                "checkin", "record", "--lever", "a", "--levers-done", "a",
                "--action-drift", "no", "--action-reason", "a",
                "--identity-protection", "no", "--identity-reason", "a",
                "--toward", "vision", "--toward-reason", "a",
                "--verdict", "在轨", "--verdict-reason", "a",
                "--tomorrow-lever", "b")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("protocol is not complete", r.stderr)
            self.assertFalse(os.path.exists(t.data_path("log", "2026-01-15.md")))
        finally:
            t.doCleanups()


class ReviseTest(CheckinTestCase):
    def revise(self, *args):
        return self.run_cli("checkin", "revise-verdict", *args)

    def test_without_new_fact_refused_and_verdict_unchanged(self):
        self.checkin()
        before = self.read_data(*LOG)
        for args in (["--verdict", "在轨"],
                     ["--new-fact", "  ", "--verdict", "在轨"]):
            r = self.revise(*args)
            self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.read_data(*LOG), before)

    def test_with_fact_changes_and_logs(self):
        self.checkin()
        self.set_now("2026-01-15T22:00:00")
        r = self.revise("--new-fact", "20:00 在健身房跑了35分钟",
                        "--verdict", "在轨")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["verdict"], "在轨")
        text = self.read_data(*LOG)
        self.assertIn("- 改判: 轻微偏离 → 在轨 — 因 20:00 在健身房跑了35分钟 事实改判", text)
        self.assertIn("- 判定: 轻微偏离", text)  # original line untouched

    def test_invalid_verdict_or_no_checkin_refused(self):
        r = self.revise("--new-fact", "x", "--verdict", "在轨")
        self.assertNotEqual(r.returncode, 0)  # no check-in today
        self.checkin()
        r = self.revise("--new-fact", "x", "--verdict", "随便")
        self.assertNotEqual(r.returncode, 0)

    def test_revision_chain_uses_latest_verdict(self):
        self.checkin()
        self.revise("--new-fact", "a", "--verdict", "在轨")
        r = self.revise("--new-fact", "b", "--verdict", "走偏")
        self.assertIn("在轨 → 走偏", self.read_data(*LOG))
        self.assertEqual(r.json()["previous"], "在轨")


class LeversTest(CheckinTestCase):
    def test_tomorrow_levers_readable_next_day(self):
        self.checkin(**{"tomorrow-lever": ["读论文", "散步"]})
        self.set_now("2026-01-16T08:00:00")
        r = self.run_cli("checkin", "levers")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["levers"], ["读论文", "散步"])
        r = self.run_cli("checkin", "levers", "--date", "2026-01-16")
        self.assertEqual(r.json()["levers"], ["读论文", "散步"])

    def test_no_levers_saved_gives_empty(self):
        self.assertEqual(self.run_cli("checkin", "levers").json()["levers"], [])

    def test_next_checkin_defaults_levers_to_saved(self):
        self.checkin()
        self.set_now("2026-01-16T21:30:00")
        r = self.checkin(lever=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("- Daily Levers: 写完第一章; 跑步30分钟",
                      self.read_data("log", "2026-01-16.md"))

    def test_tomorrow_lever_required(self):
        r = self.checkin(**{"tomorrow-lever": None})
        self.assertNotEqual(r.returncode, 0)
