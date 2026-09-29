from Voice.audio_manager import AudioManager
from Voice.speech_engine import SpeechEngine
from Voice.voice_state import VoiceState
from Voice.voice_state_machine import VoiceStateMachine


class VoiceManager:
    """State machine + listen() facade around the speech pipeline.

    The state itself lives in `VoiceStateMachine`, which is the single owner of
    transitions, capture gating, and playback gating. This class keeps the
    historical API (`set_state`, `speaking`, `waiting`, `listen`) used by
    ConversationEngine and Ui/gui.py.
    """

    def __init__(self):
        self.audio = AudioManager()
        self.speech = SpeechEngine()
        self.machine = VoiceStateMachine()

    # ----------------------------------------------------------
    # STATE (delegated)
    # ----------------------------------------------------------

    @property
    def available(self):
        return self.speech.pipeline.is_available()

    def get_state(self):
        return self.machine.get_state()

    def set_state(self, state):
        if not isinstance(state, VoiceState):
            raise TypeError(f"Not a VoiceState: {state!r}")
        return self.machine.transition(state)

    def force_state(self, state):
        """Unconditional transition, for shutdown and error recovery."""
        return self.machine.force(state)

    def subscribe(self, callback):
        self.machine.subscribe(callback)

    def may_capture(self):
        return self.machine.can_capture()

    def is_speaking(self):
        return self.machine.is_speaking()

    def is_capturing(self):
        return self.machine.is_capturing()

    # ----------------------------------------------------------
    # LISTEN
    # ----------------------------------------------------------

    def listen(self):
        """Capture one utterance and return its transcript ('' on failure).

        On a real utterance the machine ends in THINKING, not IDLE: the turn is
        still in progress and the caller is about to route it. The previous
        implementation entered PROCESSING and never left it, so any completed
        turn left the GUI on "Thinking..." forever (TD-32). An empty transcript
        or a busy microphone returns '' with the machine back at IDLE, so a
        refused capture never strands the state.
        """
        if not self.available:
            return ""

        try:
            with self.machine.capture_guard(release_to=VoiceState.THINKING):
                heard = self.speech.recognize()
        except RuntimeError:
            # Mic busy, or MAXIE is speaking. Refusing here is the structural
            # echo guard (TD-04).
            return ""
        except Exception as error:
            self.machine.error(f"transcription failed: {error}")
            self.machine.force(VoiceState.IDLE)
            return ""

        if not heard or not heard.strip():
            # Nothing was said: the turn never started.
            self.machine.force(VoiceState.IDLE)
            return ""
        return heard

    # ----------------------------------------------------------
    # TRANSITION HELPERS
    # ----------------------------------------------------------

    def waking(self):
        return self.machine.transition(VoiceState.WAKING)

    def thinking(self):
        return self.machine.transition(VoiceState.THINKING)

    def acting(self):
        return self.machine.transition(VoiceState.ACTING)

    def speaking(self):
        return self.machine.transition(VoiceState.SPEAKING)

    def cooldown(self):
        return self.machine.transition(VoiceState.COOLDOWN)

    def waiting(self):
        return self.machine.transition(VoiceState.IDLE)

    def end_turn(self):
        """Return to IDLE from anywhere, unless a capture is in flight.

        Every conversation path calls this in a `finally`, so an empty reply, a
        raising skill, or a swallowed exception can never leave the machine in
        THINKING with the GUI stuck on "Thinking..." (TD-32).

        If another thread (the GUI auto-listen loop) is mid-capture, forcing
        IDLE would erase the LISTENING marker while the mic lock is still
        held: playback could then be claimed against a physically open mic
        (TD-04). But in that case the capture itself, not the async reply,
        owns the machine, so we simply leave the state alone.
        """
        if self.machine.is_capturing():
            return False
        return self.machine.force(VoiceState.IDLE)

    # ----------------------------------------------------------
    # RESERVATION
    # ----------------------------------------------------------

    def reserve_playback(self):
        """Atomically claim the speaker; False if the microphone is open."""
        return self.machine.reserve_playback()

    def release_playback(self, target=VoiceState.COOLDOWN):
        return self.machine.release_playback(target)
