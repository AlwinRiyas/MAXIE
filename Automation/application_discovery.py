import json
import os


class ApplicationDiscovery:

    DATABASE = "Skills/app_database.json"

    def __init__(self):
        self.apps = {}

    def scan(self):

        start_menu = [
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
            os.path.expandvars(
                r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"
            ),
        ]

        for folder in start_menu:

            if not os.path.exists(folder):
                continue

            for root, dirs, files in os.walk(folder):

                for file in files:

                    if file.endswith(".lnk"):

                        name = file.replace(".lnk", "").lower()

                        self.apps[name] = os.path.join(root, file)

        self.save_database()

        return self.apps

    def save_database(self):

        os.makedirs("Skills", exist_ok=True)

        with open(self.DATABASE, "w", encoding="utf-8") as f:

            json.dump(
                self.apps,
                f,
                indent=4
            )