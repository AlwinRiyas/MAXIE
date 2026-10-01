from Skills.app_launcher import AppLauncher


class OpenAppSkill:
    """Open applications or URLs by name through the cross-platform
    launcher."""

    def __init__(self):
        self.launcher = AppLauncher()

    def execute(self, app_name):
        if not app_name or not app_name.strip():
            return "Please tell me which app to open."
        ok, message = self.launcher.open(app_name.strip())
        return message