import json
import os


class MemoryEngine:

    def __init__(self):

        self.file = "Memory/memory.json"

        if not os.path.exists(self.file):
            with open(self.file, "w") as f:
                json.dump({}, f)

    def save(self, key, value):

        with open(self.file, "r") as f:
            data = json.load(f)

        data[key] = value

        with open(self.file, "w") as f:
            json.dump(data, f, indent=4)

    def recall(self, key):

        with open(self.file, "r") as f:
            data = json.load(f)

        return data.get(key)