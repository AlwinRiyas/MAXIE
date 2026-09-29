import os
import subprocess
import sys

from Automation.system_info import SystemInfo
from Config.config import Config


class SystemSkill:
    """System information, battery, screenshot (non-destructive).

    Shutdown/restart are NOT performed from here; the Security layer
    returns a confirmation message instead of executing them.
    """

    def __init__(self):
        self.info = SystemInfo()

    def system_info(self):
        try:
            info = self.info.get_system_info()
        except Exception as error:
            return f"I couldn't read system information: {error}"

        lines = []
        for key, value in info.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def screenshot(self):
        target = Config.resolve("Logs/screenshot.png")
        try:
            if sys.platform.startswith("win"):
                return self._screenshot_windows(target)
            return self._screenshot_linux(target)
        except Exception as error:
            return f"Couldn't take a screenshot: {error}"

    def _screenshot_windows(self, target):
        script = (
            "Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
            "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            "$g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size); "
            f"$bmp.Save('{target}');"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, timeout=25, check=False,
        )
        if os.path.exists(target):
            return f"Screenshot saved to {target}."
        return "Couldn't take a screenshot."

    def _screenshot_linux(self, target):
        for tool, args in (
            ("scrot", [target]),
            ("gnome-screenshot", ["-f", target]),
            ("import", ["-window", "root", target]),
        ):
            path = Config.which(tool)
            if not path:
                continue
            result = subprocess.run(
                [path] + args, capture_output=True, timeout=25, check=False
            )
            if result.returncode == 0 and os.path.exists(target):
                return f"Screenshot saved to {target}."
        return "No screenshot tool available on this system."