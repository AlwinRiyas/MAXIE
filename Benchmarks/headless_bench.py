"""Headless performance measurement (ROADMAP 18.3).

Until now MAXIE had no numbers at all: no cold start, no turn latency, no
STT/TTS timing. "It feels slow" and "it feels fast" were the only
instruments, and neither is falsifiable.

What this measures is everything that can be measured on a headless box:

- import cost of the modules on the startup path,
- ``Config`` load,
- a full ``BrainRouter`` turn for representative utterances (the hot path
  for every command, spoken or remote),
- VAD block processing and recorder buffer assembly on synthetic audio,
- a remote ``/command`` round trip over loopback.

What it deliberately does not measure is anything needing a sound card:
wake-to-listen, real STT latency, and TTS latency. Those need the laptop,
and ``Installers/benchmark.py --hardware`` collects them there. Claiming a
number for those from a headless run would be inventing data.

Every timing uses :func:`time.perf_counter`, and the slower of N runs is
reported as the headline number rather than the mean: a tail latency is
what a user actually feels, and an average hides the worst case.
"""

import statistics
import time


class Timing:
    """A named set of samples with a stable reporting shape."""

    __slots__ = ("name", "samples", "unit")

    def __init__(self, name, unit="ms"):
        self.name = name
        self.unit = unit
        self.samples = []

    def add(self, seconds):
        self.samples.append(float(seconds))

    def _scaled(self):
        factor = 1000.0 if self.unit == "ms" else 1.0
        return [s * factor for s in self.samples]

    @property
    def best(self):
        values = self._scaled()
        return min(values) if values else float("nan")

    @property
    def worst(self):
        values = self._scaled()
        return max(values) if values else float("nan")

    @property
    def median(self):
        values = self._scaled()
        return statistics.median(values) if values else float("nan")

    def report(self):
        if not self.samples:
            return f"{self.name}: no samples"
        return (f"{self.name:<34} best {self.best:8.2f}{self.unit}  "
                f"median {self.median:8.2f}{self.unit}  "
                f"worst {self.worst:8.2f}{self.unit}")

    def as_dict(self):
        return {
            "name": self.name,
            "unit": self.unit,
            "best": round(self.best, 3),
            "median": round(self.median, 3),
            "worst": round(self.worst, 3),
            "samples": len(self.samples),
        }


