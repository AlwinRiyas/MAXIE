import subprocess
import sys

from Config.config import Config


class MediaSkill:
    """Playback control: play/pause toggle, next, previous, stop.

    Windows uses the standard media keys (ctypes keybd_event, no deps).
    Linux uses playerctl when available. Volume is handled separately
    by VolumeSkill.
    """

    # Virtual-key codes (Windows)
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    VK_MEDIA_STOP = 0xB2
    VK_MEDIA_PLAY_PAUSE = 0xB3

    def execute(self, text):
        action = self._interpret(text)
        if not action:
            return "Say next, previous, pause, resume, or stop."

        if sys.platform.startswith("win"):
            return self._windows(action)
        if sys.platform.startswith("linux"):
            return self._linux(action)
        return "Media control isn't supported on this platform."

    # ----------------------------------------------------------
    # Interpretation (pure, easily testable)
    # ----------------------------------------------------------

    @staticmethod
    def _interpret(text):
        text = text.lower().strip()
        previous_words = ("previous", "prev", "last song", "last track", "go back")
        next_words = ("next", "skip", "change the song", "change the track",
                      "switch song", "change song")
        stop_words = ("stop the music", "stop music", "stop playback")

        if any(word in text for word in previous_words):
            return "previous"
        if any(word in text for word in next_words):
            return "next"
        if any(word in text for word in stop_words):
            return "stop"
        if any(word in text for word in ("pause", "resume", "unpause",
                                         "play music", "play a song",
                                         "play some music", "play my music",
                                         "play my songs", "play song",
                                         "music")):
            return "play_pause"
        return None

    # ----------------------------------------------------------
    # Windows (media keys via ctypes)
    # ----------------------------------------------------------

    def _windows(self, action):
        key = {
            "next": self.VK_MEDIA_NEXT_TRACK,
            "previous": self.VK_MEDIA_PREV_TRACK,
            "stop": self.VK_MEDIA_STOP,
            "play_pause": self.VK_MEDIA_PLAY_PAUSE,
        }[action]
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.keybd_event(key, 0, 0, 0)
            user32.keybd_event(key, 0, 2, 0)
        except (ImportError, OSError) as error:
            return f"Couldn't press the media key: {error}"

        words = {
            "next": "Playing the next track.",
            "previous": "Going back to the previous track.",
            "stop": "Stopped playback.",
            "play_pause": "Toggled play. Hope you enjoy the music, Mr. Alwin.",
        }
        return words[action]

    # ----------------------------------------------------------
    # Linux (playerctl)
    # ----------------------------------------------------------

    def _linux(self, action):
        playerctl = Config.which("playerctl")
        if playerctl is None:
            return "I need playerctl to control playback on Linux."

        flag = {
            "next": "next",
            "previous": "previous",
            "stop": "stop",
            "play_pause": "play-pause",
        }[action]
        try:
            subprocess.run(
                [playerctl, flag], capture_output=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"Media control failed: {error}"

        words = {
            "next": "Playing the next track.",
            "previous": "Going back to the previous track.",
            "stop": "Stopped playback.",
            "play_pause": "Toggled play. Hope you enjoy the music, Mr. Alwin.",
        }
        return words[action]