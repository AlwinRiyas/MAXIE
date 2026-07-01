from AI.ollama_client import OllamaClient


class AIEngine:

    def __init__(self):

        self.client = OllamaClient()

    def ask(self, question):

        return self.client.ask(question)