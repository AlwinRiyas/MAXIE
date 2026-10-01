import os
import tempfile
import unittest

from Brain.intent_engine import IntentEngine
from Skills.media_controller import MediaSkill
from Skills.phone_controller import PhoneController
from Skills.power_skill import PowerSkill
from Skills.recommendation_skill import RecommendationSkill
from Skills.todo_skill import TodoListSkill
from Skills.youtube_skill import YouTubeSkill


class IntentMapTest(unittest.TestCase):
    """New-generation intent routing table."""

    def setUp(self):
        self.engine = IntentEngine()

    def check(self, cases):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.engine.classify(text), expected)

    def test_todo_intents(self):
        self.check([
            ("add buy milk to my list", "TODO_ADD"),
            ("remind me to call mom", "TODO_ADD"),
            ("add task fix router", "TODO_ADD"),
            ("show my todo list", "TODO_LIST"),
            ("what's on my to-do list", "TODO_LIST"),
            ("mark walk the dog as done", "TODO_DONE"),
            ("complete task 2", "TODO_DONE"),
            ("remove walk the dog from my list", "TODO_REMOVE"),
            ("delete task 3", "TODO_REMOVE"),
            ("clear my todo list", "TODO_CLEAR"),
            ("what do i have on my list", "TODO_LIST"),
        ])

    def test_media_intents(self):
        self.check([
            ("next song", "MEDIA_NEXT"),
            ("skip this song", "MEDIA_NEXT"),
            ("change the song", "MEDIA_NEXT"),
            ("previous track", "MEDIA_PREVIOUS"),
            ("play some music", "MEDIA_PLAY_PAUSE"),
            ("resume music", "MEDIA_PLAY_PAUSE"),
            ("pause the music", "MEDIA_PLAY_PAUSE"),
        ])

    def test_call_intents(self):
        self.check([
            ("answer the call", "CALL_ANSWER"),
            ("attend the phone", "CALL_ANSWER"),
            ("reject the call", "CALL_REJECT"),
            ("hang up the phone", "CALL_REJECT"),
        ])

    def test_recommend_intents(self):
        self.check([
            ("recommend a movie", "RECOMMEND"),
            ("recommend me something", "RECOMMEND"),
            ("give me a match", "RECOMMEND"),
            ("what should i watch", "RECOMMEND"),
        ])

    def test_youtube_intents(self):
        self.check([
            ("open youtube", "OPEN_APP"),
            ("open youtube and search funny cats", "YOUTUBE_SEARCH"),
            ("search python on youtube", "YOUTUBE_SEARCH"),
            ("play shape of you", "YOUTUBE_SEARCH"),
            ("play minecraft", "UNKNOWN"),
        ])

    def test_power_intents(self):
        self.check([
            ("shut down the laptop", "SHUTDOWN"),
            ("shutdown the pc", "SHUTDOWN"),
            ("restart the laptop", "RESTART"),
            ("reboot", "RESTART"),
        ])


class TodoListSkillTest(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(
            tempfile.gettempdir(), "maxie_todos_test.json"
        )
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.skill = TodoListSkill(path=self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_add_show_done_remove(self):
        self.assertIn("empty", self.skill.show())
        self.assertIn("buy milk", self.skill.add("add buy milk to my list"))
        self.assertIn("walk the dog", self.skill.add("add walk the dog"))
        listed = self.skill.show()
        self.assertIn("buy milk", listed)
        self.assertIn("walk the dog", listed)
        self.assertIn("Marked 'walk the dog' as done", self.skill.done("mark walk the dog as done"))
        self.assertIn("[x] walk the dog", self.skill.show())
        self.assertIn("Removed 'walk the dog'", self.skill.remove("remove walk the dog"))

    def test_clear(self):
        self.skill.add("add buy milk to my list")
        self.assertIn("Cleared", self.skill.clear("clear my todo list"))
        self.assertIn("empty", self.skill.show())

    def test_done_by_number_and_ordinal(self):
        self.skill.add("add buy milk")
        self.skill.add("add walk the dog")
        self.assertIn("Marked 'buy milk' as done", self.skill.done("mark task 1 as done"))
        self.assertIn("Marked 'walk the dog' as done", self.skill.done("mark the second task done"))

    def test_remind_me_form(self):
        self.assertIn("call mom", self.skill.add("remind me to call mom"))


class MediaSkillTest(unittest.TestCase):

    def test_interpret(self):
        self.assertEqual(MediaSkill._interpret("next song"), "next")
        self.assertEqual(MediaSkill._interpret("skip this track"), "next")
        self.assertEqual(MediaSkill._interpret("change the song"), "next")
        self.assertEqual(MediaSkill._interpret("previous track"), "previous")
        self.assertEqual(MediaSkill._interpret("go back a song"), "previous")
        self.assertEqual(MediaSkill._interpret("stop the music"), "stop")
        self.assertEqual(MediaSkill._interpret("pause music"), "play_pause")
        self.assertEqual(MediaSkill._interpret("resume"), "play_pause")
        self.assertIsNone(MediaSkill._interpret("hello"))


class PhoneControllerTest(unittest.TestCase):

    def test_graceful_when_no_device(self):
        controller = PhoneController()
        message = controller.answer()
        self.assertIsInstance(message, str)
        self.assertTrue(message)

    def test_reject_graceful_when_no_device(self):
        controller = PhoneController()
        message = controller.reject()
        self.assertIsInstance(message, str)
        self.assertTrue(message)


class PowerSkillTest(unittest.TestCase):

    def test_returns_message_not_crash(self):
        skill = PowerSkill()
        self.assertIn("won't", skill.shutdown())
        self.assertIn("won't", skill.restart())


class YouTubeSkillTest(unittest.TestCase):

    def test_build_url(self):
        self.assertEqual(
            YouTubeSkill.build_url("funny cat videos"),
            "https://www.youtube.com/results?search_query=funny%20cat%20videos",
        )
        self.assertEqual(YouTubeSkill.build_url("  "), YouTubeSkill.BASE)


class RecommendationSkillTest(unittest.TestCase):

    def setUp(self):
        self.skill = RecommendationSkill()

    def test_category_picks(self):
        movie = self.skill.recommend("recommend a movie")
        self.assertTrue(any(title in movie for title, _ in self.skill.CATALOG["movie"]))
        music = self.skill.recommend("recommend a song")
        self.assertTrue(any(title in music for title, _ in self.skill.CATALOG["music"]))

    def test_anything_pick(self):
        result = self.skill.recommend("give me a match")
        all_titles = [t for items in self.skill.CATALOG.values() for t, _ in items]
        self.assertTrue(any(title in result for title in all_titles))


if __name__ == "__main__":
    unittest.main()