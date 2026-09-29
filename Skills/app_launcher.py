import os
import subprocess
import sys
import webbrowser

from Config.config import Config
from Skills.application_registry import ApplicationRegistry


class AppLauncher:
    """Open and close applications/URLs cross-platform.

    Opening:
      - URLs -> webbrowser (cross-platform)
      - Registry/Builtin commands -> subprocess without shell
      - Files/folders -> os.startfile (Windows) or xdg-open (Linux)

    Closing:
      - Windows -> taskkill /IM <exe>
      - Linux   -> pkill -f <name>
    """

    def __init__(self):
        self.registry = ApplicationRegistry()

    # ----------------------------------------------------------
    # OPEN
    # ----------------------------------------------------------

    def open(self, descriptor):
        spec = self.registry.resolve(descriptor)
        if spec is None:
            return False, f"I couldn't find {descriptor}."

        kind, value = spec

        if kind == "url":
            webbrowser.open(value)
            return True, f"Opening {descriptor}."

        if kind == "command":
            try:
                subprocess.Popen(value, stdin=None, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True)
                return True, f"Opening {descriptor}."
            except OSError as error:
                return False, f"Couldn't launch {descriptor}: {error}"

        if kind == "path":
            try:
                self._open_path(value)
                return True, f"Opening {descriptor}."
            except OSError as error:
                return False, f"Couldn't open {descriptor}: {error}"

        return False, f"I couldn't find {descriptor}."

    def _open_path(self, path):
        if ApplicationRegistry.is_windows():
            os.startfile(path)  # noqa: S606 - allowlisted registry paths only
            return
        xdg = Config.which("xdg-open")
        if xdg:
            subprocess.Popen([xdg, path])
            return
        subprocess.Popen(["open", path])

    # ----------------------------------------------------------
    # CLOSE
    # ----------------------------------------------------------

    def close(self, name):
        exe = self._resolve_executable(name)
        if not exe:
            return False, f"I don't know how to close {name}."
        return self._close_process(exe)

    def _resolve_executable(self, name):
        spec = self.registry.resolve(name)
        if spec is None:
            return None

        kind, value = spec
        if kind == "command":
            for arg in value:
                if arg.lower().endswith((".exe",)) or "." not in arg:
                    return os.path.basename(arg)
            return os.path.basename(value[0])

        if kind == "path":
            return os.path.basename(value).replace(".lnk", "").lower()
        return None

    def _close_process(self, exe):
        try:
            if ApplicationRegistry.is_windows():
                if not exe.lower().endswith(".exe"):
                    exe = exe + ".exe"
                subprocess.run(
                    ["taskkill", "/IM", exe, "/F"],
                    capture_output=True, timeout=15, check=False,
                )
            elif ApplicationRegistry.is_linux():
                subprocess.run(
                    ["pkill", "-f", exe],
                    capture_output=True, timeout=15, check=False,
                )
            else:
                return False, f"Closing apps isn't supported on {sys.platform}."
            return True, f"Closing {exe}."
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, f"Couldn't close {exe}: {error}."