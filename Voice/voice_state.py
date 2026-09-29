from enum import Enum


class VoiceState(Enum):
    """Explicit lifecycle states for a single voice turn.

    Replaces the previous four-value enum, which had no transition table and no
    guard: `VoiceManager.listen()` entered PROCESSING and never returned to
    WAITING, so any completed turn left the GUI showing "Thinking..." forever
    (TD-32).
    """

    IDLE = "idle"
    WAKING = "waking"
    LISTENING = "listening"
    THINKING = "thinking"
    ACTING = "acting"
    SPEAKING = "speaking"
    COOLDOWN = "cooldown"
    ERROR = "error"


#: States in which the microphone must be closed. MAXIE's echo protection is
#: structural -- the mic is not open while the speaker is -- so anything that
#: captures while SPEAKING will transcribe MAXIE's own reply and route the echo
#: back into the brain (TD-04).
CAPTURING_STATES = frozenset({VoiceState.WAKING, VoiceState.LISTENING})

#: States in which playback is active or imminent.
SPEAKING_STATES = frozenset({VoiceState.SPEAKING, VoiceState.COOLDOWN})

#: The only legal move out of any state. Shutdown must always be able to reach
#: IDLE, so IDLE is permitted from everywhere; ERROR is likewise always
#: reachable because any step may fail.
_ALWAYS = frozenset({VoiceState.IDLE, VoiceState.ERROR})

#: Declared transitions. Anything absent here is rejected, which is the whole
#: point: the previous machine accepted any assignment from any thread.
#:
#: SPEAKING is deliberately absent from WAKING and LISTENING. Playback is not
#: reachable from a capturing state, so a reply can never start while the
#: microphone is open -- the structural echo guard (TD-04).
VALID_TRANSITIONS = {
    VoiceState.IDLE: frozenset({
        VoiceState.WAKING, VoiceState.LISTENING, VoiceState.THINKING,
        VoiceState.ACTING, VoiceState.SPEAKING, VoiceState.ERROR,
    }),
    VoiceState.WAKING: frozenset({
        VoiceState.LISTENING,
    }),
    VoiceState.LISTENING: frozenset({
        VoiceState.THINKING,
    }),
    VoiceState.THINKING: frozenset({
        VoiceState.ACTING, VoiceState.SPEAKING, VoiceState.LISTENING,
    }),
    VoiceState.ACTING: frozenset({
        VoiceState.SPEAKING, VoiceState.THINKING,
    }),
    VoiceState.SPEAKING: frozenset({
        VoiceState.COOLDOWN, VoiceState.LISTENING,
    }),
    VoiceState.COOLDOWN: frozenset({
        VoiceState.LISTENING, VoiceState.WAKING, VoiceState.SPEAKING,
    }),
    VoiceState.ERROR: frozenset({
        VoiceState.WAKING, VoiceState.LISTENING, VoiceState.SPEAKING,
    }),
}


def can_transition(current, target):
    """True if `current -> target` is a declared transition."""
    if current is None or target is None:
        return False
    if target is VoiceState.IDLE:
        return True
    if current is VoiceState.IDLE:
        # Bootstrap into any active state.
        return target in VALID_TRANSITIONS[VoiceState.IDLE]
    allowed = VALID_TRANSITIONS.get(current, frozenset())
    return target in allowed or target in _ALWAYS


def is_capturing(state):
    return state in CAPTURING_STATES


def is_speaking(state):
    return state in SPEAKING_STATES
