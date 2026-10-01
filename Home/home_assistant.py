"""Home Assistant backend (ROADMAP 13.5).

Talks to a local HA instance over its REST API. Every attribute lives in
the `home.home_assistant` config section and none of it is required: with
no token, `from_config()` returns None and MAXIE behaves exactly as it did
before home automation existed.

The token is read from config, never logged, and never written anywhere --
if it is in `Config/system_config.json` that file is already gitignored.
"""

from Home.home_adapter import HomeAdapter

# Home Assistant's service names per device type and action.
SERVICES = {
    "light": {"on": "turn_on", "off": "turn_off", "toggle": "toggle"},
    "lamp": {"on": "turn_on", "off": "turn_off", "toggle": "toggle"},
    "switch": {"on": "turn_on", "off": "turn_off", "toggle": "toggle"},
    "plug": {"on": "turn_on", "off": "turn_off", "toggle": "toggle"},
    "fan": {"on": "turn_on", "off": "turn_off", "toggle": "toggle"},
    "media_player": {"on": "turn_on", "off": "turn_off",
                     "toggle": "media_play_pause"},
    "lock": {"on": "lock", "off": "unlock"},
}

# Which service call carries a brightness/level field, per domain. A domain
# missing from this cannot be dimmed and is told so rather than sent a field
# Home Assistant would reject.
_LEVEL_FIELDS = {
    "light": ("brightness_pct",),
}

ENTITY_DOMAIN = {
    "light": "light",
    "lamp": "light",
    "fan": "fan",
    "plug": "switch",
    "thermostat": "climate",
    "blind": "cover",
    "lock": "lock",
    "speaker": "media_player",
    "tv": "media_player",
}


class HomeAssistantAdapter(HomeAdapter):
    """Control Home Assistant entities by service call."""

    name = "home_assistant"

    def __init__(self, url, token, verify_ssl=True, session=None):
        self.url = str(url).rstrip("/")
        self.token = token
        self.verify_ssl = bool(verify_ssl)
        self._session = session

    @classmethod
    def configured(cls):
        section = cls._section()
        return bool(section.get("url") and section.get("token"))

    @classmethod
    def from_config(cls):
        section = cls._section()
        if not section.get("url") or not section.get("token"):
            return None
        return cls(section["url"], section["token"],
                   section.get("verify_ssl", True))

    @staticmethod
    def _section():
        from Config.config import Config

        return Config.home_config().get("home_assistant", {}) or {}

    def _entity_id(self, device):
        target = device.get("target") or device["name"]
        if "." in target:
            return target  # the user gave a full entity id
        domain = ENTITY_DOMAIN.get(device["type"])
        if not domain:
            return None
        return f"{domain}.{target.replace(' ', '_').lower()}"

    def _post(self, path, payload):
        import requests  # lazy: a machine with no HA must not pay for it

        session = self._session or requests
        url = f"{self.url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        response = session.post(url, json=payload, headers=headers,
                                timeout=self.timeout_seconds(),
                                verify=self.verify_ssl)
        response.raise_for_status()
        return response

    def _dispatch(self, device, action, level=None):
        entity_id = self._entity_id(device)
        if not entity_id:
            return f"I don't know how Home Assistant addresses a "\
                   f"{device['type']}."

        domain = entity_id.split(".", 1)[0]
        services = SERVICES.get(domain, {})
        if action == "status":
            return f"I can turn {device['name']} on or off, "\
                   f"but not report its state."

        # "set" is a level change, not a service name: it is a turn_on
        # carrying a brightness. Resolved before the service lookup so a
        # dimming request is not rejected as an unknown action.
        level_payload = None
        if action == "set":
            if "brightness_pct" not in _LEVEL_FIELDS.get(domain, ()):
                return f"I don't know how to set the level of a {domain}."
            level_payload = {"brightness_pct": max(0, min(100,
                                                         int(level or 0)))}
            action = "on"

        service = services.get(action)
        if not service:
            return f"I don't know how to do '{action}' to a {domain}."

        payload = {"entity_id": entity_id}
        if level_payload:
            payload.update(level_payload)

        self._post(f"/api/services/{domain}/{service}", payload)
        return f"{device['name']} is {'on' if action != 'off' else 'off'}."


__all__ = ["HomeAssistantAdapter"]
