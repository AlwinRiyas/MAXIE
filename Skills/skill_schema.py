"""Declarative argument contracts for skills (ROADMAP 12.7, 3.1).

Every skill today hand-rolls its own argument extraction: the router
guesses a string, the skill re-parses it, and nothing in between knows
whether ``add 3 apples`` or ``add {"item": "3 apples"}`` was meant. This
module gives each intent a schema — argument names, types, required-ness,
enums — that is validated once at the boundary, before any skill runs.

Two consumers, one source of truth:

- ``SkillManager.execute_args`` validates a dict of arguments and then
  dispatches, so a bad or unknown field is rejected *before* a skill can
  act on it.
- ``SkillSchema.to_ollama_tool`` renders the same schema as an Ollama
  tool definition, so an LLM tool-calling layer inherits the contract
  instead of inventing a second, drifting one.

Security: a schema is a *narrowing* of what a skill accepts, never a
widening. Unknown argument names are rejected rather than forwarded, so a
model cannot smuggle an extra field past a skill that only reads one.
Destructiveness is not modelled here — that stays keyed on capability in
``Security.permissions``, so a new schema can never quietly de-gate a
destructive intent.
"""


class SchemaError(Exception):
    """Raised when arguments do not satisfy a :class:`SkillSchema`."""


class SkillSchema:
    """The argument contract for one intent.

    ``arguments`` is a sequence of plain dicts so the definition stays
    declarative data (it is rendered straight to JSON for the model)::

        {"name": "app", "type": "string", "required": True,
         "description": "Application name to launch", "max_length": 60}

    Supported types: ``string``, ``int``, ``float``, ``bool``, ``enum``.
    A schema names at most one ``primary`` argument: the one the existing
    single-string skill interface consumes, so argument dispatch needs no
    skill rewrites.
    """

    MAX_VALUE_LENGTH = 200
    TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
    FALSE_WORDS = frozenset({"0", "false", "no", "off"})

    def __init__(self, name, description="", arguments=(), primary=None):
        self.name = name
        self.description = description
        self.arguments = tuple(dict(a) for a in arguments)
        self.primary = primary
        self._by_name = {}
        for spec in self.arguments:
            argument = spec.get("name")
            if not argument:
                raise SchemaError(f"{name}: an argument has no name")
            if argument in self._by_name:
                raise SchemaError(f"{name}: duplicate argument {argument!r}")
            self._by_name[argument] = spec
        if primary is not None and primary not in self._by_name:
            raise SchemaError(f"{name}: primary {primary!r} is not an argument")

    # ----------------------------------------------------------
    # Validation
    # ----------------------------------------------------------

    def validate(self, arguments):
        """Return normalised arguments, or raise :class:`SchemaError`.

        Normalisation is deliberate and lossy in exactly one direction:
        numbers written as strings are coerced, and nothing else is.
        A value that cannot be coerced is a hard error, never a silent
        default, so a model cannot believe it set a volume it never set.
        """
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise SchemaError(
                f"{self.name}: arguments must be an object, got "
                f"{type(arguments).__name__}")

        unknown = [k for k in arguments if k not in self._by_name]
        if unknown:
            raise SchemaError(
                f"{self.name}: unknown argument(s) {', '.join(sorted(unknown))}")

        cleaned = {}
        for spec in self.arguments:
            name = spec["name"]
            present = name in arguments
            raw = arguments.get(name)

            if not present or raw is None or (isinstance(raw, str)
                                              and not raw.strip()):
                if spec.get("required"):
                    raise SchemaError(f"{self.name}: {name} is required")
                if "default" in spec:
                    cleaned[name] = spec["default"]
                continue

            cleaned[name] = self._coerce(name, spec, raw)
        return cleaned

    def _coerce(self, name, spec, raw):
        kind = spec.get("type", "string")
        max_length = int(spec.get("max_length", self.MAX_VALUE_LENGTH))

        if kind == "string":
            if not isinstance(raw, str):
                raise SchemaError(
                    f"{self.name}: {name} must be a string, got "
                    f"{type(raw).__name__}")
            value = " ".join(raw.split())
            if len(value) > max_length:
                raise SchemaError(
                    f"{self.name}: {name} is longer than {max_length} "
                    "characters")
            return value

        if kind == "int":
            try:
                value = int(str(raw).strip())
            except (TypeError, ValueError):
                raise SchemaError(
                    f"{self.name}: {name} must be a whole number, got "
                    f"{raw!r}") from None
            return self._check_bounds(name, spec, value)

        if kind == "float":
            try:
                value = float(str(raw).strip())
            except (TypeError, ValueError):
                raise SchemaError(
                    f"{self.name}: {name} must be a number, got {raw!r}"
                ) from None
            return self._check_bounds(name, spec, value)

        if kind == "bool":
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().lower()
            if text in self.TRUE_WORDS:
                return True
            if text in self.FALSE_WORDS:
                return False
            raise SchemaError(
                f"{self.name}: {name} must be true or false, got {raw!r}")

        if kind == "enum":
            allowed = list(spec.get("values", ()))
            text = str(raw).strip()
            if text not in allowed:
                raise SchemaError(
                    f"{self.name}: {name} must be one of "
                    f"{', '.join(str(a) for a in allowed)}")
            return text

        raise SchemaError(f"{self.name}: {name} has unknown type {kind!r}")

    def _check_bounds(self, name, spec, value):
        """Bounds are enforced, not decorative: a model that asks for
        volume 400 gets a schema error rather than a clipped surprise."""
        low, high = spec.get("minimum"), spec.get("maximum")
        if low is not None and value < low:
            raise SchemaError(
                f"{self.name}: {name} must be {low} or more")
        if high is not None and value > high:
            raise SchemaError(
                f"{self.name}: {name} must be {high} or less")
        return value

    # ----------------------------------------------------------
    # Rendering
    # ----------------------------------------------------------

    def to_ollama_tool(self):
        """Render this schema as an Ollama ``/api/chat`` tool definition."""
        properties = {}
        required = []
        for spec in self.arguments:
            name = spec["name"]
            kind = spec.get("type", "string")
            json_type = {
                "string": "string", "int": "integer", "float": "number",
                "bool": "boolean", "enum": "string",
            }.get(kind, "string")
            properties[name] = {
                "type": json_type,
                "description": spec.get("description", name),
            }
            if kind == "enum":
                properties[name]["enum"] = list(spec.get("values", ()))
            if spec.get("required"):
                required.append(name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def primary_value(self, arguments):
        """The single string the existing skill interface wants."""
        cleaned = self.validate(arguments)
        if self.primary is None:
            return ""
        value = cleaned.get(self.primary, "")
        if isinstance(value, bool):
            return "true" if value else "false"
        return "" if value is None else str(value)


# ----------------------------------------------------------
# The schemas. One entry per allowlisted intent, so the model can only
# ever be offered a capability that is already permitted.
# ----------------------------------------------------------

_APP = {"name": "app", "type": "string", "required": True,
        "description": "Application name", "max_length": 60}
_TEXT = {"name": "text", "type": "string", "required": True,
         "description": "Text to remember", "max_length": 200}
_ITEM = {"name": "item", "type": "string", "required": True,
         "description": "Task text", "max_length": 120}
_TASK = {"name": "task", "type": "string", "required": True,
         "description": "Task number, ordinal, or text", "max_length": 60}
_QUERY = {"name": "query", "type": "string", "required": True,
          "description": "What to search for", "max_length": 120}
_EXPR = {"name": "expression", "type": "string", "required": True,
         "description": "Arithmetic expression", "max_length": 60}
_TOPIC = {"name": "topic", "type": "string", "required": False,
          "description": "Subject the user is interested in",
          "max_length": 80, "default": ""}
_MEDIA = {"name": "action", "type": "enum", "required": False,
          "description": "Playback action", "default": "toggle",
          "values": ["play", "pause", "toggle", "next", "previous"]}

SKILL_SCHEMAS = {}


_DEVICE = {"name": "device", "type": "string", "required": True,
           "description": "Device name as spoken, e.g. 'living room light'",
           "max_length": 80}
_HOME_ACTION = {"name": "action", "type": "enum", "required": False,
                "description": "on, off, toggle, set, or status",
                "values": ["on", "off", "toggle", "set", "status"],
                "default": "on"}


def _register(schema):
    SKILL_SCHEMAS[schema.name] = schema
    return schema


_register(SkillSchema("OPEN_APP", "Launch a desktop application", (_APP,), "app"))
_register(SkillSchema("CLOSE_APP", "Close a running application", (_APP,), "app"))
_register(SkillSchema("TIME", "Say the current time"))
_register(SkillSchema("DATE", "Say today's date"))
_register(SkillSchema("WEATHER", "Report the current weather"))
_register(SkillSchema("CALCULATE", "Evaluate an arithmetic expression",
                      (_EXPR,), "expression"))
_register(SkillSchema("SEARCH", "Search the web", (_QUERY,), "query"))
_register(SkillSchema("SYSTEM_INFO", "Report system information"))
_register(SkillSchema("SCREENSHOT", "Take a screenshot"))
_register(SkillSchema("VOLUME", "Set or report the system volume",
                      ({"name": "level", "type": "int", "required": False,
                        "description": "Volume percent 0-100",
                        "minimum": 0, "maximum": 100},),
                      "level"))
_register(SkillSchema("SAVE_MEMORY", "Remember a fact about the user",
                      (_TEXT,), "text"))
_register(SkillSchema("RECALL_MEMORY", "Recall a stored fact",
                      ({"name": "text", "type": "string", "required": False,
                        "description": "What to look for", "max_length": 120,
                        "default": ""},), "text"))
_register(SkillSchema("DELETE_MEMORY", "Forget a stored fact",
                      (_TASK,), "task"))
_register(SkillSchema("TODO_ADD", "Add a task to the to-do list",
                      (_ITEM,), "item"))
_register(SkillSchema("TODO_LIST", "Read the to-do list"))
_register(SkillSchema("TODO_DONE", "Mark a task done", (_TASK,), "task"))
_register(SkillSchema("TODO_REMOVE", "Remove a task", (_TASK,), "task"))
_register(SkillSchema("TODO_CLEAR", "Clear the to-do list"))
_register(SkillSchema("MEDIA_NEXT", "Skip to the next track"))
_register(SkillSchema("MEDIA_PREVIOUS", "Go to the previous track"))
_register(SkillSchema("MEDIA_PLAY_PAUSE", "Control media playback",
                      (_MEDIA,), "action"))
_register(SkillSchema("CALL_ANSWER", "Answer a ringing call"))
_register(SkillSchema("CALL_REJECT", "Reject a ringing call"))
_register(SkillSchema("YOUTUBE_SEARCH", "Search YouTube", (_QUERY,), "query"))
_register(SkillSchema("RECOMMEND", "Recommend something to watch or listen to",
                      (_TOPIC,), "topic"))
_register(SkillSchema("SHUTDOWN", "Shut the computer down (needs the user's "
                                 "confirmation in a separate turn)"))
_register(SkillSchema("RESTART", "Restart the computer (needs the user's "
                                 "confirmation in a separate turn)"))
_register(SkillSchema(
    "HOME_CONTROL", "Control a smart-home device (light, fan, plug, "
                    "thermostat, blind)",
    (_DEVICE, _HOME_ACTION,
     {"name": "level", "type": "int", "required": False,
      "description": "Brightness or level percent 0-100, for the 'set' action",
      "minimum": 0, "maximum": 100}), "device"))
_register(SkillSchema(
    "HOME_UNLOCK", "Unlock a door lock (needs the user's confirmation in a "
                   "separate turn)",
    (_DEVICE,), "device"))
