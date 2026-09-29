from Skills.skill_manager import SkillManager


class CommandEngine:
    """Intent-based command dispatcher.

    ``execute(intent, value, text)`` passes work to the allowlisted
    SkillManager. Backward-compatible canonical-string calls are also
    supported via ``execute_text``.
    """

    def __init__(self, skill_manager=None):
        self.skills = skill_manager if skill_manager is not None else SkillManager()

    def execute(self, intent, value="", text=None):
        return self.skills.execute(intent, value or "", extra=text or value)

    def execute_text(self, command):
        """Handle a canonical command string like 'time' / 'open brave'."""
        from Brain.intent_engine import IntentEngine

        command = command.lower().strip()
        intent = IntentEngine().classify(command)
        value = self._extract(command, intent)
        return self.execute(intent, value, command)

    @staticmethod
    def _extract(command, intent):
        verbs = {
            "OPEN_APP": ("open ", "launch ", "start ", "run "),
            "CLOSE_APP": ("close ", "kill ", "quit ", "exit app "),
            "SEARCH": ("search for ", "search ", "look up ", "google "),
        }
        if intent in verbs:
            for verb in verbs[intent]:
                if command.startswith(verb):
                    return command[len(verb):].strip()
            return command.strip()
        return command.strip()