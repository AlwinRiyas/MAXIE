import re
import subprocess
import sys

from Config.config import Config


class VolumeSkill:
    """Cross-platform volume control.

    Windows: PowerShell + IAudioEndpointVolume (no extra deps).
    Linux: pactl/amixer if available.
    """

    def execute(self, text):
        text = text.lower().strip()

        action = "get"
        amount = None

        if "mute" in text:
            action = "mute"
        elif "unmute" in text:
            action = "unmute"
        elif any(w in text for w in ("set", "max", "minimum", "min", "turn")):
            action = "set"
            numbers = re.findall(r"\d+", text)
            if numbers:
                amount = int(numbers[0])
            elif "max" in text or "maximum" in text:
                amount = 100
            elif "max" in text or "min" in text:
                amount = 0 if "min" in text else 100
        elif "up" in text or "increase" in text or "louder" in text or "add" in text or "raise" in text or "boost" in text:
            action = "up"
            numbers = re.findall(r"\d+", text)
            amount = int(numbers[0]) if numbers else 10
        elif "down" in text or "decrease" in text or "lower" in text or "quieter" in text or "reduce" in text:
            action = "down"
            numbers = re.findall(r"\d+", text)
            amount = int(numbers[0]) if numbers else 10

        try:
            if sys.platform.startswith("win"):
                return self._windows(action, amount, text)
            if sys.platform.startswith("linux"):
                return self._linux(action, amount, text)
            return "Volume control isn't supported on this platform."
        except Exception as error:
            return f"Volume control failed: {error}"

    # ----------------------------------------------------------
    # Windows (PowerShell IAudioEndpointVolume)
    # ----------------------------------------------------------

    def _windows(self, action, amount, text):
        if action == "get":
            script = self._get_script()
            out = self._run_powershell(script)
            percent = self._parse_master(out)
            return f"Volume is at {percent}%" if percent is not None else (
                "I couldn't read the current volume."
            )

        if action == "set":
            return self._windows_set(amount)
        if action == "mute":
            return self._windows_set(None, mute=True)
        if action == "unmute":
            return self._windows_set(None, unmute=True)

        if action in ("up", "down"):
            current = self._get_percent()
            if current is None:
                return "I couldn't read the current volume."
            target = max(0, min(100, current + (amount if action == "up" else -amount)))
            return self._windows_set(target)

        return "I didn't understand that volume command."

    def _windows_set(self, percent, mute=False, unmute=False):
        lines = [self._get_script()]
        if percent is not None:
            lines.append(
                "$dev.SetMasterVolumeLevelScalar([Math]::Round({0}/100, 2), $null)"
                .format(percent)
            )
        if mute:
            lines.append("$dev.Mute($true, $null)")
        if unmute:
            lines.append("$dev.Mute($false, $null)")
        if not lines[1:]:
            return "Volume command not recognized."
        self._run_powershell("\n".join(lines))
        return f"Volume set to {percent}%." if percent is not None else (
            "Audio muted." if mute else "Audio unmuted."
        )

    def _get_percent(self):
        out = self._run_powershell(self._get_script())
        return self._parse_master(out)

    @staticmethod
    def _parse_master(output):
        match = re.search(r"MASTER=([\d.]+)", output or "")
        if not match:
            return None
        try:
            return int(round(float(match.group(1))))
        except ValueError:
            return None

    def _get_script(self):
        return (
            "$M = New-Object -ComObject MMDeviceEnumerator; "
            "$D = $M.GetDefaultAudioEndpoint(0, 1); "
            "$dev = $D.AudioEndpointVolume; "
            "Write-Output ('MASTER=' + [Math]::Round($dev.MasterVolumeLevelScalar * 100));"
        )

    def _run_powershell(self, script):
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout

    # ----------------------------------------------------------
    # Linux (pactl / amixer)
    # ----------------------------------------------------------

    def _linux(self, action, amount, text):
        pactl = Config.which("pactl")
        if pactl is None:
            return "No volume utility found on this Linux system."

        try:
            if action == "get":
                out = subprocess.run(
                    [pactl, "get-sink-volume", "@DEFAULT_SINK@"],
                    capture_output=True, text=True, timeout=10, check=False,
                ).stdout
                match = re.search(r"(\d+)%", out)
                return f"Volume is at {match.group(1)}%" if match else (
                    "I couldn't read the current volume."
                )

            if action == "set":
                subprocess.run(
                    [pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{amount}%"],
                    capture_output=True, timeout=10, check=False,
                )
                return f"Volume set to {amount}%."

            if action == "mute":
                subprocess.run(
                    [pactl, "set-sink-mute", "@DEFAULT_SINK@", "1"],
                    capture_output=True, timeout=10, check=False,
                )
                return "Audio muted."
            if action == "unmute":
                subprocess.run(
                    [pactl, "set-sink-mute", "@DEFAULT_SINK@", "0"],
                    capture_output=True, timeout=10, check=False,
                )
                return "Audio unmuted."

            if action in ("up", "down"):
                delta = amount if action == "up" else -amount
                subprocess.run(
                    [pactl, "set-sink-volume", "@DEFAULT_SINK@",
                     ("+" if delta > 0 else "") + f"{delta}%"],
                    capture_output=True, timeout=10, check=False,
                )
                return "Volume increased." if action == "up" else "Volume decreased."
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"Volume control failed: {error}"

        return "I didn't understand that volume command."