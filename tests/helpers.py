"""Shared black-box fixture for CLI tests.

Usage:
    from tests.helpers import CliTestCase

    class MyTest(CliTestCase):
        def test_x(self):
            self.set_now("2026-01-15T09:00:00")
            r = self.run_cli("init")
            self.assertEqual(r.returncode, 0)
            state = self.read_state()
            text = self.read_data("anti-vision.md")

Every CLI call runs in a subprocess with LIFE_REDESIGN_HOME pointing at a
per-test temp dir, LIFE_REDESIGN_NOW pinned, and HOME redirected to another
temp dir so the real home directory is never touched.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(REPO_ROOT, "skill", "scripts", "life_redesign.py")

DEFAULT_NOW = "2026-01-15T09:00:00"


class CliResult(object):
    def __init__(self, completed):
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr

    def json(self):
        return json.loads(self.stdout)


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="life-redesign-test-")
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.fake_home = os.path.join(self._tmp, "home")
        os.makedirs(self.fake_home)
        # The data dir does not exist yet: init must create it.
        self.data_dir = os.path.join(self._tmp, "data")
        self.now = DEFAULT_NOW

    def set_now(self, iso):
        self.now = iso

    def env(self, use_override=True, now=True):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("LIFE_REDESIGN_")}
        env["HOME"] = self.fake_home
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if use_override:
            env["LIFE_REDESIGN_HOME"] = self.data_dir
        if now:
            env["LIFE_REDESIGN_NOW"] = self.now
        return env

    def run_cli(self, *args, **kw):
        completed = subprocess.run(
            [sys.executable, CLI] + list(args),
            env=self.env(**kw), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True)
        return CliResult(completed)

    def data_path(self, *parts):
        return os.path.join(self.data_dir, *parts)

    def read_data(self, *parts):
        with open(self.data_path(*parts), encoding="utf-8") as f:
            return f.read()

    def write_data(self, text, *parts):
        path = self.data_path(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read_state(self):
        return json.loads(self.read_data("state.json"))


ALL_QUESTIONS = (["1.%d" % i for i in range(1, 15)]
                 + ["3.%d" % i for i in range(1, 8)] + ["3.constraints"])


class ActiveCliTestCase(CliTestCase):
    """CliTestCase with an initialised data dir and a completed protocol."""

    def setUp(self):
        super().setUp()
        self.run_cli("init")
        self.run_cli("protocol", "resume")
        for qid in ALL_QUESTIONS:
            r = self.run_cli("protocol", "answer", qid, "--text", "a " + qid)
            assert r.returncode == 0, r.stderr
        assert self.read_state()["phase"] == "active"
