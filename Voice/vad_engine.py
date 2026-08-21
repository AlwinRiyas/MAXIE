from silero_vad import load_silero_vad, get_speech_timestamps
import torch


class VADEngine:

    def __init__(self):

        print("Loading Silero VAD...")

        self.model = load_silero_vad()

        self.sample_rate = 16000

        print("Silero Ready.")

    def has_voice(self, audio):

        audio = torch.as_tensor(
            audio,
            dtype=torch.float32
        ).flatten()

        timestamps = get_speech_timestamps(
            audio,
            self.model,
            sampling_rate=self.sample_rate
        )

        return len(timestamps) > 0