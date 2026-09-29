import subprocess
import sys

from Config.config import Config


class PhoneController:
    """Answer and reject calls on an Android phone over ADB.

    Uses ``adb`` from PATH (USB debugging or wireless debugging).
    On Windows without an ADB device, answer falls back to the system
    media key (best effort for softphone/Bluetooth rings).
    """

    KEYEVENT_HEADSETHOOK = 79
    KEYEVENT_ENDCALL = 6
    VK_MEDIA_PLAY_PAUSE = 0xB3

    def __init__(self):
        self.adb = Config.which("adb")

    # ----------------------------------------------------------
    # ADB helpers
    # ----------------------------------------------------------

    def has_adb_device(self):
        if not self.adb:
            return False
        try:
            result = subprocess.run(
                [self.adb, "devices"], capture_output=True,
                text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        lines = (result.stdout or "").splitlines()
        # Skip header "List of devices attached"; blank lines; offline states.
        for line in lines[1:]:
            if line.strip() and "offline" not in line and "unauthorized" not in line:
                return True
        return False

    def _adb_keyevent(self, keycode):
        return subprocess.run(
            [self.adb, "shell", "input", "keyevent", str(keycode)],
            capture_output=True, text=True, timeout=15, check=False,
        )

    def _adb_message(self, keycode, action_word):
        result = self._adb_keyevent(keycode)
        if result.returncode == 0:
            return f"I {action_word} the call on your phone."
        return f"I couldn't {action_word} the call over ADB: {result.stderr.strip() or 'adb error'}"

    # ----------------------------------------------------------
    # Call control
    # ----------------------------------------------------------

    def answer(self, text=""):
        if self.has_adb_device():
            return self._adb_message(self.KEYEVENT_HEADSETHOOK, "answered")

        if sys.platform.startswith("win"):
            return self._windows_fallback("answer")
        return ("I can't answer calls here. Connect your Android phone "
                "via ADB (USB or wireless debugging).")

    def reject(self, text=""):
        if self.has_adb_device():
            return self._adb_message(self.KEYEVENT_ENDCALL, "rejected")

        if sys.platform.startswith("win"):
            return ("Rejecting calls from the laptop needs an Android device "
                    "over ADB; connect via USB or wireless debugging.")
        return ("I can't reject calls here. Connect your Android phone "
                "via ADB (USB or wireless debugging).")

    # ----------------------------------------------------------
    # Windows best-effort answer
    # ----------------------------------------------------------

    def _windows_fallback(self, action):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.keybd_event(self.VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
            user32.keybd_event(self.VK_MEDIA_PLAY_PAUSE, 0, 2, 0)
        except (ImportError, OSError):
            return "No Android device was detected, and I couldn't press the answer key."

        return ("No Android device was connected, so I pressed the system "
                "answer key as a best effort.")