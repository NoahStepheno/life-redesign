import os

from tests.helpers import CliTestCase

PART1 = ["1.%d" % i for i in range(1, 15)]
PART3 = ["3.%d" % i for i in range(1, 8)] + ["3.constraints"]
ALL = PART1 + PART3


class ProtocolTestCase(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("init")

    def answer(self, qid, text=None):
        return self.run_cli("protocol", "answer", qid, "--text",
                            text or ("answer to " + qid))

    def answer_through(self, last):
        for qid in ALL:
            r = self.answer(qid)
            self.assertEqual(r.returncode, 0, r.stderr)
            if qid == last:
                return

    def proto(self, *args):
        return self.run_cli("protocol", *args)


class ProgressTest(ProtocolTestCase):
    def test_resume_from_new_starts_at_first_question(self):
        r = self.proto("resume")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.json()
        self.assertEqual(out["phase"], "protocol_in_progress")
        self.assertEqual(out["question"], "1.1")
        self.assertEqual(self.read_state()["phase"], "protocol_in_progress")

    def test_answer_is_written_immediately_and_progress_advances(self):
        self.proto("resume")
        r = self.answer("1.1", "I tolerate my job")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["next"], "1.2")
        text = self.read_data("protocol", "2026-01-15.md")
        self.assertIn("## 1.1\nI tolerate my job\n", text)
        st = self.read_state()["protocol"]
        self.assertEqual((st["part"], st["question"]), (1, "1.2"))

    def test_progress_survives_new_process_same_day(self):
        self.proto("resume")
        self.answer("1.1")
        self.answer("1.2")
        out = self.proto("resume").json()
        self.assertEqual(out["question"], "1.3")
        self.assertFalse(out["feeling_check_required"])
        self.assertEqual(self.proto("status").json()["answered"], 2)

    def test_must_answer_current_question_in_order(self):
        self.proto("resume")
        r = self.answer("1.3")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("1.1", r.stderr)

    def test_unknown_and_interrupt_ids_rejected(self):
        self.proto("resume")
        for qid in ("9.9", "2.1", "x"):
            r = self.answer(qid)
            self.assertNotEqual(r.returncode, 0, qid)

    def test_answer_before_resume_rejected(self):
        r = self.answer("1.1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("resume", r.stderr)

    def test_empty_and_forged_heading_rejected(self):
        self.proto("resume")
        self.assertNotEqual(self.answer("1.1", "  ").returncode, 0)
        self.assertNotEqual(self.answer("1.1", "a\n## 1.2\nb").returncode, 0)

    def test_part_switches_to_3_after_q14(self):
        self.proto("resume")
        self.answer_through("1.14")
        st = self.read_state()["protocol"]
        self.assertEqual((st["part"], st["question"]), (3, "3.1"))

    def test_completion_makes_phase_active(self):
        self.proto("resume")
        self.answer_through("3.constraints")
        self.assertEqual(self.read_state()["phase"], "active")
        out = self.proto("status").json()
        self.assertEqual(out["phase"], "active")
        self.assertIsNone(out["question"])


class OvernightTest(ProtocolTestCase):
    def start_day_one(self):
        self.proto("resume")
        self.answer("1.1")
        self.answer("1.2")

    def test_overnight_requires_feeling_check_before_answering(self):
        self.start_day_one()
        self.set_now("2026-01-16T09:00:00")
        out = self.proto("resume").json()
        self.assertTrue(out["feeling_check_required"])
        r = self.answer("1.3")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("confirm-feeling", r.stderr)

    def test_fresh_continues_from_breakpoint(self):
        self.start_day_one()
        self.set_now("2026-01-16T09:00:00")
        self.proto("resume")
        r = self.proto("confirm-feeling", "fresh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["question"], "1.3")
        self.assertEqual(self.answer("1.3").returncode, 0)
        self.assertTrue(os.path.isfile(self.data_path("protocol", "2026-01-16.md")))
        self.assertTrue(os.path.isfile(self.data_path("protocol", "2026-01-15.md")))

    def test_faded_marks_segment_discarded_keeps_file_and_restarts(self):
        self.start_day_one()
        self.set_now("2026-01-16T09:00:00")
        r = self.proto("confirm-feeling", "faded")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.json()["question"], "1.1")
        old = self.data_path("protocol", "2026-01-15.discarded.md")
        self.assertTrue(os.path.isfile(old))
        with open(old, encoding="utf-8") as f:
            self.assertIn("answer to 1.1", f.read())
        self.assertEqual(self.answer("1.1", "new").returncode, 0)
        self.assertIn("new", self.read_data("protocol", "2026-01-16.md"))
        self.assertNotIn("answer to 1.1", self.read_data("protocol", "2026-01-16.md"))

    def test_confirm_feeling_without_pending_check_rejected(self):
        self.start_day_one()
        r = self.proto("confirm-feeling", "fresh")
        self.assertNotEqual(r.returncode, 0)

    def test_confirm_feeling_rejects_other_values(self):
        self.start_day_one()
        self.set_now("2026-01-16T09:00:00")
        self.assertNotEqual(self.proto("confirm-feeling", "meh").returncode, 0)


class ShelveTest(ProtocolTestCase):
    def test_over_seven_days_shelves_and_archives(self):
        self.proto("resume")
        self.answer("1.1")
        self.set_now("2026-01-23T09:00:01")
        out = self.proto("status").json()
        self.assertEqual(out["phase"], "protocol_shelved")
        self.assertEqual(self.read_state()["phase"], "protocol_shelved")
        self.assertFalse(os.path.exists(self.data_path("protocol", "2026-01-15.md")))
        arch = self.data_path("protocol", "2026-01-15.archived.md")
        self.assertTrue(os.path.isfile(arch))

    def test_exactly_seven_days_is_not_shelved(self):
        self.proto("resume")
        self.answer("1.1")
        self.set_now("2026-01-22T09:00:00")
        out = self.proto("status").json()
        self.assertEqual(out["phase"], "protocol_in_progress")

    def test_resume_after_shelve_restarts_fresh(self):
        self.proto("resume")
        self.answer("1.1")
        self.set_now("2026-02-20T09:00:00")
        self.proto("status")
        out = self.proto("resume").json()
        self.assertEqual(out["phase"], "protocol_in_progress")
        self.assertEqual(out["question"], "1.1")
        self.assertEqual(out["answered"], 0)

    def test_resume_directly_after_long_gap_shelves_then_restarts(self):
        self.proto("resume")
        self.answer("1.1")
        self.set_now("2026-02-20T09:00:00")
        out = self.proto("resume").json()
        self.assertEqual(out["question"], "1.1")
        self.assertTrue(os.path.isfile(self.data_path("protocol", "2026-01-15.archived.md")))


class GateTest(ProtocolTestCase):
    def test_gate_refuses_until_active(self):
        r = self.run_cli("protocol", "gate")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("finish the protocol first", r.stderr)
        self.proto("resume")
        self.assertNotEqual(self.run_cli("protocol", "gate").returncode, 0)
        self.answer_through("3.constraints")
        self.assertEqual(self.run_cli("protocol", "gate").returncode, 0)

    def test_require_active_is_importable(self):
        import sys
        from tests.helpers import REPO_ROOT
        sys.path.insert(0, os.path.join(REPO_ROOT, "skill", "scripts"))
        try:
            import life_redesign
        finally:
            sys.path.pop(0)
        self.assertTrue(callable(life_redesign.require_active))


class RedoTest(ProtocolTestCase):
    def finish(self):
        self.proto("resume")
        self.answer_through("3.constraints")

    def test_resume_or_answer_on_active_needs_explicit_redo(self):
        self.finish()
        self.assertNotEqual(self.proto("resume").returncode, 0)
        r = self.answer("1.1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("redo", r.stderr)

    def test_redo_requires_active(self):
        r = self.proto("redo")
        self.assertNotEqual(r.returncode, 0)

    def test_redo_appends_new_version_and_keeps_old(self):
        self.finish()
        self.set_now("2026-03-01T09:00:00")
        out = self.proto("redo").json()
        self.assertEqual(out["question"], "1.1")
        self.assertEqual(out["phase"], "active")
        self.answer("1.1", "second time")
        self.assertIn("answer to 1.1", self.read_data("protocol", "2026-01-15.md"))
        self.assertIn("second time", self.read_data("protocol", "2026-03-01.md"))

    def test_same_day_redo_does_not_touch_original_file(self):
        self.finish()
        before = self.read_data("protocol", "2026-01-15.md")
        self.proto("redo")
        self.answer("1.1", "again")
        self.assertEqual(self.read_data("protocol", "2026-01-15.md"), before)
        self.assertEqual(len(os.listdir(self.data_path("protocol"))), 2)

    def test_redo_completion_stays_active_and_clears_redo(self):
        self.finish()
        self.proto("redo")
        self.answer_through("3.constraints")
        out = self.proto("status").json()
        self.assertEqual(out["phase"], "active")
        self.assertFalse(out["redo"])
        self.assertNotEqual(self.answer("1.1").returncode, 0)

    def test_redo_in_progress_keeps_gate_open_and_rejects_second_redo(self):
        self.finish()
        self.proto("redo")
        self.assertEqual(self.run_cli("protocol", "gate").returncode, 0)
        self.assertNotEqual(self.proto("redo").returncode, 0)

    def test_stale_redo_is_cancelled_and_archived_but_stays_active(self):
        self.finish()
        self.set_now("2026-03-01T09:00:00")
        self.proto("redo")
        self.answer("1.1")
        self.set_now("2026-03-20T09:00:00")
        out = self.proto("status").json()
        self.assertEqual(out["phase"], "active")
        self.assertFalse(out["redo"])
        self.assertTrue(os.path.isfile(self.data_path("protocol", "2026-03-01.archived.md")))

    def test_redo_overnight_faded_discards_and_restarts_redo(self):
        self.finish()
        self.set_now("2026-03-01T09:00:00")
        self.proto("redo")
        self.answer("1.1")
        self.set_now("2026-03-02T09:00:00")
        out = self.proto("confirm-feeling", "faded").json()
        self.assertTrue(out["redo"])
        self.assertEqual(out["question"], "1.1")
        self.assertTrue(os.path.isfile(self.data_path("protocol", "2026-03-01.discarded.md")))
        self.assertEqual(out["phase"], "active")
