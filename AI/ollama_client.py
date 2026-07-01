import requests


class OllamaClient:

    def __init__(self):

        self.url = "http://127.0.0.1:11434/api/generate"

        self.model = "llama3.2:3b"

    def ask(self, prompt):

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }

        try:

            response = requests.post(
                self.url,
                json=payload,
                timeout=60
            )

            response.raise_for_status()

            data = response.json()

            return data.get("response", "I couldn't generate a response.")

        except requests.exceptions.ConnectionError:

            return "Ollama is running but MAXIE couldn't connect. Please verify the Ollama service."

        except requests.exceptions.Timeout:

            return "Ollama took too long to respond."

        except Exception as e:

            return f"Ollama Error: {e}"