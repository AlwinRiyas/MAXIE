"""Runtime voice-command gate for the ConversationEngine.

MAXIE must react to "stop" and "exit/goodbye" the instant they are
heard (or typed, or pushed from the phone). These helpers are the
single source of truth for those phrases so the barge-in listener and
the conversation loop never disagree.
"""


class VoiceCommands:
    """Phrase matching for stop/interrupt and exit/shutdown commands."""

    STOP_PHRASES = {
        "stop",
        "stop stop",
        "stop it",
        "stop now",
        "stop speaking",
        "shut up",
        "shut up stop",
        "be quiet",
        "quiet",
        "quiet stop",
        "enough",
        "cancel",
        "that's enough",
        "that is enough",
    }

    EXIT_PHRASES = {
        "exit",
        "quit",
        "close",
        "goodbye",
        "good bye",
        "bye",
        "exit maxie",
        "close maxie",
        "quit maxie",
        "shutdown maxie",
        "goodbye maxie",
        "bye maxie",
        "go offline",
    }

    def _normalize(self, text):
        text = (text or "").lower().strip()
        for char in (".", ",", "!", "?", "'", '"'):
            text = text.replace(char, "")
        return " ".join(text.split())

    def is_stop(self, text):
        """True for short interrupt phrases ("stop", "be quiet", ...)."""
        normalized = self._normalize(text)
        if not normalized:
            return False

        if normalized in self.STOP_PHRASES:
            return True

        # "stop stop stop ..." is still a stop.
        words = normalized.split()
        return all(word in ("stop", "quiet") for word in words)

    def leads_stop(self, text):
        """TD-30: True when the utterance *begins* with a stop phrase.

        'stop, actually what time is it' leads with 'stop' and must
        interrupt, even though the whole sentence is not a pure stop
        phrase and is longer than MAXIE's own-speech gate.
        """
        normalized = self._normalize(text)
        if not normalized:
            return False
        for phrase in self.STOP_PHRASES:
            if normalized == phrase or normalized.startswith(phrase + " "):
                return True
        return False

    def is_exit(self, text):
        """True for exit/shutdown phrases ("exit", "goodbye", ...)."""
        return self._normalize(text) in self.EXIT_PHRASES