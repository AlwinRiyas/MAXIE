import sounddevice as sd
import scipy.io.wavfile as wav
import numpy as np

from Voice.audio_manager import AudioManager


class AudioRecorder:

    def __init__(self):

        self.sample_rate = 16000

        self.channels = 1

        self.audio_manager = AudioManager()

    def record(self, seconds=3, filename="voice.wav"):

        device = self.audio_manager.get_best_microphone()

        print()

        print("Using Microphone:", device)

        print("🎤 Listening...")

        audio = sd.rec(
    int(seconds * self.sample_rate),
    samplerate=self.sample_rate,
    channels=1,
    dtype="float32",
    device=device
)

        sd.wait()

        wav.write(filename, self.sample_rate, audio)

        print("✅ Recording Complete")

        return filename