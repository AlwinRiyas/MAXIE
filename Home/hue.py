"""Philips Hue backend (ROADMAP 13.5).

Hue v2 (CLIP) API: find a light by name or id on the bridge, then PUT the
new on/off state to its resource. Requires a bridge IP and a username
created by pressing the link button on the bridge.

Everything is optional. With no bridge IP or no username, `from_config()`
returns None and MAXIE behaves as if the feature did not exist -- which is
the correct behaviour for the 99% of machines with no Hue bridge.
"""

import json
import urllib.request

from Home.home_adapter import HomeAdapter

CLIP = "/clip/v2/resource"


def _is_v2_id(value):
    """A Hue v2 resource id is a UUID: 36 chars, 4 dashes, hex only.

    Checked properly rather than by length alone, so a 36-character device
    *name* is looked up on the bridge instead of being sent to it as an id.
    """
    text = str(value)
    if len(text) != 36 or text.count("-") != 4:
        return False
    return all(char in "0123456789abcdefABCDEF-"
               for char in text)


class HueAdapter(HomeAdapter):
    """Control Hue lights over the local bridge."""

    name = "hue"

    def __init__(self, bridge_ip, username, opener=None):
        self.bridge_ip = str(bridge_ip).strip()
        self.username = username
        self._open = opener or self._default_opener

    @classmethod
    def _section(cls):
        from Config.config import Config

        return Config.home_config().get("hue", {}) or {}

    @classmethod
    def configured(cls):
        section = cls._section()
        return bool(section.get("bridge_ip") and section.get("username"))

    @classmethod
    def from_config(cls):
        section = cls._section()
        if not section.get("bridge_ip") or not section.get("username"):
            return None
        return cls(section["bridge_ip"], section["username"])

    def _base(self):
        return f"https://{self.bridge_ip}"

    def _default_opener(self, url, payload, timeout):
        body = json.dumps(payload).encode("utf-8") if payload else b""
        request = urllib.request.Request(
            url, data=body or None,
            headers={"Content-Type": "application/json"},
            method="PUT" if body else "GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}

    def _light_id(self, device):
        target = str(device.get("target") or device["name"])
        if _is_v2_id(target):
            return target  # already a full v2 id

        lights = self._open(f"{self._base()}{CLIP}/light", None,
                            self.timeout_seconds())
        wanted = {target.strip().lower(),
                  device["name"].strip().lower(),
                  *device.get("aliases", [])}
        for entry in (lights.get("data") or []):
            metadata = entry.get("metadata", {}) or {}
            name = str(metadata.get("name", "")).strip().lower()
            if name in wanted:
                return entry.get("id")
        return None

    def _dispatch(self, device, action, level=None):
        if action in ("status",):
            return f"I can turn {device['name']} on or off, "\
                   f"but not report its state."

        light_id = self._light_id(device)
        if not light_id:
            return f"I couldn't find '{device.get('target') or device['name']}'"\
                   f" on the Hue bridge."

        if action == "toggle":
            # Read first: the bridge owns the state, not our last-known
            # file, so a toggle after a restart still means the right thing.
            current = self._open(f"{self._base()}{CLIP}/light/{light_id}",
                                 None, self.timeout_seconds())
            is_on = bool((current.get("data") or {}).get("on", {}).get("on"))
            on_state = {"on": not is_on}
        elif action == "on":
            on_state = {"on": True}
        elif action == "off":
            on_state = {"on": False}
        else:
            return f"I don't know how to do '{action}' to a Hue light."

        payload = {"on": on_state}
        if action == "set" or (action == "on" and level is not None):
            brightness = max(0, min(100, int(level or 0)))
            payload["dimming"] = {"brightness": brightness}

        self._open(f"{self._base()}{CLIP}/light/{light_id}", payload,
                   self.timeout_seconds())
        return f"{device['name']} is {'on' if on_state['on'] else 'off'}."


__all__ = ["HueAdapter"]
