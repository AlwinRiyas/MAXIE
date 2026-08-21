import requests
import time


class OllamaClient:

    def __init__(self):

        self.url = "http://127.0.0.1:11434/api/generate"

        self.model = "llama3.2:3b"

    def ask(self, prompt):

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m"
        }

        try:

            print("\n🧠 Thinking...")

            start = time.perf_counter()

            response = requests.post(
                self.url,
                json=payload,
                timeout=120
            )

            elapsed = time.perf_counter() - start

            print(f"⚡ {elapsed:.2f}s")

            response.raise_for_status()

            data = response.json()

            return data.get("response", "I couldn't generate a response.")

        except requests.exceptions.ConnectionError:
            return "Ollama is not running."

        except requests.exceptions.Timeout:
            return "Ollama timeout."

        except Exception as e:
            return f"Ollama Error: {e}"