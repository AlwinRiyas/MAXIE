class AudioManager:

    def __init__(self):

        self.is_speaking = False

        self.is_listening = False

    def start_listening(self):

        self.is_listening = True

    def stop_listening(self):

        self.is_listening = False

    def start_speaking(self):

        self.is_speaking = True

    def stop_speaking(self):

        self.is_speaking = False