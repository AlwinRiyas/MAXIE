"""Fold older conversation turns into one running summary (12.10).

Without this, a long conversation simply loses its old turns: `get_context`
returns the newest N rows and the rest of the thread is gone from the model's
point of view. With it, the model keeps a compressed version of what came
before, which is usually enough to resolve a follow-up like "and the other
one?".

Three rules make this safe to run unattended:

1. **Never lose the user's words silently.** If the model is unavailable or
   the summary comes back empty, the older rows are left exactly where they
   are. Truncation is the existing behaviour; this only ever *adds*
   continuity, it never trades it for failure.
2. **Summarise older rows only.** The most recent turns are never folded in,
   because the live window already carries them verbatim and a model
   summarising the present tense will happily lose a detail the user is about
   to refer back to.
3. **The summary is the assistant's own prior words.** It is stored with the
   `assistant` role and re-injected as such, so it can never arrive in the
   conversation looking like something the user just said.
"""

from Config.config import Config

SUMMARY_PREFIX = "Earlier in this conversation: "


class ContextSummariser:
    """Decide when to summarise, and summarise.

    Attributes:
        memory: a MemoryEngine (needs `db`, `context_size`,
            `get_summary`, `context_rows_before`, `save_summary`,
            `delete_context_before`).
        logger: the shared Logger.
    """

    def __init__(self, memory, logger=None):
        self.memory = memory
        self.logger = logger

    def _config(self):
        ai = Config.ai_config()
        return {
            # 0 disables summarisation entirely.
            "after_turns": int(ai.get("summarise_after_turns", 0) or 0),
            "keep_recent": int(ai.get("summarise_keep_recent", 4) or 4),
            "max_chars": int(ai.get("summary_max_chars", 600) or 600),
        }

    def due(self):
        """Whether the stored context is long enough to be worth folding.

        Returns ``None`` when summarisation is off, has already covered
        everything old enough to fold, or when there is nothing to fold.
        """
        settings = self._config()
        if settings["after_turns"] <= 0:
            return None

        _existing, summarised_through = self.memory.db.get_summary()
        newest = self.memory.db.newest_context_id()
        pending = [row for row in
                   self.memory.db.context_rows_before(newest + 1)
                   if row[0] > summarised_through]
        if len(pending) < settings["after_turns"]:
            return None

        foldable = len(pending) - settings["keep_recent"]
        if foldable <= 0:
            return None

        boundary = pending[foldable - 1][0]
        return boundary, pending[:foldable]

    def summarise(self, summarise_fn):
        """Fold the foldable rows into the stored summary.

        Args:
            summarise_fn: ``(transcript) -> text``. Usually the model. It is
                called at most once and its failure is contained: any
                exception, empty string, or over-long result leaves the rows
                untouched.

        Returns the new summary text, or None when nothing was folded.
        """
        due = self.due()
        if due is None:
            return None
        boundary, rows = due

        transcript = "\n".join(
            f"{role}: {text}" for _id, role, text in rows)
        settings = self._config()
        try:
            summary = summarise_fn(transcript)
        except Exception as error:  # noqa: BLE001 - never break a turn
            self._log(f"Summarisation skipped: {error}")
            return None

        if not summary or not summary.strip():
            self._log("Summarisation produced nothing; rows kept")
            return None

        summary = summary.strip()
        if len(summary) > settings["max_chars"]:
            summary = summary[:settings["max_chars"]].rstrip() + "..."

        existing, summarised_through = self.memory.db.get_summary()
        if existing and summarised_through:
            # Fold the previous summary in, so the thread stays whole
            # across several summarisations.
            summary = f"{existing} {summary}".strip()
            if len(summary) > settings["max_chars"]:
                summary = summary[-settings["max_chars"]:].strip()

        self.memory.db.save_summary(summary, boundary)
        self.memory.db.delete_context_before(boundary + 1)
        self._log(f"Context summarised through row {boundary} "
                  f"({len(rows)} rows folded)")
        return summary

    def _log(self, message):
        if self.logger is not None:
            self.logger.info(f"Context summary: {message}")


__all__ = ["ContextSummariser", "SUMMARY_PREFIX"]
