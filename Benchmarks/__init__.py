"""MAXIE benchmarks: what can be measured, and on what hardware.

ROADMAP 18.3 asked for a baseline of cold start, wake-to-listen, STT
latency, TTS latency, and full turn. Only some of those are answerable
without a sound card, and this module is explicit about which is which
rather than printing a number that means nothing.
"""

from Benchmarks.headless_bench import HeadlessBench, Timing

__all__ = ["HeadlessBench", "Timing"]
