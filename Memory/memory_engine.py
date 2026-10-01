from Memory.memory_database import MemoryDatabase
from Memory.context_summariser import SUMMARY_PREFIX


class MemoryEngine:
    """High-level memory service used by the Brain.

    Backward-compatible ``save``/``recall`` signatures are preserved
    while adding search/delete/update and short-term context.
    """

    def __init__(self, database=None):
        from Config.config import Config

        if database is None:
            db_path = Config.resolve("Memory/maxie_memory.db")
            database = MemoryDatabase(db_path)

        self.db = database

        legacy = Config.resolve("Memory/memory.json")
        self.db.migrate_json(legacy)

    # ----------------------------------------------------------
    # Long-term memory
    # ----------------------------------------------------------

    def save(self, key, value, kind="fact"):
        return self.db.save(key, value, kind)

    def update(self, key, value):
        """TD-40: update preserves the existing kind."""
        return self.db.update(key, value)

    def recall(self, key):
        return self.db.recall(key)

    def recall_any(self, prompt):
        result = self.db.any_recall(prompt)
        return result["value"] if result else None

    def search(self, term):
        return self.db.search(term)

    def delete(self, key):
        if self.db.delete(key):
            return True
        match = self.db.any_recall(key)
        if match:
            return self.db.delete(match["key"])
        return False

    def all(self):
        return self.db.all_memories()

    def remember_sentence(self, sentence):
        """Store a free-form remembered fact.

        'remember that I am learning cybersecurity' is split into a
        concise key + full value so it can be retrieved with a
        follow-up question like 'what am I learning'.
        """
        sentence = sentence.strip().lstrip(".,!? ").lower()

        prefixes = ["remember that", "remember"]
        for p in prefixes:
            if sentence.startswith(p):
                sentence = sentence[len(p):].strip()
                break
        if not sentence:
            return False

        words = [w for w in sentence.split() if w not in {"i", "am", "that"}]
        base = " ".join(words[:5]).strip(" .") or sentence

        # TD-41: first-5-words keys collide ("i like coffee a lot" vs
        # "i like coffee a little"), so disambiguate with a stable content
        # hash. The key stays human-readable; collisions become unique.
        import hashlib

        digest = hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:8]
        key = f"{base} #{digest}"
        self.db.save(key, sentence, kind="note")
        return True

    def recall_for(self, prompt, top=3):
        """Return memory lines relevant to the prompt (word overlap)."""
        lines = []
        for entry in self.all():
            hay = f"{entry['key']} {entry['value']}".lower()
            words = {
                w for w in prompt.lower().replace("?", " ").split()
                if len(w) > 2
            }
            score = sum(1 for w in words if w in hay)
            if score > 0:
                lines.append((score, entry["value"]))
        lines.sort(key=lambda item: item[0], reverse=True)
        return [value for score, value in lines[:top]]

    # ----------------------------------------------------------
    # Short-term context
    # ----------------------------------------------------------

    def add_context(self, role, text):
        self.db.add_context(role, text)

    def get_context(self, max_turns=None):
        """The live window, prefixed by the running summary (12.10).

        The summary is stored with the `assistant` role: it is the
        assistant's own compressed record of earlier turns, so re-injecting
        it can never present the user's words back to the model as if they
        had just been said.
        """
        from Config.config import Config

        if max_turns is None:
            max_turns = Config.ai_config().get("context_turns", 6)
        rows = self.db.get_context(max_turns)
        summary, _through = self.db.get_summary()
        if summary:
            rows = [("assistant", f"{SUMMARY_PREFIX}{summary}")] + rows
        return rows

    def summariser(self, logger=None):
        """A ContextSummariser over this engine's store."""
        from Memory.context_summariser import ContextSummariser

        return ContextSummariser(self, logger)

    def clear_context(self):
        self.db.clear_context()

    def close(self):
        self.db.close()