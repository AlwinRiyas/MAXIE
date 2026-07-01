class BrainRouter:

    def __init__(self,
                 command_engine,
                 skill_manager=None,
                 memory_engine=None,
                 ai_engine=None):

        self.command_engine = command_engine
        self.skill_manager = skill_manager
        self.memory_engine = memory_engine
        self.ai_engine = ai_engine

    def process(self, text):

        text = text.lower()

        command_words = [
            "open",
            "close",
            "shutdown",
            "restart",
            "weather",
            "time",
            "date"
        ]

        if any(text.startswith(word) for word in command_words):

            return self.command_engine.execute(text)

        return "I'm not able to answer that yet, Alwin."