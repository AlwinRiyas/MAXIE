import requests


class OllamaClient:

    def __init__(self):

        self.url = "http://localhost:11434/api/generate"

        self.model = "llama3.2:3b"

    def ask(self, prompt):

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }

        response = requests.post(
            self.url,
            json=payload
        )

        data = response.json()

        return data["response"]