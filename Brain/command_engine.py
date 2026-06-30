from Brain.command_parser import CommandParser
from Brain.intent_detector import IntentDetector
from Skills.skill_manager import SkillManager


class CommandEngine:

    def __init__(self):

        self.parser = CommandParser()

        self.intent = IntentDetector()

        self.skills = SkillManager()

    def execute(self, command):

        command = self.parser.parse(command)

        intent = self.intent.detect(command)

        if intent == "OPEN_APP":

            app = command.replace("open", "").strip()

            return self.skills.execute(intent, app)

        elif intent == "SEARCH":

            return "Search System is under development."

        elif intent == "SHUTDOWN":

            return "Shutdown requires confirmation."

        elif intent == "RESTART":

            return "Restart requires confirmation."

        return "Sorry, I don't understand that command."