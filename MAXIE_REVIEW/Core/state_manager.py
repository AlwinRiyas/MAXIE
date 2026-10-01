from enum import Enum


class AssistantState(Enum):
    STARTING = "starting"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    SHUTDOWN = "shutdown"


class StateManager:

    def __init__(self):
        self.state = AssistantState.STARTING

    def set_state(self, state):
        self.state = state
        print(f"[STATE] {state.value.upper()}")

    def get_state(self):
        return self.state