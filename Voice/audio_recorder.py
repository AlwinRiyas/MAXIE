import time

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

from Voice.audio_manager import AudioManager
from Voice.vad_engine import VADEngine


class AudioRecorder:

    def __init__(self):

        self.sample_rate = 16000
        self.channels = 1

        self.audio_manager = AudioManager()
        self.vad = VADEngine()

    def record(
        self,
        filename="voice.wav",
        max_seconds=10,
        silence_seconds=1.0
    ):

        device = self.audio_manager.get_best_microphone()

        print(f"\nUsing Microphone: {device}")
        print("🎤 Waiting for speech...")

        block_duration = 0.5
        block_size = int(
            self.sample_rate * block_duration
        )

        collected = []

        speech_started = False
        silence_time = 0.0
        start_time = time.monotonic()

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=device,
            blocksize=block_size
        ) as stream:

            while True:

                audio, overflowed = stream.read(block_size)

                audio = np.asarray(
                    audio,
                    dtype=np.float32
                ).reshape(-1)

                if overflowed:
                    print("⚠️ Audio overflow")

                # Don't run Silero on tiny/empty blocks
                if len(audio) < 512:
                    continue

                voice = self.vad.has_voice(audio)

                if voice:

                    if not speech_started:

                        speech_started = True

                        print("🗣️ Speech detected")

                    collected.append(audio)

                    silence_time = 0.0

                elif speech_started:

                    collected.append(audio)

                    silence_time += block_duration

                    if silence_time >= silence_seconds:

                        break

                if (
                    time.monotonic() - start_time
                    >= max_seconds
                ):

                    break

        if not collected:

            print("No speech detected.")

            return None

        audio_data = np.concatenate(collected)

        wav.write(
            filename,
            self.sample_rate,
            audio_data
        )

        print("✅ Recording Complete")

        return filename