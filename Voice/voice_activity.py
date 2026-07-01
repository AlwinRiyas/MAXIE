import webrtcvad


class VoiceActivity:

    def __init__(self):

        self.vad = webrtcvad.Vad(2)

    def is_voice(self, frame, sample_rate=16000):

        return self.vad.is_speech(frame, sample_rate)