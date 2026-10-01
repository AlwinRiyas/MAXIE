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
        try:
            os.remove(os.path.join(self.tmp, "memory.json"))
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

    def test_search_escapes_like_metacharacters(self):
        """TD-18: '%' and '_' in a query are literal, not wildcards."""
        db = MemoryDatabase(self.db_path)
        db.save("progress", "50% complete")
        db.save("plain", "hello")
        self.assertEqual(len(db.search("%")), 1, "only literal % should match")
        self.assertEqual(len(db.search("_")), 0, "_ must not be a wildcard")
        db.close()

    def test_context_turns(self):
        db = MemoryDatabase(self.db_path)
        for i in range(5):
            db.add_context("user", f"msg {i}")
        self.assertEqual(len(db.get_context(max_turns=2)), 2)
        db.clear_context()
        self.assertEqual(db.get_context(), [])
        db.close()

    def test_context_zero_turns_returns_nothing(self):
        """TD-11: max_turns=0 must not return the entire table."""
        db = MemoryDatabase(self.db_path)
        for i in range(5):
            db.add_context("user", f"msg {i}")
        self.assertEqual(db.get_context(max_turns=0), [])
        db.close()

    def test_context_never_grows_past_cap(self):
        """TD-11: the conversation table is bounded by a retention sweep."""
        db = MemoryDatabase(self.db_path)
        db._conversation_cap = 3
        for i in range(10):
            db.add_context("user", f"msg {i}")
        remaining = db.get_context()
        self.assertEqual(len(remaining), 3)
        self.assertEqual(remaining[-1][1], "msg 9", "keep the newest rows")
        db.close()

    def test_migrate_json_bool_entries_store_value_not_True(self):
        """TD-12: boolean legacy entries keep their text, not 'True'."""
        db = MemoryDatabase(self.db_path)
        legacy = os.path.join(self.tmp, "memory.json")
        with open(legacy, "w", encoding="utf-8") as f:
            import json

            json.dump({"remember that I love tea": True}, f)

        migrated = db.migrate_json(legacy)
        self.assertEqual(migrated, 1)
        self.assertNotEqual(db.recall("remember that I love tea"), "True")

        # Second run: the migration marker makes it one-shot (TD-12).
        db2 = MemoryDatabase(self.db_path)
        self.assertEqual(db2.migrate_json(legacy), 0)
        db.close()
        db2.close()

    def test_update_preserves_kind(self):
        """TD-40: updating a note must not silently rename it to a fact."""
        db = MemoryDatabase(self.db_path)
        db.save("todo", "buy milk", kind="note")
        db.update("todo", "buy oat milk")
        row = db._conn.execute(
            "SELECT value, kind FROM memory WHERE key = ?", ("todo",)
        ).fetchone()
        self.assertEqual(row["value"], "buy oat milk")
        self.assertEqual(row["kind"], "note")
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


class MemoryRecallQualityTest(MemoryTestBase):
    """TD-19: recall must not produce confident wrong answers."""

    def test_stopword_only_query_returns_none(self):
        db = MemoryDatabase(self.db_path)
        db.save("college", "Loyola Institute of Technology")
        result = db.any_recall("tell me about the the")
        self.assertIsNone(
            result,
            "a query with only stopwords must not recall a memory",
        )

    def test_word_boundary_prevents_substring_mismatch(self):
        db = MemoryDatabase(self.db_path)
        db.save("brand", "Coca Cola sells cola")
        db.save("notes", "educational catalog for art")
        self.assertIsNotNone(db.any_recall("cola"))
        # "cat" is a substring of "catalog" but not a standalone word.
        self.assertIsNone(
            db.any_recall("cat"),
            "word-boundary matching must not match 'cat' inside 'catalog'",
        )

    def test_concurrent_writes_do_not_lose_rows(self):
        """Four threads inserting both conversation rows and memories must
        not interleave the single SQLite connection.

        The previous implementation had `check_same_thread=False` but no
        lock; with concurrent `add_context` + `prune_context` it lost ~70% of
        rows and raised `InterfaceError`s. That is the exact regression this
        test prevents.
        """
        import threading

        db = MemoryDatabase(self.db_path)
        n_threads, n_rounds = 4, 25

        errors = []

        def run(thread_id):
            try:
                for i in range(n_rounds):
                    db.add_context("user", f"t{thread_id}-{i}")
                    db.save(f"k{thread_id}-{i}", f"v{thread_id}-{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = []
        for tid in range(n_threads):
            threads.append(threading.Thread(target=run, args=(tid,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = n_threads * n_rounds
        self.assertEqual(errors, [], "no database errors under concurrency")
        self.assertEqual(db.context_size(), expected)
        self.assertEqual(db.count(), expected)
        self.assertEqual(db.recall("k3-24"), "v3-24")
        ctx = db.get_context(expected)
        texts = [text for _, text in ctx]
        self.assertIn("t0-0", texts)
        self.assertIn(f"t{n_threads - 1}-{n_rounds - 1}", texts)


if __name__ == "__main__":
    unittest.main()