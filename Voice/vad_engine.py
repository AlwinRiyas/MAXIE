from silero_vad import load_silero_vad, get_speech_timestamps
import torch


class VADEngine:

    def __init__(self):

        print("Loading Silero VAD...")

        self.model = load_silero_vad()

        print("Silero Ready.")

    def has_voice(self, audio):

        audio = torch.from_numpy(audio).float()

        timestamps = get_speech_timestamps(
            audio,
            self.model,
            sampling_rate=16000
        )

        return len(timestamps) > 0