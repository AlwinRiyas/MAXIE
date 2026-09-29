import os
import tempfile
import unittest
from unittest import mock

from Brain.brain_router import BrainRouter
from Memory.memory_database import MemoryDatabase
from Memory.memory_engine import MemoryEngine


def fresh_engine():
    path = os.path.join(tempfile.mkdtemp(), "maxie_learn_test.db")
    return MemoryEngine(MemoryDatabase(path)), path


class AutoLearnTest(unittest.TestCase):
    """Continuous learning: preferences are captured silently and recalled
    through synonym matching, and survive a restart of the memory store."""

    def router(self):
        router = BrainRouter()
        router.memory, self.db_path = fresh_engine()
        # The router falls through to the live Ollama client for phrases
        # that no skill handles. The suite must run headless and offline,
        # so replace the network hop with a canned conversational answer;
        # these tests assert on memory, not on the model reply.
        router.ai = mock.MagicMock()
        router.ai.ask.return_value = "Got it."
        return router

    def test_learns_preference_phrase(self):
        router = self.router()
        router.process("i like dark roast coffee")
        liked = router.memory.recall_any("what do i like")
        self.assertIsNotNone(liked)
        self.assertIn("dark roast coffee", liked)

    def test_learns_via_synonyms(self):
        router = self.router()
        router.process("i love mangoes")
        liked = router.memory.recall_any("what do i like")
        self.assertIsNotNone(liked)
        self.assertIn("mangoes", liked)

    def test_learns_loving_and_studying(self):
        router = self.router()
        router.process("i am learning netball")
        learned = router.memory.recall_any("what am I studying")
        self.assertIsNotNone(learned)
        self.assertIn("netball", learned)

    def test_commands_do_not_learn(self):
        router = self.router()
        engine = MemoryEngine(MemoryDatabase(self.db_path))
        before = len(engine.all())
        router.process("what is 47 plus 53")
        after = len(engine.all())
        self.assertEqual(before, after)

    def test_fact_survives_store_reopen(self):
        router = self.router()
        router.process("my favourite movie is interstellar")
        engine = MemoryEngine(MemoryDatabase(self.db_path))
        remembered = engine.recall_any("my favorite movie")
        self.assertIsNotNone(remembered)
        self.assertIn("interstellar", remembered)


class MemorySynonymRecallTest(unittest.TestCase):

    def test_synonym_matrix(self):
        engine, _ = fresh_engine()
        engine.remember_sentence("i love reading thrillers")
        self.assertIn("thrillers", engine.recall_any("what do I enjoy"))
        self.assertGreaterEqual(engine.recall_any("what do I prefer") is not None, True)

        engine2, _ = fresh_engine()
        engine2.remember_sentence("i watch cricket every night")
        self.assertIn("cricket", engine2.recall_any("what do i watch"))

    def test_remember_not_required(self):
        engine, _ = fresh_engine()
        engine.remember_sentence("i love reggae music")
        self.assertIn("reggae", engine.recall_any("what music do i listen to"))


if __name__ == "__main__":
    unittest.main()