import unittest

from Brain.command_corrector import CommandCorrector


class CommandCorrectorTest(unittest.TestCase):

    def setUp(self):
        self.corrector = CommandCorrector()

    def test_time_phrases(self):
        for phrase in ("what time is it", "whats the time", "tell me the time"):
            self.assertEqual(self.corrector.correct(phrase), "time")

    def test_date_phrases(self):
        for phrase in ("what is the date", "today's date"):
            self.assertEqual(self.corrector.correct(phrase), "date")

    def test_weather_phrases(self):
        self.assertEqual(self.corrector.correct("what is the weather"), "weather")

    def test_misspelled_app_aliases(self):
        self.assertEqual(self.corrector.correct("open calculater"), "open calculator")
        self.assertEqual(self.corrector.correct("open braille"), "open brave")
        self.assertEqual(self.corrector.correct("until brave"), "open brave")

    def test_unknown_returns_cleaned_text(self):
        self.assertEqual(self.corrector.correct("Explain Python"), "explain python")

    def test_math_symbols_preserved(self):
        self.assertEqual(self.corrector.correct("What is 47 + 53?"), "what is 47 + 53")
        self.assertEqual(self.corrector.correct("12 * 8"), "12 * 8")
        self.assertEqual(self.corrector.correct("50 percent of 200"), "50 percent of 200")


if __name__ == "__main__":
    unittest.main()