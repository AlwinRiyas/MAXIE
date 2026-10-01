import unittest

from Voice.wake_word_engine import WakeWordEngine


class WakeWordEngineTest(unittest.TestCase):

    def setUp(self):
        self.detector = WakeWordEngine()

    def test_detects_phrase(self):
        self.assertTrue(self.detector.detect("hey maxie open chrome"))

    def test_case_insensitive(self):
        self.assertTrue(self.detector.detect("  HEY Maxie "))

    def test_rejects_other_audio(self):
        self.assertFalse(self.detector.detect("hey siri what time is it"))
        self.assertFalse(self.detector.detect("hello there"))


if __name__ == "__main__":
    unittest.main()