import importlib.util
import os
import queue
import threading
import time
import tkinter as tk

from Voice.voice_state import VoiceState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_autostart():
    path = os.path.join(ROOT, "Installers", "set_autostart.py")
    spec = importlib.util.spec_from_file_location("maxie_autostart", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MaxieGUI:
    """Desktop control panel (tkinter).

    - live conversation log (console lines redirected here)
    - push-to-talk mic button + auto-listen thread when a mic exists
    - quick actions, autostart toggle, status readout
    - every command goes through ConversationEngine.submit_text so the
      remote worker handles it thread-safely and TTS is guarded
    """

    def __init__(self, assistant=None, minimized=False):
        if assistant is None:
            from Core.core_manager import Maxie
            assistant = Maxie()
        self.maxie = assistant
        self.minimized = minimized
        self.queue = queue.Queue()
        self.auto_listening = False
        self._alive = True
        # One microphone at a time, shared by push-to-talk and auto-listen.
        self._talk_lock = threading.Lock()

        self.maxie.conversation.set_log_callback(self.queue.put)
        try:
            self.autostart = _load_autostart()
        except Exception:
            self.autostart = None

        self._build_window()
        if self.maxie.remote is not None:
            self.maxie.remote.start()
        self._log_line("========== MAXIE GUI ==========")
        self._log_line("Ask me anything. The phone endpoint is live too.")
        self._send_remote("hello")

    # ----------------------------------------------------------
    # Window
    # ----------------------------------------------------------

    def _build_window(self):
        self.root = tk.Tk()
        self.root.title("MAXIE — FRIDAY")
        self.root.geometry("640x520")
        self.root.minsize(520, 420)

        header = tk.Frame(self.root, bg="#0b1320", pady=8)
        header.pack(fill="x")

        tk.Label(
            header, text="MAXIE", bg="#0b1320", fg="#e6edf3",
            font=("Consolas", 16, "bold"),
        ).pack(side="left", padx=12)
        self.status_var = tk.StringVar(value="Idle")
        tk.Label(
            header, textvariable=self.status_var, bg="#0b1320", fg="#7ee787",
            font=("Consolas", 10),
        ).pack(side="right", padx=12)

        self.log = tk.Text(
            self.root, wrap="word", state="disabled",
            bg="#010409", fg="#e6edf3", insertbackground="#e6edf3",
            font=("Consolas", 10),
        )
        self.log.pack(fill="both", expand=True, padx=8, pady=6)

        toolbar = tk.Frame(self.root, bg="#0d1117")
        toolbar.pack(fill="x", padx=8)

        tk.Button(
            toolbar, text="🎤 Talk", command=self._on_talk,
            bg="#238636", fg="white", relief="flat",
        ).pack(side="left", padx=(0, 4))
        self.auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            toolbar, text="Auto-listen", variable=self.auto_var,
            command=self._toggle_auto, bg="#0d1117", fg="#8b949e",
            selectcolor="#0d1117", activebackground="#0d1117",
        ).pack(side="left")

        if self.autostart:
            self.autostart_var = tk.BooleanVar(
                value=self.autostart.is_enabled()
            )
            tk.Checkbutton(
                toolbar, text="Start at login", variable=self.autostart_var,
                command=self._toggle_autostart, bg="#0d1117", fg="#8b949e",
                selectcolor="#0d1117", activebackground="#0d1117",
            ).pack(side="left", padx=8)

        entry_row = tk.Frame(self.root, bg="#0d1117")
        entry_row.pack(fill="x", padx=8, pady=6)
        self.entry = tk.Entry(entry_row, bg="#161b22", fg="#e6edf3",
                              insertbackground="#e6edf3", relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self._on_send())
        tk.Button(
            entry_row, text="Send", command=self._on_send,
            bg="#1f6feb", fg="white", relief="flat",
        ).pack(side="right", padx=(6, 0))

        chips = tk.Frame(self.root, bg="#0d1117")
        chips.pack(fill="x", padx=8, pady=(0, 8))
        for label, cmd in (
            ("Time", "what time is it"),
            ("Todo", "show my todo"),
            ("Next", "next song"),
            ("Call", "answer the call"),
            ("Help", "help"),
            ("Exit", "exit"),
        ):
            tk.Button(
                chips, text=label, command=lambda c=cmd: self._send_remote(c),
                bg="#21262d", fg="#e6edf3", relief="flat",
            ).pack(side="left", padx=2)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.minimized:
            self.root.after(400, self.root.iconify)

    # ----------------------------------------------------------
    # Actions
    # ----------------------------------------------------------

    def _on_send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._log_line(f"You : {text}")
        self._send_remote(text)

    def _on_talk(self):
        if not self._talk_lock.acquire(blocking=False):
            return

        def worker():
            try:
                heard = self.maxie.conversation.listen_once()
            finally:
                self._talk_lock.release()
            if heard:
                self.queue.put(f"\nYou : {heard}")
                self.maxie.conversation.submit_text(heard)

        threading.Thread(target=worker, daemon=True).start()

    def _send_remote(self, text):
        try:
            future = self.maxie.conversation.submit_text(text)
        except Exception as error:
            self._log_line(f"MAXIE : (error) {error}")
            return

        def done(f):
            try:
                result = f.result()
            except Exception as error:  # never crash the GUI
                result = f"(error) {error}"
            self.queue.put(f"\nMAXIE : {result}")

        future.add_done_callback(done)

    def _toggle_auto(self):
        self.auto_listening = self.auto_var.get()
        if self.auto_listening:
            threading.Thread(target=self._auto_loop, daemon=True).start()

    def _auto_loop(self):
        while self.auto_listening:
            # _alive is plain Python, not tkinter, so it is safe to read from
            # this worker thread. Calling root.winfo_exists() here was an
            # off-thread tkinter call and crashed on teardown (TD-15).
            if not self._alive:
                break

            # Take the same lock as _on_talk. Without this, auto-listen and
            # push-to-talk opened two InputStreams on one device and MAXIE
            # transcribed itself, re-executing mutating commands (TD-04).
            if not self._talk_lock.acquire(blocking=False):
                time.sleep(0.2)
                continue
            try:
                heard = self.maxie.conversation.listen_once()
            except Exception as error:
                self.queue.put(f"⚠️ Auto-listen error: {error}")
                heard = ""
            finally:
                self._talk_lock.release()

            if not heard:
                # No speech: sleep instead of spinning a core at 100% (TD-15).
                time.sleep(0.3)
                continue
            self.queue.put(f"\nYou : {heard}")
            self.maxie.conversation.submit_text(heard)

    def _toggle_autostart(self):
        if not self.autostart:
            return
        if self.autostart_var.get():
            message = self.autostart.enable()
        else:
            message = self.autostart.disable()
        self._log_line(message)

    def _on_close(self):
        # Clear both flags so the auto-listen worker exits before the Tk
        # interpreter is torn down; it was previously left running against a
        # destroyed root.
        self.auto_listening = False
        self._alive = False
        try:
            self.maxie.shutdown()
        except Exception:
            pass
        self.root.destroy()

    # ----------------------------------------------------------
    # Render loop
    # ----------------------------------------------------------

    def _log_line(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", str(line).strip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                line = self.queue.get_nowait()
                self._log_line(line)
        except queue.Empty:
            pass

    def _poll_status(self):
        self._drain()
        try:
            state = self.maxie.conversation.voice_manager.get_state()
        except Exception:
            state = None
        labels = {
            VoiceState.WAKING: "Waking…",
            VoiceState.LISTENING: "Listening…",
            VoiceState.THINKING: "Thinking…",
            VoiceState.ACTING: "Working…",
            VoiceState.SPEAKING: "Speaking…",
            VoiceState.COOLDOWN: "Cooling down…",
            VoiceState.ERROR: "Error",
            VoiceState.IDLE: "Idle",
        }
        self.status_var.set(labels.get(state, "Idle"))
        self.root.after(200, self._poll_status)

    # ----------------------------------------------------------
    # Entry point
    # ----------------------------------------------------------

    def run(self):
        self._poll_status()
        self.root.mainloop()


def launch(minimized=False):
    gui = MaxieGUI(minimized=minimized)
    gui.run()
    return gui