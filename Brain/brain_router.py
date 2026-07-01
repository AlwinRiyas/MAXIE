from Brain.intent_engine import IntentEngine
from AI.ai_engine import AIEngine
from Memory.memory_engine import MemoryEngine


class BrainRouter:

    def __init__(self, command_engine):

        self.command = command_engine
        self.intent = IntentEngine()
        self.ai = AIEngine()
        self.memory = MemoryEngine()

    def process(self, text):

        intent = self.intent.classify(text)

        # ---------------- OPEN APP ----------------

        if intent == "OPEN_APP":
            return self.command.execute(text)

        # ---------------- MEMORY ----------------

        elif intent == "SAVE_MEMORY":

            sentence = text.replace("remember", "").strip()

            self.memory.save(sentence, True)

            return "Okay Alwin, I'll remember that."

        # ---------------- AI ----------------

        elif intent == "AI_CHAT":

            return self.ai.ask(text)

        # ---------------- COMMANDS ----------------

        elif intent == "TIME":

            return self.command.execute("time")

        elif intent == "DATE":

            return self.command.execute("date")

        elif intent == "WEATHER":

            return self.command.execute("weather")

        return self.ai.ask(text)