import os
import tempfile
import unittest

from Memory.memory_database import MemoryDatabase
from Memory.memory_engine import MemoryEngine


class MemoryTestBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maxie_mem_")
        self.db_path = os.path.join(self.tmp, "test.db")

    def tearDown(self):
        for name in (self.db_path, self.db_path + "-wal", self.db_path + "-shm"):
            try:
                os.remove(name)
            except OSError:
                pass
        os.rmdir(self.tmp)


class MemoryDatabaseTest(MemoryTestBase):

    def test_save_and_recall(self):
        db = MemoryDatabase(self.db_path)
        db.save("gym", "6 PM")
        self.assertEqual(db.recall("gym"), "6 PM")
        db.close()

    def test_update_overwrites(self):
        db = MemoryDatabase(self.db_path)
        db.save("gym", "6 PM")
        db.save("gym", "7 PM")
        self.assertEqual(db.recall("gym"), "7 PM")
        db.close()

    def test_delete(self):
        db = MemoryDatabase(self.db_path)
        db.save("color", "blue")
        self.assertTrue(db.delete("color"))
        self.assertFalse(db.delete("color"))
        self.assertIsNone(db.recall("color"))
        db.close()

    def test_search_like(self):
        db = MemoryDatabase(self.db_path)
        db.save("project", "MAXIE assistant")
        db.save("hobby", "cybersecurity")
        results = db.search("cyber")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], "cybersecurity")
        db.close()

    def test_context_turns(self):
        db = MemoryDatabase(self.db_path)
        for i in range(5):
            db.add_context("user", f"msg {i}")
        self.assertEqual(len(db.get_context(max_turns=2)), 2)
        db.clear_context()
        self.assertEqual(db.get_context(), [])
        db.close()


class MemoryEngineTest(MemoryTestBase):

    def test_memory_engine_recall_and_forget(self):
        db = MemoryDatabase(self.db_path)
        engine = MemoryEngine(database=db)

        engine.save("gym", "6 PM")
        self.assertEqual(engine.recall("gym"), "6 PM")

        self.assertTrue(engine.remember_sentence("remember that I like coffee"))
        self.assertIsNotNone(engine.recall_any("coffee"))

        self.assertTrue(engine.delete("gym"))
        self.assertIsNone(engine.recall("gym"))
        engine.close()

    def test_remember_sentence_strips_prefix(self):
        db = MemoryDatabase(self.db_path)
        engine = MemoryEngine(database=db)
        engine.remember_sentence("remember that I am learning cybersecurity")
        values = [m["value"] for m in engine.all()]
        self.assertTrue(any("cybersecurity" in v for v in values))
        engine.close()


if __name__ == "__main__":
    unittest.main()