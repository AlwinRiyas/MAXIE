"""Structured outcome of a single skill call (ROADMAP 12.6).

Skills used to return a bare string, which is fine for a reply but loses
everything an agent loop needs to decide what happens next: did it work,
what changed, and can the change be taken back?

`SkillResult` carries those three answers. The undo hook is what makes
rollback (12.8) honest -- a step only gets a compensating action if the
skill declares one, so "rolled back" can never quietly mean "nothing was
ever done" or "something half-happened".
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class SkillResult:
    """One skill's outcome, plus an optional compensating action.

    Attributes:
        skill: the intent that was dispatched.
        ok: whether it completed.
        message: the user-facing response.
        data: structured detail for a later step or a log line.
        undo: ``(skill, arguments)`` to reverts this action, validated and
            allowlisted exactly like any other dispatch. None means the
            skill offers no way back (playing music, telling the time).
        error: the failure detail when ``ok`` is False.
        reverted: whether the compensating action already ran. Guards
            against a rollback that is applied twice.
    """

    skill: str
    ok: bool = True
    message: str = ""
    data: dict = field(default_factory=dict)
    undo: Optional[Tuple[str, dict]] = None
    error: str = ""
    reverted: bool = False

    @classmethod
    def success(cls, skill, message="", data=None, undo=None):
        return cls(skill=skill, ok=True, message=message,
                   data=dict(data or {}), undo=undo)

    @classmethod
    def failure(cls, skill, error="", message=None):
        return cls(skill=skill, ok=False, message=message or "",
                   error=str(error))

    def signature(self):
        """A stable identity for loop detection.

        Two steps are "the same action" when they name the same skill with
        the same arguments, regardless of the dict's key order.
        """
        import json

        try:
            arguments = json.dumps(self.data.get("arguments", {}),
                                   sort_keys=True, default=str)
        except (TypeError, ValueError):
            arguments = repr(self.data.get("arguments", {}))
        return f"{self.skill}:{arguments}"

    def with_arguments(self, arguments):
        """Record the dispatched arguments so `signature` can see them."""
        self.data["arguments"] = dict(arguments or {})
        return self

    def mark_reverted(self):
        self.reverted = True
        return self

    def describe(self):
        if self.ok:
            return self.message
        return self.message or f"{self.skill} failed: {self.error}"

    def __str__(self):
        return self.describe()


def is_undo_spec(value):
    """Whether `value` is a usable compensating-action spec.

    Kept as a predicate rather than trusting the type, because the undo
    hook arrives from a skill module and a bad one must be refused at the
    boundary instead of raising deep inside a rollback.
    """
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return False
    skill, arguments = value
    return isinstance(skill, str) and bool(skill) and isinstance(
        arguments, (dict, type(None)))


__all__ = ["SkillResult", "is_undo_spec"]
