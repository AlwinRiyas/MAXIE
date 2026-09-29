import unittest

from Skills.calculator import CalculatorSkill


class CalculatorSkillTest(unittest.TestCase):

    def setUp(self):
        self.calc = CalculatorSkill()

    def test_basic_arithmetic(self):
        self.assertEqual(self.calc.execute("2 + 2"), "The answer is 4.")

    def test_spoken_words(self):
        self.assertEqual(self.calc.execute("ten plus five"), "The answer is 15.")
        self.assertEqual(self.calc.execute("what is 12 times 8"), "The answer is 96.")

    def test_functions(self):
        self.assertEqual(self.calc.execute("square root of 16"), "The answer is 4.")
        self.assertEqual(self.calc.execute("3 squared"), "The answer is 9.")

    def test_power_and_divide(self):
        self.assertEqual(self.calc.execute("2 to the power of 10"), "The answer is 1024.")
        self.assertEqual(self.calc.execute("what is 20 divided by 4"), "The answer is 5.")

    def test_division_by_zero_is_safe(self):
        response = self.calc.execute("1 divided by 0")
        self.assertIn("isn't possible", response)

    def test_unsafe_code_never_evaluates(self):
        response = self.calc.execute("import os")
        self.assertIn("couldn't", response)

    def test_empty_guard(self):
        response = self.calc.execute("")
        self.assertIn("couldn't", response.lower())


if __name__ == "__main__":
    unittest.main()