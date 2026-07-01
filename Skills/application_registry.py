import json
import os


class ApplicationRegistry:

    DATABASE = "Skills/app_database.json"

    def load(self):

        if not os.path.exists(self.DATABASE):

            return {}

        with open(self.DATABASE, "r", encoding="utf-8") as f:

            return json.load(f)