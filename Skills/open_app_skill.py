import subprocess


class OpenAppSkill:

    APPS = {
        "calculator": "calc",
        "notepad": "notepad",
        "paint": "mspaint",
    }

    def execute(self, app_name):

        app_name = app_name.lower().strip()

        if app_name not in self.APPS:
            return f"I couldn't find {app_name}."

        subprocess.Popen(self.APPS[app_name])

        return f"Opening {app_name}."