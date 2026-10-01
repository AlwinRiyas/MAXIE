import unittest

from Brain.voice_commands import VoiceCommands


class VoiceCommandsTest(unittest.TestCase):

    def setUp(self):
        self.cmds = VoiceCommands()

    def test_stop_phrases(self):
        for phrase in ("stop", "stop stop", "be quiet", "shut up",
                       "enough", "cancel", "quiet"):
            self.assertTrue(self.cmds.is_stop(phrase), phrase)

    def test_non_stop_sentences(self):
        for phrase in ("tell me about stop signs", "what time is it",
                       "explain how to stop a process"):
            self.assertFalse(self.cmds.is_stop(phrase), phrase)

    def test_exit_phrases(self):
        for phrase in ("exit", "quit", "goodbye", "bye", "goodbye maxie",
                       "exit maxie", "close maxie"):
            self.assertTrue(self.cmds.is_exit(phrase), phrase)

    def test_non_exit_phrases(self):
        for phrase in ("what time is it", "open chrome"):
            self.assertFalse(self.cmds.is_exit(phrase), phrase)

    def test_punctuation_ignored(self):
        self.assertTrue(self.cmds.is_stop("stop."))
        self.assertTrue(self.cmds.is_exit("Goodbye!"))


if __name__ == "__main__":
    unittest.main()