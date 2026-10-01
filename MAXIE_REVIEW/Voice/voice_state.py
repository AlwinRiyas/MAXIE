from enum import Enum


class VoiceState(Enum):

    WAITING = 1

    LISTENING = 2

    PROCESSING = 3

    SPEAKING = 4