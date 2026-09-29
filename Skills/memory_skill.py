from Memory.memory_engine import MemoryEngine


class MemorySkill:
    """Voice-friendly wrappers over MemoryEngine for the router."""

    def __init__(self, engine=None):
        self.engine = engine if engine is not None else MemoryEngine()

    def save_sentence(self, sentence):
        ok = self.engine.remember_sentence(sentence)
        if not ok:
            return "I couldn't store that memory."
        return "Okay, I'll remember that."

    def recall(self, prompt):
        direct = self.engine.recall_any(prompt)
        if direct:
            return f"Here's what I remember: {direct}."
        related = self.engine.recall_for(prompt)
        if related:
            return "I remember that " + "; also ".join(related) + "."
        return "I don't have a memory about that yet."

    def recall_all(self):
        memories = self.engine.all()
        if not memories:
            return "I don't have any memories stored yet."
        lines = [f"{m['key']}: {m['value']}" for m in memories]
        return "I remember: " + "; ".join(lines)

    def delete(self, key):
        key = (key or "").strip().lower()
        if not key or key in ("all", "everything", "memories", "my memory"):
            return self.delete_all()
        if self.engine.delete(key):
            return f"Forgotten '{key}'."
        return f"I don't have '{key}' in my memory."

    def delete_all(self):
        count = 0
        for entry in self.engine.all():
            if self.engine.delete(entry["key"]):
                count += 1
        return "All memories cleared." if count else "There was nothing to clear."