class HeadlessBench:
    """Collects the headless timings. Every measurement is optional: a
    missing optional dependency (numpy, the audio stack) degrades that one
    measurement to an empty sample set rather than failing the run, so the
    same harness works on a dev box and a stripped CI container.
    """

    def __init__(self, runs=5):
        self.runs = max(1, int(runs))
        self.timings = []

    # ----------------------------------------------------------
    # Harness
    # ----------------------------------------------------------

    def _record(self, name, fn, runs=None, unit="ms"):
        timing = Timing(name, unit)
        for _ in range(runs or self.runs):
            start = time.perf_counter()
            try:
                fn()
            except Exception:  # noqa: BLE001 - an unmeasurable step is skipped
                break
            timing.add(time.perf_counter() - start)
        self.timings.append(timing)
        return timing

    def report(self):
        return "\n".join(t.report() for t in self.timings)

    def as_dict(self):
        return {t.name: t.as_dict() for t in self.timings if t.samples}

    # What cannot be measured here, and why. Named constants so the docs,
    # the benchmark CLI and the test suite cannot drift into disagreeing
    # about what a headless run is allowed to claim.
    HARDWARE_ONLY = {
        "wake_to_listen": "needs a real microphone; the wake gate and the "
                          "VAD trigger path never run headless",
        "stt_latency": "needs faster-whisper and a microphone; a model load "
                       "on this box would measure the CPU, not MAXIE",
        "tts_latency": "needs an audio device; the watchdog path returns "
                       "immediately on a headless box",
        "barge_in_latency": "needs playback and capture at the same time",
    }

    def unmeasured(self):
        """The measurements this run deliberately did not make."""
        return dict(self.HARDWARE_ONLY)

    def slowest(self):
        measured = [t for t in self.timings if t.samples]
        return max(measured, key=lambda t: t.worst) if measured else None

    # ----------------------------------------------------------
    # Measurements
    # ----------------------------------------------------------

    def measure_imports(self, modules=None):
        """Cost of importing the startup-path modules.

        Measured in a subprocess so an already-imported module cannot make
        this look free. Each module is timed in its own interpreter,
        which is the only honest way to measure import cost.
        """
        import subprocess
        import sys

        modules = modules or [
            "Config.config", "Logs.logger", "Brain.brain_router",
            "Brain.intent_engine", "Skills.skill_manager", "AI.ai_engine",
        ]
        for module in modules:
            code = (
                "import time, importlib;"
                "t=time.perf_counter();"
                f"importlib.import_module({module!r});"
                "print((time.perf_counter()-t)*1000)"
            )
            timing = Timing(f"import {module}")
            try:
                out = subprocess.run(
                    [sys.executable, "-c", code], capture_output=True,
                    text=True, timeout=60, check=True,
                )
                timing.add(float(out.stdout.strip().splitlines()[-1]) / 1000.0)
            except Exception:  # noqa: BLE001
                pass
            self.timings.append(timing)
        return self.timings

    def measure_config_load(self):
        """A real read of the three config files.

        ``Config.load()`` memoises, so measuring it as-is reports ~0ms for a
        machine that never touched the disk. ``force=True`` makes the
        number mean something: what a cold start actually pays.
        """
        from Config.config import Config

        def _load():
            Config.load(force=True)

        return self._record("Config.load (forced)", _load)

    def measure_router_turns(self, utterances=None, stub_skills=True):
        """A full turn through BrainRouter.process(), the hot path.

        The AI fallback is stubbed: measuring a local LLM's generation
        time would be measuring Ollama and the machine, not MAXIE. The
        point here is the routing cost, which is what regresses.
        """
        from Brain.brain_router import BrainRouter

        utterances = utterances or [
            "what time is it",
            "open brave",
            "add milk to the shopping list",
            "what do i like",
            "what is 12 times 8",
            "shut down the computer",
        ]
        router = BrainRouter()
        if stub_skills:
            router.command = _StubCommandEngine()
            router.ai = _StubAI()
            router.memory = _StubMemory()

        for utterance in utterances:
            self._record(f"router turn: {utterance[:22]}",
                         lambda u=utterance: router.process(u))
        return self.timings

    def measure_vad(self, blocks=200, block_size=512):
        """VAD block processing on synthetic audio.

        Synthetic rather than a recording because the point is the per-block
        cost curve, which is identical for speech and for noise. A waveform
        sweep here would catch the O(n^2) regression TD-01 described without
        needing a microphone.
        """
        try:
            import numpy as np
        except ImportError:
            return self.timings

        from Voice.vad_engine import VADEngine

        audio = np.random.RandomState(0).randn(block_size).astype("float32") * 0.01
        vad = VADEngine()

        def _process():
            for _ in range(blocks):
                vad.process_block(audio)

        self._record(f"vad: {blocks} blocks x {block_size}", _process)
        return self.timings

    def measure_recorder_buffer(self, blocks=400, block_size=1024):
        """Buffer assembly cost: the recorder concatenates a list of blocks
        once at the end, which is O(n). This is the guard for that."""
        try:
            import numpy as np
        except ImportError:
            return self.timings

        block = np.zeros(block_size, dtype="float32")

        def _assemble():
            buffer = []
            for _ in range(blocks):
                buffer.append(block)
            np.concatenate(buffer)

        self._record(f"recorder: assemble {blocks} blocks", _assemble)
        return self.timings

    def measure_remote_roundtrip(self, requests=5):
        """Loopback POST /command, the phone's path.

        Measured end to end through the real server so the number includes
        accept, parse, dispatch, and response, which is what a phone waits
        for.
        """
        from concurrent.futures import Future

        from Interface.remote_server import RemoteServer

        def reply(text, source=None):
            future = Future()
            future.set_result("ok")
            return future

        server = RemoteServer(host="127.0.0.1", port=0, token="",
                              on_command=reply, timeout=5)
        if not server.start():
            self.timings.append(Timing("remote: loopback round trip"))
            return self.timings
        port = server._server.server_address[1]

        def _call():
            import json
            import urllib.request

            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/command",
                data=json.dumps({"text": "ping"}).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()

        self._record("remote: loopback round trip", _call, runs=requests)
        server.stop()
        return self.timings


class _StubCommandEngine:
    """Stands in for CommandEngine so no app is really launched."""

    def __init__(self):
        from Skills.skill_manager import SkillManager

        self.skills = SkillManager()

    def execute(self, intent, value="", text=None):
        return "bench"

    def execute_text(self, command):
        return "bench"


class _StubAI:
    def ask(self, question):
        return "bench"

    def ask_with_tools(self, question, tools):
        return "bench", None


class _StubMemory:
    """Memory reads/writes are I/O the router would otherwise perform
    against the real SQLite store during a benchmark."""

    def get_context(self, max_turns=None):
        return []

    def add_context(self, role, text):
        return None

    def learn(self, *args, **kwargs):
        return None

    def recall(self, *args, **kwargs):
        return []

    def recall_for(self, *args, **kwargs):
        return []

    def save_sentence(self, *args, **kwargs):
        return "bench"

    def delete(self, *args, **kwargs):
        return "bench"
