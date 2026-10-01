"""Smart-home control skill (ROADMAP 13).

Thin by design: every decision (which device, is this action allowed, does
it need confirmation) belongs to `Home.home_automation` and
`Security.permissions`, so the same rules apply whether the request arrived
from a voice turn, the phone, or the model proposing a tool call.

`execute` also declares the compensating action for a device it changed
(ROADMAP 12.9), which is what makes `AgentExecutor.rollback` able to undo
something rather than merely claim to have.
"""

from Home.home_automation import HomeAutomation
from Skills.skill_result import SkillResult


class HomeControlSkill:
    """Turn devices on and off, set levels, report state."""

    def __init__(self, home=None):
        self.home = home if home is not None else HomeAutomation()

    def execute(self, device="", action="on", level=None, intent=None):
        level = self.home.normalise_level(level)
        intent = intent or ("HOME_UNLOCK" if str(action).lower()
                            in ("unlock", "open") and
                            self.home.type_from_phrase(device) == "lock"
                            else "HOME_CONTROL")
        return self.home.execute(device, action, level, intent=intent)

    def execute_result(self, device="", action="on", level=None,
                       intent=None):
        """`execute`, plus the compensating action when there is one.

        The agent path calls this so a multi-step plan that switches a light
        on and then fails can put it back. A voice turn does not need it and
        still gets a plain sentence from `execute`.
        """
        resolved = self.home.registry.resolve(device)
        before = self.home.prior_state(resolved) if resolved else None
        reply = self.execute(device, action, level, intent=intent)
        undo = self._compensating(resolved, before, action)
        ok = self.home._looks_like_success(reply)
        return SkillResult.success(
            "HOME_CONTROL", message=reply,
            data={"device": device, "action": action},
            undo=undo if ok else None)

    def _compensating(self, device, before, action):
        """The `(skill, arguments)` that undoes this action, or None.

        Only for an on/off change, and only when the device resolves: a
        compensating action aimed at a name we cannot resolve would be a
        second guess, not a rollback.

        A dim is *not* compensated by dimming back -- the level we would
        restore is the one we just read as current, which is the state the
        failure interrupted, not the state before the plan. Returning None
        is the honest answer there.
        """
        if device is None:
            return None
        wanted = str(action or "on").strip().lower()
        if wanted not in ("on", "off"):
            return None
        # Keyed on the resolved device's declared type, never on a word in
        # its name: "front door" contains no "lock", and reading a name to
        # decide something destructive is the habit this whole skill avoids.
        if device.get("type") == "lock":
            return None
        restore = "off" if wanted == "on" else "on"
        return ("HOME_CONTROL", {"device": device["name"],
                                 "action": restore})

    def status(self, device=""):
        return self.home.status(device)

    def devices(self):
        return self.home.describe_all()


__all__ = ["HomeControlSkill"]
