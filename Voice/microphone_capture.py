import logging
import queue
import time


class DeviceLostError(Exception):
    """The capture device stopped delivering audio mid-stream."""


class SoundDeviceStream:
    """sounddevice backend implementing the `DeviceBackend` protocol.

    Imports sounddevice lazily so the module (and the test suite) stays
    importable on headless boxes where it is not installed.
    """

    @staticmethod
    def is_available():
        try:
            import sounddevice
            return True
        except Exception:
            return False

    def open(self, samplerate, channels, blocksize, dtype, device, callback):
        import sounddevice as sd

        self.stream = sd.InputStream(
            samplerate=samplerate,
            channels=channels,
            blocksize=blocksize,
            dtype=dtype,
            device=device,
            callback=callback,
        )
        try:
            self.stream.start()
        except Exception:
            # InputStream() succeeded but start() failed — a common PortAudio
            # error. Close the handle or it leaks on every failed listen
            # (TD-31).
            try:
                self.stream.close()
            except Exception:
                pass
            raise
        return self.stream

    def close(self):
        stream = getattr(self, "stream", None)
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass


class MicrophoneCapture:
    """Owns one live input stream with an explicit open/read/close lifecycle.

    Extracted from ``AudioRecorder`` (ROADMAP 1.1): the recorder drives
    VAD and writes the wav; this class owns the device stream, the block
    queue, and the lifecycle. The backend is pluggable (1.2) so the suite
    can run headless with a fake stream. Includes device hot-plug
    recovery (1.3): when the queue runs dry for a configured number of
    blocks (a re-plugged headset stops delivering callbacks), the stream
    is closed and reopened on the next attempt.
    """

    log = logging.getLogger("MAXIE.capture")

    @staticmethod
    def backend_available():
        return SoundDeviceStream.is_available()

    def __init__(self, sample_rate=16000, channels=1, block_size=512,
                 device=None, backend=None):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.block_size = int(block_size)
        self.device = device
        self.backend = backend if backend is not None else SoundDeviceStream()

        self.queue = queue.Queue(maxsize=512)
        self.stream = None
        self._open_error = None

        self.stall_blocks = 0
        # 0 disables stall detection (used by tests that hand-feed blocks).
        self.stall_threshold = 0
        self.recovery_attempts = 2

        self._callback_error = [None]

    # ----------------------------------------------------------
    # LIFECYCLE
    # ----------------------------------------------------------

    def open(self):
        """Open and start the stream. Re-raises the backing error."""
        self.queue = queue.Queue(maxsize=512)
        self._open_error = None
        self.stall_blocks = 0

        def callback(indata, frames, time_info, status):
            if status:
                # PortAudio reports device under/overflow here; a status on
                # every callback past a short grace period means the device
                # is lost.
                self._callback_error[0] = self._callback_error[0] or str(status)
                if self.stall_threshold:
                    self.stall_blocks += 1
                return
            if self.queue.full():
                return
            self.queue.put_nowait(indata.copy())

        try:
            self.stream = self.backend.open(
                self.sample_rate,
                self.channels,
                self.block_size,
                "float32",
                self.device,
                callback,
            )
        except Exception as error:
            self._open_error = error
            self.stream = None
            raise
        return self

    def read(self, timeout=0.1):
        """Return one audio block, or None when the stream is dry/stalled."""
        if self.stream is None:
            self.stall_blocks += 1
            return None
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            self.stall_blocks += 1
            return None

    def close(self):
        if self.stream is None:
            return
        try:
            self.backend.close()
        finally:
            self.stream = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False

    # ----------------------------------------------------------
    # HOT-PLUG RECOVERY (ROADMAP 1.3)
    # ----------------------------------------------------------

    def has_stalled(self):
        """True when the stream stopped delivering audio for too long."""
        if not self.stall_threshold:
            return False
        return self.stall_blocks >= self.stall_threshold

    def recover(self):
        """Close and reopen the stream after a device was lost.

        Bounded so a device that is genuinely gone does not spin.
        Returns True when the stream is usable again.
        """
        while self.recovery_attempts > 0:
            self.recovery_attempts -= 1
            self.close()
            self._callback_error[0] = None
            self.stall_blocks = 0
            try:
                self.open()
                return True
            except Exception as error:
                self.log.warning(f"Capture recovery failed: {error}")
                time.sleep(0.2)
        return False


if __name__ == "__main__":
    print("MicrophoneCapture — lazy sounddevice backend, no hardware filter.")