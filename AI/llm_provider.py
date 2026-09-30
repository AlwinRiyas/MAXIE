"""Provider boundary for MAXIE's conversational AI (ROADMAP 9.1).

Every LLM backend (Ollama today, llama.cpp / OpenAI-compatible servers
later) implements ``ask`` and ``is_available`` through :class:`LLMProvider`.
The rest of MAXIE only talks to this abstraction, so a provider swap never
touches Brain, Conversation, or Core.

Contract guarantees (SEC-05 / ROADMAP 9.9):

- ``ask`` returns plain assistant text. It MUST never embed the provider
  URL, host, stack fragment, or any internal detail in a caller-visible
  string, because replies are spoken aloud and pushed to the phone.
- Failure strings are the module-level, user-facing constants consumed by
  ``AIEngine._is_offline_message`` so errors never persist as context.
- ``is_available`` is a cheap, short-timeout health probe (fail fast,
  preferred over a full generation attempt).
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract local-LLM provider (Ollama, llama.cpp, OpenAI-compatible).

    Implementations must not block forever: ``ask`` honours a bounded
    timeout and ``is_available`` uses a short probe timeout when the
    underlying HTTP library supports it.
    """

    @abstractmethod
    def ask(self, prompt, history=None, system=None):
        """Return the assistant's reply as text.

        ``history`` is a sequence of ``(role, content)`` tuples already
        capped by the caller's context budget. On failure return one of
        the stable user-facing messages from this module (never an
        exception string or URL).
        """

    @abstractmethod
    def is_available(self):
        """Return True when a generation could likely complete soon.

        Implementations should fail fast (a few seconds) and never raise.
        """

    def ask_with_tools(self, prompt, tools, history=None, system=None):
        """Optional structured tool-calling (ROADMAP 12.7).

        Returns ``(text, tool_call)`` where ``tool_call`` is ``None`` or a
        ``(name, arguments)`` pair. Not abstract on purpose: a provider
        without tool support returns ``None`` for the call, which the
        router treats as "answer in prose", so adding tool-calling to one
        provider never breaks the others.

        The pair is a *proposal*. The caller validates the name against
        the allowlist and the arguments against the intent's schema
        before anything runs.
        """

        text = self.ask(prompt, history=history, system=system)
        return text, None

    def ask_json(self, prompt, schema_hint="", history=None, system=None):
        """Optional JSON-mode generation (ROADMAP 12.2).

        Returns the model's raw JSON text, or None when the provider has no
        JSON mode. The planner parses and validates it itself -- a
        provider is not trusted to have produced a usable plan, and
        "returns None" is what lets the caller fall back to a plain
        answer instead of guessing at a broken plan.
        """

        return self.ask(prompt, history=history, system=system)

    @classmethod
    def from_config(cls, **overrides):
        """Build a provider from the `ai` section of Config.

        Optional keyword overrides let tests and callers substitute values
        without touching the on-disk config.
        """
        return cls(**overrides)