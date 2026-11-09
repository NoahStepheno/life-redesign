import os
import stat
import sys

from tests.helpers import ActiveCliTestCase, CliTestCase


def mins(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


class NotifyTestCase(ActiveCliTestCase):
    def setUp(self):
        super().setUp()
        self.set_now("2026-01-15T09:00:00")  # protocol completed on the 15th

    def plan(self, date, **kw):
        r = self.run_cli("notify", "plan", "--date", date, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.json()

    def checkin(self, day):
        self.set_now("2026-01-%02dT21:00:00" % day)
        return self.run_cli(
            "checkin", "record", "--lever", "写作", "--levers-done", "写了",
            "--action-drift", "no", "--action-reason", "无",
            "--identity-protection", "yes", "--identity-reason", "无",
            "--toward", "vision", "--toward-reason", "写了",
            "--verdict", "在轨", "--verdict-reason", "理由",
            "--tomorrow-lever", "写作")


class PlanTest(NotifyTestCase):
    def test_three_pushes_morning_random_evening(self):
        p = self.plan("2026-01-16")
        self.assertEqual([x["slot"] for x in p["pushes"]],
                         ["morning", "random", "evening"])
        self.assertEqual(p["pushes"][0]["time"], "08:30")
        self.assertEqual(p["pushes"][2]["time"], "21:30")

    def test_random_inside_window_deterministic_and_varies(self):
        times = set()
        for d in range(16, 31):
            date = "2026-01-%02d" % d
            a, b = self.plan(date), self.plan(date)
            self.assertEqual(a, b)
            t = a["pushes"][1]["time"]
            self.assertTrue(mins("11:00") <= mins(t) <= mins("17:00"), t)
            times.add(t)
        self.assertGreater(len(times), 5)

    def test_window_config_respected(self):
        r = self.run_cli("notify", "config", "--window", "12:00", "12:30")
        self.assertEqual(r.returncode, 0, r.stderr)
        for d in range(16, 26):
            t = self.plan("2026-01-%02d" % d)["pushes"][1]["time"]
            self.assertTrue(mins("12:00") <= mins(t) <= mins("12:30"), t)

    def test_bad_window_rejected(self):
        r = self.run_cli("notify", "config", "--window", "17:00", "11:00")
        self.assertNotEqual(r.returncode, 0)

    def test_random_text_from_prewritten_pool(self):
        q = self.plan("2026-01-16")["pushes"][1]["text"]
        self.assertTrue(q.endswith("?") or q.endswith("?") or "?" in q)

    def test_silence_after_three_unrecorded(self):
        self.checkin(15)
        self.set_now("2026-01-19T08:00:00")  # 16,17,18 unrecorded
        p = self.plan("2026-01-19")
        self.assertEqual([x["slot"] for x in p["pushes"]], ["evening"])

    def test_two_unrecorded_not_silenced(self):
        self.set_now("2026-01-18T08:00:00")  # 16,17 unrecorded
        self.assertEqual(len(self.plan("2026-01-18")["pushes"]), 3)

    def test_dnd_date_empty(self):
        self.run_cli("dnd", "add", "2026-01-16")
        self.assertEqual(self.plan("2026-01-16")["pushes"], [])
        self.assertEqual(len(self.plan("2026-01-17")["pushes"]), 3)

    def test_inactive_phase_empty(self):
        self.write_data("{}", "x")  # data dir exists
        state = self.read_state()
        state["phase"] = "protocol_shelved"
        import json
        self.write_data(json.dumps(state), "state.json")
        self.assertEqual(self.plan("2026-01-16")["pushes"], [])


class PrivacyTest(NotifyTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("append", "goals", "--year-goal", "SECRETGOAL出版一本书",
                     "--month-project", "m", "--constraints", "c")
        self.run_cli("plan", "change", "daily-levers", "--text", "SECRETLEVER跑步",
                     "--why", "r")

    def test_default_has_no_user_text(self):
        r = self.run_cli("notify", "plan", "--date", "2026-01-16")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("SECRET", r.stdout)
        self.assertIn("打开查看今日杠杆", r.stdout)
        fire = self.run_cli("notify", "fire", "morning", "--dry-run")
        self.assertNotIn("SECRET", fire.stdout)

    def test_opt_in_shows_user_text(self):
        self.run_cli("notify", "config", "--show-user-text", "on")
        r = self.run_cli("notify", "plan", "--date", "2026-01-16")
        self.assertIn("SECRETGOAL", r.stdout)
        self.assertIn("SECRETLEVER", r.stdout)
        self.run_cli("notify", "config", "--show-user-text", "off")
        self.assertNotIn(
            "SECRET", self.run_cli("notify", "plan", "--date", "2026-01-16").stdout)


class LeverParsingTest(NotifyTestCase):
    def test_list_marker_stripped_but_leading_digits_kept(self):
        self.run_cli("plan", "change", "daily-levers", "--why", "r",
                     "--text", "- 10 pushups\n5km run\n1. read\n2) write")
        self.run_cli("notify", "config", "--show-user-text", "on")
        text = self.plan("2026-01-16")["pushes"][0]["text"]
        self.assertIn("今日杠杆: 10 pushups; 5km run; read; write", text)


class InstallTest(NotifyTestCase):
    def test_install_dry_run_prints_plists_and_commands(self):
        r = self.run_cli("notify", "install", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.json()
        self.assertTrue(out["dry_run"])
        self.assertEqual(len(out["jobs"]), 3)
        self.assertIn("<key>StartCalendarInterval</key>", out["jobs"][0]["plist"])
        self.assertIn("notify", out["jobs"][0]["plist"])
        flat = [" ".join(c) for c in out["commands"]]
        self.assertTrue(any("launchctl bootstrap gui/" in c for c in flat))
        self.assertFalse(os.path.exists(
            os.path.join(self.fake_home, "Library")))

    def test_uninstall_dry_run(self):
        r = self.run_cli("notify", "uninstall", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        flat = [" ".join(c) for c in r.json()["commands"]]
        self.assertEqual(len(flat), 3)
        self.assertTrue(all("launchctl bootout gui/" in c for c in flat))
        self.assertFalse(os.path.exists(
            os.path.join(self.fake_home, "Library")))

    def test_plist_uses_configured_times(self):
        self.run_cli("notify", "config", "--morning", "07:45")
        out = self.run_cli("notify", "install", "--dry-run").json()
        morning = [j for j in out["jobs"] if j["label"].endswith("morning")][0]
        self.assertIn("<integer>45</integer>", morning["plist"])
        self.assertIn("<integer>7</integer>", morning["plist"])


class FireTest(NotifyTestCase):
    def fake_client(self, body, name="fake"):
        path = os.path.join(self._tmp, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def evening(self, *extra):
        self.set_now("2026-01-16T21:30:00")
        r = self.run_cli("notify", "fire", "evening", "--dry-run", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.json()

    def test_fire_dry_run_prints_display_without_sending(self):
        out = self.evening()
        self.assertEqual(out["source"], "template")
        self.assertFalse(out["fired"])
        self.assertIn("display notification", " ".join(out["display_command"])
                      ) if out["display_command"][0] == "osascript" else None

    def test_fire_skips_when_not_in_plan(self):
        self.run_cli("dnd", "add", "2026-01-16")
        out = self.evening()
        self.assertIn("skipped", out)

    def test_ai_used_when_enabled_and_command_is_read_only(self):
        client = self.fake_client('echo "AI提醒一句"')
        self.run_cli("notify", "config", "--client", client + " -p", "--ai", "on")
        out = self.evening()
        self.assertEqual((out["source"], out["text"]), ("ai", "AI提醒一句"))

    def test_claude_client_gets_read_only_flags(self):
        self.run_cli("notify", "config", "--client", "claude -p", "--ai", "on")
        out = self.evening()
        cmd = out["client_command"]
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertIn("--disallowedTools", cmd)
        self.assertIn("Write", cmd[cmd.index("--disallowedTools") + 1])
        self.assertIn("Bash", cmd[cmd.index("--disallowedTools") + 1])

    def test_failing_client_falls_back_to_template(self):
        client = self.fake_client("exit 3")
        self.run_cli("notify", "config", "--client", client, "--ai", "on")
        out = self.evening()
        self.assertEqual(out["source"], "template")
        self.assertIn("打卡", out["text"])

    def test_missing_client_falls_back_to_template(self):
        self.run_cli("notify", "config", "--client", "/no/such/client", "--ai", "on")
        self.assertEqual(self.evening()["source"], "template")

    def test_ai_off_by_default_never_runs_client(self):
        marker = os.path.join(self._tmp, "ran")
        client = self.fake_client("touch %s" % marker)
        self.run_cli("notify", "config", "--client", client)
        self.evening()
        self.assertFalse(os.path.exists(marker))

    def test_client_runs_outside_data_dir_with_only_recent_logs(self):
        self.write_data("# 2026-01-01\n- OLDLOG\n", "log", "2026-01-01.md")
        self.write_data("# 2026-01-15\n- NEWLOG\n", "log", "2026-01-15.md")
        out = os.path.join(self._tmp, "seen")
        client = self.fake_client('pwd > %s; echo "$@" >> %s; echo ok' % (out, out))
        self.run_cli("notify", "config", "--client", client, "--ai", "on")
        self.evening()
        seen = open(out, encoding="utf-8").read()
        self.assertNotIn(self.data_dir, seen.split("\n")[0])
        self.assertIn("NEWLOG", seen)
        self.assertNotIn("OLDLOG", seen)


class TickTest(NotifyTestCase):
    def test_tick_fires_only_at_planned_time(self):
        self.set_now("2026-01-16T09:00:00")
        t = self.plan("2026-01-16")["pushes"][1]["time"]
        h, m = int(t[:2]), int(t[3:])
        self.set_now("2026-01-16T%02d:%02d:30" % (h, m))
        out = self.run_cli("notify", "fire", "random", "--tick", "--dry-run").json()
        self.assertNotIn("skipped", out)
        self.set_now("2026-01-16T06:00:00")
        out = self.run_cli("notify", "fire", "random", "--tick", "--dry-run").json()
        self.assertIn("skipped", out)
