import os
import tempfile
import unittest
from unittest import mock

from Voice.speech_pipeline import SpeechPipeline


class SpeechPipelineTest(unittest.TestCase):
    """TD-31: recognize() must not leave relative voice.wav files in CWD."""

    def test_recognize_uses_temp_wav_and_cleans_up(self):
        pipeline = SpeechPipeline.__new__(SpeechPipeline)
        pipeline.recorder = mock.MagicMock()
        pipeline.transcriber = mock.MagicMock()
        pipeline.audio_manager = mock.MagicMock()
        pipeline._tmpdir = None

        recorded_to = []

        def fake_record(filename):
            recorded_to.append(filename)
            with open(filename, "wb") as f:
                f.write(b"RIFF fake wav")
            return filename

        pipeline.recorder.record.side_effect = fake_record
        pipeline.transcriber.transcribe.return_value = "hello there"

        result = pipeline.recognize()

        self.assertEqual(result, "hello there")
        self.assertEqual(len(recorded_to), 1)
        path = recorded_to[0]
        self.assertFalse(os.path.isfile(path),
                         "the temp wav must be removed after transcription")
        self.assertTrue(os.path.isdir(os.path.dirname(path)))


if __name__ == "__main__":
    unittest.main()