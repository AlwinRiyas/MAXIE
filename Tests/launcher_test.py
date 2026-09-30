"""Launcher guard (TD-27): a bad config setting must print one readable
line and exit 2, never a traceback from inside a subsystem."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import run as launcher
from Config.config import Config


class LauncherConfigErrorTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_files = dict(Config.FILES)
        self._orig_data = json.loads(json.dumps(Config.data))
        self.addCleanup(self._restore)

        bad = json.loads(json.dumps(Config.DEFAULT_SYSTEM))
        bad["remote_server"]["port"] = 99999
        path = os.path.join(self._tmp.name, "system.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(bad, handle)

        personality = os.path.join(self._tmp.name, "personality.json")
        with open(personality, "w", encoding="utf-8") as handle:
            json.dump(Config.DEFAULT_PERSONALITY, handle)
        audio = os.path.join(self._tmp.name, "audio.json")
        with open(audio, "w", encoding="utf-8") as handle:
            json.dump(Config.DEFAULT_AUDIO, handle)

        Config.FILES = {
            "system": path, "personality": personality, "audio": audio,
        }
        # Force a real read: load() short-circuits on already-loaded data.
        Config.data = {}
        self.addCleanup(Config.load)

    def _restore(self):
        Config.FILES = dict(self._orig_files)
        Config.data = json.loads(json.dumps(self._orig_data))

    def _run_main(self, argv):
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["run.py", *argv]):
            with redirect_stdout(buffer):
                with self.assertRaises(SystemExit) as caught:
                    launcher.main()
        return caught.exception.code, buffer.getvalue()

    def test_bad_config_prints_one_line_and_exits_two(self):
        code, output = self._run_main(["--console"])
        self.assertEqual(code, 2)
        self.assertIn("cannot start", output)
        self.assertIn("remote_server.port", output)
        self.assertIn("65535", output)
        self.assertIn(Config.FILES["system"], output)
        self.assertNotIn("Traceback", output)

    def test_bad_config_never_builds_maxie(self):
        with mock.patch(
            "Core.core_manager.Maxie"
        ) as maxie:  # import path used inside main()
            self._run_main(["--console"])
        maxie.assert_not_called()


class LauncherArgumentTest(unittest.TestCase):
    """The launcher still reaches MAXIE when the config is healthy."""

    def test_console_flag_reaches_maxie(self):
        fake = mock.MagicMock()
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["run.py", "--console"]):
            with mock.patch("Core.core_manager.Maxie", return_value=fake):
                with mock.patch("Config.config.Config.load"):
                    with redirect_stdout(buffer):
                        launcher.main()
        fake.start.assert_called_once()
        self.assertGreaterEqual(fake.shutdown.call_count, 1)


if __name__ == "__main__":
    unittest.main()