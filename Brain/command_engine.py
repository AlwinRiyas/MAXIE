from Brain.command_parser import CommandParser
from Brain.intent_detector import IntentDetector
from Skills.skill_manager import SkillManager


class CommandEngine:

    def __init__(self):

        self.parser = CommandParser()
        self.intent = IntentDetector()
        self.skills = SkillManager()

    def normalize(self, command):

        command = command.lower().strip()

        # Remove punctuation
        for char in [".", ",", "!", "?", "'"]:
            command = command.replace(char, "")

        # Common Whisper variations
        replacements = {
            "calculated": "calculator",
            "calculate": "calculator",
            "calculater": "calculator",
            "calclator": "calculator",
            "braille": "brave",
            "brave browser": "brave",
            "the calculator": "calculator",
            "the brave": "brave",
        }

        for wrong, correct in replacements.items():

            command = command.replace(
                wrong,
                correct
            )

        # Remove conversational prefixes
        prefixes = [
            "can you ",
            "could you ",
            "would you ",
            "please ",
            "i want to ",
            "i need to ",
            "help me ",
            "the ",
        ]

        for prefix in prefixes:

            if command.startswith(prefix):

                command = command[len(prefix):]

        # Command verbs
        verbs = [
            "open ",
            "launch ",
            "start ",
            "run ",
        ]

        for verb in verbs:

            if command.startswith(verb):

                command = command[len(verb):]

                break

        return command.strip()

    def execute(self, command):

        original = command

        command = self.normalize(command)

        # Direct application aliases
        aliases = {
            "calculator": "calculator",
            "calc": "calculator",
            "brave": "brave",
            "notepad": "notepad",
            "paint": "paint",
            "android studio": "android studio",
        }

        if command in aliases:

            return self.skills.execute(
                "OPEN_APP",
                aliases[command]
            )

        # Normal intent detection
        parsed = self.parser.parse(original)

        intent = self.intent.detect(parsed)

        if intent == "OPEN_APP":

            return self.skills.execute(
                intent,
                command
            )

        elif intent == "SEARCH":

            return "Search System is under development."

        elif intent == "SHUTDOWN":

            return "Shutdown requires confirmation."

        elif intent == "RESTART":

            return "Restart requires confirmation."

        return "Sorry, I don't understand that command."