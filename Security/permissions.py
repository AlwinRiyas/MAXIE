class Permissions:
    """Security boundary for skill execution.

    LLM output is never executed directly. Every action MAXIE takes
    goes through SkillManager, and only allowlisted intents can run
    (see ``ALLOWED``). Actions in ``REQUIRES_CONFIRMATION`` are reported
    back to the user instead of being executed.
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

    REQUIRES_CONFIRMATION = {
        "SHUTDOWN": "I won't shut down without your explicit confirmation.",
        "RESTART": "I won't restart without your explicit confirmation.",
        "DELETE_MEMORY": "I won't delete your memories without confirmation.",
        "FORMAT": "I can't format drives. This is too destructive.",
    }

    @classmethod
    def can_execute(cls, intent):
        return intent in cls.ALLOWED

    @classmethod
    def confirmation_for(cls, intent):
        if intent in cls.REQUIRES_CONFIRMATION:
            message = cls.REQUIRES_CONFIRMATION[intent]
            another = "confirm " + intent.replace("_", " ").lower()
            return f"{message} Say '{another}' to confirm."
        return None