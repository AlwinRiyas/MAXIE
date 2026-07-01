from Core.state_manager import StateManager, AssistantState

state = StateManager()

state.set_state(AssistantState.IDLE)
state.set_state(AssistantState.LISTENING)
state.set_state(AssistantState.THINKING)
state.set_state(AssistantState.SPEAKING)
state.set_state(AssistantState.IDLE)