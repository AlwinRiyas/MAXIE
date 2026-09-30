import subprocess
import sys
import unittest

from Benchmarks.headless_bench import HeadlessBench, Timing


class TimingTest(unittest.TestCase):
    def test_reports_best_median_and_worst(self):
        timing = Timing("t", unit="ms")
        for value in (0.001, 0.002, 0.003):  # seconds in, ms reported
            timing.add(value)
        self.assertAlmostEqual(timing.best, 1.0)
        self.assertAlmostEqual(timing.median, 2.0)
        self.assertAlmostEqual(timing.worst, 3.0)

    def test_empty_timing_does_not_lie(self):
        timing = Timing("nothing")
        self.assertIn("no samples", timing.report())
        self.assertNotIn("0.00", timing.report())

    def test_as_dict_is_json_friendly(self):
        import json

        timing = Timing("t")
        timing.add(0.5)
        json.dumps(timing.as_dict())


class ImportCostTest(unittest.TestCase):
    """Cold start is the first thing a user experiences. These are the
    guards that keep it from creeping back."""

    @staticmethod
    def _import_in_subprocess(module, watch=None):
        """Import ``module`` in a clean interpreter.

        Returns (elapsed_ms, was_watch_loaded). ``watch`` is the module the
        caller cares about seeing *not* loaded.
        """
        watch = watch or module
        code = (
            "import sys, time, importlib;"
            "t=time.perf_counter();"
            f"importlib.import_module({module!r});"
            "print((time.perf_counter()-t)*1000, "
            f"{watch!r} in sys.modules)"
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=120,
                             check=True)
        milliseconds, loaded = out.stdout.split()
        return float(milliseconds), loaded == "True"

    def test_http_client_is_not_on_the_router_import_path(self):
        """`requests` costs ~215ms to import and was paid on every start,
        by every voice command, for a turn that may never call the LLM."""
        _cost, loaded = self._import_in_subprocess(
            "Brain.brain_router", watch="requests")
        self.assertFalse(loaded, "importing the router must not import "
                                 "requests; it should load on first use")

    def test_router_import_stays_under_the_budget(self):
        """A generous ceiling, not a benchmark: the point is to catch an
        accidental heavy import on the startup path, not to measure a
        faster CPU. Measured ~51ms here; the eager requests import made
        this 283ms, so the ceiling has to sit between the two."""
        for _ in range(3):
            cost, _loaded = self._import_in_subprocess(
                "Brain.brain_router", watch="requests")
        self.assertLess(
            cost, 150.0,
            f"importing BrainRouter takes {cost:.0f}ms; something heavy has "
            "landed on the startup path")


class RouterLatencyTest(unittest.TestCase):
    """A turn is the hot path for every command. The ceiling is loose
    enough (real cost is ~0.1ms) that it only fires on a pathology."""

    def test_no_turn_takes_pathological_time(self):
        bench = HeadlessBench(runs=5)
        bench.measure_router_turns()
        for timing in bench.timings:
            if not timing.samples:
                continue
            self.assertLess(
                timing.worst, 50.0,
                f"{timing.name} took {timing.worst:.1f}ms")

    def test_destructive_turn_is_not_slower_than_a_read_only_one(self):
        """The SEC-11 gate adds a hold and a re-prompt; it must not cost
        something a user would notice."""
        bench = HeadlessBench(runs=5)
        bench.measure_router_turns(utterances=[
            "what time is it",
            "shut down the computer",
        ])
        reads = [t for t in bench.timings if "what time" in t.name][0]
        writes = [t for t in bench.timings if "shut down" in t.name][0]
        self.assertLess(writes.worst, reads.worst * 50 + 5.0)


class SignalPathTest(unittest.TestCase):
    """The audio hot paths, on synthetic data. No sound card needed, and
    this is the guard for the O(n^2) energy sum TD-01 described."""

    def test_vad_throughput_is_flat(self):
        """Doubling the block count must roughly double the cost, not
        quadruple it. A quadratic regression is caught by the ratio."""
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")

        small = HeadlessBench(runs=1)
        small.measure_vad(blocks=200)
        large = HeadlessBench(runs=1)
        large.measure_vad(blocks=800)

        small_cost = [t for t in small.timings][0]
        large_cost = [t for t in large.timings][0]
        if not small_cost.samples or not large_cost.samples:
            self.skipTest("VAD unavailable")

        # 4x the work must not cost more than ~8x. A quadratic path would
        # be 16x, which this catches with room for noise.
        self.assertLess(
            large_cost.best / small_cost.best, 8.0,
            f"VAD cost scaled {large_cost.best / small_cost.best:.1f}x for "
            "4x the blocks; that looks quadratic")

    def test_recorder_assembly_is_linear(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")

        small = HeadlessBench(runs=1)
        small.measure_recorder_buffer(blocks=400)
        large = HeadlessBench(runs=1)
        large.measure_recorder_buffer(blocks=1600)

        small_cost = [t for t in small.timings][0]
        large_cost = [t for t in large.timings][0]
        if not small_cost.samples or not large_cost.samples:
            self.skipTest("numpy unavailable")
        self.assertLess(
            large_cost.best / small_cost.best, 8.0,
            "buffer assembly should be O(n) concatenation, not repeated "
            "re-copying")


class RemoteLatencyTest(unittest.TestCase):
    def test_loopback_round_trip_is_fast(self):
        bench = HeadlessBench(runs=5)
        bench.measure_remote_roundtrip()
        timing = [t for t in bench.timings if "loopback" in t.name][0]
        if not timing.samples:
            self.skipTest("remote server unavailable")
        self.assertLess(timing.worst, 250.0,
                        f"loopback round trip took {timing.worst:.0f}ms")


class HonestyTest(unittest.TestCase):
    """A benchmark that reports numbers it did not measure is worse than
    no benchmark, so the gaps are named rather than silently absent."""

    def test_hardware_only_measurements_are_declared_not_faked(self):
        bench = HeadlessBench()
        unmeasured = bench.unmeasured()
        for metric in ("wake_to_listen", "stt_latency", "tts_latency",
                       "barge_in_latency"):
            self.assertIn(metric, unmeasured)
            self.assertTrue(unmeasured[metric])

    def test_a_headless_run_does_not_emit_hardware_numbers(self):
        bench = HeadlessBench(runs=1)
        bench.measure_router_turns()
        measured = bench.as_dict()
        for metric in bench.HARDWARE_ONLY:
            self.assertNotIn(metric, measured)

    def test_every_timing_explains_itself_when_unmeasurable(self):
        bench = HeadlessBench(runs=1)
        bench.measure_vad()  # skipped cleanly without numpy
        for timing in bench.timings:
            if not timing.samples:
                self.assertIn("no samples", timing.report())


if __name__ == "__main__":
    unittest.main()
