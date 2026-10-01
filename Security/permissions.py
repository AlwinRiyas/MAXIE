"""Capability declarations and the execution boundary (SEC-07).

LLM output is never executed directly. Every action MAXIE takes goes through
``SkillManager``, and only allowlisted intents can run (see ``ALLOWED``).

Why capabilities rather than a "known-bad" list
-----------------------------------------------
The earlier version kept a ``DESTRUCTIVE`` set of *intent names* and gated on
membership. That reads as if a new destructive intent cannot slip through, and
the docstring said so, but it could: whoever added the new intent had to
remember to add its name to a second list, and the failure mode of forgetting
was silent execution. The gate is now keyed on a declared *capability*
(``CAPABILITIES`` -> ``DESTRUCTIVE_CAPABILITIES``), which makes the safe answer
the default one:

- An intent is gated when any capability it declares is destructive.
- An intent with no capability declaration is gated too, because
  ``requires_confirmation`` fails closed on an unclassified intent.

So the two mistakes a new capability can make are both safe. Forgetting to
declare it gets it gated; declaring a benign capability gets it through
deliberately, and that shows up in review as a diff on this file rather than
as an absence from it.
"""


def _derive_destructive(capabilities, destructive_capabilities, legacy):
    """Intents that must be confirmation-gated.

    Derived rather than hand-maintained: the set cannot drift away from
    ``CAPABILITIES`` the way a parallel list of names could. ``legacy`` covers
    the two entries that are deliberately *not* allowlistable and so have no
    capabilities to declare (``FORMAT``, ``DELETE_MEMORY_BULK``).
    """
    return frozenset(
        intent
        for intent, caps in capabilities.items()
        if caps & destructive_capabilities
    ) | frozenset(legacy)


