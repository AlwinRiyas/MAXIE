import numpy as np

from Voice.vad_engine import VADEngine

vad = VADEngine()

audio = np.zeros(16000, dtype=np.float32)

print(vad.has_voice(audio))