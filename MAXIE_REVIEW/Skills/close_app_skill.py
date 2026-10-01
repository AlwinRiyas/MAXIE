from Skills.app_launcher import AppLauncher


class CloseAppSkill:
    """Close applications by name through the cross-platform launcher."""

    def __init__(self):
        self.launcher = AppLauncher()

    def execute(self, app_name):
        if not app_name or not app_name.strip():
            return "Please tell me which app to close."
        ok, message = self.launcher.close(app_name.strip())
        return message