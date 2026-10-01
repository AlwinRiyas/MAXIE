"""The adapter contract every smart-home backend implements.

Two backends ship (`Home/home_assistant.py`, `Home/hue.py`) and neither is
required: `HomeAdapter.from_config()` returns `None` when nothing is
configured, and every caller treats `None` as "no home automation here"
rather than as an error.

`call()` is deliberately the only method that performs I/O, so the timeout
wrapper lives in one place (`Home/home_automation.py`) instead of being
re-implemented -- or forgotten -- per backend.
"""

from Config.config import Config


class HomeAdapter:
    """Base class for smart-home backends.

    Subclasses implement :meth:`_dispatch` and must not raise: a transport
    failure is a returned string, because the caller's job is to tell the
    user what happened, not to unwind.
    """

    name = "none"

    @classmethod
    def from_config(cls):
        """Return the configured adapter instance, or None.

        None is the normal answer on a machine with no smart-home setup,
        and every caller must handle it.
        """
        return None

    @classmethod
    def configured(cls):
        """Whether the `home` section names this backend *and* has the
        credentials it needs."""
        return False

    def _dispatch(self, device, action, level=None):
        """Perform the action. Return a short success phrase, or a
        refusal/failure phrase as plain text."""
        raise NotImplementedError

    def call(self, device, action, level=None):
        """Dispatch one action, with a short timeout.

        The timeout is the point of this method: a voice turn must not hang
        on an unreachable hub, so the call runs in a worker thread and an
        unresponsive backend is reported as words rather than as silence.
        """
        from Logs.logger import Logger

        try:
            return self._dispatch(device, action, level)
        except Exception as error:  # noqa: BLE001 - a backend must not
            Logger.instance().warning(          # break the voice turn
                f"Home adapter {self.name} failed: {type(error).__name__}")
            return f"The smart-home hub didn't respond ({type(error).__name__})."

    def timeout_seconds(self):
        return float(Config.home_config().get("timeout_seconds", 3.0))


__all__ = ["HomeAdapter"]
