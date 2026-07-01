import os

from Skills.application_registry import ApplicationRegistry


class AppLauncher:

    def __init__(self):

        self.registry = ApplicationRegistry()

    def open(self, app_name):

        apps = self.registry.load()

        app_name = app_name.lower()

        if app_name in apps:

            os.startfile(apps[app_name])

            return True

        return False