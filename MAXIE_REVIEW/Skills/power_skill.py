import subprocess
import sys

from Config.config import Config


class PowerSkill:
    """Shutdown and restart. Only runs after explicit confirmation
    (handled by the router). On Linux the dev machine is protected by
    ``allow_local_power_control`` (default False) in system config.
    """

    def shutdown(self, text=""):
        if sys.platform.startswith("win"):
            result = subprocess.run(
                ["shutdown", "/s", "/t", "5"], capture_output=True,
                text=True, timeout=15, check=False,
            )
            if result.returncode == 0:
                return "As you wish. Shutting down the system now."
            return f"I couldn't shut down: {result.stderr.strip() or 'shutdown error'}"

        if sys.platform.startswith("linux"):
            if not self._linux_allowed():
                return self._linux_refused("shut down")
            subprocess.run(
                ["systemctl", "poweroff"], capture_output=True, timeout=15,
                check=False,
            )
            return "As you wish. Shutting down the system now."

        return "Shutdown isn't supported on this platform."

    def restart(self, text=""):
        if sys.platform.startswith("win"):
            result = subprocess.run(
                ["shutdown", "/r", "/t", "5"], capture_output=True,
                text=True, timeout=15, check=False,
            )
            if result.returncode == 0:
                return "As you wish. Restarting the system now."
            return f"I couldn't restart: {result.stderr.strip() or 'shutdown error'}"

        if sys.platform.startswith("linux"):
            if not self._linux_allowed():
                return self._linux_refused("restart")
            subprocess.run(
                ["systemctl", "reboot"], capture_output=True, timeout=15,
                check=False,
            )
            return "As you wish. Restarting the system now."

        return "Restart isn't supported on this platform."

    # ----------------------------------------------------------
    # Linux safety gate
    # ----------------------------------------------------------

    @staticmethod
    def _linux_allowed():
        return bool(Config.system().get("allow_local_power_control", False))

    @staticmethod
    def _linux_refused(action):
        return (
            f"I won't {action} this machine (dev safety). Set "
            "'allow_local_power_control': true in Config/system_config.json "
            "to enable it here."
        )