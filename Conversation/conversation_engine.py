import queue
import threading
import time

from Brain.voice_commands import VoiceCommands
from Config.config import Config
from Logs.logger import Logger
from Voice.audio_manager import AudioManager
from Voice.barge_in_listener import BargeInListener
from Voice.voice_manager import VoiceManager
from Voice.voice_state import VoiceState


class ConversationEngine:
    """Main conversation loop.

    - listens for voice commands (streaming VAD recorder)
    - accepts text commands pushed by the remote server (phone/CLI).
      A dedicated worker thread answers remote commands immediately,
      even while the console is blocked on ``input()`` or a mic listen.
    - stops/answers via TTS with an echo-protected barge-in listener
    - always reacts to stop/exit even during speech
    - falls back to a text-only CLI when no microphone is available
    """

    def __init__(self, router, voice_engine, log_callback=None):
        self.router = router
        self.voice_engine = voice_engine
        self.log_callback = log_callback
        self.logger = Logger.instance()

        self.voice_manager = VoiceManager()
        self.audio_manager = self.voice_manager.audio

        self.transcriber = None
        self.microphone = None
        self.barge_in = None

        self.echo_cooldown = float(
            Config.audio().get("echo_cooldown_seconds", 0.45)
        )

        self.running = threading.Event()
        self.running.set()

        self.remote_queue = queue.Queue()
        self._remote_worker = None

        self._speech_check = VoiceCommands()

    # ----------------------------------------------------------
    # Logging hook (console by default, GUI injects its own)
    # ----------------------------------------------------------

    def _log(self, line):
        if self.log_callback is not None:
            try:
                self.log_callback(line)
            except Exception:
                pass
        else:
            print(line)

    def set_log_callback(self, callback):
        self.log_callback = callback

    def listen_once(self):
        """Single voice capture (push-to-talk). Returns text or ''."""
        try:
            heard = self.voice_manager.listen()
        except Exception as error:
            self.logger.error(f"Listen failed: {error}")
            return ""
        return (heard or "").strip()

    # ----------------------------------------------------------
    # Public control
    # ----------------------------------------------------------

    def submit_text(self, text, source=None):
        """Thread-safe entry point for the remote server: returns a
        Future that resolves with MAXIE's response string.

        ``source`` identifies the caller (the remote server passes the
        client address) so a destructive confirmation can be bound to the
        device that asked for it (SEC-11).
        """
        from concurrent.futures import Future

        future = Future()
        self.remote_queue.put((str(text), future, source))
        self._ensure_remote_worker()
        return future

    def stop(self):
        # TD-10: clear running FIRST so the worker loop terminates, then
        # drain every queued future so callers (RemoteServer, GUI) never
        # block a full timeout on a response that will never arrive.
        self.running.clear()

        shutdown_error = RuntimeError("MAXIE is shutting down.")
        while True:
            try:
                item = self.remote_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            future = item[1]
            if not future.done():
                future.set_exception(shutdown_error)

        self.remote_queue.put(None)
        worker = self._remote_worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2)

        if self.barge_in is not None:
            self.barge_in.stop()
        self.voice_engine.shutdown()

    # ----------------------------------------------------------
    # Remote worker (answers phone/CLI commands right away,
    # independent of what the main loop is blocked on)
    # ----------------------------------------------------------

    def _ensure_remote_worker(self):
        if self._remote_worker is not None and self._remote_worker.is_alive():
            return
        self._remote_worker = threading.Thread(
            target=self._remote_worker_loop, daemon=True, name="MAXIE-RemoteWorker"
        )
        self._remote_worker.start()

    def _remote_worker_loop(self):
        while self.running.is_set():
            try:
                item = self.remote_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                return
            text, future, source = item

            # SEC-11: bind the destructive-confirmation state to the caller
            # for the duration of this one turn.
            binder = getattr(self.router, "bind_source", None)
            if binder is not None:
                binder(source)
            try:
                response = self._process_remote(text)
            finally:
                if binder is not None:
                    binder(None)
            if not future.done():
                future.set_result(response)
            if response:
                self._maybe_speak_remote(response)

    def _process_remote(self, text):
        text = (text or "").strip()
        if not text:
            return "I didn't catch that."

        if self._speech_check.is_stop(text):
            self._stop_utterance()
            return "Okay, stopped."

        if self._speech_check.is_exit(text):
            self.voice_engine.stop()
            if self.barge_in is not None:
                self.barge_in.stop()
            goodbye = f"Goodbye {Config.USER_NAME}."
            self.voice_engine.speak(goodbye)
            self._log(f"📱 Remote exit -> MAXIE : {goodbye}")
            self.running.clear()
            return goodbye

        response = self.router.process(text)
        if not response:
            return ""

        self._log(f"📱 Remote : {text}\nMAXIE : {response}")
        return response

    # ----------------------------------------------------------
    # Remote spoken reply (async, only when MAXIE is idle so the
    # laptop speaker never feeds the microphone while listening).
    # ----------------------------------------------------------

    def _maybe_speak_remote(self, response):
        # Cheap pre-filter, then an atomic claim. Checking can_speak() and
        # transitioning later was a time-of-check race: a capture could open
        # the mic in between and MAXIE would talk into it (TD-04).
        if self.voice_engine.disabled or self.voice_manager.is_capturing():
            return
        if not self.voice_manager.reserve_playback():
            return
        speak_thread = threading.Thread(
            target=self._speak_remote_guarded,
            args=(response,),
            daemon=True,
            name="MAXIE-RemoteTTS",
        )
        speak_thread.start()

    def _speak_remote_guarded(self, response):
        try:
            self._speak_with_barge(response, reserved=True)
        except Exception as error:
            self.logger.error(f"Remote TTS failed: {error}")
            self.voice_engine.stop()
            self.voice_manager.release_playback()
            self.voice_manager.end_turn()

    # ----------------------------------------------------------
    # MAIN LOOP
    # ----------------------------------------------------------

    def start(self):
        if self.voice_manager.available:
            self._start_voice_mode()
        else:
            self._start_text_mode()

    def _start_voice_mode(self):
        self.transcriber = (
            self.voice_manager.speech.pipeline.transcriber
        )
        self.microphone = self.audio_manager.get_best_microphone()
        self.barge_in = BargeInListener(self.transcriber, self.microphone)

        mic_name = self.audio_manager.selected_name() or str(self.microphone)

        self._log("\n========== MAXIE VOICE MODE ==========")
        self._log(f"🎤 Microphone: {mic_name}")
        self._log("Say 'exit' to close MAXIE. Say 'stop' to interrupt.\n")

        try:
            while self.running.is_set():
                # Wake-word dislike: optional text gate before listening.
                if Config.system().get("wake_word_enabled", False):
                    if not self._wait_for_wake_word():
                        continue

                command = self.voice_manager.listen()
                if not command or not command.strip():
                    continue

                command = command.strip()
                self._log(f"\nYou : {command}")
                self._handle_command(command)
        finally:
            # TD-28: cleanup must run even when a loop iteration raises.
            self._cleanup_voice()

    def _start_text_mode(self):
        self._log("\n========== MAXIE TEXT MODE ==========")
        self._log("No microphone found — using the text interface.")
        self._log("Type your command. 'exit' quits. Commands from the phone")
        self._log("are answered instantly.\n")

        while self.running.is_set():
            try:
                command = input("You : ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not command:
                continue

            self._log("")
            self._handle_command(command)
            self._log("")

        self._cleanup_voice()

    # ----------------------------------------------------------
    # COMMAND HANDLING (shared by voice / text / remote)
    # ----------------------------------------------------------

    def _handle_command(self, command):
        """Route one command and close the turn.

        `end_turn()` runs in a `finally` on every path. Without it, an empty
        response, a raising skill, or a stop/exit branch left the machine in
        THINKING and the GUI stuck on "Thinking..." forever (TD-32).
        """
        try:
            return self._handle_command_inner(command)
        finally:
            self.voice_manager.end_turn()

    def _handle_command_inner(self, command):
        if self._speech_check.is_stop(command):
            self._stop_utterance()
            return "Okay, stopped."

        if self._speech_check.is_exit(command):
            self.voice_engine.stop()
            if self.barge_in is not None:
                self.barge_in.stop()
            goodbye = f"Goodbye {Config.USER_NAME}."
            self.voice_engine.speak(goodbye)
            self._log(f"MAXIE : {goodbye}")
            self.running.clear()
            return goodbye

        response = self.router.process(command)
        if not response:
            return ""

        self._log(f"\nMAXIE : {response}")
        self._speak_with_barge(response)
        return response

    def _stop_utterance(self):
        self.voice_engine.stop()
        if self.barge_in is not None:
            self.barge_in.stop()
        self._flush_microphone()
        self._echo_cooldown()

    # ----------------------------------------------------------
    # TTS + BARGE-IN (echo-protected)
    # ----------------------------------------------------------

    def _speak_with_barge(self, response, reserved=False):
        if self.voice_engine.disabled:
            if reserved:
                # _maybe_speak_remote claimed the speaker before we discovered
                # TTS is off; release it or the machine stays stuck in SPEAKING
                # and every later capture is refused.
                self.voice_manager.release_playback(VoiceState.IDLE)
            return

        if not reserved:
            # Atomically claim the speaker. If the microphone is open (the GUI
            # auto-loop holds it) we stay silent: the text reply is still
            # returned, but speaking here would be captured by MAXIE's own mic
            # and re-routed as a new command (TD-04).
            if not self.voice_manager.reserve_playback():
                self._log("🔇 Skipping spoken reply — microphone is busy.")
                return

        self._speak_safe(response, timeout=30)

        if self.barge_in is not None:
            self.barge_in.start()

        interrupted = False
        try:
            deadline = time.time() + 40
            while self.voice_engine.is_speaking() and self.running.is_set():
                if time.time() > deadline:
                    self.voice_engine.stop()
                    break
                if self.barge_in is not None and self.barge_in.was_interrupted():
                    interrupted = True
                    break

                time.sleep(0.03)

            # Drain: an interrupt that arrives in the final frame of TTS (or
            # is still being decoded) must not be killed by the cleanup below.
            # Poll briefly even after is_speaking() turns False (TD-30).
            if not interrupted and self.barge_in is not None:
                drain_deadline = time.time() + 0.35
                while time.time() < drain_deadline and self.running.is_set():
                    if self.barge_in.was_interrupted():
                        interrupted = True
                        break
                    time.sleep(0.02)

            if interrupted:
                self._log("\n🛑 Speech interrupted by user.")
        finally:
            # Cut MAXIE's own speech only when the user actually interrupted;
            # otherwise the loop already exited because speech completed.
            if interrupted or (
                self.barge_in is not None
                and self.barge_in.was_interrupted()
            ):
                self.voice_engine.stop()
            if self.barge_in is not None:
                self.barge_in.stop()
            self._flush_microphone()
            self._echo_cooldown()
            self.voice_manager.release_playback(VoiceState.IDLE)

    def _speak_safe(self, response, timeout=30):
        """Run TTS on a daemon thread with a hard timeout so a missing
        audio stack (headless boxes, broken espeak/pyttsx3) can never
        block the conversation or the phone reply forever."""
        speak_thread = threading.Thread(
            target=self.voice_engine.speak,
            args=(response,),
            daemon=True,
            name="MAXIE-TTS",
        )
        speak_thread.start()
        speak_thread.join(timeout)
        if speak_thread.is_alive():
            self.logger.warning("TTS timed out; forcing stop.")
            try:
                self.voice_engine.stop()
            except Exception:
                pass

    # ----------------------------------------------------------
    # ECHO PROTECTION HELPERS
    # ----------------------------------------------------------

    def _flush_microphone(self):
        recorder = self.voice_manager.speech.pipeline.recorder
        try:
            recorder.clear_audio()
        except Exception:
            pass

    def _echo_cooldown(self):
        if self.echo_cooldown > 0:
            time.sleep(self.echo_cooldown)

    # ----------------------------------------------------------
    # WAKE WORD (lightweight text gate)
    # ----------------------------------------------------------

    def _wait_for_wake_word(self):
        from Voice.wake_word_engine import WakeWordEngine

        detector = WakeWordEngine()
        heard = self.voice_manager.listen()
        if not heard:
            return False
        self._log(f"\nYou : {heard}")
        if detector.detect(heard):
            self._speak_with_barge("Yes?")
            return True
        return False

    # ----------------------------------------------------------
    # CLEANUP
    # ----------------------------------------------------------

    def _cleanup_voice(self):
        try:
            self.voice_engine.shutdown()
        except Exception:
            pass
        if self.barge_in is not None:
            self.barge_in.stop()