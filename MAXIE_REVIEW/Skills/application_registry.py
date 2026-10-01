import json
import os
import sys

from Config.config import Config


class ApplicationRegistry:
    """Cross-platform application/handler registry.

    - JSON database of Windows Start-Menu shortcuts (``app_database.json``)
      when present.
    - Known-app map with per-OS resolution (Windows binaries vs Linux
      PATH lookup).

    Paths always come from the projector-provided DB or a known map.
    Never builds commands from untrusted text.
    """

    DATABASE = None

    KNOWN_APPS = {
        "calculator": {
            "win": "calc",
            "linux": ["gnome-calculator", "kcalc", "xcalc"],
        },
        "notepad": {
            "win": "notepad",
            "linux": ["gedit", "kate", "mousepad", "nano"],
        },
        "paint": {
            "win": "mspaint",
            "linux": ["pinta", "kolourpaint"],
        },
        "brave": {
            "win": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            "linux": ["brave", "brave-browser"],
        },
        "chrome": {
            "win": "chrome",
            "linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
        },
        "firefox": {
            "win": "firefox",
            "linux": ["firefox"],
        },
        "edge": {
            "win": "msedge",
            "linux": ["microsoft-edge", "microsoft-edge-stable"],
        },
        "android studio": {
            "win": "studio64.exe",
            "linux": ["android-studio", "studio"],
        },
        "terminal": {
            "win": "cmd",
            "linux": ["gnome-terminal", "konsole", "xterm", "kitty", "alacritty"],
        },
        "file explorer": {
            "win": "explorer",
            "linux": ["nautilus", "dolphin", "thunar", "pcmanfm"],
        },
        "settings": {
            "win": "ms-settings:",
            "linux": ["gnome-control-center", "systemsettings"],
        },
    }

    KNOWN_SITES = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "maps": "https://maps.google.com",
        "github": "https://github.com",
        "reddit": "https://www.reddit.com",
        "wikipedia": "https://www.wikipedia.org",
        "whatsapp": "https://web.whatsapp.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "twitter": "https://twitter.com",
        "x": "https://twitter.com",
        "netflix": "https://www.netflix.com",
        "spotify": "https://open.spotify.com",
    }

    def __init__(self):
        if ApplicationRegistry.DATABASE is None:
            ApplicationRegistry.DATABASE = Config.resolve("Skills/app_database.json")

    # ----------------------------------------------------------
    # Registry loader
    # ----------------------------------------------------------

    def load(self):
        registry = {}
        path = self.DATABASE
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
            except (OSError, ValueError):
                registry = {}
        return registry if isinstance(registry, dict) else {}

    # ----------------------------------------------------------
    # Resolution helpers
    # ----------------------------------------------------------

    @staticmethod
    def is_windows():
        return sys.platform.startswith("win")

    @staticmethod
    def is_linux():
        return sys.platform.startswith("linux")

    def resolve_known(self, name):
        """Return a command list (without shell) or a path for a known app."""
        name = name.lower().strip()
        entry = self.KNOWN_APPS.get(name)
        if not entry:
            return None

        if self.is_windows():
            candidate = entry.get("win")
            if candidate:
                return [candidate]
            return None

        candidates = entry.get("linux", [])
        for cand in candidates:
            found = Config.which(cand)
            if found:
                return [found]
        return None

    def resolve_registry(self, name):
        """Look up a start-menu database entry (Windows .lnk)."""
        if not self.is_windows():
            return None
        registry = self.load()
        return registry.get(name.lower().strip())

    def resolve(self, name):
        """Return a launch spec: ('command', [args]) or ('path', value)."""
        name = name.lower().strip()

        if name.startswith(("http://", "https://", "www.")):
            return ("url", name)

        site = self.KNOWN_SITES.get(name)
        if site:
            return ("url", site)

        if self._looks_like_hostname(name):
            return ("url", "https://" + name)

        path = self.resolve_registry(name)
        if path and os.path.exists(path):
            return ("path", path)

        if os.path.isdir(name) or os.path.isfile(name):
            return ("path", name)

        cmd = self.resolve_known(name)
        if cmd:
            return ("command", cmd)

        return None

    @staticmethod
    def _looks_like_hostname(name):
        """e.g. youtube.com / foo.net / example.org -> open in browser."""
        if not name:
            return False
        if any(ch.isspace() for ch in name):
            return False
        if "/" in name:
            return False
        host, _, port = name.partition(":")
        if port and not port.isdigit():
            return False
        tlds = ("com", "net", "org", "io", "me", "dev", "co", "gov", "edu")
        if not host.endswith(tlds):
            return False
        return all(ch.isalnum() or ch in ".-_" for ch in host)