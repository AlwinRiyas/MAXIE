import threading
from contextlib import contextmanager

from Voice.voice_state import (
    VoiceState,
    can_transition,
    is_capturing,
    is_speaking,
)


class VoiceStateMachine:
    """Single source of truth for voice lifecycle state.

    Replaces a lock-free enum attribute written by three threads, which the
    2026-09-28 audit found to be unguarded and unvalidated (TD-32). Every
    transition goes through `transition()`, which checks `VALID_TRANSITIONS` and
    refuses illegal moves instead of silently accepting them.

    The machine also owns the capture and playback latches, so the GUI cannot
    open the microphone while MAXIE is speaking -- the single structural
    property the whole echo-control design depends on.
    """

    def __init__(self, initial=VoiceState.IDLE):
        self._state = initial
        self._lock = threading.RLock()
        self._capture_lock = threading.RLock()
        self._playback_lock = threading.RLock()
        self._listeners = []
        self._last_error = None
        self.rejected = 0

    # ----------------------------------------------------------
    # STATE
    # ----------------------------------------------------------

    @property
    def state(self):
        with self._lock:
            return self._state

    def get_state(self):
        return self.state

    def transition(self, target, force=False):
        """Move to `target`. Returns True if the move was accepted.

        An illegal transition is refused and counted in `rejected`;
        `force=True` is reserved for shutdown and error paths.
        """
        with self._lock:
            current = self._state
            if current is target:
                return True
            if not force and not can_transition(current, target):
                self.rejected += 1
                return False
            previous = current
            self._state = target
            listeners = list(self._listeners)

        for callback in listeners:
            try:
                callback(previous, target)
            except Exception:
                # A misbehaving observer must never break the turn.
                continue
        return True

    def force(self, target):
        return self.transition(target, force=True)

    def error(self, message=None):
        with self._lock:
            self._last_error = message
        self.force(VoiceState.ERROR)
        return message

    @property
    def last_error(self):
        return self._last_error

    def reset(self):
        with self._lock:
            self._last_error = None
        return self.force(VoiceState.IDLE)

    # ----------------------------------------------------------
    # SUBSCRIBERS
    # ----------------------------------------------------------

    def subscribe(self, callback):
        """Register a `callback(previous, current)` observer.

        Observers are called outside the lock and their exceptions are
        swallowed, so one bad listener cannot strand the machine.
        """
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unsubscribe(self, callback):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    # ----------------------------------------------------------
    # CAPTURE / PLAYBACK GATING
    # ----------------------------------------------------------

    def can_capture(self):
        """True when opening the microphone cannot self-capture MAXIE."""
        return not is_speaking(self.state)

    def can_play(self):
        return not is_capturing(self.state)

    def is_capturing(self):
        return is_capturing(self.state)

    def is_speaking(self):
        return is_speaking(self.state)

    def describe(self):
        return self.state.value

    # ----------------------------------------------------------
    # RESERVATION (atomic check-and-claim, closes the TD-04 race)
    # ----------------------------------------------------------

    def reserve_capture(self):
        """Atomically claim the microphone and enter LISTENING.

        Reading `can_capture()` and then transitioning was a time-of-check to
        time-of-use race: playback could be reserved in between, and the
        recorder would open on a speaker that was already talking. The claim
        and the state change happen under the same lock, and the capture latch
        is taken here so no second caller can win the microphone.
        """
        with self._lock:
            if is_speaking(self._state) or is_capturing(self._state):
                return False
            if not self._capture_lock.acquire(blocking=False):
                return False
            self._state = VoiceState.LISTENING
            return True

    def release_capture(self, target=VoiceState.IDLE):
        with self._lock:
            try:
                self._capture_lock.release()
            except RuntimeError:
                # Not held by this thread: nothing to release.
                pass
            self.transition(target)
            return self.state

    def reserve_playback(self):
        """Atomically claim the speaker and enter SPEAKING.

        Same rationale as `reserve_capture`: the check and the claim cannot be
        separated, otherwise a capture can slip in and MAXIE talks over an open
        microphone.
        """
        with self._lock:
            if is_capturing(self._state):
                return False
            if not self._playback_lock.acquire(blocking=False):
                return False
            if not self.transition(VoiceState.SPEAKING):
                try:
                    self._playback_lock.release()
                except RuntimeError:
                    pass
                return False
            return True

    def release_playback(self, target=VoiceState.COOLDOWN):
        with self._lock:
            try:
                self._playback_lock.release()
            except RuntimeError:
                pass
            self.transition(target)
            return self.state

    @contextmanager
    def capture_guard(self, release_to=VoiceState.IDLE):
        """Own the microphone for one utterance; refuse while MAXIE speaks.

        `release_to` is the state entered once the microphone closes. It is
        THINKING for a real utterance: the mic is shut, but the turn has not
        finished, which is what the GUI status reflects.
        """
        if not self.reserve_capture():
            if is_speaking(self.state):
                raise RuntimeError("microphone is busy (MAXIE is speaking)")
            raise RuntimeError("microphone is already in use")
        try:
            yield self
        finally:
            self.release_capture(release_to)

    @contextmanager
    def playback_guard(self):
        """Own the speaker for one reply; refuse while the mic is open."""
        if not self.reserve_playback():
            if is_capturing(self.state):
                raise RuntimeError("speaker is busy (microphone is open)")
            raise RuntimeError("speaker is already in use")
        try:
            yield self
        finally:
            self.release_playback()

