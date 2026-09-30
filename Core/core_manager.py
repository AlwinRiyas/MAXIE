import signal
import threading

from Logs.logger import Logger
from Config.config import Config


class Maxie:
    """Application lifecycle: builds every subsystem, starts the
    conversation loop, and guarantees a clean shutdown.

    Subsystem construction order:

    VoiceEngine -> BrainRouter -> ConversationEngine -> RemoteServer
    """

    def __init__(self, voice_engine=None, router=None):
        self.logger = Logger.instance()
        self.shutting_down = False
        self._shutdown_lock = threading.Lock()

        self.config = Config.load()

        # TD-17: drop rotated log files past the retention window once per
        # process start, so an assistant that runs for months cannot fill
        # the disk with old transcripts.
        try:
            swept = self.logger.sweep()
            if swept:
                self.logger.info(
                    f"Log retention sweep removed {len(swept)} old file(s).")
        except Exception as error:
            self.logger.error(f"Log retention sweep failed: {error}")

        # ------------------------------------------------------
        # Voice
        # ------------------------------------------------------
        if voice_engine is None:
            from Voice.voice_engine import VoiceEngine

            voice_engine = VoiceEngine()
        self.voice_engine = voice_engine

        # ------------------------------------------------------
        # Brain
        # ------------------------------------------------------
        if router is None:
            from Brain.brain_router import BrainRouter

            router = BrainRouter()
        self.router = router

        # ------------------------------------------------------
        # Conversation
        # ------------------------------------------------------
        from Conversation.conversation_engine import ConversationEngine

        self.conversation = ConversationEngine(self.router, self.voice_engine)

        # ------------------------------------------------------
        # Remote (mobile/CLI) access
        # ------------------------------------------------------
        self.remote = None
        remote_cfg = Config.remote_config()
        if remote_cfg.get("enabled", False):
            from Interface.remote_server import RemoteServer

            self.remote = RemoteServer(host=remote_cfg.get("host", "127.0.0.1"),
                                       port=int(remote_cfg.get("port", 8778)),
                                       token=remote_cfg.get("token", ""),
                                       on_command=self.conversation.submit_text,
                                       on_voice=self._handle_voice,
                                       config=remote_cfg)

        self._install_signal_handlers()

    def _install_signal_handlers(self):
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except ValueError:
            # Not in the main thread (e.g. tests): skip signal handling.
            pass

    def _handle_voice(self, wav_path):
        """Phone /voice endpoint: transcribe on the laptop and reply.

        Uses the process-wide cached Transcriber (SEC-01) so a burst of
        phone requests shares one Whisper model instead of reloading it
        per request (a memory/CPU DoS amplifier).
        """
        from Voice.transcriber import Transcriber

        transcriber = Transcriber.shared()
        if not transcriber.is_available():
            return {
                "error": "Speech model is not installed on the laptop. "
                "Install faster-whisper or use the phone's own mic UI."
            }

        transcript = (transcriber.transcribe(wav_path) or "").strip()
        if not transcript:
            return {"response": "I couldn't hear anything."}

        future = self.conversation.submit_text(transcript)
        answer = ""
        try:
            answer = future.result(timeout=self.remote.timeout) or ""
        except Exception as error:
            self.logger.error(f"Voice reply failed: {error}")
            answer = "MAXIE took too long to respond. Please try again."
        return {"transcript": transcript, "response": answer}

    def _handle_signal(self, signum, frame):
        print("\n\nInterrupt received. Shutting down MAXIE...")
        # TD-23: a signal handler must not run blocking network I/O
        # (remote.stop() waits on the serve_forever thread; the recorder
        # may be mid-stream). Defer cleanup to the main thread instead:
        # start()'s finally and run.py's finally both call shutdown()
        # synchronously once SystemExit propagates. If we blocked here we
        # could deadlock the very shutdown we are trying to perform.
        self.logger.warning(
            f"Signal {signum} received; cleanup runs on the main thread.")
        raise SystemExit(0)

    def start(self):
        self.print_banner()

        if self.remote is not None:
            self.remote.start()

        try:
            self.conversation.start()
        except Exception as error:
            self.logger.error(f"Conversation loop error: {error}")
            print(f"\nMAXIE stopped with an error: {error}")
        finally:
            self.shutdown()

    def shutdown(self):
        # TD-25: check-then-set must be atomic or two shutdown paths
        # (signal + main loop finally) can both run the teardown steps.
        with self._shutdown_lock:
            if self.shutting_down:
                return
            self.shutting_down = True

        self.logger.info("MAXIE shutting down.")

        # TD-22: one failing teardown step must never orphan the others,
        # and the error must reach the log, not escape as an exception.
        teardown = [("remote", lambda: self.remote.stop()),
                    ("conversation", self.conversation.stop),
                    ("voice", self.voice_engine.shutdown)]
        for name, step in teardown:
            if name == "remote" and self.remote is None:
                continue
            try:
                step()
            except Exception as error:
                self.logger.error(f"{name} shutdown error: {error}")

        self.logger.info("MAXIE shutdown complete.")

    def print_banner(self):
        name = Config.ASSISTANT_NAME
        version = Config.VERSION
        print("=" * 50)
        print(f"                {name.upper()}")
        print("      Personal AI Assistant")
        print(f"          version {version}")
        print("=" * 50)