import subprocess


class AppLauncher:

    def open(self, app):

        apps = {

            "calculator": "calc",

            "notepad": "notepad",

            "paint": "mspaint",

        }

        if app in apps:

            subprocess.Popen(apps[app])

            return True

        return False