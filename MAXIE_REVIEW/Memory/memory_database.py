import json
import os
import sqlite3
from datetime import datetime


class MemoryDatabase:
    """SQLite persistence layer for MAXIE.

    Tables:
      memory(key TEXT PRIMARY KEY, value TEXT, kind TEXT, updated_at TEXT)
      conversation(id INTEGER PRIMARY KEY, role TEXT, text TEXT, created_at TEXT)
    """

    def __init__(self, db_path=None):
        if db_path is None:
            from Config.config import Config

            db_path = Config.resolve("Memory/maxie_memory.db")

        directory = os.path.dirname(db_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'fact',
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def close(self):
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    # ----------------------------------------------------------
    # Memory CRUD
    # ----------------------------------------------------------

    def save(self, key, value, kind="fact"):
        key = key.strip().lower()
        stamp = datetime.now().isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO memory (key, value, kind, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    kind = excluded.kind,
                    updated_at = excluded.updated_at
                """,
                (key, value, kind, stamp),
            )

    def update(self, key, value):
        self.save(key, value)

    def recall(self, key):
        cur = self._conn.execute(
            "SELECT value FROM memory WHERE key = ?",
            (key.lower().strip(),),
        )
        row = cur.fetchone()
        return row["value"] if row else None

    def any_recall(self, key):
        """Exact match fallback: return any memory whose key or value
        overlaps with keywords from the query."""
        cur = self._conn.execute(
            "SELECT key, value FROM memory ORDER BY updated_at DESC"
        )
        rows = cur.fetchall()
        if not rows:
            return None
        return self._best_match(key, rows)

    @staticmethod
    def _best_match(key, rows):
        words = {w for w in key.lower().replace("?", " ").split() if len(w) > 2}
        if not words:
            return None

        words = MemoryDatabase._expand_synonyms(words)

        scored = []
        for row in rows:
            hay = f"{row['key']} {row['value']}".lower()
            score = sum(1 for w in words if w in hay)
            if score:
                scored.append((score, row["key"], row["value"]))

        if not scored:
            return None

        scored.sort(key=lambda item: item[0], reverse=True)
        return {"key": scored[0][1], "value": scored[0][2],
                "score": scored[0][0]}

    SYNONYM_CLUSTERS = [
        {"like", "love", "adore", "enjoy", "prefer", "favorite",
         "favourite"},
        {"watch", "watching", "watchlist", "series", "show", "movie",
         "film"},
        {"listen", "listening", "music", "song", "songs", "playlist"},
        {"learn", "learning", "study", "studying", "course"},
        {"play", "playing", "game", "games"},
    ]

    # Word -> every word in the same cluster, so "enjoy" and "study"
    # recall the same facts as "like" and "learning".
    SYNONYMS = {
        word: cluster
        for cluster in SYNONYM_CLUSTERS
        for word in cluster
    }

    @classmethod
    def _expand_synonyms(cls, words):
        expanded = set(words)
        for word in words:
            expanded.update(cls.SYNONYMS.get(word, ()))
        return expanded

    def search(self, term):
        pattern = f"%{term.strip().lower()}%"
        cur = self._conn.execute(
            "SELECT key, value FROM memory "
            "WHERE key LIKE ? OR value LIKE ? "
            "ORDER BY updated_at DESC",
            (pattern, pattern),
        )
        return [{"key": r["key"], "value": r["value"]} for r in cur.fetchall()]

    def delete(self, key):
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM memory WHERE key = ?", (key.lower().strip(),)
            )
            return cur.rowcount > 0

    def all_memories(self):
        cur = self._conn.execute(
            "SELECT key, value FROM memory ORDER BY updated_at DESC"
        )
        return [{"key": r["key"], "value": r["value"]} for r in cur.fetchall()]

    def count(self):
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM memory")
        return cur.fetchone()["c"]

    # ----------------------------------------------------------
    # Short-term conversation context
    # ----------------------------------------------------------

    def add_context(self, role, text):
        stamp = datetime.now().isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT INTO conversation (role, text, created_at) "
                "VALUES (?, ?, ?)",
                (role, text, stamp),
            )

    def get_context(self, max_turns=10):
        cur = self._conn.execute(
            "SELECT role, text FROM conversation ORDER BY id ASC"
        )
        rows = cur.fetchall()
        if max_turns:
            rows = rows[-max_turns:]
        return [(r["role"], r["text"]) for r in rows]

    def clear_context(self):
        with self._conn:
            self._conn.execute("DELETE FROM conversation")

    # ----------------------------------------------------------
    # Migration from the legacy JSON store
    # ----------------------------------------------------------

    def migrate_json(self, json_path):
        """Import any existing Memory/memory.json entries so no user data
        is lost. Boolean entries (legacy 'remember <sentence>' records)
        become free-form notes."""
        if not os.path.exists(json_path):
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return 0

        if not isinstance(data, dict):
            return 0

        count = 0
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            kind = "note" if isinstance(value, bool) else "fact"
            if self.recall(key) is None:
                self.save(key, str(value), kind)
                count += 1
        return count


# Re-exported helper to satisfy any import style.
def get_database(path=None):
    return MemoryDatabase(path)