import json
import os
import tempfile
import unittest

from Config.config import Config


class ConfigTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Config.load(force=True)

    def test_system_defaults(self):
        system = Config.system()
        self.assertEqual(system["assistant_name"], "Maxie")
        self.assertTrue(system["wake_word_enabled"] in (True, False))
        self.assertEqual(system["remote_server"]["host"], "127.0.0.1")

    def test_audio_defaults(self):
        audio = Config.audio()
        self.assertEqual(int(audio["sample_rate"]), 16000)
        self.assertGreater(float(audio["max_seconds"]), 0)
        self.assertIn("whisper_model", audio)

    def test_personality_defaults(self):
        personality = Config.personality()
        self.assertIn("style", personality)
        self.assertIn("voice_gender", personality)

    def test_compat_attributes(self):
        self.assertEqual(Config.ASSISTANT_NAME, "Maxie")
        self.assertEqual(Config.USER_NAME, "Alwin")
        self.assertTrue(Config.VERSION)

    def test_remote_config(self):
        remote = Config.remote_config()
        self.assertIn("enabled", remote)
        self.assertIn("port", remote)

    def test_project_root_resolves(self):
        root = Config.get_project_root()
        self.assertTrue(os.path.isdir(root))


class ConfigReadNoWriteTest(unittest.TestCase):
    """TD-09: reading configuration must never write to disk."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._orig_files = dict(Config.FILES)

    def tearDown(self):
        Config.FILES = dict(self._orig_files)

    def test_read_does_not_rewrite_a_valid_file(self):
        path = os.path.join(self._dir.name, "system.json")
        original = {"assistant_name": "Rosie", "user_name": "Leslie"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(original, f)

        Config.FILES = {
            **self._orig_files,
            "system": path,
        }
        Config.load(force=True)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(
            json.loads(content), original,
            "a read must never re-serialize/write a user's valid config",
        )

    def test_malformed_config_is_not_silently_destroyed(self):
        path = os.path.join(self._dir.name, "system.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ this is not json ]]")

        Config.FILES = {
            **self._orig_files,
            "system": path,
        }
        Config.load(force=True)

        self.assertTrue(
            os.path.exists(path + ".bak"),
            "a backup must exist before a malformed file is touched",
        )
        with open(path + ".bak", "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "{ this is not json ]]")

    def test_missing_file_creates_defaults_once(self):
        path = os.path.join(self._dir.name, "system.json")
        Config.FILES = {
            **self._orig_files,
            "system": path,
        }
        Config.load(force=True)

        self.assertTrue(os.path.exists(path), "missing config is created")
        mtime = os.path.getmtime(path)
        Config.load(force=True)
        self.assertEqual(
            os.path.getmtime(path), mtime,
            "creating a missing file must happen once, not on every read",
        )

    def test_defaults_are_not_mutated_by_loading(self):
        Config.load(force=True)
        before = json.dumps(Config.DEFAULT_SYSTEM, sort_keys=True)
        Config.load(force=True)
        after = json.dumps(Config.DEFAULT_SYSTEM, sort_keys=True)
        self.assertEqual(
            before, after,
            "loading must never alias/mutate the class default templates",
        )


if __name__ == "__main__":
    unittest.main()