import os
import unittest

from tests.helpers import CliTestCase

INITIAL_STATE = {
    "phase": "new",
    "protocol": {"started_at": None, "part": None, "question": None},
    "streak": {"drift": 0, "unrecorded": 0},
    "dnd_dates": [],
    "notify": {"client": "claude -p", "times": {
        "morning": "08:30", "evening": "21:30",
        "random_window": ["11:00", "17:00"]}},
    "privacy_ack": False,
}


class InitTest(CliTestCase):
    def test_init_creates_protocol_conformant_initial_state(self):
        r = self.run_cli("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_state(), INITIAL_STATE)
        self.assertEqual(self.read_state()["phase"], "new")

    def test_override_dir_used_and_real_home_untouched(self):
        self.run_cli("init")
        self.assertTrue(os.path.isdir(self.data_dir))
        self.assertEqual(os.listdir(self.fake_home), [])

    def test_default_location_is_dot_life_redesign_in_home(self):
        r = self.run_cli("init", use_override=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        state = os.path.join(self.fake_home, ".life-redesign", "state.json")
        self.assertTrue(os.path.isfile(state))
        self.assertFalse(os.path.exists(self.data_dir))

    def test_injected_now_is_used_by_commands(self):
        self.set_now("2026-03-02T07:05:00")
        self.assertEqual(self.run_cli("now").json()["now"],
                         "2026-03-02T07:05:00")
        self.set_now("2027-12-31T23:59:00")
        self.assertEqual(self.run_cli("now").json()["now"],
                         "2027-12-31T23:59:00")

    def test_invalid_now_is_rejected(self):
        self.set_now("not-a-time")
        r = self.run_cli("now")
        self.assertNotEqual(r.returncode, 0)

    def test_privacy_ack_is_persisted_and_not_asked_again(self):
        first = self.run_cli("init").json()
        self.assertTrue(first["privacy_required"])
        self.assertFalse(self.read_state()["privacy_ack"])

        self.run_cli("ack-privacy")
        self.assertTrue(self.read_state()["privacy_ack"])

        again = self.run_cli("init").json()
        self.assertFalse(again["privacy_required"])
        self.assertFalse(self.run_cli("status").json()["privacy_required"])

    def test_init_with_ack_flag_records_acknowledgement(self):
        r = self.run_cli("init", "--ack-privacy").json()
        self.assertFalse(r["privacy_required"])
        self.assertTrue(self.read_state()["privacy_ack"])

    def test_repeated_init_does_not_destroy_existing_data(self):
        self.run_cli("init", "--ack-privacy")
        self.write_data("## 2026-01-15\nmine\n", "anti-vision.md")
        state = self.read_state()
        state["phase"] = "active"
        state["streak"]["drift"] = 2
        self.write_data(__import__("json").dumps(state), "state.json")

        r = self.run_cli("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_state(), state)
        self.assertEqual(self.read_data("anti-vision.md"),
                         "## 2026-01-15\nmine\n")

    def test_status_before_init_fails_without_creating_anything(self):
        r = self.run_cli("status")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.data_dir))


if __name__ == "__main__":
    unittest.main()
