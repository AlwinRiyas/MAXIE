import json
import math
import os
import re
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

        from Config.config import Config

        self._conversation_cap = int(
            Config.memory_config().get("conversation_cap", 500)
        )

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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
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
        """TD-40: update the value without silently reclassifying the kind."""
        key = key.strip().lower()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE memory SET value = ?, updated_at = ? WHERE key = ?",
                (value, datetime.now().isoformat(), key),
            )
        return cur.rowcount > 0

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
    def _tokenize(text):
        return re.findall(r"[a-z']+", text.lower())

    STOPWORDS = frozenset({
        "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
        "with", "about", "what", "when", "where", "which", "who", "whom",
        "how", "why", "do", "does", "did", "i", "me", "my", "mine", "you",
        "your", "yours", "we", "our", "ours", "they", "them", "their", "it",
        "its", "is", "are", "was", "were", "be", "been", "am", "tell", "the",
        "that", "this", "there", "here", "these", "those", "have", "has",
        "had", "not", "so", "just", "know",
    })

    @classmethod
    def _best_match(cls, key, rows):
        """Score each memory row by IDF-weighted word overlap.

        TD-19: substring matching with `len(w) > 2` admitted stopwords and
        matched mid-word ("cat" inside "catalog"), producing confident wrong
        answers. Word-boundary tokens, a stopword list, idf weighting, and a
        minimum score prevent that.
        """
        words = {w for w in cls._tokenize(key) if w not in cls.STOPWORDS}
        if not words:
            return None

        words = cls._expand_synonyms(words)

        n_rows = max(1, len(rows))
        document_frequency = {}
        for word in words:
            matches = 0
            for row in rows:
                hay = cls._hay(row)
                if re.search(rf"\b{re.escape(word)}\b", hay):
                    matches += 1
            document_frequency[word] = matches

        scored = []
        for row in rows:
            hay = cls._hay(row)
            score = 0.0
            for word in words:
                if re.search(rf"\b{re.escape(word)}\b", hay):
                    idf = math.log((n_rows + 1) / (document_frequency[word] + 1)) + 1
                    score += idf
            if score >= cls.MIN_SCORE:
                scored.append((score, row["key"], row["value"]))

        if not scored:
            return None

        scored.sort(key=lambda item: item[0], reverse=True)
        return {"key": scored[0][1], "value": scored[0][2],
                "score": scored[0][0]}

    MIN_SCORE = 1.0

    @staticmethod
    def _hay(row):
        return f"{row['key']} {row['value']}".lower()

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

    @staticmethod
    def _escape_like(term):
        """TD-18: '%' and '_' in the query must not act as wildcards."""
        return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def search(self, term):
        safe = self._escape_like(term.strip().lower())
        pattern = f"%{safe}%"
        cur = self._conn.execute(
            "SELECT key, value FROM memory "
            "WHERE key LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\' "
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
            self.prune_context()

    def prune_context(self, cap=None):
        """TD-11: bound the conversation table instead of growing forever."""
        if cap is None:
            cap = self._conversation_cap
        cap = max(1, int(cap))
        with self._conn:
            self._conn.execute(
                "DELETE FROM conversation WHERE id NOT IN ("
                "  SELECT id FROM conversation ORDER BY id DESC LIMIT ?"
                ")",
                (cap,),
            )

    def get_context(self, max_turns=10):
        cur = self._conn.execute(
            "SELECT role, text FROM conversation ORDER BY id ASC"
        )
        rows = cur.fetchall()
        if max_turns is None:
            max_turns = 10
        if max_turns <= 0:
            return []
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
        is lost.

        TD-12: boolean entries (legacy 'remember <sentence>' records) store
        the sentence itself as the value, never the literal string "True".
        Runs once per database: a meta-flag makes the migration one-shot so
        a rewritten live DB isn't re-imported from a stale JSON file.
        """
        import hashlib

        if not os.path.exists(json_path):
            return 0

        marker = "migrate_json:" + hashlib.sha1(
            os.path.abspath(json_path).encode("utf-8")
        ).hexdigest()
        if self._meta_get(marker):
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
            if not isinstance(key, str) or not key.strip():
                continue
            if isinstance(value, bool):
                # Legacy "remember <sentence>" records: the sentence is the
                # value, the fact is a note, and recall never says "True".
                self.save(key.strip(), key.strip(), kind="note")
                count += 1
            elif self.recall(key) is None:
                self.save(key, value, kind="fact")
                count += 1

        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (marker, datetime.now().isoformat()),
            )
        return count

    def _meta_get(self, key):
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


# Re-exported helper to satisfy any import style.
def get_database(path=None):
    return MemoryDatabase(path)