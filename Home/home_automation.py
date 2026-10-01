"""Resolve a spoken request into one device action, and run it.

The order in `execute` is the whole design:

1. is home automation configured at all (else say so, do nothing);
2. does the phrase name a device (else list what is known -- a voice
   assistant that guesses which of four lights you meant is worse than one
   that admits it did not);
3. is the action one we allow;
4. is the *intent* allowlisted and, for locks, confirmation-gated -- checked
   here as well as in the router, because a skill that can be called from
   anywhere must not depend on the caller having checked;
5. dispatch under a timeout.

No step here can run a destructive device action unconfirmed: `unlock` goes
through the `HOME_UNLOCK` intent, which `Permissions` gates by capability.
"""

from Home.device_registry import ACTIONS, DEVICE_TYPES, DeviceRegistry
from Security.permissions import Permissions

LEVEL_ARG_NAMES = ("level", "brightness", "percent")


class HomeAutomation:
    """Device resolution plus dispatch.

    Attributes:
        registry: a DeviceRegistry.
        adapter: a HomeAdapter, or None when no backend is configured.
    """

    def __init__(self, registry=None, adapter=None):
        self.registry = registry if registry is not None else DeviceRegistry()
        self.adapter = adapter if adapter is not None else self._adapter()

    @staticmethod
    def _adapter():
        from Config.config import Config

        choice = str(Config.home_config().get("adapter", "none")).lower()
        if choice in ("home_assistant", "ha"):
            from Home.home_assistant import HomeAssistantAdapter

            return HomeAssistantAdapter.from_config()
        if choice in ("hue", "philips_hue"):
            from Home.hue import HueAdapter

            return HueAdapter.from_config()
        return None

    # ----------------------------------------------------------
    # Reading
    # ----------------------------------------------------------

    def devices(self):
        return self.registry.names()

    def describe_all(self):
        names = self.devices()
        if not names:
            return ("I don't know about any smart-home devices yet. Add them "
                    "to Config/home_devices.json.")
        return "I know about: " + ", ".join(names) + "."

    def status(self, phrase):
        device = self.registry.resolve(phrase)
        if device is None:
            return f"I don't know a device called '{phrase}'."
        return self.registry.describe(device)

    # ----------------------------------------------------------
    # Acting
    # ----------------------------------------------------------

    def execute(self, phrase, action="on", level=None, intent="HOME_CONTROL"):
        """Perform one action on one device, or explain why not."""
        if self.adapter is None:
            return ("Smart-home control isn't set up on this machine. See "
                    "Config/system_config.json, section system.home.")

        device = self.registry.resolve(phrase)
        if device is None:
            known = self.devices()
            if known:
                return f"I don't know a device called '{phrase}'. "\
                       f"I know about: {', '.join(known)}."
            return self.describe_all()

        action = str(action or "on").strip().lower()
        if action not in ACTIONS:
            return f"I don't know how to '{action}' something. I can "\
                   f"turn it on, off, toggle it, set its level, or say "\
                   f"its state."

        # Capability check, not string matching (SEC-07): a new or renamed
        # device type cannot unlock a door just by being spelled differently.
        if not Permissions.can_execute(intent):
            return Permissions.confirmation_for(intent) or \
                f"I'm not allowed to do that ({intent})."
        # Keyed on the resolved device's type, not on the intent the caller
        # declared: "turn on the front door" routed as HOME_CONTROL would
        # otherwise slip past a gate that only HOME_UNLOCK triggers. A caller
        # picks the intent; it does not get to pick the capability.
        if device["type"] == "lock" and action in ("on", "toggle"):
            return Permissions.confirmation_for("HOME_UNLOCK") or \
                Permissions.confirmation_for(intent)

        if action == "toggle":
            action = self.registry.toggle_from(device)

        if action == "status":
            return self.registry.describe(device)

        if action == "set":
            if level is None:
                return "What level should I set it to?"
            level = max(0, min(100, int(level)))

        reply = self._with_timeout(device, action, level)
        if self._looks_like_success(reply):
            self.registry.set_state(device, action, level)
        return reply

    def _with_timeout(self, device, action, level):
        """Run the backend call under a deadline.

        A voice turn must not hang on an unreachable hub, so the call runs
        in a worker thread and a slow backend is reported rather than waited
        on. The thread cannot be cancelled, so it is a daemon: it cannot
        keep the process alive either.
        """
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        from Logs.logger import Logger

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self.adapter.call, device, action, level)
        try:
            return future.result(timeout=self.adapter.timeout_seconds())
        except TimeoutError:
            Logger.instance().warning(
                f"Home adapter {self.adapter.name} timed out on "
                f"{device['name']}")
            return "The smart-home hub didn't answer in time."
        finally:
            future.cancel()
            executor.shutdown(wait=False)

    def prior_state(self, device):
        """What this device was last told to do, or None if we do not know.

        Read *before* the action so a caller can describe what to restore.
        `None` means MAXIE has never controlled this device, which is not the
        same as "it was off" -- see `HomeControlSkill._compensating`.
        """
        return self.registry.state.get(device["name"].lower())

    @staticmethod
    def _looks_like_success(reply):
        """Whether the reply reads like the call worked.

        Deliberately conservative: state is only recorded when the backend
        said the device is on or off. An ambiguous or failed reply leaves
        the last-known state alone, so a toggle does not silently invert
        based on a message we could not read.
        """
        if not isinstance(reply, str):
            return False
        lowered = reply.lower()
        negatives = ("didn't", "couldn't", "don't know", "don't respond",
                     "not know", "failed", "error")
        if any(marker in lowered for marker in negatives):
            return False
        return lowered.rstrip(".").endswith(("on", "off")) or \
            " is on" in lowered or " is off" in lowered

    @staticmethod
    def normalise_level(value):
        """Read a level out of whatever the caller had to hand.

        `"brightness to 40"`, `"40%"`, `40` all mean 40.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip().lower()
        digits = "".join(ch if ch.isdigit() else " " for ch in text).split()
        return int(digits[-1]) if digits else None

    @staticmethod
    def type_from_phrase(phrase):
        """The device type a phrase names, if any."""
        lowered = str(phrase or "").lower()
        for kind in DEVICE_TYPES:
            if kind in lowered:
                return kind
        return None


__all__ = ["HomeAutomation", "LEVEL_ARG_NAMES"]