class Permissions:
    """Security boundary for skill execution."""

    ALLOWED = {
        "TIME", "DATE", "WEATHER", "OPEN_APP", "CLOSE_APP", "CALCULATE",
        "SEARCH", "VOLUME", "SYSTEM_INFO", "SAVE_MEMORY", "RECALL_MEMORY",
        "DELETE_MEMORY", "GREETING", "HELP", "SCREENSHOT", "AI_CHAT",
        "TODO_ADD", "TODO_LIST", "TODO_DONE", "TODO_REMOVE", "TODO_CLEAR",
        "MEDIA_NEXT", "MEDIA_PREVIOUS", "MEDIA_PLAY_PAUSE",
        "CALL_ANSWER", "CALL_REJECT",
        "YOUTUBE_SEARCH", "RECOMMEND",
        "SHUTDOWN", "RESTART",
        # Home automation (ROADMAP 13). Two intents rather than one, so
        # unlocking a door is gated by capability while switching a light is
        # not, and the gate cannot be sidestepped by spelling the action
        # differently. HOME_CONTROL re-checks the resolved device type
        # before it acts, so it is also safe on its own.
        "HOME_CONTROL", "HOME_UNLOCK",
    }

    # Capability bucket: anything destructive by nature, for any skill.
    DESTRUCTIVE_CAPABILITIES = frozenset({
        "power.system",
        "memory.irreversible",
        "device.unlock",
    })

    # What each allowlisted intent is *allowed to do*. Read this as the
    # permission the skill holds, not as a description of it.
    CAPABILITIES = {
        "TIME": frozenset({"clock.read"}),
        "DATE": frozenset({"clock.read"}),
        "WEATHER": frozenset({"net.read"}),
        "OPEN_APP": frozenset({"process.launch"}),
        "CLOSE_APP": frozenset({"process.terminate"}),
        "CALCULATE": frozenset({"compute.local"}),
        "SEARCH": frozenset({"net.read"}),
        "VOLUME": frozenset({"audio.local"}),
        "SYSTEM_INFO": frozenset({"sysinfo.read"}),
        "SAVE_MEMORY": frozenset({"memory.write"}),
        "RECALL_MEMORY": frozenset({"memory.read"}),
        "DELETE_MEMORY": frozenset({"memory.write", "memory.irreversible"}),
        "GREETING": frozenset({"dialogue.local"}),
        "HELP": frozenset({"dialogue.local"}),
        "SCREENSHOT": frozenset({"capture.screen"}),
        "AI_CHAT": frozenset({"llm.infer"}),
        "TODO_ADD": frozenset({"file.write"}),
        "TODO_LIST": frozenset({"file.read"}),
        "TODO_DONE": frozenset({"file.write"}),
        "TODO_REMOVE": frozenset({"file.write"}),
        "TODO_CLEAR": frozenset({"file.write"}),
        "MEDIA_NEXT": frozenset({"media.transport"}),
        "MEDIA_PREVIOUS": frozenset({"media.transport"}),
        "MEDIA_PLAY_PAUSE": frozenset({"media.transport"}),
        "CALL_ANSWER": frozenset({"phone.call_control"}),
        "CALL_REJECT": frozenset({"phone.call_control"}),
        "YOUTUBE_SEARCH": frozenset({"net.read"}),
        "RECOMMEND": frozenset({"data.read"}),
        "SHUTDOWN": frozenset({"power.system"}),
        "RESTART": frozenset({"power.system"}),
        "HOME_CONTROL": frozenset({"device.control"}),
        "HOME_UNLOCK": frozenset({"device.control", "device.unlock"}),
    }

    # Intents that are never allowlistable, so they have no capability to
    # declare. Gated and refused regardless.
    LEGACY_GATED = frozenset({"FORMAT", "DELETE_MEMORY_BULK"})

    DESTRUCTIVE = _derive_destructive(
        CAPABILITIES, DESTRUCTIVE_CAPABILITIES, LEGACY_GATED)

    # Spoken words that express a bulk memory wipe ("delete all memories").
    BULK_DELETE_WORDS = frozenset({"all", "everything", "memories"})

    REQUIRES_CONFIRMATION = {
        "SHUTDOWN": "I won't shut down without your explicit confirmation.",
        "RESTART": "I won't restart without your explicit confirmation.",
        "DELETE_MEMORY": "I won't delete your memories without confirmation.",
        "DELETE_MEMORY_BULK": "I won't wipe ALL of your memories without confirmation.",
        "FORMAT": "I can't format drives. This is too destructive.",
        "HOME_UNLOCK": "I won't unlock a door without your explicit confirmation.",
    }

    UNCLASSIFIED_REFUSAL = (
        "I don't recognise that action, so I won't run it without your say-so.")

    @classmethod
    def can_execute(cls, intent):
        return intent in cls.ALLOWED

    @classmethod
    def capabilities_for(cls, intent):
        """The declared capabilities, or None when unclassified.

        None is meaningful: it means nobody has said what this intent may do,
        so the confirmation gate treats it as gated rather than safe.
        """
        return cls.CAPABILITIES.get(intent)

    @classmethod
    def is_classified(cls, intent):
        return intent in cls.CAPABILITIES

    @classmethod
    def requires_confirmation(cls, intent):
        """SEC-07: capability-keyed gate, failing closed where it matters.

        True for every intent that declares a destructive capability, and
        also for an *allowlisted but unclassified* intent — one that has
        been cleared to run but never had its powers described, so it does
        not run on trust.

        An intent that is neither classified nor allowlisted (the router's
        ``UNKNOWN``, meaning nothing was recognised) is **not** gated. It
        also cannot execute: ``can_execute`` refuses it, and a refusal is
        not a confirmation prompt. Gating it here would replace "I didn't
        catch that, want me to ask the AI?" with a scary prompt about an
        action that was never going to run.
        """
        if intent in cls.DESTRUCTIVE:
            return True
        if not cls.is_classified(intent):
            return Permissions.can_execute(intent)
        return bool(
            cls.CAPABILITIES[intent] & cls.DESTRUCTIVE_CAPABILITIES)

    @classmethod
    def confirmation_for(cls, intent):
        if intent in cls.REQUIRES_CONFIRMATION:
            message = cls.REQUIRES_CONFIRMATION[intent]
            another = "confirm " + intent.replace("_", " ").lower()
            return f"{message} Say '{another}' to confirm."
        if not cls.is_classified(intent):
            return cls.UNCLASSIFIED_REFUSAL
        return None
