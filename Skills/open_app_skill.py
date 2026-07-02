import subprocess


class OpenAppSkill:

    APPS = {
        "calculator": "calc",
        "calc": "calc",
        "calculate": "calc",

        "notepad": "notepad",

        "paint": "mspaint",

        "brave": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",

        "android studio": "studio64.exe",
    }

    def execute(self, app_name):

        app_name = (
            app_name.lower()
            .replace(".", "")
            .replace(",", "")
            .strip()
        )

        if app_name not in self.APPS:
            return f"I couldn't find {app_name}."

        subprocess.Popen(self.APPS[app_name], shell=True)

        return f"Opening {app_name}."