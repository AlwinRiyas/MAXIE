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
        import os

        root = Config.get_project_root()
        self.assertTrue(os.path.isdir(root))


if __name__ == "__main__":
    unittest.main()