import os


class ApplicationDiscovery:

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

        return self.apps