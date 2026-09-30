class Permissions:
    """Security boundary for skill execution (SEC-07: default-deny by
    capability, not by string matching).

    LLM output is never executed directly. Every action MAXIE takes
    goes through SkillManager, and only allowlisted intents can run
    (see ``ALLOWED``). Actions in ``DESTRUCTIVE`` are *confirmation
    gated by capability*: a new or renamed destructive intent cannot
    bypass the gate by omission because the gate asks ``requires_
    confirmation`` rather than matching a known-bad list, and intents
    missing from ``ALLOWED`` get no tool access at all.
    """

    ALLOWED = {
        "TIME", "DATE", "WEATHER", "OPEN_APP", "CLOSE_APP", "CALCULATE",
        "SEARCH", "VOLUME", "SYSTEM_INFO", "SAVE_MEMORY", "RECALL_MEMORY",
        "DELETE_MEMORY", "GREETING", "HELP", "SCREENSHOT", "AI_CHAT",
        "TODO_ADD", "TODO_LIST", "TODO_DONE", "TODO_REMOVE", "TODO_CLEAR",
        "MEDIA_NEXT", "MEDIA_PREVIOUS", "MEDIA_PLAY_PAUSE",
        "CALL_ANSWER", "CALL_REJECT",
        "YOUTUBE_SEARCH", "RECOMMEND",
        "SHUTDOWN", "RESTART",
    }

    # Capability bucket. Anything in here is destructive by nature and
    # always needs an explicit human "yes" before the router executes it.
    DESTRUCTIVE = frozenset({
        "SHUTDOWN", "RESTART", "FORMAT", "DELETE_MEMORY", "DELETE_MEMORY_BULK",
    })

    # Spoken words that express a bulk memory wipe ("delete all memories").
    BULK_DELETE_WORDS = frozenset({"all", "everything", "memories"})

    REQUIRES_CONFIRMATION = {
        "SHUTDOWN": "I won't shut down without your explicit confirmation.",
        "RESTART": "I won't restart without your explicit confirmation.",
        "DELETE_MEMORY": "I won't delete your memories without confirmation.",
        "DELETE_MEMORY_BULK": "I won't wipe ALL of your memories without confirmation.",
        "FORMAT": "I can't format drives. This is too destructive.",
    }

    @classmethod
    def can_execute(cls, intent):
        return intent in cls.ALLOWED

    @classmethod
    def requires_confirmation(cls, intent):
        """SEC-07: capability-keyed gate. True for every destructive
        intent; the router confirms first and never trusts the string."""
        return intent in cls.DESTRUCTIVE

    @classmethod
    def confirmation_for(cls, intent):
        if intent in cls.REQUIRES_CONFIRMATION:
            message = cls.REQUIRES_CONFIRMATION[intent]
            another = "confirm " + intent.replace("_", " ").lower()
            return f"{message} Say '{another}' to confirm."
        return None