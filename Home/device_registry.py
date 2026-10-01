"""Named devices, their aliases, and what they were last told to do.

Home automation is only usable if "the living room light" resolves to one
thing. That mapping is explicit -- a JSON file the user writes -- rather
than inferred, because guessing which of four lights someone meant is how a
voice assistant switches off the wrong room.

Two files, both under `Config/` (which `.gitignore` already excludes, so a
real home never lands in a commit):

- `home_devices.json` -- the user's own declarations, committed nowhere.
- `home_state.json` -- last-known state written back after each call.

Nothing here talks to the network. Dispatch is `Home/home_automation.py`'s
job, so a registry read can never block a turn.
"""

import json
import os

from Config.config import Config

DEVICE_TYPES = ("light", "lamp", "fan", "plug", "thermostat", "lock",
                "speaker", "tv", "blind")

ACTIONS = ("on", "off", "toggle", "status", "set")

# Actions that change a device's brightness/level rather than its power.
LEVEL_ACTIONS = ("set",)


class DeviceRegistry:
    """Resolve a spoken name to a device, and remember its state.

    Attributes:
        devices: ``{name: {"type", "target", "room", "aliases"}}`` as read
            from disk. `target` is the adapter-specific identifier, e.g. a
            Home Assistant entity id or a Hue light id.
        state: ``{name: {"action", "level"}}``, last known.
    """

    def __init__(self, devices_path=None, state_path=None):
        self.devices_path = devices_path or Config.resolve(
            "Config/home_devices.json")
        self.state_path = state_path or Config.resolve(
            "Config/home_state.json")
        self.devices = self._read_devices()
        self.state = self._read_state()

    # ----------------------------------------------------------
    # Loading
    # ----------------------------------------------------------

    def _read_devices(self):
        try:
            with open(self.devices_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}

        entries = data.get("devices") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return {}

        devices = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            kind = str(entry.get("type", "")).strip().lower()
            if not name or kind not in DEVICE_TYPES:
                continue  # a device we cannot address is not a device
            aliases = entry.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            devices[name.lower()] = {
                "name": name,
                "type": kind,
                "target": str(entry.get("target", name)),
                "room": str(entry.get("room", "")).strip(),
                "aliases": [str(a).strip().lower() for a in aliases
                            if str(a).strip()],
            }
        return devices

    def _read_state(self):
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_state(self):
        """Persist last-known state. Failure is not worth breaking a turn
        over -- the state is a convenience, not a source of truth."""
        try:
            directory = os.path.dirname(self.state_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, indent=2)
        except OSError:
            return False
        return True

    # ----------------------------------------------------------
    # Lookup
    # ----------------------------------------------------------

    def names(self):
        return sorted(self.devices)

    def get(self, name):
        if not name:
            return None
        return self.devices.get(str(name).strip().lower())

    def resolve(self, phrase):
        """Find the device a phrase refers to, or None.

        Scores every name, alias and "<room> <type>" pair contained in the
        phrase and takes the longest match, so "the kitchen ceiling light"
        resolves to that rather than to a bare "light" declared elsewhere.
        """
        if not phrase:
            return None
        text = str(phrase).strip().lower()
        if not text:
            return None

        # No per-word shortcut: with both "lamp" and "porch lamp"
        # declared, "the porch lamp" must reach the second. Only the
        # longest candidate contained in the phrase can win.
        best = None
        best_length = 0
        for key, device in self.devices.items():
            candidates = [key, device["name"].lower(), *device["aliases"]]
            if device["room"]:
                candidates.append(f"{device['room']} {device['type']}")
            for candidate in candidates:
                if not candidate:
                    continue
                if candidate == text or f" {candidate} " in f" {text} ":
                    if len(candidate) > best_length:
                        best, best_length = device, len(candidate)
        return best

    def of_type(self, kind):
        return {name: device for name, device in self.devices.items()
                if device["type"] == kind}

    def describe(self, device):
        """One line for the user, with the state if it is known."""
        state = self.state.get(device["name"].lower(), {})
        action = state.get("action")
        level = state.get("level")
        if action == "set" and level is not None:
            detail = f" is on at {level}%"
        elif action in ("on", "off"):
            detail = f" is {action}"
        elif action == "toggle":
            detail = " was toggled"
        else:
            detail = " (I don't know its current state)"
        room = f" in the {device['room']}" if device["room"] else ""
        return f"The {device['type']} {device['name']}{room}{detail}"

    def set_state(self, device, action, level=None):
        key = device["name"].lower()
        entry = {"action": action}
        if level is not None:
            entry["level"] = int(level)
        self.state[key] = entry
        self.save_state()
        return entry

    def toggle_from(self, device):
        """The action a "toggle" should perform, given what we last did.

        Unknown state toggles *on*, which is the safe direction: a light the
        user can see is a light they can turn off again.
        """
        current = self.state.get(device["name"].lower(), {}).get("action")
        if current in ("on", "set"):
            # Dimming it left it on, so toggling it off is the honest
            # reading of "toggle" after a "set".
            return "off"
        if current == "off":
            return "on"
        return "on"

    def __len__(self):
        return len(self.devices)


__all__ = ["DeviceRegistry", "DEVICE_TYPES", "ACTIONS", "LEVEL_ACTIONS"]
