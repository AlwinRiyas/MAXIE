import os
import tempfile
import threading
import time
import unittest

from Config.config import Config
from Logs.logger import Logger


class LoggerLifecycleTest(unittest.TestCase):
    """TD-16 (race) and TD-47 (flush/shutdown) on the singleton."""

    def setUp(self):
        self.original = Logger._instance
        self.addCleanup(self._restore)

    def _restore(self):
        Logger._instance = self.original
        Logger.instance()  # rebuild a healthy handler chain for later tests

    def test_shutdown_flushes_closes_and_allows_rebuild(self):
        logger = Logger.instance()
        self.assertTrue(logger.logger.handlers)
        logger.shutdown()
        self.assertIsNone(Logger._instance, "shutdown must clear the singleton")
        rebuilt = Logger.instance()
        self.assertTrue(rebuilt.logger.handlers, "instance() must self-heal")

    def test_concurrent_first_calls_create_one_instance(self):
        Logger._instance = None
        barrier = threading.Barrier(10)
        seen = set()

        def worker():
            barrier.wait()
            seen.add(id(Logger.instance()))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(seen), 1, "only one Logger instance may exist")

    def test_log_file_is_owner_only(self):
        path = os.path.join(Config.resolve("Logs"), "maxie.log")
        if not os.path.exists(path):
            self.skipTest("log file not created in this environment")
        # Some development shares (vfat/ntfs/SMB) ignore POSIX modes and
        # report every file as 0777; chmod is a silent no-op there.
        try:
            os.chmod(path, 0o600)
        except OSError:
            self.skipTest("chmod unsupported on this filesystem")
        if (os.stat(path).st_mode & 0o077) != 0:
            self.skipTest("filesystem does not honour POSIX permissions")
        mode = os.stat(path).st_mode & 0o777
        self.assertFalse(
            mode & 0o077,
            f"log file must not be world/group readable: mode {mode:o}",
        )


class UtteranceRedactionTest(unittest.TestCase):
    """TD-17: user utterances must not be persisted in plaintext by
    default; a length + digest keeps correlation without the words."""

    def setUp(self):
        self._orig = Config.data
        self.addCleanup(lambda: setattr(Config, "data", self._orig))

    @staticmethod
    def _with_logging(**settings):
        data = {
            "system": {"logging": {"log_utterances": False,
                                   "retention_days": 7}},
        }
        data["system"]["logging"].update(settings)
        return data

    def test_utterance_is_redacted_by_default(self):
        Config.data = self._with_logging()
        rendered = Logger.utterance("my bank pin is 4021")
        self.assertNotIn("4021", rendered)
        self.assertNotIn("bank", rendered)
        self.assertIn("chars", rendered)

    def test_utterance_digest_is_stable_and_distinguishing(self):
        Config.data = self._with_logging()
        first = Logger.utterance("play some jazz")
        again = Logger.utterance("play some jazz")
        other = Logger.utterance("play some rock")
        self.assertEqual(first, again, "same utterance must correlate")
        self.assertNotEqual(first, other)

    def test_redaction_reports_length(self):
        Config.data = self._with_logging()
        text = "open the browser"
        self.assertIn(str(len(text)), Logger.utterance(text))

    def test_plaintext_only_when_explicitly_enabled(self):
        Config.data = self._with_logging(log_utterances=True)
        self.assertEqual(
            Logger.utterance("open the browser"), "open the browser")

    def test_missing_logging_section_still_redacts(self):
        Config.data = {"system": {}}
        self.assertNotIn("secret", Logger.utterance("secret sauce"))

    def test_none_and_empty_are_safe(self):
        Config.data = self._with_logging()
        self.assertIn("0 chars", Logger.utterance(None))
        self.assertIn("0 chars", Logger.utterance(""))


class LogRetentionSweepTest(unittest.TestCase):
    """TD-17: rotated log files past the retention window are deleted."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig = Config.data
        self.addCleanup(lambda: setattr(Config, "data", self._orig))

    def _make(self, name, age_days):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
        stamp = time.time() - (age_days * 86400)
        os.utime(path, (stamp, stamp))
        return path

    def test_removes_only_files_past_retention(self):
        old = self._make("maxie.log.1", 30)
        fresh = self._make("maxie.log.2", 1)
        Config.data = {"system": {"logging": {"retention_days": 7}}}
        removed = Logger.sweep(logs_dir=self._tmp.name)
        self.assertIn("maxie.log.1", removed)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh), "fresh backup must survive")

    def test_never_deletes_the_live_log(self):
        live = self._make("maxie.log", 365)
        Config.data = {"system": {"logging": {"retention_days": 7}}}
        Logger.sweep(logs_dir=self._tmp.name)
        self.assertTrue(os.path.exists(live))

    def test_never_touches_unrelated_files(self):
        other = self._make("notes.txt", 365)
        self._make("maxie.log.9", 365)
        Config.data = {"system": {"logging": {"retention_days": 7}}}
        Logger.sweep(logs_dir=self._tmp.name)
        self.assertTrue(os.path.exists(other))

    def test_zero_retention_disables_the_sweep(self):
        old = self._make("maxie.log.1", 365)
        Config.data = {"system": {"logging": {"retention_days": 0}}}
        self.assertEqual(Logger.sweep(logs_dir=self._tmp.name), [])
        self.assertTrue(os.path.exists(old))

    def test_missing_directory_is_not_an_error(self):
        Config.data = {"system": {"logging": {"retention_days": 7}}}
        missing = os.path.join(self._tmp.name, "nope")
        self.assertEqual(Logger.sweep(logs_dir=missing), [])


class LoggerNoCrashTest(unittest.TestCase):
    """Logger methods accept only plain string messages."""

    def test_message_only_api(self):
        handler = Logger.instance()
        handler.info("a plain message")
        handler.error("another plain message")


if __name__ == "__main__":
    unittest.main()